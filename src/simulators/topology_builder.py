from .graph_model import (
    NetworkGraph,
    NetworkNode,
    NetworkEdge,
)


# =====================================================
# COLETA DE INFORMAÇÕES
# =====================================================

def get_load_buses(dss):

    buses = set()

    try:

        if dss.loads.first():

            dss.loads.first()

            for _ in range(dss.loads.count):
                bus = (
                    dss.cktelement.bus_names[0].split(".")[0]
                )

                buses.add(bus)
                dss.loads.next()


    except Exception:

        pass

    return buses

def get_pv_buses(dss):

    buses = set()

    try:

        if dss.pvsystems.first():

            dss.pvsystems.first()

            for _ in range(dss.pvsystems.count):
                bus = (
                    dss.cktelement.bus_names[0].split(".")[0]
                )

                buses.add(bus)
                dss.pvsystems.next()


    except Exception:

        pass

    return buses

def get_transformer_buses(dss):

    buses = set()

    try:

        if dss.transformers.first():

            dss.transformers.first()

            for _ in range(dss.transformers.count):

                for bus in dss.cktelement.bus_names:

                    buses.add(
                        bus.split(".")[0].lower()
                    )

                dss.transformers.next()

    except Exception:

        pass

    return buses

# =====================================================
# CLASSIFICAÇÃO
# =====================================================

def get_node_type(
    bus_id,
    load_buses,
    pv_buses,
    transformer_buses,
):

    if bus_id == "sourcebus":
        return "refbus"

    if bus_id.startswith("mid"):
        return "virtual_bus"

    if bus_id.endswith("r"):
        return "regulator_bus"

    if bus_id in pv_buses:
        return "pv"

    if bus_id in load_buses:
        return "load"

    if bus_id in transformer_buses:
        return "transformer_bus"

    return "bus"

# =====================================================
# NÓS
# =====================================================

def add_nodes(
    graph,
    dss,
    load_buses,
    pv_buses,
    transformer_buses,
):

    for bus in dss.circuit.buses_names:

        bus_id = bus.lower()

        graph.add_node(
            NetworkNode(
                id=bus_id,
                label=bus,
                node_type=get_node_type(
                    bus_id,
                    load_buses,
                    pv_buses,
                    transformer_buses,
                ),
            )
        )


# =====================================================
# ARESTAS - LINHAS
# =====================================================

def add_line_edges(
    graph,
    dss,
):

    if dss.lines.first():
        
        dss.lines.first()

        for _ in range(dss.lines.count):

            bus1 = (
            dss.lines.bus1()
            .split(".")[0]
            .lower()
            )

            bus2 = (
                dss.lines.bus2()
                .split(".")[0]
                .lower()
            )

            graph.add_edge(
                NetworkEdge(
                    id=f"line_{dss.lines.name()}",
                    source=bus1,
                    target=bus2,
                    edge_type="line",
                )
            )

            dss.lines.next()



# =====================================================
# ARESTAS - TRANSFORMADORES
# =====================================================

def add_transformer_edges(
    graph,
    dss,
):

    if not dss.transformers.first():
        return

    added = set()

    while True:

        buses = dss.CktElement.BusNames()

        if len(buses) >= 2:

            bus1 = buses[0].split(".")[0].lower()
            bus2 = buses[1].split(".")[0].lower()

            edge_id = f"{bus1}_{bus2}"

            if edge_id not in added:

                graph.add_edge(
                    NetworkEdge(
                        id=edge_id,
                        source=bus1,
                        target=bus2,
                        edge_type="transformer",
                    )
                )

                added.add(edge_id)

        if dss.Transformers.Next() == 0:
            break


# =====================================================
# BUILD
# =====================================================

def build_graph(dss):

    graph = NetworkGraph()

    load_buses = get_load_buses(dss)

    pv_buses = get_pv_buses(dss)

    transformer_buses = get_transformer_buses(
        dss
    )

    add_nodes(
        graph,
        dss,
        load_buses,
        pv_buses,
        transformer_buses,
    )

    add_line_edges(
        graph,
        dss,
    )

    add_transformer_edges(
        graph,
        dss,
    )

    return graph