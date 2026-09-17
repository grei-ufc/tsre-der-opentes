"""Tests for the circuit graph builder.

The previous implementation classified buses by naming convention
(``bus_id == "sourcebus"``, ``endswith("r")``) and keyed edges by bus pair.
These tests pin the model-derived behaviour that replaced it.
"""

import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss.graph_model import serialize_graph
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
        self.n_pvsystems = dss.pvsystems.count
        self.buses = {b.split(".")[0].lower() for b in dss.circuit.buses_names}
        self.switches = {
            name.lower(): {
                "r1": wrapper.get_property(name, "r1", "Line"),
                "length": wrapper.get_property(name, "length", "Line"),
            }
            for name in dss.lines.names
            if wrapper.get_property(name, "switch", "Line") == "True"
        }
        self.edges_by_name = {e.metadata["name"].lower(): e for e in self.graph.edges.values()}


def _open(path):
    if not path.exists():
        pytest.skip(f"fixture not found: {path}")
    wrapper = OpenDSS(
        topofile=str(path),
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


# Uma barra fora do arquivo de coordenadas. Antes o IEEE123 fornecia duas de
# graça (`300_open` e `94_open`, artefatos de como as chaves normalmente abertas
# eram modeladas), mas ao adotar o bloco de chaves com `switch=yes` elas deixaram
# de existir: agora as chaves ligam as barras reais 300 e 94, que constam do
# BusCoords.dat. O caso continua valendo, então o circuito passa a criá-lo.
UNLOCATED_BUS_CIRCUIT = """\
Redirect "{master}"
New Line.ramal_novo phases=3 bus1=675 bus2=barra_sem_coordenada linecode=mtx601 length=0.1 units=mi
Calcvoltagebases
Solve
"""


@pytest.fixture(scope="module")
def sem_coordenada(tmp_path_factory):
    if not IEEE13.exists():
        pytest.skip(f"fixture not found: {IEEE13}")

    path = tmp_path_factory.mktemp("coords") / "sem_coord.dss"
    path.write_text(UNLOCATED_BUS_CIRCUIT.format(master=IEEE13.as_posix()))
    return _open(path)


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


class TestSwitchesInTheFeeder:
    """As oito chaves do IEEE123, declaradas com ``switch=yes``.

    O alimentador original as define como linhas curtas quaisquer, e o próprio
    arquivo observa que poderiam ser declaradas com a propriedade. Sem ela não há
    como distinguir uma chave de um trecho curto de linha. O bloco de chaves do
    ``IEEE123Switches.dss`` foi adotado no master por isso.
    """

    SWITCHES = frozenset({"sw1", "sw2", "sw3", "sw4", "sw5", "sw6", "sw7", "sw8"})
    # Normalmente abertas, pelo terminal 2.
    ABERTAS = frozenset({"sw7", "sw8"})

    def test_all_eight_are_declared_as_switches(self, ieee123):
        assert set(ieee123.switches) == self.SWITCHES

    def test_the_normally_open_ones_are_open(self, ieee123):
        """Abertas pelo terminal 2 — o caso que uma leitura do terminal 1 perde."""
        abertas = {n for n in self.SWITCHES if ieee123.edges_by_name[n].metadata["open"]}
        assert abertas == self.ABERTAS

    def test_they_connect_real_buses(self, ieee123):
        """Ligam 300 e 94, e não as fictícias 300_open/94_open de antes.

        É o que devolve a coordenada às duas últimas barras sem posição do
        alimentador; ver ``test_every_ieee123_bus_is_located``.
        """
        sw7 = ieee123.edges_by_name["sw7"]
        sw8 = ieee123.edges_by_name["sw8"]

        assert {sw7.source, sw7.target} == {"151", "300"}
        assert {sw8.source, sw8.target} == {"54", "94"}

    def test_the_impedance_survived_the_declaration(self, ieee123):
        """``switch=yes`` sobrescreve a impedância por um padrão do OpenDSS.

        O ``.dss`` a repõe logo depois, na mesma linha. Se a ordem se inverter,
        o circuito muda sem que nada acuse — as chaves ficariam com a impedância
        default em vez dos 1e-3 ohm do alimentador.
        """
        for name in self.SWITCHES:
            assert ieee123.switches[name]["r1"] == pytest.approx(1e-3), name
            assert ieee123.switches[name]["length"] == pytest.approx(0.001), name


class TestNodeMetadata:
    def test_buses_carry_coordinates_and_base(self, ieee13):
        node = ieee13.graph.nodes["634"]

        assert node.metadata["kv_base"] > 0
        assert node.metadata["num_nodes"] > 0
        assert "x" in node.metadata
        assert "y" in node.metadata

    def test_defined_coordinates_are_numbers(self, ieee123):
        located = [n for n in ieee123.graph.nodes.values() if n.metadata["coord_defined"]]
        assert located

        for node in located:
            assert isinstance(node.metadata["x"], float)
            assert isinstance(node.metadata["y"], float)

    def test_missing_coordinates_are_null_not_origin(self, sem_coordenada):
        """Barra fora do BusCoords: o OpenDSS diz (0, 0), que não é uma posição."""
        unlocated = [
            n for n in sem_coordenada.graph.nodes.values() if not n.metadata["coord_defined"]
        ]
        assert unlocated, "a fixture deveria ter uma barra sem coordenada"

        for node in unlocated:
            assert node.metadata["x"] is None
            assert node.metadata["y"] is None

    def test_missing_coordinates_serialize_as_json_null(self, sem_coordenada):
        payload = json.loads(json.dumps(serialize_graph(sem_coordenada.graph), allow_nan=False))
        unlocated = [n for n in payload["nodes"] if not n["metadata"]["coord_defined"]]

        assert unlocated
        assert all(n["metadata"]["x"] is None and n["metadata"]["y"] is None for n in unlocated)

    def test_every_ieee123_bus_is_located(self, ieee123):
        """O alimentador inteiro tem coordenada real, desde a adoção das chaves.

        As duas barras que faltavam eram as fictícias ``300_open``/``94_open``;
        com as chaves normalmente abertas ligando as barras reais ``300`` e
        ``94``, não sobra nenhuma fora do ``BusCoords.dat``.
        """
        unlocated = [n.id for n in ieee123.graph.nodes.values() if not n.metadata["coord_defined"]]
        assert unlocated == []

    def test_edges_carry_phase_count(self, ieee13):
        for edge in ieee13.graph.edges.values():
            assert edge.metadata["phases"] >= 1


class TestElements:
    """Cada PV/Storage vira um elemento próprio, com a fase em que está.

    O ``node_type`` da barra só diz que existe geração fotovoltaica ali: três
    PVs monofásicos numa barra trifásica ficavam indistinguíveis de um único
    PV trifásico.
    """

    def test_every_pvsystem_becomes_an_element(self, ieee13_pv):
        pvs = [e for e in ieee13_pv.graph.elements.values() if e.element_type == "pv"]

        assert len(pvs) == ieee13_pv.n_pvsystems

    def test_element_bus_joins_with_a_node(self, ieee13_pv):
        """``element.bus`` usa a normalização de ``node.id``; o join é direto."""
        for element in ieee13_pv.graph.elements.values():
            assert element.bus in ieee13_pv.graph.nodes

    def test_single_phase_pv_keeps_its_own_phase(self, ieee13_pv):
        """pv-4 está em 646.2, não na barra inteira."""
        pv = ieee13_pv.graph.elements["pv_pv-4"]

        assert pv.bus == "646"
        assert pv.phases == 1
        assert pv.nodes == [2]

    def test_bus_indexes_the_elements_attached_to_it(self, ieee13_pv):
        attached = ieee13_pv.graph.nodes["646"].metadata["attached"]

        assert attached["pv"] == ["pv_pv-4"]
        assert attached["storage"] == []

    def test_every_bus_carries_the_index(self, ieee13_pv):
        """Vazia ou não, a chave existe: o consumidor itera sem checar."""
        for node in ieee13_pv.graph.nodes.values():
            assert set(node.metadata["attached"]) == {"pv", "storage"}

    def test_buses_do_not_share_one_index_instance(self, ieee13_pv):
        """Um dict compartilhado faria um PV aparecer em todas as barras."""
        vazias = [
            n.metadata["attached"]
            for n in ieee13_pv.graph.nodes.values()
            if not n.metadata["attached"]["pv"]
        ]

        assert len({id(a) for a in vazias}) == len(vazias)

    def test_circuit_without_der_has_no_elements(self, ieee13):
        assert ieee13.graph.elements == {}
        assert all(
            n.metadata["attached"] == {"pv": [], "storage": []} for n in ieee13.graph.nodes.values()
        )


STORAGE_CIRCUIT = """\
Redirect "{master}"
New Storage.bat1 bus1=675.1 phases=1 kV=2.4 kWrated=50 kWhrated=200
New Storage.bat_desligada bus1=680 phases=3 kV=4.16 kWrated=10 kWhrated=40 enabled=no
"""


@pytest.fixture(scope="module")
def circuito_com_storage(tmp_path_factory):
    """Nenhum circuito de data/ tem bateria; o caminho de Storage exige um."""
    if not IEEE13.exists():
        pytest.skip("IEEE13 fixture not found")

    path = tmp_path_factory.mktemp("topo") / "storage.dss"
    path.write_text(STORAGE_CIRCUIT.format(master=IEEE13.as_posix()))
    return _open(path)


class TestStorage:
    def test_storage_becomes_an_element(self, circuito_com_storage):
        bat = circuito_com_storage.graph.elements["storage_bat1"]

        assert bat.element_type == "storage"
        assert bat.bus == "675"
        assert bat.phases == 1
        assert bat.nodes == [1]

    def test_storage_bus_is_classified(self, circuito_com_storage):
        assert circuito_com_storage.graph.nodes["675"].node_type == "storage"

    def test_storage_bus_indexes_the_battery(self, circuito_com_storage):
        attached = circuito_com_storage.graph.nodes["675"].metadata["attached"]

        assert attached["storage"] == ["storage_bat1"]

    def test_disabled_storage_is_not_an_element(self, circuito_com_storage):
        assert "storage_bat_desligada" not in circuito_com_storage.graph.elements

    def test_disabled_storage_does_not_classify_its_bus(self, circuito_com_storage):
        assert circuito_com_storage.graph.nodes["680"].node_type != "storage"

    def test_storage_scan_does_not_break_the_other_classes(self, circuito_com_storage):
        """Enumerar baterias troca a classe ativa do OpenDSS.

        Cargas e transformadores são varridos logo depois, pelas interfaces
        tipadas; se a troca de classe as atrapalhasse, o circuito inteiro sairia
        classificado como ``bus``.
        """
        tipos = {n.node_type for n in circuito_com_storage.graph.nodes.values()}

        assert {"load", "refbus", "transformer_bus"} <= tipos
        assert len(circuito_com_storage.graph.edges) == (
            circuito_com_storage.n_lines + circuito_com_storage.n_transformers
        )


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
