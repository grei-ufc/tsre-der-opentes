from dataclasses import dataclass, field


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

    metadata: dict = field(
        default_factory=dict
    )


@dataclass
class NetworkEdge:

    id: str

    source: str
    target: str

    edge_type: str

    metadata: dict = field(
        default_factory=dict
    )


class NetworkGraph:

    def __init__(self):

        self.nodes = {}
        self.edges = {}

    def add_node(self, node):

        self.nodes[node.id] = node

    def add_edge(self, edge):

        self.edges[edge.id] = edge

    @property
    def total_nodes(self):

        return len(self.nodes)

    @property
    def total_edges(self):

        return len(self.edges)