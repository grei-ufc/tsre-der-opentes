"""Tests for the circuit graph builder.

The previous implementation classified buses by naming convention
(``bus_id == "sourcebus"``, ``endswith("r")``) and keyed edges by bus pair.
These tests pin the model-derived behaviour that replaced it.
"""

import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss.opendss_wrapper import OpenDSS
from simulators.opendss.topology_builder import build_graph, get_source_bus

DATA = (pathlib.Path(__file__).parent.parent / "data").resolve()
IEEE13 = DATA / "13Bus" / "IEEE13Nodeckt.dss"
IEEE13_PV = DATA / "13Bus" / "run_ieee13_cosim_pv_5min.dss"
IEEE123 = DATA / "123Bus" / "run_ieee123_cosim_5min.dss"


class Circuit:
    """Grafo e contagens capturados enquanto o circuito está compilado.

    Todas as instâncias de ``py_dss_interface.DSS()`` compartilham um único
    motor, então compilar o próximo circuito repõe o anterior. Guardar o
    wrapper entre testes daria leituras do circuito errado; por isso tudo o
    que os testes precisam é colhido aqui, de uma vez.
    """

    def __init__(self, wrapper):
        dss = wrapper.dss
        self.graph = build_graph(dss)
        self.source_bus = get_source_bus(dss)
        self.n_lines = dss.lines.count
        self.n_transformers = dss.transformers.count
        self.buses = {b.split(".")[0].lower() for b in dss.circuit.buses_names}


def _open(path):
    if not path.exists():
        pytest.skip(f"fixture not found: {path}")
    wrapper = OpenDSS(
        redirects=str(path),
        time_step=dt.timedelta(seconds=300),
        start_time=dt.datetime(2025, 1, 1),
    )
    if wrapper.dss.circuit.num_buses == 0:
        pytest.skip("circuit failed to compile")
    return Circuit(wrapper)


@pytest.fixture(scope="module")
def ieee13():
    return _open(IEEE13)


@pytest.fixture(scope="module")
def ieee13_pv():
    return _open(IEEE13_PV)


@pytest.fixture(scope="module")
def ieee123():
    return _open(IEEE123)


class TestSourceBus:
    """The reference bus comes from the Vsource, not from being named 'sourcebus'."""

    def test_ieee13_source_is_named_sourcebus(self, ieee13):
        assert ieee13.source_bus == "sourcebus"

    def test_ieee123_source_is_not_named_sourcebus(self, ieee123):
        """Bus '150' is the source; the old name check missed it entirely."""
        assert ieee123.source_bus == "150"

    def test_ieee123_source_is_marked_refbus(self, ieee123):
        assert ieee123.graph.nodes["150"].node_type == "refbus"

    def test_exactly_one_refbus(self, ieee123):
        refbuses = [n for n in ieee123.graph.nodes.values() if n.node_type == "refbus"]
        assert len(refbuses) == 1


class TestParallelElements:
    """Elements sharing a bus pair must not overwrite each other."""

    def test_every_transformer_becomes_an_edge(self, ieee13):
        edges = [e for e in ieee13.graph.edges.values() if e.edge_type == "transformer"]

        assert len(edges) == ieee13.n_transformers

    def test_phase_regulators_on_one_bus_pair_all_survive(self, ieee13):
        """reg1/reg2/reg3 all connect 650 to rg60; the old key kept only one."""
        ids = set(ieee13.graph.edges)

        assert {"transformer_reg1", "transformer_reg2", "transformer_reg3"} <= ids

    def test_every_line_becomes_an_edge(self, ieee13):
        edges = [e for e in ieee13.graph.edges.values() if e.edge_type == "line"]

        assert len(edges) == ieee13.n_lines

    @pytest.mark.parametrize("fixture", ["ieee13", "ieee123"])
    def test_edge_ids_are_unique(self, request, fixture):
        circuit = request.getfixturevalue(fixture)

        # NetworkGraph stores edges in a dict, so a collision silently drops
        # one. Counting the elements is what exposes it.
        expected = circuit.n_lines + circuit.n_transformers
        assert len(circuit.graph.edges) == expected


class TestNodeClassification:
    def test_regulated_bus_comes_from_regcontrol(self, ieee13):
        assert ieee13.graph.nodes["rg60"].node_type == "regulator_bus"

    def test_pv_buses_are_detected(self, ieee13_pv):
        pv_nodes = {n.id for n in ieee13_pv.graph.nodes.values() if n.node_type == "pv"}

        # PVs sit on 634, 692, 680, 646, 611, 652
        assert pv_nodes == {"634", "692", "680", "646", "611", "652"}

    def test_load_buses_are_detected(self, ieee13):
        load_nodes = [n for n in ieee13.graph.nodes.values() if n.node_type == "load"]
        assert load_nodes

    def test_every_bus_is_classified(self, ieee123):
        assert all(n.node_type for n in ieee123.graph.nodes.values())

    def test_node_ids_cover_the_circuit(self, ieee123):
        assert set(ieee123.graph.nodes) == ieee123.buses


class TestNodeMetadata:
    def test_buses_carry_coordinates_and_base(self, ieee13):
        node = ieee13.graph.nodes["634"]

        assert node.metadata["kv_base"] > 0
        assert node.metadata["num_nodes"] > 0
        assert "x" in node.metadata
        assert "y" in node.metadata

    def test_edges_carry_phase_count(self, ieee13):
        for edge in ieee13.graph.edges.values():
            assert edge.metadata["phases"] >= 1


DISABLED_CIRCUIT = """\
Redirect "{master}"
New Line.linha_desligada bus1=675 bus2=680 phases=3 length=0.1 enabled=no
New Line.chave_aberta bus1=671 bus2=684 phases=3 length=0.001 switch=yes
Open Line.chave_aberta 1
"""


@pytest.fixture(scope="module")
def circuito_com_desligados(tmp_path_factory):
    """The shipped circuits have no disabled elements or open switches."""
    if not IEEE13.exists():
        pytest.skip("IEEE13 fixture not found")

    path = tmp_path_factory.mktemp("topo") / "desligados.dss"
    path.write_text(DISABLED_CIRCUIT.format(master=IEEE13.as_posix()))
    return _open(path)


class TestDisabledElements:
    def test_disabled_line_is_not_an_edge(self, circuito_com_desligados):
        assert "line_linha_desligada" not in circuito_com_desligados.graph.edges

    def test_open_switch_stays_but_is_flagged(self, circuito_com_desligados):
        """An open switch still exists physically; the viewer can dash it."""
        edge = circuito_com_desligados.graph.edges.get("line_chave_aberta")
        assert edge is not None
        assert edge.metadata["open"] is True

    def test_closed_lines_are_not_flagged_open(self, circuito_com_desligados):
        assert circuito_com_desligados.graph.edges["line_650632"].metadata["open"] is False
