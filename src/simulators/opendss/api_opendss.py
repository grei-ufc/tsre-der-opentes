import datetime
import math

import mosaik_api_v3

from ._utils import extract_3phase_pq, to_3phase
from .opendss_wrapper import OpenDSS

META = {
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "Grid": {"public": True, "params": ["topofile"], "attrs": []},
        "Load": {
            "public": False,
            "params": [],
            "attrs": ["P_mw", "Q_mvar", "P_out_mw", "Q_out_mvar"],
        },
        "Line": {
            "public": False,
            "params": [],
            "attrs": [
                "is_open",
                "I1_A",
                "I1_ang",
                "I2_A",
                "I2_ang",
                "I3_A",
                "I3_ang",
                "P1_w",
                "Q1_var",
                "P2_w",
                "Q2_var",
                "P3_w",
                "Q3_var",
            ],
        },
        "Bus": {
            "public": False,
            "params": [],
            "attrs": ["V1_pu", "V1_ang", "V2_pu", "V2_ang", "V3_pu", "V3_ang"],
        },
        "RegControl": {"public": False, "params": [], "attrs": ["tap", "v_meas", "i_meas"]},
        "Storage": {
            "public": True,
            "params": [],
            "attrs": [
                "P_set",
                "Q_set",
                "SoC_set",
                "P_act",
                "Q_act",
                "SoC",
                "P1",
                "P2",
                "P3",
                "Q1",
                "Q2",
                "Q3",
                "I1_A",
                "I2_A",
                "I3_A",
            ],
        },
        "PVSystem": {
            "public": True,
            "params": [],
            "attrs": [
                "P_des",
                "Q_des",
                "P_meas",
                "Q_meas",
                "P1",
                "P2",
                "P3",
                "Q1",
                "Q2",
                "Q3",
                "I1_A",
                "I2_A",
                "I3_A",
            ],
        },
    },
    "extra_methods": [
        "get_dss_wrapper",
        "get_detected_regulators",
        "get_detected_pvsystems",
        "get_detected_storages",
    ],
}


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
        self.detected_regulators = []
        self.regulator_map = {}
        self.detected_pvsystems = []
        self.pvsystem_map = {}
        self.detected_storages = []
        self.storage_map = {}

    def init(
        self, sid, time_resolution, topofile, step_size=900, output_graph_path=None, **sim_params
    ):
        self.sid = sid
        self.time_resolution = time_resolution
        self.step_size = step_size
        self.dss_wrapper = OpenDSS(
            redirects=topofile,
            time_step=datetime.timedelta(seconds=self.step_size),
            start_time=datetime.datetime(2025, 1, 1),
        )

        if output_graph_path is not None:
            self.dss_wrapper.grafo_tsdq(output_graph_path)

        return self.meta

    def create(self, num, model, **model_params):
        if model == "Grid":
            return self._create_grid()
        else:
            raise ValueError(
                "Use 'Grid' model to initialize the system. Access elements via children."
            )

    def _create_grid(self):
        child_entities = []

        # --- Cargas ---
        loads_df = self.dss_wrapper.get_all_elements("Load")
        if not loads_df.empty:
            for full_name in loads_df.index:
                name = full_name.split(".")[1]
                eid = f"Load-{name}"
                self.entity_map[eid] = name
                child_entities.append({"eid": eid, "type": "Load"})
                self._check_load_profile(eid, name)

        # --- Geradores (A incluir) ---

        # --- Linhas ---
        lines_df = self.dss_wrapper.get_all_elements("Line")
        if not lines_df.empty:
            for full_name in lines_df.index:
                name = full_name.split(".")[1]
                eid = f"Line-{name}"
                self.entity_map[eid] = name
                child_entities.append({"eid": eid, "type": "Line"})

        # --- Barras ---
        buses = self.dss_wrapper.get_all_buses()
        for name in buses:
            eid = f"Bus-{name}"
            self.entity_map[eid] = name
            child_entities.append({"eid": eid, "type": "Bus"})

        # --- Reguladores de tensão ---
        if self.dss_wrapper.dss.regcontrols.count > 0:
            reg_infos = self.dss_wrapper.get_all_regulators_info()

            for info in reg_infos:
                name = info["name"]
                eid = f"RegControl-{name}"

                info["eid_dss"] = eid

                self.entity_map[eid] = name
                self.detected_regulators.append(info)
                self.regulator_map[eid] = info

                child_entities.append({"eid": eid, "type": "RegControl"})
                print(
                    f"[OpenTES] Regulador detectado: {name} @ {info['target_bus']}.{info['target_phase']}"
                )

        # --- Baterias ---
        storage_infos = self.dss_wrapper.get_all_storages_info()

        if storage_infos:
            for name, info in storage_infos.items():
                eid = f"Storage-{name}"
                info["eid_dss"] = eid
                info["name"] = name

                self.entity_map[eid] = name
                self.detected_storages.append(info)
                self.storage_map[eid] = info  # <--- Guardando a referência aqui!

                child_entities.append({"eid": eid, "type": "Storage"})
                print(
                    f"[OpenTES] Storage detectado: {name} | kW_rated: {info['kw_rated']} | kWh_rated: {info['kwh_rated']}"
                )

        #  --- Sistema Fotovoltaico ---
        pv_infos = self.dss_wrapper.get_all_pvsystems_info()  # Usa o método que criamos no wrapper

        if pv_infos:
            # 1. Criamos curvas IDEAIS no OpenDSS para que ele não aplique dupla penalidade
            self.dss_wrapper.dss.text(
                "New XYCurve.EffIdeal_Cosim npts=2 xarray=[0.0 1.0] yarray=[1.0 1.0]"
            )
            self.dss_wrapper.dss.text(
                "New XYCurve.PTIdeal_Cosim npts=2 xarray=[0.0 100.0] yarray=[1.0 1.0]"
            )

            for name, info in pv_infos.items():
                eid = f"PVSystem-{name}"
                info["eid_dss"] = eid
                info["name"] = name

                self.entity_map[eid] = name
                self.detected_pvsystems.append(info)
                self.pvsystem_map[eid] = info

                child_entities.append({"eid": eid, "type": "PVSystem"})
                print(
                    f"[OpenTES] PVSystem detectado: {name} | Pmpp: {info['pmpp']} kW | kVA: {info['kva']}"
                )

                # 2. Lobotomiza o elemento nativo: tira os cortes e atrela às curvas 100% ideais
                cmd = f"Edit PVSystem.{name} %cutin=0.0001 %cutout=0.0001 EffCurve=EffIdeal_Cosim P-TCurve=PTIdeal_Cosim"
                self.dss_wrapper.dss.text(cmd)

        return [{"eid": "Grid-0", "type": "Grid", "children": child_entities}]

    def _check_load_profile(self, eid, name):
        """
        Lógica auxiliar para carregar perfis de carga (LoadShapes)

        :param self: Description
        """

        shape_name = None
        try:
            yearly = self.dss_wrapper.get_property(name, "yearly", "Load")
            daily = self.dss_wrapper.get_property(name, "daily", "Load")
            if isinstance(yearly, str) and yearly.lower() not in ["none", "constant", ""]:
                shape_name = yearly
            if isinstance(daily, str) and daily.lower() not in ["none", "constant", ""]:
                shape_name = daily

        except Exception:
            pass

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
        try:
            self.dss_wrapper.dss.loadshapes.name = shape_name
            p_mult = list(self.dss_wrapper.dss.loadshapes.p_mult)
            q_mult = list(self.dss_wrapper.dss.loadshapes.q_mult)
            npts = self.dss_wrapper.dss.loadshapes.npts

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

            # print(f"[DEBUG] LoadShape '{shape_name}' cacheada com {npts} pontos.")

        except Exception as e:
            print(f"[ERRO] Erro ao ler LoadShape '{shape_name}': {e}")

    def step(self, time, inputs, max_advance):
        # PROCESSAR INPUTS DE CONTROLE
        for eid, attrs in inputs.items():
            if eid not in self.entity_map:
                continue
            # Controle de Regulador

            name = self.entity_map[eid]
            model_type = eid.split("-")[0]

            # --- Controle do Regulador ---
            if model_type == "RegControl" and "tap" in attrs:
                try:
                    new_tap = int(list(attrs["tap"].values())[0])

                    self.dss_wrapper.set_tap(name=name, tap=new_tap)

                    # print(f"[LOG] {name} Tap alterado para {new_tap}")
                except Exception as e:
                    print(f"[ERRO] Falha ao ajustar tap de {name}: {e}")

            # --- Controle de Bateria ---
            elif model_type == "Storage":
                try:
                    p_val = list(attrs["P_set"].values())[0] if "P_set" in attrs else None
                    q_val = list(attrs["Q_set"].values())[0] if "Q_set" in attrs else None
                    soc_val = list(attrs["SoC_set"].values())[0] if "SoC_set" in attrs else None

                    if p_val is not None or q_val is not None or soc_val is not None:
                        self.dss_wrapper.set_power(name, p=p_val, q=q_val, element="Storage")

                except Exception as e:
                    print(f"[ERRO] Falha ao ajustar bateria {name}: {e}")

            # --- Controle do PVSystem ---
            elif model_type == "PVSystem":
                # Pegar os valores desejados (se existirem na iteração atual), senão mantém 0
                p_des = list(attrs.get("P_des", {}).values())[0] if "P_des" in attrs else 0.0
                q_des = list(attrs.get("Q_des", {}).values())[0] if "Q_des" in attrs else 0.0

                self.dss_wrapper.set_pvsystem_pq(name, p_des, q_des)

        # ATUALIZAÇÃO DAS CARGAS
        for eid, profile in self.loads_with_profiles.items():
            shape_name = profile["shape_name"]
            if shape_name not in self.shape_data_cache:
                continue
            data = self.shape_data_cache[shape_name]
            idx = math.floor(time / data["interval_s"]) % data["npts"]

            # Acesso seguro ao índice ---
            try:
                pmult = data["p_mult"][idx]
                qmult = data["q_mult"][idx]
            except IndexError:
                # Fallback seguro caso algo muito estranho aconteça com os índices
                pmult = data["p_mult"][0]
                qmult = data["q_mult"][0]
            # -------------------------------------------

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

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            if eid not in self.entity_map:
                continue
            name = self.entity_map[eid]
            model_type = eid.split("-")[0]
            data[eid] = {}

            if model_type == "Load":
                p_kw, _ = self.dss_wrapper.get_power(name, element="Load")
                if "P_out_mw" in attrs:
                    data[eid]["P_out_mw"] = p_kw / 1000.0

            elif model_type == "Line":
                data[eid].update(self._extract_line_data(name, attrs))

            elif model_type == "Bus":
                data[eid].update(self._extract_bus_data(name, attrs))

            elif model_type == "RegControl":
                info = self.regulator_map.get(eid)
                if not info:
                    continue
                meas = self.dss_wrapper.get_regulator_measurements(info)
                if "v_meas" in attrs:
                    data[eid]["v_meas"] = meas["v"]
                if "i_meas" in attrs:
                    data[eid]["i_meas"] = meas["i"]
                if "tap" in attrs:
                    data[eid]["tap"] = meas["tap"]

            elif model_type == "Storage":
                data[eid].update(
                    extract_3phase_pq(
                        self.dss_wrapper,
                        name,
                        "Storage",
                        attrs,
                        sign=-1,
                    )
                )

            elif model_type == "PVSystem":
                data[eid].update(
                    extract_3phase_pq(
                        self.dss_wrapper,
                        name,
                        "PVSystem",
                        attrs,
                        sign=-1,
                    )
                )

        return data

    # ------------------------------------------------------------------
    # Helpers de extração de dados (usados por get_data)
    # ------------------------------------------------------------------

    def _extract_line_data(self, name, attrs):
        """Extrai correntes e potências de uma linha, retornando dict de attrs."""
        result = {}

        # Correntes
        curr_mag, curr_ang = self.dss_wrapper.get_current(
            name,
            element="Line",
            polar=True,
            mag_only=False,
            line_bus=1,
        )
        mags = to_3phase(curr_mag)
        angs = to_3phase(curr_ang)

        current_map = {
            "I1_A": mags[0],
            "I2_A": mags[1],
            "I3_A": mags[2],
            "I1_ang": angs[0],
            "I2_ang": angs[1],
            "I3_ang": angs[2],
        }
        for attr in attrs:
            if attr in current_map:
                result[attr] = current_map[attr]

        # Potências
        p_w, q_var = self.dss_wrapper.get_power(
            name,
            element="Line",
            line_bus=1,
        )
        ps = to_3phase(p_w)
        qs = to_3phase(q_var)

        power_map = {
            "P1_w": ps[0],
            "P2_w": ps[1],
            "P3_w": ps[2],
            "Q1_var": qs[0],
            "Q2_var": qs[1],
            "Q3_var": qs[2],
        }
        for attr in attrs:
            if attr in power_map:
                result[attr] = power_map[attr]

        return result

    def _extract_bus_data(self, name, attrs):
        """Extrai tensões de uma barra, retornando dict de attrs."""
        result = {}

        volt_mag, volt_ang = self.dss_wrapper.get_bus_voltage(
            bus=name,
            pu=True,
            mag_only=False,
            polar=True,
        )
        mags = to_3phase(volt_mag)
        angs = to_3phase(volt_ang)

        voltage_map = {
            "V1_pu": mags[0],
            "V2_pu": mags[1],
            "V3_pu": mags[2],
            "V1_ang": angs[0],
            "V2_ang": angs[1],
            "V3_ang": angs[2],
        }
        for attr in attrs:
            if attr in voltage_map:
                result[attr] = voltage_map[attr]

        return result

    def get_dss_wrapper(self):
        return self.dss_wrapper

    def get_detected_regulators(self):
        return self.detected_regulators

    def get_detected_pvsystems(self):
        return self.detected_pvsystems

    def get_detected_storages(self):
        return self.detected_storages
