"""Tests for the circuit graph builder.

The first implementation classified buses by naming convention
(``bus_id == "sourcebus"``, ``endswith("r")``) and keyed edges by bus pair. The
second classified them by what was attached, through a precedence of its own.
The graph now classifies nothing: these tests pin that it reports what the
compiled model declares — buses, series elements, attached elements — each fact
in one place only.
"""

import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss.graph_model import SCHEMA_VERSION, serialize_graph
from simulators.opendss.opendss_wrapper import OpenDSS
from simulators.opendss.topology_builder import build_graph

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
        self.payload = json.loads(json.dumps(serialize_graph(self.graph), allow_nan=False))
        self.n_lines = dss.lines.count
        self.n_transformers = dss.transformers.count
        self.n_pvsystems = dss.pvsystems.count
        self.n_loads = dss.loads.count
        self.buses = {b.split(".")[0].lower() for b in dss.circuit.buses_names}
        self.switches = {
            name.lower(): {
                "r1": wrapper.get_property(name, "r1", "Line"),
                "length": wrapper.get_property(name, "length", "Line"),
            }
            for name in dss.lines.names
            if wrapper.get_property(name, "switch", "Line") == "True"
        }
        self.edges_by_name = {e.name.lower(): e for e in self.graph.edges.values()}

    def of_type(self, element_type):
        """Elementos de um tipo, na ordem do grafo."""
        return [e for e in self.graph.elements.values() if e.type == element_type]

    def types_at(self, bus):
        """Tipos dos elementos pendurados numa barra."""
        return {e.type for e in self.graph.elements.values() if e.bus == bus}


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


class TestSource:
    """The feeding bus comes from the Vsource element, not from being named 'sourcebus'."""

    def test_ieee13_source_sits_on_sourcebus(self, ieee13):
        assert [e.bus for e in ieee13.of_type("Vsource")] == ["sourcebus"]

    def test_ieee123_source_is_not_named_sourcebus(self, ieee123):
        """Bus '150' is the source; the old name check missed it entirely."""
        assert [e.bus for e in ieee123.of_type("Vsource")] == ["150"]

    def test_the_source_is_three_phase(self, ieee123):
        (source,) = ieee123.of_type("Vsource")

        assert source.phases == 3
        assert source.nodes == [1, 2, 3]


class TestParallelElements:
    """Elements sharing a bus pair must not overwrite each other."""

    def test_every_transformer_becomes_an_edge(self, ieee13):
        edges = [e for e in ieee13.graph.edges.values() if e.type == "Transformer"]

        assert len(edges) == ieee13.n_transformers

    def test_phase_regulators_on_one_bus_pair_all_survive(self, ieee13):
        """reg1/reg2/reg3 all connect 650 to rg60; the old key kept only one."""
        keys = set(ieee13.graph.edges)

        assert {("Transformer", "reg1"), ("Transformer", "reg2"), ("Transformer", "reg3")} <= keys

    def test_every_line_becomes_an_edge(self, ieee123):
        """Lines and switches are both OpenDSS ``Line``s."""
        edges = [e for e in ieee123.graph.edges.values() if e.type in ("Line", "Switch")]

        assert len(edges) == ieee123.n_lines

    @pytest.mark.parametrize("fixture", ["ieee13", "ieee123"])
    def test_edge_keys_are_unique(self, request, fixture):
        circuit = request.getfixturevalue(fixture)

        # NetworkGraph stores edges in a dict, so a collision silently drops
        # one. Counting the elements is what exposes it.
        expected = circuit.n_lines + circuit.n_transformers
        assert len(circuit.graph.edges) == expected


class TestFactsOnly:
    """Cada dado num lugar só, e nenhuma classificação.

    O formato anterior trazia o mesmo fato por dois caminhos (``attached`` na
    barra e ``bus`` no elemento; ``id`` montado de tipo e nome) e um
    ``node_type`` decidido por precedência, que escondia a carga de uma barra
    com PV.
    """

    NODE_FIELDS = frozenset({"name", "kv_base", "nodes", "x", "y"})
    EDGE_FIELDS = frozenset({"type", "name", "source", "target", "phases", "open", "regcontrols"})
    ELEMENT_FIELDS = frozenset({"type", "name", "bus", "nodes", "phases"})

    def test_the_payload_is_versioned(self, ieee13_pv):
        assert set(ieee13_pv.payload) == {"version", "nodes", "edges", "elements"}
        assert ieee13_pv.payload["version"] == SCHEMA_VERSION == 2

    def test_records_carry_exactly_their_fields(self, ieee13_pv):
        """Sem ``node_type``, ``id``, ``label``, ``metadata`` nem ``attached``."""
        payload = ieee13_pv.payload

        assert all(set(n) == self.NODE_FIELDS for n in payload["nodes"])
        assert all(set(e) == self.EDGE_FIELDS for e in payload["edges"])
        assert all(set(e) == self.ELEMENT_FIELDS for e in payload["elements"])

    def test_a_bus_with_load_and_pv_lists_both(self, ieee13_pv):
        """O caso que a precedência escondia: a 646 era só ``pv``."""
        assert ieee13_pv.types_at("646") == {"Load", "PVSystem"}

    def test_pv_buses_are_reported(self, ieee13_pv):
        pv_buses = {e.bus for e in ieee13_pv.of_type("PVSystem")}

        # PVs sit on 634, 692, 680, 646, 611, 652
        assert pv_buses == {"634", "692", "680", "646", "611", "652"}

    def test_every_load_becomes_an_element(self, ieee123):
        assert len(ieee123.of_type("Load")) == ieee123.n_loads

    def test_capacitors_become_elements(self, ieee13):
        caps = {e.name: e for e in ieee13.of_type("Capacitor")}

        assert set(caps) == {"cap1", "cap2"}
        assert (caps["cap1"].bus, caps["cap1"].nodes) == ("675", [1, 2, 3])
        assert (caps["cap2"].bus, caps["cap2"].nodes) == ("611", [3])

    def test_regulated_transformers_name_the_regulated_bus(self, ieee13):
        """Substitui o ``regulator_bus``: o fato fica no transformador."""
        for reg in ("reg1", "reg2", "reg3"):
            edge = ieee13.graph.edges[("Transformer", reg)]
            assert edge.regcontrols == [{"name": reg, "bus": "rg60"}]

    def test_unregulated_edges_carry_an_empty_list(self, ieee13):
        """Vazia ou não, a chave existe: o consumidor itera sem checar."""
        unregulated = [
            e for e in ieee13.graph.edges.values() if e.name not in ("reg1", "reg2", "reg3")
        ]

        assert unregulated
        assert all(e.regcontrols == [] for e in unregulated)

    def test_node_names_cover_the_circuit(self, ieee123):
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

    def test_they_are_switch_edges(self, ieee123):
        """O mesmo modelo ``Switch`` do adaptador, e não ``Line``."""
        switches = {e.name for e in ieee123.graph.edges.values() if e.type == "Switch"}

        assert switches == self.SWITCHES

    def test_the_normally_open_ones_are_open(self, ieee123):
        """Abertas pelo terminal 2 — o caso que uma leitura do terminal 1 perde."""
        abertas = {n for n in self.SWITCHES if ieee123.edges_by_name[n].open}
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


class TestNodeFields:
    def test_buses_carry_base_and_nodes(self, ieee13):
        node = ieee13.graph.nodes["634"]

        assert node.kv_base > 0
        assert node.nodes == [1, 2, 3]

    def test_defined_coordinates_are_numbers(self, ieee123):
        located = [n for n in ieee123.graph.nodes.values() if n.x is not None]
        assert located

        for node in located:
            assert isinstance(node.x, float)
            assert isinstance(node.y, float)

    def test_missing_coordinates_are_null_not_origin(self, sem_coordenada):
        """Barra fora do BusCoords: o OpenDSS diz (0, 0), que não é uma posição."""
        node = sem_coordenada.graph.nodes["barra_sem_coordenada"]

        assert node.x is None
        assert node.y is None

    def test_missing_coordinates_serialize_as_json_null(self, sem_coordenada):
        (node,) = [
            n for n in sem_coordenada.payload["nodes"] if n["name"] == "barra_sem_coordenada"
        ]

        assert node["x"] is None
        assert node["y"] is None

    def test_every_ieee123_bus_is_located(self, ieee123):
        """O alimentador inteiro tem coordenada real, desde a adoção das chaves.

        As duas barras que faltavam eram as fictícias ``300_open``/``94_open``;
        com as chaves normalmente abertas ligando as barras reais ``300`` e
        ``94``, não sobra nenhuma fora do ``BusCoords.dat``.
        """
        unlocated = [n.name for n in ieee123.graph.nodes.values() if n.x is None]
        assert unlocated == []

    def test_edges_carry_phase_count(self, ieee13):
        for edge in ieee13.graph.edges.values():
            assert edge.phases >= 1


class TestElements:
    """Cada elemento de uma barra vira um registro próprio, com a fase em que está.

    Três PVs monofásicos numa barra trifásica são três elementos, e não um tipo
    de barra.
    """

    def test_every_pvsystem_becomes_an_element(self, ieee13_pv):
        assert len(ieee13_pv.of_type("PVSystem")) == ieee13_pv.n_pvsystems

    def test_element_bus_joins_with_a_node(self, ieee13_pv):
        """``element.bus`` usa a normalização de ``node.name``; o join é direto."""
        for element in ieee13_pv.graph.elements.values():
            assert element.bus in ieee13_pv.graph.nodes

    def test_single_phase_pv_keeps_its_own_phase(self, ieee13_pv):
        """pv-4 está em 646.2, não na barra inteira."""
        pv = ieee13_pv.graph.elements[("PVSystem", "pv-4")]

        assert pv.bus == "646"
        assert pv.phases == 1
        assert pv.nodes == [2]

    def test_phases_and_nodes_are_distinct_facts(self, ieee13):
        """A carga 646 é monofásica em delta: uma fase, dois nós."""
        load = ieee13.graph.elements[("Load", "646")]

        assert load.phases == 1
        assert load.nodes == [2, 3]

    def test_circuit_without_der_has_no_der(self, ieee13):
        tipos = {e.type for e in ieee13.graph.elements.values()}

        assert tipos == {"Vsource", "Load", "Capacitor"}


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
        bat = circuito_com_storage.graph.elements[("Storage", "bat1")]

        assert bat.bus == "675"
        assert bat.phases == 1
        assert bat.nodes == [1]

    def test_storage_is_listed_beside_the_rest_of_its_bus(self, circuito_com_storage):
        """A 675 tem cargas e capacitor também; nenhum deles some."""
        assert circuito_com_storage.types_at("675") == {"Load", "Capacitor", "Storage"}

    def test_disabled_storage_is_not_an_element(self, circuito_com_storage):
        assert ("Storage", "bat_desligada") not in circuito_com_storage.graph.elements
        assert "Storage" not in circuito_com_storage.types_at("680")

    def test_storage_scan_does_not_break_the_other_classes(self, circuito_com_storage):
        """Enumerar as classes troca a classe ativa do OpenDSS.

        Linhas e transformadores são varridos logo depois, pelas interfaces
        tipadas; se a troca de classe as atrapalhasse, o grafo sairia sem
        arestas.
        """
        assert len(circuito_com_storage.of_type("Load")) == circuito_com_storage.n_loads
        assert len(circuito_com_storage.graph.edges) == (
            circuito_com_storage.n_lines + circuito_com_storage.n_transformers
        )


GENERATOR_CIRCUIT = """\
Redirect "{master}"
New Generator.g_mono bus1=611.3 phases=1 kV=2.4 kW=100 pf=1
New Generator.g_desligado bus1=680 phases=3 kV=4.16 kW=200 enabled=no
"""


@pytest.fixture(scope="module")
def circuito_com_gerador(tmp_path_factory):
    """Nenhum circuito co-simulável de data/ tem gerador."""
    if not IEEE13.exists():
        pytest.skip("IEEE13 fixture not found")

    path = tmp_path_factory.mktemp("topo") / "gerador.dss"
    path.write_text(GENERATOR_CIRCUIT.format(master=IEEE13.as_posix()))
    return _open(path)


class TestGenerator:
    def test_generator_becomes_an_element(self, circuito_com_gerador):
        gerador = circuito_com_gerador.graph.elements[("Generator", "g_mono")]

        assert gerador.bus == "611"
        assert gerador.phases == 1
        assert gerador.nodes == [3]

    def test_generator_is_listed_beside_the_rest_of_its_bus(self, circuito_com_gerador):
        """A 611 tem carga e capacitor; o gerador entra ao lado, sem disputa."""
        assert circuito_com_gerador.types_at("611") == {"Load", "Capacitor", "Generator"}

    def test_disabled_generator_is_not_an_element(self, circuito_com_gerador):
        assert ("Generator", "g_desligado") not in circuito_com_gerador.graph.elements

    def test_it_reaches_the_exported_json(self, circuito_com_gerador):
        exportados = {(e["type"], e["name"]) for e in circuito_com_gerador.payload["elements"]}

        assert ("Generator", "g_mono") in exportados


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
        assert "linha_desligada" not in circuito_com_desligados.edges_by_name

    def test_open_switch_stays_but_is_flagged(self, circuito_com_desligados):
        """An open switch still exists physically; the viewer can dash it."""
        edge = circuito_com_desligados.graph.edges.get(("Switch", "chave_aberta"))
        assert edge is not None
        assert edge.open is True

    def test_closed_lines_are_not_flagged_open(self, circuito_com_desligados):
        assert circuito_com_desligados.graph.edges[("Line", "650632")].open is False


class TestJoinsWithTheAdapter:
    """``f"{type}-{name}"`` é o eid da entidade mosaik.

    É o que liga o JSON às colunas do CSV dos resultados
    (``DSS-0.PVSystem-pv-4-P_meas``) sem tabela de tradução. Vsource e Capacitor não
    têm modelo no adaptador e ficam fora da junção.

    No fim do arquivo: compila outro circuito no motor compartilhado.
    """

    WITHOUT_MODEL = frozenset({"Vsource", "Capacitor"})

    def test_types_and_names_are_the_adapter_eids(self):
        from simulators.opendss.api_opendss import META, OpenDSSSimulator

        if not IEEE13_PV.exists():
            pytest.skip("IEEE13 PV fixture not found")
        sim = OpenDSSSimulator()
        sim.init("DSS-0", 1.0, topofile=str(IEEE13_PV), step_size=300)
        eids = {child["eid"] for child in sim.create(1, "Grid")[0]["children"]}
        grafo = build_graph(sim.dss_wrapper.dss)

        registros = [*grafo.edges.values(), *grafo.elements.values()]
        assert {r.type for r in registros} <= set(META["models"]) | self.WITHOUT_MODEL

        for registro in registros:
            if registro.type not in self.WITHOUT_MODEL:
                assert f"{registro.type}-{registro.name}" in eids, registro
        for node in grafo.nodes.values():
            assert f"Bus-{node.name}" in eids, node
        for edge in grafo.edges.values():
            for regcontrol in edge.regcontrols:
                assert f"RegControl-{regcontrol['name']}" in eids, regcontrol


class TestStandaloneExport:
    """`util.topologia.exportar_topologia` passa pela fachada.

    Antes ele compilava com um `DSS()` cru, sem conferir o arquivo nem o erro.
    No fim do arquivo: compila outro circuito no motor compartilhado.
    """

    def test_it_writes_the_same_graph_as_the_facade(self, tmp_path):
        from simulators.util.topologia import exportar_topologia

        if not IEEE13.exists():
            pytest.skip("IEEE13 fixture not found")
        saida = tmp_path / "topologia.json"

        grafo = exportar_topologia(str(IEEE13), str(saida))
        exportado = json.loads(saida.read_text(encoding="utf-8"))

        assert len(exportado["nodes"]) == grafo.total_nodes > 0
        assert len(exportado["edges"]) == grafo.total_edges
        assert len(exportado["elements"]) == grafo.total_elements

    def test_a_missing_file_is_refused(self, tmp_path):
        from simulators.opendss.opendss_wrapper import OpenDSSException
        from simulators.util.topologia import exportar_topologia

        with pytest.raises(OpenDSSException, match="not found"):
            exportar_topologia(str(tmp_path / "nao_existe.dss"), str(tmp_path / "t.json"))
