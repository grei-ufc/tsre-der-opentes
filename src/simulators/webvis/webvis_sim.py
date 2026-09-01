"""Simulador mosaik que publica a topologia e os dados da simulação na web.

Fork de ``mosaik_components.web.mosaik`` do mosaik-web 0.5.0 (LGPL-2.1); veja
``LICENSE.txt`` e ``README.md`` neste diretório. As mudanças em relação ao
original são comentadas com ``[OpenTES]``.

O simulador não calcula nada: ele monta o grafo de entidades da simulação
inteira (via ``get_related_entities``) e, a cada passo, repassa ao navegador um
valor por nó. Quem decide o que é esse valor é o cenário, por meio de
``set_etypes``.
"""

import copy
import logging
from datetime import datetime

import mosaik_api_v3
import networkx as nx

from .server import Server

logger = logging.getLogger("simulators.webvis")

meta = {
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "Topology": {
            "public": True,
            "params": [],
            "attrs": [],
            "any_inputs": True,
        },
    },
    "extra_methods": [
        "set_config",
        "set_etypes",
        # [OpenTES] Coordenadas reais das barras, quando o circuito as tem.
        "set_node_positions",
    ],
}

# TODO: Document config file format
default_config = {
    "ignore_types": ["Topology"],
    "merge_types": ["Branch", "Transformer"],
    "merge_nodes": [],
    "disable_heatmap": False,
    "timeline_hours": 24,
    "etypes": {},
    "ignore_names": [],
    # [OpenTES] Mapa full_id -> (x, y) no sistema de coordenadas do circuito.
    "node_positions": {},
}

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# [OpenTES] Como reduzir os vários atributos de um nó (as três fases, tipicamente)
# ao único número que colore o mapa de calor. O frontend pode escolher outro sem
# recarregar; este é o valor inicial.
AGGREGATORS = {
    "first": lambda values: values[0],
    "min": min,
    "max": max,
    "mean": lambda values: sum(values) / len(values),
    # Amplitude entre fases: é o desequilíbrio visto pelo desenho.
    "spread": lambda values: max(values) - min(values),
}


def to_iso_local(start_date):
    """Converte ``'YYYY-MM-DD HH:MM:SS'`` em ISO 8601 no fuso local.

    [OpenTES] O original usava ``arrow`` só para isto; a biblioteca padrão
    produz a mesma string — que é o que o ``new Date()`` do navegador entende —
    e o fork fica com uma dependência a menos.

    Args:
        start_date: Instante inicial da simulação, sem fuso.

    Returns:
        String ISO 8601 com o deslocamento do fuso local (``...-03:00``).
    """
    return datetime.strptime(start_date, DATE_FORMAT).astimezone().isoformat()


def etype_attrs(etype_conf):
    """Atributos que um tipo de entidade publica, na ordem em que são exibidos.

    [OpenTES] O upstream só admitia um atributo por tipo (``attr``), o que basta
    para uma rede monofásica equivalente mas não para uma trifásica, em que uma
    barra tem uma tensão por fase. ``attrs`` é a forma nova; ``attr`` continua
    valendo e equivale a uma lista de um elemento.

    Args:
        etype_conf: Configuração de um tipo, vinda de ``set_etypes``.

    Returns:
        Lista de nomes de atributo; vazia se o tipo não declara nenhum.
    """
    if not etype_conf:
        return []

    attrs = etype_conf.get("attrs")
    if attrs:
        return list(attrs)

    attr = etype_conf.get("attr")
    return [attr] if attr else []


def aggregate_values(values, how="first", ignore_zero=True):
    """Reduz os valores de um nó ao escalar que colore o mapa de calor.

    Args:
        values: Valores dos atributos do nó, na ordem de :func:`etype_attrs`;
            ``None`` onde o simulador não mandou dado.
        how: Nome de um agregador de :data:`AGGREGATORS`.
        ignore_zero: Descarta os zeros antes de agregar. É o padrão porque, numa
            rede trifásica, a fase que a barra não tem é reportada como ``0.0``:
            incluí-la faria um ramal monofásico parecer estar com a tensão
            colapsada — exatamente o nó que o mapa de calor deve destacar.

    Returns:
        O valor agregado, ou ``None`` se não houver nenhum valor utilizável.
    """
    usable = [v for v in values if v is not None]
    if ignore_zero:
        usable = [v for v in usable if v]

    if not usable:
        return None

    aggregator = AGGREGATORS.get(how)
    if aggregator is None:
        print(
            f"[OpenTES][AVISO] Agregador '{how}' desconhecido; "
            f"use um de {sorted(AGGREGATORS)}. Usando 'first'."
        )
        aggregator = AGGREGATORS["first"]

    return aggregator(usable)


def normalize_positions(positions):
    """Leva as coordenadas do circuito para o quadrado unitário, sem distorcer.

    Um alimentador tem uma forma: normalizar cada eixo pela sua própria extensão
    esticaria um ramal longo e estreito até virar um quadrado. Por isso os dois
    eixos usam a mesma escala, e a sobra é centralizada.

    O eixo Y é invertido porque no OpenDSS ele cresce para o norte e na tela
    cresce para baixo.

    Args:
        positions: Mapa ``full_id -> (x, y)`` nas coordenadas do circuito.

    Returns:
        Mapa ``full_id -> (x, y)`` com ambos em ``[0, 1]``.
    """
    if not positions:
        return {}

    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    span = max(max_x - min_x, max_y - min_y)
    if not span:
        # Todas as barras no mesmo ponto: sem escala possível, ficam no centro.
        return dict.fromkeys(positions, (0.5, 0.5))

    offset_x = (span - (max_x - min_x)) / 2
    offset_y = (span - (max_y - min_y)) / 2

    return {
        node: (
            (x - min_x + offset_x) / span,
            1.0 - (y - min_y + offset_y) / span,
        )
        for node, (x, y) in positions.items()
    }


class Simulator(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(meta)
        self.start_date = None
        self.step_size = None
        self.server = None
        self.sid = None
        self.eid = None
        # [OpenTES] Uma cópia: no original, `set_config` escrevia no dicionário
        # de módulo, de modo que a configuração de um cenário vazava para o
        # próximo simulador criado no mesmo processo.
        self.config = copy.deepcopy(default_config)

        self.time_resolution = None

        # [OpenTES] Corrige o nome (era `server_addrs`, nunca lido) e permite
        # que `init` preencha o endereço quando o simulador roda in-process.
        self.server_addr = None
        self.activate_ssl = None
        self.related_entities = []

    def configure(self, args):
        """Lê o endereço do webserver quando iniciado como subprocesso.

        Só é chamado no modo ``cmd`` do mosaik; in-process (``python``) o
        endereço vem dos parâmetros ``host``/``port`` do :meth:`init`.
        """
        self.server_addr = mosaik_api_v3._parse_addr(args["--serve"])

    def init(
        self,
        sid,
        time_resolution,
        start_date,
        step_size,
        host="127.0.0.1",
        port=8000,
        activate_ssl=False,
        keyfile=None,
        certfile=None,
    ):
        """Inicializa o simulador e sobe o servidor web.

        Args:
            sid: Identificador do simulador no mosaik.
            time_resolution: Resolução temporal do mosaik; só 1.0 é suportado.
            start_date: Instante inicial da simulação, ``'YYYY-MM-DD HH:MM:SS'``.
            step_size: Intervalo entre atualizações enviadas ao navegador, em
                segundos de simulação.
            host: Interface do servidor web. Use ``'0.0.0.0'`` para expor a
                visualização fora da máquina local (ex.: dentro do Docker).
            port: Porta do servidor web.
            activate_ssl: Serve por HTTPS/WSS; exige ``certfile``.
            keyfile: Arquivo da chave privada.
            certfile: Arquivo do certificado.
        """
        self.time_resolution = float(time_resolution)
        if self.time_resolution != 1.0:
            logger.warning(
                "%s got a time_resolution other than 1.0, which cannot be handled "
                "by this simulator.",
                sid,
            )
        self.sid = sid
        self.start_date = to_iso_local(start_date)
        self.step_size = step_size

        self.activate_ssl = activate_ssl
        if self.activate_ssl:
            assert certfile, "if `activate_ssl==True`, a certfile is required"
            ssl_filepaths = (certfile, keyfile)
        else:
            ssl_filepaths = None

        if self.server_addr is None:
            self.server_addr = (host, int(port))

        self.server = Server(self.server_addr, ssl_filepaths)
        yield self.server.start()

        scheme = "https" if self.activate_ssl else "http"
        shown_host = "127.0.0.1" if self.server_addr[0] in ("0.0.0.0", "") else self.server_addr[0]
        print(
            f"[OpenTES] Visualizacao disponivel em {scheme}://{shown_host}:{self.server_addr[1]}/"
        )

        return self.meta

    def create(self, num, model):
        if num != 1 or self.eid is not None:
            raise ValueError("Can only create one Topology instance.")
        if model != "Topology":
            raise ValueError(f'Unknown model: "{model}"')

        self.eid = "topo"

        return [{"eid": self.eid, "type": model, "rel": []}]

    def step(self, time, inputs, max_advance):
        # [OpenTES] `inputs[self.eid]` quebrava o passo em que nenhum simulador
        # conectado tinha dado novo a enviar; sem entrada, todos os nós ficam no
        # valor padrão.
        inputs = inputs.get(self.eid, {})

        if not self.server.topology:
            yield from self._build_topology()

        progress = yield self.mosaik.get_progress()

        self.server.set_new_data(time, progress, self._node_data(inputs))

        return time + self.step_size

    def _node_data(self, inputs):
        """Valores de cada nó neste passo, no formato que o navegador consome.

        [OpenTES] Cada nó passa a levar ``values`` — um valor por atributo
        declarado, na ordem de ``attrs`` — além do ``value`` agregado que o
        upstream já mandava. É o que permite ao frontend alternar entre as fases
        sem que a simulação seja refeita.

        Args:
            inputs: Entradas do mosaik para a entidade ``Topology``, no formato
                ``{atributo: {full_id: valor}}``.

        Returns:
            Mapa ``full_id -> {"value": escalar, "values": [por atributo]}``.
        """
        etype_conf = self.config["etypes"]
        node_data = {}

        for node in self.server.topology["nodes"]:
            node_id = node["name"]
            conf = etype_conf.get(node["type"], {})

            attrs = etype_attrs(conf)
            values = [inputs.get(attr, {}).get(node_id) for attr in attrs]
            value = aggregate_values(
                values,
                how=conf.get("aggregate", "first"),
                # Descartar zeros só faz sentido para grandezas por fase, onde o
                # zero é a fase que a barra não tem. Num atributo único — uma
                # potência, uma posição de tap — zero é um valor legítimo.
                ignore_zero=conf.get("ignore_zero", len(attrs) > 1),
            )

            if value is None:
                value = conf.get("default", 0)

            node_data[node_id] = {"value": value, "values": values}

        return node_data

    def finalize(self):
        # [OpenTES] In-process o servidor divide o laço de eventos com o mosaik,
        # então precisa ser fechado junto com a simulação.
        if self.server is not None:
            self.server.close()

    def set_config(self, cfg=None, **kwargs):
        if cfg is not None:
            self.config.update(cfg)
        self.config.update(**kwargs)

    def set_etypes(self, etype_conf):
        self.config["etypes"].update(etype_conf)

    def set_node_positions(self, positions):
        """Fixa nós em coordenadas conhecidas, em vez de deixá-los ao layout de forças.

        [OpenTES] Com as coordenadas das barras o alimentador é desenhado como
        no diagrama do circuito e não muda de forma a cada carregamento. Os nós
        sem coordenada continuam posicionados pela simulação de forças.

        Args:
            positions: Mapa ``full_id -> (x, y)`` no sistema de coordenadas do
                circuito (``'DSS-0.Bus-800'``, e não ``'Bus-800'``). A escala é
                irrelevante: o que importa são as posições relativas.
        """
        self.config["node_positions"].update(
            {node: (float(x), float(y)) for node, (x, y) in positions.items()}
        )

    def _build_topology(self):
        """Get all related entities, create the topology and set it to the
        web server."""
        logger.info("Creating topology ...")

        data = yield self.mosaik.get_related_entities(None)
        nxg = nx.Graph()
        nxg.add_nodes_from(data["nodes"].items())
        nxg.add_edges_from(data["edges"])

        # Required for get_data() calls.
        full_id = f"{self.sid}.{self.eid}"
        self.related_entities = [(e, nxg.nodes[e]["type"]) for e in nxg.neighbors(full_id)]

        self._clean_nx_graph(nxg)
        self.server.topology = self._make_d3js_topology(nxg)
        self.server.topology_ready.set()

        logger.info("Topology created")

    def _clean_nx_graph(self, nxg):
        """Remove and merge nodes and edges according to ``self.ignore_types``
        and ``self.merge_types``."""
        self._merge_nodes(nxg, [n for n in nxg.nodes if n in self.config["merge_nodes"]])

        nxg.remove_nodes_from(
            [
                n
                for n, d in nxg.nodes.items()
                if d["type"] in self.config["ignore_types"] or n in self.config["ignore_names"]
            ]
        )

        self._merge_nodes(
            nxg,
            [n for n, d in nxg.nodes.items() if d["type"] in self.config["merge_types"]],
        )

    def _merge_nodes(self, nxg, nodes):
        """Substitui cada nó por uma aresta ligando seus dois vizinhos.

        [OpenTES] O original abortava com ``AssertionError`` quando o nó não
        tinha exatamente dois vizinhos. Numa rede de distribuição isso acontece
        por motivos banais — uma linha com barra ausente, ou um elemento também
        ligado ao coletor de dados —, e derrubar a simulação inteira por causa
        do desenho não se justifica: o nó é mantido como está e o caso é
        avisado.

        Args:
            nxg: Grafo de entidades, alterado no lugar.
            nodes: Nós candidatos à fusão.
        """
        for node in nodes:
            neighbors = list(nxg.neighbors(node))

            if len(neighbors) != 2:
                print(
                    f"[OpenTES][AVISO] Nao foi possivel fundir '{node}' numa aresta: "
                    f"tem {len(neighbors)} vizinho(s) "
                    f"({', '.join(neighbors) or 'nenhum'}), e nao 2. "
                    "O no sera desenhado como esta."
                )
                continue

            nxg.remove_node(node)
            nxg.add_edge(*neighbors)

    def _make_d3js_topology(self, nxg):
        """Create the topology for D3JS."""
        # We have to use two loops to make sure "node_idx" is filled for the
        # second one.
        topology = {
            "start_date": self.start_date,
            "update_interval": self.step_size,
            "timeline_hours": self.config["timeline_hours"],
            "disable_heatmap": self.config["disable_heatmap"],
            "etypes": self.config["etypes"],
            "nodes": [],
            "links": [],
        }
        node_idx = {}
        # [OpenTES] Só as barras desenhadas entram na normalização: incluir uma
        # barra removida pelos filtros deslocaria a escala de todo o resto.
        positions = normalize_positions(
            {
                node: self.config["node_positions"][node]
                for node in nxg.nodes
                if node in self.config["node_positions"]
            }
        )

        for node, attrs in nxg.nodes.items():
            node_idx[node] = len(topology["nodes"])
            entry = {
                "name": node,
                "type": attrs["type"],
                "value": 0,
            }
            if node in positions:
                entry["x"], entry["y"] = positions[node]
            topology["nodes"].append(entry)

        for source, target in nxg.edges():
            topology["links"].append(
                {
                    "source": node_idx[source],
                    "target": node_idx[target],
                    "length": 0,  # TODO: Add eddge data['length'],
                }
            )

        return topology


def main():
    desc = "Simple visualization for mosaik simulations"
    extra_opts = [
        "-s HOST:PORT, --serve=HOST:PORT    ",
        ("            Host and port for the webserver [default: 127.0.0.1:8000]"),
    ]
    mosaik_api_v3.start_simulation(Simulator(), desc, extra_opts)


if __name__ == "__main__":
    main()
