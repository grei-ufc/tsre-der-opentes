import copy
import datetime
import math

import mosaik_api_v3

from .element_specs import MODEL_SPECS, build_meta
from .opendss_wrapper import OpenDSS, OpenDSSException


def _parse_bus(bus_string):
    """Separa a referência de barra do OpenDSS em nome e nós.

    Args:
        bus_string: Barra como o OpenDSS reporta, com ou sem nós
            (``'671.1.2.3'``, ``'646.2'``, ``'634'``).

    Returns:
        Tupla ``(nome, nós)``. A lista de nós fica vazia quando a barra não
        traz sufixo, caso em que o OpenDSS assume todas as fases do elemento.
    """
    name, _, nodes = str(bus_string or "").partition(".")
    if not nodes:
        return name, []
    return name, [int(n) for n in nodes.split(".") if n.isdigit()]


def _resolve_nodes(nodes, phases):
    """Completa os nós implícitos de uma barra sem sufixo.

    ``Bus1=634`` num elemento trifásico significa ``634.1.2.3``; o OpenDSS
    simplesmente omite o sufixo. Sem essa resolução o cenário receberia uma
    lista vazia e teria de tratar o caso à parte.

    Args:
        nodes: Nós explícitos vindos de :func:`_parse_bus`.
        phases: Número de fases do elemento.

    Returns:
        Lista de nós; os ``phases`` primeiros quando não havia sufixo.
    """
    if nodes:
        return nodes
    return list(range(1, max(int(phases or 0), 0) + 1))


def _as_float(value, default=0.0):
    """Converte uma propriedade DSS (sempre string) para float, com fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    """Converte uma propriedade DSS (sempre string) para int, com fallback."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# A META e derivada do registry em element_specs.py, nao escrita a mao:
# assim ela nao pode declarar um atributo que o simulador nao implementa.
META = build_meta()


class OpenDSSSimulator(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.sid = None
        self.dss_wrapper = None
        self.step_size = None
        self.entity_map = {}
        self.loads_with_profiles = {}
        self.shape_data_cache = {}
        self.time_resolution = 1.0

        self.bypass_native_pv_curves = True
        self._children = []
        self._extra_info = {}
        self._eids_by_type = {}
        self._type_by_eid = {}
        self._bus_eids = {}

    # ------------------------------------------------------------------
    # Metadados das entidades
    # ------------------------------------------------------------------

    def get_extra_info(self):
        """Metadados estáticos de cada entidade, indexados por eid.

        Em mosaik >= 3.3 os mesmos dados chegam ao cenário direto em
        ``entity.extra_info``; este método dá acesso por eid sem percorrer a
        árvore de filhos.
        """
        return self._extra_info

    def _info_by_type(self, model_type):
        return [self._extra_info[eid] for eid in self._eids_by_type.get(model_type, [])]

    def _map_by_type(self, model_type):
        return {eid: self._extra_info[eid] for eid in self._eids_by_type.get(model_type, [])}

    @property
    def detected_regulators(self):
        return self._info_by_type("RegControl")

    @property
    def detected_pvsystems(self):
        return self._info_by_type("PVSystem")

    @property
    def detected_storages(self):
        return self._info_by_type("Storage")

    @property
    def regulator_map(self):
        return self._map_by_type("RegControl")

    @property
    def pvsystem_map(self):
        return self._map_by_type("PVSystem")

    @property
    def storage_map(self):
        return self._map_by_type("Storage")

    def init(
        self,
        sid,
        time_resolution,
        topofile,
        step_size=900,
        output_graph_path=None,
        bypass_native_pv_curves=True,
        **sim_params,
    ):
        """Inicializa o simulador e compila o circuito.

        Args:
            sid: Identificador do simulador no mosaik.
            time_resolution: Resolução temporal do mosaik.
            topofile: Arquivo ``.dss`` do circuito.
            step_size: Passo de simulação, em segundos.
            output_graph_path: Se informado, exporta o grafo do circuito.
            bypass_native_pv_curves: Neutraliza as curvas de eficiência e
                derating térmico dos PVSystems. Deixe ``True`` quando o
                inversor for modelado por outro simulador — caso contrário a
                penalidade é aplicada duas vezes. Use ``False`` para deixar o
                OpenDSS cuidar da conversão DC/AC.
        """
        self.sid = sid
        self.time_resolution = time_resolution
        self.step_size = step_size
        self.bypass_native_pv_curves = bypass_native_pv_curves
        self.dss_wrapper = OpenDSS(
            redirects=topofile,
            time_step=datetime.timedelta(seconds=self.step_size),
            start_time=datetime.datetime(2025, 1, 1),
        )

        if output_graph_path is not None:
            self.dss_wrapper.grafo_tsdq(output_graph_path)

        return self.meta

    def create(self, num, model, **model_params):
        if model != "Grid":
            raise ValueError(
                "Use 'Grid' model to initialize the system. Access elements via children."
            )
        if num != 1:
            raise ValueError(f"exactly one Grid entity must be created, got num={num}")
        if self._children:
            raise ValueError("Grid was already created")

        return self._create_grid()

    def setup_done(self):
        """Resolve o fluxo inicial depois de todas as entidades e conexões.

        Sem isso, o primeiro ``get_data`` — o que alimenta as conexões
        ``time_shifted`` com dados iniciais — leria a solução feita durante a
        compilação, antes de qualquer ajuste feito na criação das entidades
        (como o bypass das curvas nativas dos PVSystems).
        """
        self.dss_wrapper.run_dss()

    # ------------------------------------------------------------------
    # Criação de entidades
    # ------------------------------------------------------------------

    def _create_grid(self):
        # As barras vêm primeiro: são as âncoras que todos os demais
        # elementos referenciam em `rel`.
        self._add_buses()
        self._add_loads()
        self._add_lines()
        self._add_regulators()
        self._add_storages()
        self._add_pvsystems()

        return [
            {
                "eid": "Grid-0",
                "type": "Grid",
                "children": self._children,
                "rel": [],
            }
        ]

    def _add_child(self, eid, model_type, name, rel=None, extra_info=None):
        """Registra uma entidade filha com sua topologia e seus metadados.

        O ``extra_info`` entregue ao cenário é uma cópia. Compartilhar o objeto
        daria ao cenário local uma referência viva para o estado interno do
        simulador, enquanto um cenário remoto receberia um retrato congelado —
        a mesma escrita produziria resultados diferentes conforme o transporte.

        Args:
            eid: Identificador mosaik da entidade.
            model_type: Nome do modelo declarado na META.
            name: Nome do elemento no OpenDSS.
            rel: eids aos quais a entidade está conectada (barras).
            extra_info: Metadados estáticos expostos ao cenário.
        """
        self.entity_map[eid] = name
        self._extra_info[eid] = extra_info or {}
        self._eids_by_type.setdefault(model_type, []).append(eid)
        self._type_by_eid[eid] = model_type
        self._children.append(
            {
                "eid": eid,
                "type": model_type,
                "rel": rel or [],
                "extra_info": copy.deepcopy(self._extra_info[eid]),
            }
        )

    def _bus_rel(self, bus_string, owner):
        """Resolve a referência de barra de um elemento para o eid da barra.

        O mosaik constrói o grafo de entidades com ``add_edge``, que cria nós
        inexistentes em silêncio — uma referência pendurada corromperia o grafo
        sem erro nenhum. Por isso a resolução é validada aqui.

        Args:
            bus_string: Barra como o OpenDSS reporta (``'671.1.2.3'``).
            owner: eid do elemento, usado só na mensagem de aviso.

        Returns:
            Lista com o eid da barra, ou lista vazia se a barra não existe.
        """
        bus_name, _ = _parse_bus(bus_string)
        eid = self._bus_eids.get(bus_name.lower())

        if eid is None:
            print(
                f"[OpenTES][AVISO] {owner}: barra '{bus_string}' nao esta na lista "
                f"de barras do circuito; a entidade ficara sem topologia (rel)."
            )
            return []

        return [eid]

    def _add_buses(self):
        dss = self.dss_wrapper.dss

        for name in self.dss_wrapper.get_all_buses():
            eid = f"Bus-{name}"
            self._bus_eids[name.lower()] = eid

            dss.circuit.set_active_bus(name)
            self._add_child(
                eid,
                "Bus",
                name,
                rel=[],
                extra_info={
                    "name": name,
                    "kv_base": dss.bus.kv_base,
                    "nodes": list(dss.bus.nodes),
                    "num_nodes": dss.bus.num_nodes,
                    "x": dss.bus.x,
                    "y": dss.bus.y,
                },
            )

    def _add_loads(self):
        loads_df = self.dss_wrapper.get_all_elements("Load")
        if loads_df.empty:
            return

        for full_name, row in loads_df.iterrows():
            name = full_name.split(".")[1]
            eid = f"Load-{name}"
            bus_name, nodes = _parse_bus(row.get("bus1", ""))
            phases = _as_int(row.get("phases"), len(nodes) or 3)
            nodes = _resolve_nodes(nodes, phases)

            self._add_child(
                eid,
                "Load",
                name,
                rel=self._bus_rel(row.get("bus1", ""), eid),
                extra_info={
                    "name": name,
                    "bus": bus_name,
                    "nodes": nodes,
                    "phases": phases,
                    "kv": _as_float(row.get("kV")),
                    "kw": _as_float(row.get("kW")),
                    "kvar": _as_float(row.get("kvar")),
                    "conn": row.get("conn", ""),
                },
            )
            self._check_load_profile(eid, name)

    def _add_lines(self):
        lines_df = self.dss_wrapper.get_all_elements("Line")
        if lines_df.empty:
            return

        for full_name, row in lines_df.iterrows():
            name = full_name.split(".")[1]
            eid = f"Line-{name}"
            bus1, nodes1 = _parse_bus(row.get("bus1", ""))
            bus2, nodes2 = _parse_bus(row.get("bus2", ""))
            phases = _as_int(row.get("phases"), len(nodes1) or 3)
            nodes1 = _resolve_nodes(nodes1, phases)
            nodes2 = _resolve_nodes(nodes2, phases)

            self._add_child(
                eid,
                "Line",
                name,
                rel=(
                    self._bus_rel(row.get("bus1", ""), eid)
                    + self._bus_rel(row.get("bus2", ""), eid)
                ),
                extra_info={
                    "name": name,
                    "bus1": bus1,
                    "bus2": bus2,
                    "nodes1": nodes1,
                    "nodes2": nodes2,
                    "phases": phases,
                    "length": _as_float(row.get("length")),
                    "linecode": row.get("linecode", ""),
                },
            )

    def _add_regulators(self):
        if self.dss_wrapper.dss.regcontrols.count == 0:
            return

        for info in self.dss_wrapper.get_all_regulators_info():
            name = info["name"]
            eid = f"RegControl-{name}"
            info["eid_dss"] = eid
            info["bus"] = info["target_bus"]
            info["phase"] = info["target_phase"]

            self._add_child(
                eid,
                "RegControl",
                name,
                rel=self._bus_rel(info["target_bus"], eid),
                extra_info=info,
            )
            print(
                f"[OpenTES] Regulador detectado: {name} @ "
                f"{info['target_bus']}.{info['target_phase']}"
            )

    def _add_storages(self):
        for name, info in self.dss_wrapper.get_all_storages_info().items():
            eid = f"Storage-{name}"
            bus_name, nodes = _parse_bus(info.get("bus", ""))
            phases = info.get("num_phases") or len(nodes) or 3
            info["eid_dss"] = eid
            info["name"] = name
            info["bus"] = bus_name
            info["nodes"] = _resolve_nodes(nodes, phases)
            info["phases"] = phases

            self._add_child(
                eid,
                "Storage",
                name,
                rel=self._bus_rel(bus_name, eid),
                extra_info=info,
            )
            print(
                f"[OpenTES] Storage detectado: {name} @ {bus_name} | "
                f"kW_rated: {info['kw_rated']} | kWh_rated: {info['kwh_rated']}"
            )

    def _add_pvsystems(self):
        pv_infos = self.dss_wrapper.get_all_pvsystems_info()
        if not pv_infos:
            return

        if self.bypass_native_pv_curves:
            self._bypass_native_pv_curves(pv_infos)

        for name, info in pv_infos.items():
            eid = f"PVSystem-{name}"
            bus_name, nodes = _parse_bus(info.get("bus", ""))
            phases = info.get("num_phases") or len(nodes) or 3
            info["eid_dss"] = eid
            info["name"] = name
            info["bus"] = bus_name
            info["nodes"] = _resolve_nodes(nodes, phases)
            info["phases"] = phases

            self._add_child(
                eid,
                "PVSystem",
                name,
                rel=self._bus_rel(bus_name, eid),
                extra_info=info,
            )
            print(
                f"[OpenTES] PVSystem detectado: {name} @ {bus_name} | "
                f"Pmpp: {info['pmpp']} kW | kVA: {info['kva']}"
            )

    def _bypass_native_pv_curves(self, pv_infos):
        """Neutraliza as curvas nativas dos PVSystems para a co-simulação.

        Quem calcula eficiência e derating térmico é o simulador de inversor,
        então deixar as curvas do OpenDSS ativas aplicaria a penalidade duas
        vezes. As curvas originais continuam disponíveis em ``extra_info``
        (``eff_curve_*`` e ``pt_curve_*``) para quem for modelá-las fora.
        """
        dss = self.dss_wrapper.dss
        dss.text("New XYCurve.EffIdeal_Cosim npts=2 xarray=[0.0 1.0] yarray=[1.0 1.0]")
        dss.text("New XYCurve.PTIdeal_Cosim npts=2 xarray=[0.0 100.0] yarray=[1.0 1.0]")

        for name in pv_infos:
            dss.text(
                f"Edit PVSystem.{name} %cutin=0.0001 %cutout=0.0001 "
                f"EffCurve=EffIdeal_Cosim P-TCurve=PTIdeal_Cosim"
            )

    def _check_load_profile(self, eid, name):
        """Registra a LoadShape associada a uma carga, se houver.

        Uma falha aqui não é inofensiva: sem perfil, a carga fica congelada no
        valor nominal durante toda a simulação. Por isso é sinalizada em vez de
        ignorada.
        """
        shape_name = None
        try:
            yearly = self.dss_wrapper.get_property(name, "yearly", "Load")
            daily = self.dss_wrapper.get_property(name, "daily", "Load")
            if isinstance(yearly, str) and yearly.lower() not in ["none", "constant", ""]:
                shape_name = yearly
            if isinstance(daily, str) and daily.lower() not in ["none", "constant", ""]:
                shape_name = daily

        except OpenDSSException as exc:
            print(
                f"[OpenTES][AVISO] Nao foi possivel ler o perfil de Load.{name}: {exc}. "
                "A carga ficara fixa no valor nominal."
            )

        if shape_name:
            base_kw = float(self.dss_wrapper.get_property(name, "kW", "Load") or 0.0)
            base_kvar = float(self.dss_wrapper.get_property(name, "kvar", "Load") or 0.0)
            self.loads_with_profiles[eid] = {
                "shape_name": shape_name,
                "base_kw": base_kw,
                "base_kvar": base_kvar,
            }

            if shape_name not in self.shape_data_cache:
                self._cache_loadshape(shape_name)

    def _cache_loadshape(self, shape_name):
        """Lê uma LoadShape uma vez e guarda seus multiplicadores.

        Se a leitura falhar, o perfil fica ausente do cache e ``step()`` deixa
        as cargas que o usam paradas no valor nominal — daí o aviso dizer a
        consequência, e não só o erro.
        """
        try:
            self.dss_wrapper.dss.loadshapes.name = shape_name
            p_mult = list(self.dss_wrapper.dss.loadshapes.p_mult)
            q_mult = list(self.dss_wrapper.dss.loadshapes.q_mult)
            npts = self.dss_wrapper.dss.loadshapes.npts

            # O npts declarado pode passar do array realmente entregue pelo
            # motor. Ajustar aqui, uma vez, evita um IndexError por passo — e
            # o fallback silencioso para o indice 0 que ele provocava.
            if len(p_mult) < npts:
                print(
                    f"[OpenTES][AVISO] LoadShape '{shape_name}' declara npts={npts} "
                    f"mas entregou {len(p_mult)} pontos; usando {len(p_mult)}."
                )
                npts = len(p_mult)

            if not q_mult or len(q_mult) < npts:
                q_mult = p_mult

            interval = self.dss_wrapper.dss.loadshapes.s_interval
            if interval == 0:
                interval = self.dss_wrapper.dss.loadshapes.min_interval * 60
            if interval == 0:
                interval = self.dss_wrapper.dss.loadshapes.hr_interval * 3600
            if interval == 0:
                interval = self.step_size

            self.shape_data_cache[shape_name] = {
                "p_mult": p_mult,
                "q_mult": q_mult,
                "interval_s": interval,
                "npts": npts,
                "use_actual": bool(self.dss_wrapper.dss.loadshapes.use_actual),
            }

        except Exception as exc:
            print(
                f"[OpenTES][ERRO] Falha ao ler a LoadShape '{shape_name}': {exc}. "
                "As cargas que a usam ficarao fixas no valor nominal."
            )

    def step(self, time, inputs, max_advance):
        self._apply_inputs(inputs)

        # ATUALIZAÇÃO DAS CARGAS
        for eid, profile in self.loads_with_profiles.items():
            shape_name = profile["shape_name"]
            if shape_name not in self.shape_data_cache:
                continue
            data = self.shape_data_cache[shape_name]
            # npts foi conciliado com o tamanho real dos arrays em
            # _cache_loadshape, entao o indice esta sempre dentro dos limites.
            idx = math.floor(time / data["interval_s"]) % data["npts"]
            pmult = data["p_mult"][idx]
            qmult = data["q_mult"][idx]

            if data["use_actual"]:
                p_set = pmult
                q_set = qmult
            else:
                p_set = profile["base_kw"] * pmult
                q_set = profile["base_kvar"] * qmult

            load_name = self.entity_map[eid]
            self.dss_wrapper.set_power(load_name, p=p_set, q=q_set, element="Load")

            # if eid == 'Load-671' and time < 1200:
            #     print(f"[STEP {time}] Atualizando {load_name}: Multiplicador={pmult:.3f} -> Definindo kW={p_set:.2f}")

        # 2. RESOLVER FLUXO DE POTÊNCIA (SNAPSHOT)
        self.dss_wrapper.run_dss()

        return time + self.step_size

    def _apply_inputs(self, inputs):
        """Aplica as entradas do mosaik ao circuito, roteadas pelo registry.

        Cada atributo é reduzido a um único valor pelo agregador declarado no
        seu :class:`~.element_specs.InputSpec`, de modo que comandos
        concorrentes sejam somados ou sinalizados — nunca descartados em
        silêncio.
        """
        for eid, attrs in inputs.items():
            spec = self._spec_of(eid)
            if spec is None or spec.writer is None:
                continue

            values = {
                attr: spec.inputs[attr].aggregator(attr, eid, sources.values())
                for attr, sources in attrs.items()
                if attr in spec.inputs and sources
            }
            if not values:
                continue

            try:
                spec.writer(self, self.entity_map[eid], values)
            except Exception as exc:
                # Uma escrita de controle perdida faz a simulação divergir do
                # que o controlador comandou, sem nada no resultado indicando
                # isso. Parar é preferível a produzir um dia inteiro de dados
                # silenciosamente errados.
                raise OpenDSSException(f"Failed to apply {values} to {eid}: {exc}") from exc

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            spec = self._spec_of(eid)
            if spec is None:
                continue
            data[eid] = spec.reader(self, self.entity_map[eid], attrs, spec)
        return data

    def _spec_of(self, eid):
        """Especificação do modelo de *eid*, ou ``None`` se não for deste simulador."""
        model_type = self._type_by_eid.get(eid)
        if model_type is None:
            return None
        return MODEL_SPECS.get(model_type)

    def get_dss_wrapper(self):
        return self.dss_wrapper

    def get_detected_regulators(self):
        return self.detected_regulators

    def get_detected_pvsystems(self):
        return self.detected_pvsystems

    def get_detected_storages(self):
        return self.detected_storages
