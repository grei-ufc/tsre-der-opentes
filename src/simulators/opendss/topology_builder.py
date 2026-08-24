"""Constrói o grafo do circuito a partir do modelo OpenDSS.

Tudo aqui é derivado do modelo compilado — quem está ligado a cada barra, qual
barra alimenta o circuito, quais transformadores existem. A versão anterior
classificava os nós por convenção de nome (``bus_id == "sourcebus"``,
``endswith("r")``, ``startswith("mid")``), o que só funcionava nos alimentadores
do IEEE que seguem essa convenção: no IEEE123 a barra de referência chama-se
``150`` e era classificada como uma barra comum de transformador.
"""

from .graph_model import (
    NetworkEdge,
    NetworkGraph,
    NetworkNode,
)

# Ordem de precedência ao classificar uma barra que atende a mais de um
# critério (uma barra com carga e PV é classificada como 'pv').
NODE_TYPE_PRECEDENCE = (
    "refbus",
    "regulator_bus",
    "pv",
    "storage",
    "load",
    "transformer_bus",
)


def _bus_name(bus_reference):
    """Nome da barra sem sufixo de nós, normalizado para minúsculas."""
    return str(bus_reference).split(".")[0].lower()


# =====================================================
# COLETA DE INFORMAÇÕES
# =====================================================


def get_source_bus(dss):
    """Barra alimentadora do circuito, lida do ``Vsource``.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.

    Returns:
        Nome da barra em minúsculas, ou ``""`` se não houver ``Vsource``.
    """
    if not dss.vsources.count:
        return ""

    dss.vsources.first()
    dss.circuit.set_active_element(f"Vsource.{dss.vsources.name}")
    return _bus_name(dss.cktelement.bus_names[0])


def _buses_of(dss, iterator, all_terminals=False):
    """Barras ocupadas pelos elementos habilitados de uma classe.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.
        iterator: Interface tipada da classe (``dss.loads``, ``dss.pvsystems``...).
        all_terminals: Se ``True``, considera todas as barras do elemento;
            caso contrário, apenas a primeira.

    Returns:
        Conjunto de nomes de barra em minúsculas.
    """
    buses = set()

    if not iterator.count:
        return buses

    index = iterator.first()
    while index > 0:
        if dss.cktelement.is_enabled:
            names = dss.cktelement.bus_names if all_terminals else dss.cktelement.bus_names[:1]
            buses.update(_bus_name(name) for name in names)
        index = iterator.next()

    return buses


def get_load_buses(dss):
    """Barras com carga conectada."""
    return _buses_of(dss, dss.loads)


def get_pv_buses(dss):
    """Barras com PVSystem conectado."""
    return _buses_of(dss, dss.pvsystems)


def get_storage_buses(dss):
    """Barras com Storage conectado."""
    return _buses_of(dss, dss.storages)


def get_transformer_buses(dss):
    """Barras que são terminal de algum transformador."""
    return _buses_of(dss, dss.transformers, all_terminals=True)


def get_regulated_buses(dss):
    """Barras reguladas, derivadas dos ``RegControl`` e seus transformadores.

    Substitui a heurística ``bus_id.endswith("r")``, que dependia da convenção
    de nomes dos alimentadores do IEEE.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.

    Returns:
        Conjunto de nomes de barra em minúsculas.
    """
    buses = set()

    if not dss.regcontrols.count:
        return buses

    for name in dss.regcontrols.names:
        dss.regcontrols.name = name
        transformer = dss.regcontrols.transformer
        winding = dss.regcontrols.winding

        dss.circuit.set_active_element(f"Transformer.{transformer}")
        bus_names = dss.cktelement.bus_names
        if 1 <= winding <= len(bus_names):
            buses.add(_bus_name(bus_names[winding - 1]))

    return buses


# =====================================================
# CLASSIFICAÇÃO
# =====================================================


def get_node_type(bus_id, attachments):
    """Classifica uma barra pelo que está de fato ligado a ela.

    Args:
        bus_id: Nome da barra em minúsculas.
        attachments: Mapa de ``node_type`` para o conjunto de barras que o
            satisfazem, conforme :data:`NODE_TYPE_PRECEDENCE`.

    Returns:
        O primeiro tipo de :data:`NODE_TYPE_PRECEDENCE` que a barra satisfaz,
        ou ``"bus"``.
    """
    for node_type in NODE_TYPE_PRECEDENCE:
        if bus_id in attachments.get(node_type, ()):
            return node_type
    return "bus"


def collect_attachments(dss):
    """Reúne, por tipo, o conjunto de barras que o satisfazem."""
    source = get_source_bus(dss)
    return {
        "refbus": {source} if source else set(),
        "regulator_bus": get_regulated_buses(dss),
        "pv": get_pv_buses(dss),
        "storage": get_storage_buses(dss),
        "load": get_load_buses(dss),
        "transformer_bus": get_transformer_buses(dss),
    }


# =====================================================
# NÓS
# =====================================================


def add_nodes(graph, dss, attachments):
    """Adiciona uma entrada por barra, com tipo e coordenadas."""
    for bus in dss.circuit.buses_names:
        bus_id = _bus_name(bus)
        dss.circuit.set_active_bus(bus)

        graph.add_node(
            NetworkNode(
                id=bus_id,
                label=bus,
                node_type=get_node_type(bus_id, attachments),
                metadata={
                    "kv_base": dss.bus.kv_base,
                    "num_nodes": dss.bus.num_nodes,
                    "nodes": list(dss.bus.nodes),
                    "x": dss.bus.x,
                    "y": dss.bus.y,
                    "coord_defined": bool(dss.bus.coord_defined),
                },
            )
        )


# =====================================================
# ARESTAS
# =====================================================


def _add_element_edges(graph, dss, iterator, edge_type, prefix):
    """Adiciona uma aresta por elemento habilitado de uma classe.

    O identificador da aresta vem do **nome do elemento**, não do par de barras.
    Usar o par fazia elementos em paralelo colidirem e se sobrescreverem: os
    três reguladores de fase do IEEE13 ligam ``650`` a ``rg60`` e viravam uma
    aresta só, perdendo dois.

    Args:
        graph: Grafo em construção.
        dss: Instância ativa de ``py_dss_interface.DSS``.
        iterator: Interface tipada da classe.
        edge_type: Valor de ``edge_type`` na aresta.
        prefix: Prefixo do identificador da aresta.
    """
    if not iterator.count:
        return

    index = iterator.first()
    while index > 0:
        if not dss.cktelement.is_enabled:
            index = iterator.next()
            continue

        bus_names = dss.cktelement.bus_names
        if len(bus_names) >= 2:
            bus1 = _bus_name(bus_names[0])
            bus2 = _bus_name(bus_names[1])

            if bus1 != bus2:
                name = iterator.name
                graph.add_edge(
                    NetworkEdge(
                        id=f"{prefix}_{name}",
                        source=bus1,
                        target=bus2,
                        edge_type=edge_type,
                        metadata={
                            "name": name,
                            "phases": dss.cktelement.num_phases,
                            # Uma chave aberta continua existindo fisicamente,
                            # mas não conduz: o consumidor pode desenhá-la
                            # tracejada em vez de a aresta sumir do grafo.
                            "open": bool(dss.cktelement.is_terminal_open(1)),
                        },
                    )
                )

        index = iterator.next()


def add_line_edges(graph, dss):
    """Adiciona uma aresta por linha habilitada."""
    _add_element_edges(graph, dss, dss.lines, "line", "line")


def add_transformer_edges(graph, dss):
    """Adiciona uma aresta por transformador habilitado."""
    _add_element_edges(graph, dss, dss.transformers, "transformer", "transformer")


# =====================================================
# BUILD
# =====================================================


def build_graph(dss):
    """Monta o grafo do circuito compilado.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.

    Returns:
        :class:`~.graph_model.NetworkGraph` com uma barra por nó e um elemento
        série por aresta.
    """
    graph = NetworkGraph()

    attachments = collect_attachments(dss)

    add_nodes(graph, dss, attachments)
    add_line_edges(graph, dss)
    add_transformer_edges(graph, dss)

    return graph
