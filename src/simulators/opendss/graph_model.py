from dataclasses import asdict, dataclass, field


@dataclass
class NetworkNode:
    """
    Nó da rede elétrica.

    Inicialmente teremos apenas:

    - refbus
    - bus
    - load
    - pv
    """

    id: str
    label: str
    node_type: str

    voltage_pu: float | None = None

    metadata: dict = field(default_factory=dict)


@dataclass
class NetworkEdge:
    id: str

    source: str
    target: str

    edge_type: str

    metadata: dict = field(default_factory=dict)


@dataclass
class NetworkElement:
    """Elemento conectado a uma barra (PVSystem, Storage).

    Enquanto :class:`NetworkEdge` liga duas barras, um elemento pendura-se numa
    só. O ``node_type`` da barra diz apenas que existe geração fotovoltaica ali;
    é aqui que se sabe quantos inversores são, como se chamam e em que fases
    estão.

    ``bus`` segue a mesma normalização de :attr:`NetworkNode.id` — minúsculas,
    sem sufixo de nós — para que o vínculo elemento/barra seja um join direto.
    """

    id: str
    name: str
    element_type: str

    bus: str
    nodes: list[int] = field(default_factory=list)
    phases: int = 0

    # Reservado para os parâmetros nominais (pmpp, kva, kwh_rated...), que hoje
    # trafegam pelo extra_info das entidades mosaik e não por este grafo.
    metadata: dict = field(default_factory=dict)


class NetworkGraph:
    def __init__(self):

        self.nodes = {}
        self.edges = {}
        self.elements = {}

    def add_node(self, node):

        self.nodes[node.id] = node

    def add_edge(self, edge):

        self.edges[edge.id] = edge

    def add_element(self, element):

        self.elements[element.id] = element

    @property
    def total_nodes(self):

        return len(self.nodes)

    @property
    def total_edges(self):

        return len(self.edges)

    @property
    def total_elements(self):

        return len(self.elements)


def serialize_graph(graph):
    """Converte o grafo para o dicionário consumido pela visualização.

    Os três mapas viram vetores: a plataforma indexa pelos campos ``id`` e não
    precisa das chaves. Única fonte do formato — o wrapper e o script
    ``util/topologia`` serializam pelo mesmo caminho.

    Args:
        graph: :class:`NetworkGraph` montado.

    Returns:
        Dicionário com as chaves ``nodes``, ``edges`` e ``elements``.
    """
    return {
        "nodes": [asdict(node) for node in graph.nodes.values()],
        "edges": [asdict(edge) for edge in graph.edges.values()],
        "elements": [asdict(element) for element in graph.elements.values()],
    }
