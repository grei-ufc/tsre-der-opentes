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
    NetworkElement,
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

# Classes cujos elementos entram no inventário, na ordem em que aparecem no
# grafo. O prefixo do identificador segue a convenção das arestas
# ('line_650632'), e mantém um PV e um Storage homônimos distintos.
ELEMENT_TYPES = ("pv", "storage")


def parse_bus(bus_reference):
    """Separa a referência de barra do OpenDSS em nome e nós.

    Args:
        bus_reference: Barra como o OpenDSS reporta, com ou sem nós
            (``'671.1.2.3'``, ``'646.2'``, ``'634'``).

    Returns:
        Tupla ``(nome, nós)``. A lista de nós fica vazia quando a barra não
        traz sufixo, caso em que o OpenDSS assume todas as fases do elemento.
        O nome sai como o OpenDSS o reporta; normalizar fica a cargo de quem
        chama, porque só o grafo trabalha em minúsculas.
    """
    name, _, nodes = str(bus_reference or "").partition(".")
    if not nodes:
        return name, []
    return name, [int(n) for n in nodes.split(".") if n.isdigit()]


def resolve_nodes(nodes, phases):
    """Completa os nós implícitos de uma barra sem sufixo.

    ``Bus1=634`` num elemento trifásico significa ``634.1.2.3``; o OpenDSS
    simplesmente omite o sufixo. Sem essa resolução o consumidor receberia uma
    lista vazia e teria de tratar o caso à parte.

    Args:
        nodes: Nós explícitos vindos de :func:`parse_bus`.
        phases: Número de fases do elemento.

    Returns:
        Lista de nós; os ``phases`` primeiros quando não havia sufixo.
    """
    if nodes:
        return nodes
    return list(range(1, max(int(phases or 0), 0) + 1))


def _bus_name(bus_reference):
    """Nome da barra sem sufixo de nós, normalizado para minúsculas."""
    return parse_bus(bus_reference)[0].lower()


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


def _storage_names(dss):
    """Nomes dos Storage do circuito, sem o prefixo da classe.

    A interface tipada ``dss.storages`` não é confiável nesta versão do
    ``py_dss_interface``; o pacote inteiro enumera baterias pela classe ativa.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.

    Returns:
        Lista de nomes, vazia quando o circuito não tem baterias.
    """
    dss.circuit.set_active_class("Storage")

    if dss.active_class.count == 0:
        return []

    names = dss.active_class.names
    if not names or names[0] is None or str(names[0]).lower() == "none":
        return []

    return [str(name).split(".")[-1] for name in names]


def get_storage_buses(dss):
    """Barras com Storage conectado."""
    return {element.bus for element in get_storage_elements(dss)}


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
# ELEMENTOS
# =====================================================


def _element_at_active(dss, name, element_type):
    """Monta o :class:`NetworkElement` do elemento já ativo no circuito."""
    bus_name, nodes = parse_bus(dss.cktelement.bus_names[0])
    phases = dss.cktelement.num_phases

    return NetworkElement(
        id=f"{element_type}_{name}",
        name=name,
        element_type=element_type,
        bus=bus_name.lower(),
        nodes=resolve_nodes(nodes, phases),
        phases=phases,
    )


def get_pv_elements(dss):
    """Um elemento por PVSystem habilitado."""
    elements = []

    if not dss.pvsystems.count:
        return elements

    index = dss.pvsystems.first()
    while index > 0:
        if dss.cktelement.is_enabled:
            elements.append(_element_at_active(dss, dss.pvsystems.name, "pv"))
        index = dss.pvsystems.next()

    return elements


def get_storage_elements(dss):
    """Um elemento por Storage habilitado."""
    elements = []

    for name in _storage_names(dss):
        dss.circuit.set_active_element(f"Storage.{name}")
        if dss.cktelement.is_enabled:
            elements.append(_element_at_active(dss, name, "storage"))

    return elements


def collect_elements(dss):
    """Inventário dos elementos pendurados nas barras.

    O ``node_type`` da barra diz que há geração fotovoltaica ali, mas não
    quantos inversores são nem em que fases. Três PVs monofásicos numa barra
    trifásica são indistinguíveis de um único PV trifásico olhando só o tipo
    da barra.

    Args:
        dss: Instância ativa de ``py_dss_interface.DSS``.

    Returns:
        Lista de :class:`~.graph_model.NetworkElement`, PVs antes de Storages.
    """
    return get_pv_elements(dss) + get_storage_elements(dss)


def index_by_bus(elements):
    """Agrupa os identificadores dos elementos por barra.

    Args:
        elements: Saída de :func:`collect_elements`.

    Returns:
        Mapa de barra para ``{tipo: [ids]}``, com uma entrada por barra que
        tenha ao menos um elemento.
    """
    index = {}

    for element in elements:
        attached = index.setdefault(element.bus, {t: [] for t in ELEMENT_TYPES})
        attached.setdefault(element.element_type, []).append(element.id)

    return index


def add_elements(graph, elements):
    """Adiciona os elementos coletados ao grafo."""
    for element in elements:
        graph.add_element(element)


# =====================================================
# NÓS
# =====================================================


def add_nodes(graph, dss, attachments, elements=()):
    """Adiciona uma entrada por barra, com tipo, coordenadas e elementos.

    Args:
        graph: Grafo em construção.
        dss: Instância ativa de ``py_dss_interface.DSS``.
        attachments: Mapa de classificação, de :func:`collect_attachments`.
        elements: Inventário de :func:`collect_elements`, indexado por barra
            para dar ao consumidor um caminho direto barra → elementos.
    """
    attached_by_bus = index_by_bus(elements)

    for bus in dss.circuit.buses_names:
        bus_id = _bus_name(bus)
        dss.circuit.set_active_bus(bus)
        # Sem coordenada no BusCoords, o OpenDSS reporta (0, 0). Esse zero não é
        # uma posição, e quem desenhasse a barra ali a poria na origem.
        has_coords = bool(dss.bus.coord_defined)

        graph.add_node(
            NetworkNode(
                id=bus_id,
                label=bus,
                node_type=get_node_type(bus_id, attachments),
                metadata={
                    "kv_base": dss.bus.kv_base,
                    "num_nodes": dss.bus.num_nodes,
                    "nodes": list(dss.bus.nodes),
                    "x": dss.bus.x if has_coords else None,
                    "y": dss.bus.y if has_coords else None,
                    "coord_defined": has_coords,
                    # Toda barra traz a chave, mesmo vazia: o consumidor
                    # itera sem antes checar se ela existe.
                    "attached": attached_by_bus.get(bus_id, {t: [] for t in ELEMENT_TYPES}),
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
        :class:`~.graph_model.NetworkGraph` com uma barra por nó, um elemento
        série por aresta e um PVSystem ou Storage por elemento.
    """
    graph = NetworkGraph()

    # A coleta mexe no elemento ativo do circuito e a montagem dos nós mexe na
    # barra ativa; varrer tudo antes de construir evita que um passo reponha o
    # estado de que o outro depende.
    elements = collect_elements(dss)
    attachments = collect_attachments(dss)

    add_nodes(graph, dss, attachments, elements)
    add_elements(graph, elements)
    add_line_edges(graph, dss)
    add_transformer_edges(graph, dss)

    return graph
