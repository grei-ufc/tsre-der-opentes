"""Integration tests for child entity topology (``rel``) and metadata (``extra_info``).

Mosaik builds its entity graph with ``add_edge``, which silently creates missing
nodes — a ``rel`` pointing at a non-existent eid corrupts the graph without
raising. These tests are the guard for that.
"""

import pathlib
import sys

import networkx as nx
import pytest

sys.path.insert(0, "src")

from simulators.opendss.api_opendss import (
    OpenDSSSimulator,
    _parse_bus,
    _resolve_nodes,
)

DATA_DIR = (pathlib.Path(__file__).parent.parent / "data" / "13Bus").resolve()
MASTER = DATA_DIR / "run_ieee13_cosim_pv_5min.dss"


@pytest.fixture(scope="module")
def grid():
    if not MASTER.exists():
        pytest.skip(f"IEEE13 PV fixture not found at {MASTER}")

    sim = OpenDSSSimulator()
    sim.init("DSS-0", 1.0, topofile=str(MASTER), step_size=300)
    if sim.dss_wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    result = sim.create(1, "Grid")[0]
    return sim, result


@pytest.fixture(scope="module")
def children(grid):
    return grid[1]["children"]


class TestParseBus:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("671.1.2.3", ("671", [1, 2, 3])),
            ("646.2", ("646", [2])),
            ("634", ("634", [])),
            ("675.0.0.0", ("675", [0, 0, 0])),
            ("", ("", [])),
        ],
    )
    def test_parse(self, raw, expected):
        assert _parse_bus(raw) == expected

    def test_implicit_nodes_are_resolved_from_phases(self):
        assert _resolve_nodes([], 3) == [1, 2, 3]
        assert _resolve_nodes([], 1) == [1]

    def test_explicit_nodes_win(self):
        assert _resolve_nodes([2], 3) == [2]


class TestRelIsWellFormed:
    def test_no_dangling_references(self, children):
        eids = {c["eid"] for c in children}
        dangling = [(c["eid"], r) for c in children for r in c["rel"] if r not in eids]
        assert dangling == []

    def test_every_rel_points_at_a_bus(self, children):
        offenders = [(c["eid"], r) for c in children for r in c["rel"] if not r.startswith("Bus-")]
        assert offenders == []

    @pytest.mark.parametrize(
        "model_type", ["Load", "Line", "PVSystem", "RegControl", "Transformer"]
    )
    def test_elements_are_connected(self, children, model_type):
        entities = [c for c in children if c["type"] == model_type]
        assert entities, f"no {model_type} entities in the fixture"
        assert all(c["rel"] for c in entities)

    def test_lines_connect_two_buses(self, children):
        lines = [c for c in children if c["type"] == "Line"]
        assert all(len(c["rel"]) == 2 for c in lines)

    def test_buses_are_anchors(self, children):
        buses = [c for c in children if c["type"] == "Bus"]
        assert all(c["rel"] == [] for c in buses)

    def test_rel_matches_extra_info_bus(self, children):
        for child in children:
            if child["type"] in ("Load", "PVSystem", "Storage"):
                bus = child["extra_info"]["bus"]
                assert child["rel"] == [f"Bus-{bus}"]


class TestTransformers:
    """Transformers are what keeps the entity graph in one piece.

    Buses joined only by a transformer — the regulator banks, the substation
    step-up — have no line between them, so leaving transformers out of the
    entity list breaks the feeder into islands.
    """

    def test_transformers_connect_two_buses(self, children):
        trafos = [c for c in children if c["type"] == "Transformer"]
        assert trafos, "no Transformer entities in the fixture"
        assert all(len(c["rel"]) == 2 for c in trafos)

    def test_regulator_transformers_are_flagged(self, children):
        # O OpenDSS reporta os nomes em minúsculas, e o eid segue o motor.
        trafos = {c["eid"].lower(): c["extra_info"] for c in children if c["type"] == "Transformer"}
        # IEEE13: reg1/reg2/reg3 are driven by RegControls, XFM1 is not.
        assert {name for name, info in trafos.items() if info["is_regulated"]}
        assert not trafos["transformer-xfm1"]["is_regulated"]

    def test_buses_agree_with_the_engine(self, grid, children):
        sim, _ = grid
        dss = sim.dss_wrapper.dss

        for child in children:
            if child["type"] != "Transformer":
                continue
            dss.circuit.set_active_element(f"Transformer.{child['extra_info']['name']}")
            assert child["extra_info"]["buses"] == list(dss.cktelement.bus_names)

    def test_graph_is_connected(self, children):
        graph = nx.Graph()
        for child in children:
            graph.add_node(child["eid"], type=child["type"])
            for rel in child["rel"]:
                graph.add_edge(child["eid"], rel)

        assert nx.number_connected_components(graph) == 1

    def test_graph_falls_apart_without_them(self, children):
        """Guards the reason the model exists, not just its presence."""
        graph = nx.Graph()
        for child in children:
            if child["type"] == "Transformer":
                continue
            graph.add_node(child["eid"], type=child["type"])
            for rel in child["rel"]:
                graph.add_edge(child["eid"], rel)

        assert nx.number_connected_components(graph) > 1


class TestExtraInfo:
    def test_every_child_has_extra_info(self, children):
        assert all(c["extra_info"] for c in children)

    def test_is_json_serializable(self, children):
        """Remote (Docker) simulators send this over the wire."""
        import json

        json.dumps(children)

    def test_single_phase_pv_reports_its_real_node(self, children):
        by_eid = {c["eid"]: c["extra_info"] for c in children}

        # pv-4 @ 646.2, pv-5 @ 611.3, pv-6 @ 652.1
        assert by_eid["PVSystem-pv-4_bus646"]["nodes"] == [2]
        assert by_eid["PVSystem-pv-5_bus611"]["nodes"] == [3]
        assert by_eid["PVSystem-pv-6_bus652"]["nodes"] == [1]

        # Testar fases de todos (mapeados por tuple)
        pvs = [("PVSystem-pv-4_bus646", 1), ("PVSystem-pv-5_bus611", 1), ("PVSystem-pv-6_bus652", 1)]
        assert all(by_eid[n]["phases"] == phases for n, phases in pvs)

    def test_three_phase_pv_reports_all_nodes(self, children):
        by_eid = {c["eid"]: c["extra_info"] for c in children}
        assert by_eid["PVSystem-pv_bus634"]["nodes"] == [1, 2, 3]
        assert by_eid["PVSystem-pv_bus634"]["phases"] == 3

    def test_bus_carries_voltage_base(self, children):
        buses = [c["extra_info"] for c in children if c["type"] == "Bus"]
        assert all(b["kv_base"] > 0 for b in buses)

    def test_load_carries_ratings(self, children):
        loads = [c["extra_info"] for c in children if c["type"] == "Load"]
        assert all(le["kw"] > 0 and le["kv"] > 0 for le in loads)


class TestCreateGuards:
    def test_grid_cannot_be_created_twice(self, grid):
        sim, _ = grid
        with pytest.raises(ValueError, match="already created"):
            sim.create(1, "Grid")

    def test_other_models_are_rejected(self, grid):
        sim, _ = grid
        with pytest.raises(ValueError, match="Access elements via children"):
            sim.create(1, "Load")


class TestExtraInfoMatchesTheEngine:
    """extra_info replaces string-parsing of DSS bus references in scenarios.

    It only earns that if it agrees with the engine for every element.
    """

    @pytest.mark.parametrize(
        ("model_type", "dss_class"),
        [("Load", "Load"), ("PVSystem", "PVSystem"), ("Line", "Line")],
    )
    def test_bus_and_nodes_agree_with_cktelement(self, grid, children, model_type, dss_class):
        sim, _ = grid
        dss = sim.dss_wrapper.dss

        divergences = []
        entities = [c for c in children if c["type"] == model_type]
        assert entities

        for child in entities:
            info = child["extra_info"]
            dss.circuit.set_active_element(f"{dss_class}.{info['name']}")
            raw = dss.cktelement.bus_names[0]

            bus_key = "bus1" if model_type == "Line" else "bus"
            nodes_key = "nodes1" if model_type == "Line" else "nodes"

            engine_bus, engine_nodes = _parse_bus(raw)
            expected_nodes = _resolve_nodes(engine_nodes, dss.cktelement.num_phases)

            if info[bus_key].lower() != engine_bus.lower():
                divergences.append((child["eid"], "bus", info[bus_key], engine_bus))
            if info[nodes_key] != expected_nodes:
                divergences.append((child["eid"], "nodes", info[nodes_key], expected_nodes))

        assert divergences == []

    def test_line_second_terminal_agrees(self, grid, children):
        sim, _ = grid
        dss = sim.dss_wrapper.dss

        divergences = []
        for child in [c for c in children if c["type"] == "Line"]:
            info = child["extra_info"]
            dss.circuit.set_active_element(f"Line.{info['name']}")
            engine_bus, _ = _parse_bus(dss.cktelement.bus_names[1])
            if info["bus2"].lower() != engine_bus.lower():
                divergences.append((child["eid"], info["bus2"], engine_bus))

        assert divergences == []


class TestBackwardCompatibility:
    """Existing scenarios use these accessors; they must keep working."""

    def test_detected_lists(self, grid):
        sim, _ = grid
        assert len(sim.get_detected_pvsystems()) == 6
        assert len(sim.get_detected_regulators()) == 3
        assert sim.get_detected_storages() == []

    def test_maps_are_keyed_by_eid(self, grid):
        sim, _ = grid
        assert set(sim.pvsystem_map) == {
            "PVSystem-pv_bus634", "PVSystem-pv-2_bus692", "PVSystem-pv-3_bus680",
            "PVSystem-pv-4_bus646", "PVSystem-pv-5_bus611", "PVSystem-pv-6_bus652"
        }

    def test_legacy_keys_are_preserved(self, grid):
        sim, _ = grid
        info = sim.pvsystem_map["PVSystem-pv-4_bus646"]
        for key in ("eid_dss", "name", "pmpp", "kva", "pt_curve_x", "eff_curve_y"):
            assert key in info

    def test_get_extra_info_covers_every_entity(self, grid, children):
        sim, _ = grid
        assert set(sim.get_extra_info()) == {c["eid"] for c in children}
