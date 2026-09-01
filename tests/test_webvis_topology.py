"""Unit tests for the web visualization fork (``simulators.webvis``).

The topology the browser draws is derived from mosaik's entity graph, which
mixes ``rel`` edges with every ``world.connect`` edge. These tests pin down the
cleaning rules (ignore/merge) that turn that graph into a drawable feeder, plus
the fork's divergences from upstream mosaik-web.
"""

import sys
from types import SimpleNamespace

import networkx as nx
import pytest

sys.path.insert(0, "src")

from simulators.webvis.webvis_sim import (
    Simulator,
    aggregate_values,
    default_config,
    etype_attrs,
    normalize_positions,
    to_iso_local,
)


def make_graph(nodes, edges):
    """Entity graph in the shape ``get_related_entities`` returns."""
    nxg = nx.Graph()
    nxg.add_nodes_from((name, {"type": type_}) for name, type_ in nodes.items())
    nxg.add_edges_from(edges)
    return nxg


@pytest.fixture
def sim():
    return Simulator()


class TestStartDate:
    def test_is_iso_with_local_offset(self):
        iso = to_iso_local("2025-01-01 00:00:00")
        assert iso.startswith("2025-01-01T00:00:00")
        # Sem fuso o navegador interpretaria a data como UTC e a timeline
        # apareceria deslocada.
        assert iso[19] in "+-", iso

    def test_rejects_other_formats(self):
        with pytest.raises(ValueError):
            to_iso_local("01/01/2025 00:00")


class TestConfigIsolation:
    def test_set_config_does_not_leak_between_instances(self, sim):
        sim.set_config(ignore_types=["Grid"])
        assert Simulator().config["ignore_types"] == ["Topology"]
        assert default_config["ignore_types"] == ["Topology"]

    def test_set_etypes_does_not_leak_between_instances(self, sim):
        sim.set_etypes({"Bus": {"attr": "V1_pu"}})
        assert Simulator().config["etypes"] == {}


class TestCleanGraph:
    def test_ignored_types_are_removed(self, sim):
        nxg = make_graph(
            {"DSS-0.Grid-0": "Grid", "Web-0.topo": "Topology", "DSS-0.Bus-650": "Bus"},
            [],
        )
        sim.set_config(ignore_types=["Grid", "Topology"])
        sim._clean_nx_graph(nxg)

        assert set(nxg.nodes) == {"DSS-0.Bus-650"}

    def test_ignored_names_are_removed(self, sim):
        nxg = make_graph({"DSS-0.Bus-650": "Bus", "DSS-0.Bus-611": "Bus"}, [])
        sim.set_config(ignore_names=["DSS-0.Bus-611"])
        sim._clean_nx_graph(nxg)

        assert set(nxg.nodes) == {"DSS-0.Bus-650"}

    def test_line_becomes_an_edge_between_its_buses(self, sim):
        nxg = make_graph(
            {"DSS-0.Bus-650": "Bus", "DSS-0.Line-650632": "Line", "DSS-0.Bus-632": "Bus"},
            [("DSS-0.Bus-650", "DSS-0.Line-650632"), ("DSS-0.Line-650632", "DSS-0.Bus-632")],
        )
        sim.set_config(merge_types=["Line"])
        sim._clean_nx_graph(nxg)

        assert set(nxg.nodes) == {"DSS-0.Bus-650", "DSS-0.Bus-632"}
        assert nxg.has_edge("DSS-0.Bus-650", "DSS-0.Bus-632")

    def test_collector_is_removed_before_lines_are_merged(self, sim):
        """A line wired to the data collector still has to merge.

        Every ``world.connect`` adds an edge to the entity graph, so monitoring
        a line raises its degree to 3. Removing the ignored types first is what
        keeps the merge possible.
        """
        nxg = make_graph(
            {
                "DSS-0.Bus-650": "Bus",
                "DSS-0.Line-650632": "Line",
                "DSS-0.Bus-632": "Bus",
                "Collector-0.Monitor-0": "Monitor",
            },
            [
                ("DSS-0.Bus-650", "DSS-0.Line-650632"),
                ("DSS-0.Line-650632", "DSS-0.Bus-632"),
                ("DSS-0.Line-650632", "Collector-0.Monitor-0"),
            ],
        )
        sim.set_config(ignore_types=["Monitor"], merge_types=["Line"])
        sim._clean_nx_graph(nxg)

        assert nxg.has_edge("DSS-0.Bus-650", "DSS-0.Bus-632")

    def test_unmergeable_node_is_kept_instead_of_crashing(self, sim, capsys):
        """Upstream asserted ``len(neighbors) == 2`` and took down the run.

        A line whose second bus is missing from the circuit has degree 1. The
        drawing is not worth aborting a simulation for, so the node stays.
        """
        nxg = make_graph(
            {"DSS-0.Bus-650": "Bus", "DSS-0.Line-orfa": "Line"},
            [("DSS-0.Bus-650", "DSS-0.Line-orfa")],
        )
        sim.set_config(merge_types=["Line"])
        sim._clean_nx_graph(nxg)

        assert "DSS-0.Line-orfa" in nxg.nodes
        assert "DSS-0.Line-orfa" in capsys.readouterr().out

    def test_merge_nodes_by_name(self, sim):
        nxg = make_graph(
            {"a": "Bus", "b": "Bus", "c": "Bus"},
            [("a", "b"), ("b", "c")],
        )
        sim.set_config(merge_nodes=["b"])
        sim._clean_nx_graph(nxg)

        assert set(nxg.nodes) == {"a", "c"}
        assert nxg.has_edge("a", "c")


class TestEtypeAttrs:
    def test_list_of_attributes(self):
        assert etype_attrs({"attrs": ["V1_pu", "V2_pu", "V3_pu"]}) == ["V1_pu", "V2_pu", "V3_pu"]

    def test_upstream_single_attribute_still_works(self):
        assert etype_attrs({"attr": "V1_pu"}) == ["V1_pu"]

    def test_attrs_wins_over_attr(self):
        assert etype_attrs({"attr": "V1_pu", "attrs": ["V_min_pu"]}) == ["V_min_pu"]

    def test_unconfigured_type_has_none(self):
        assert etype_attrs({}) == []
        assert etype_attrs(None) == []


class TestAggregateValues:
    """The heatmap needs one number per node; a three-phase bus has three."""

    def test_absent_phase_is_not_a_collapsed_voltage(self):
        # Ramal monofásico: o OpenDSS reporta 0.0 nas fases que a barra não tem.
        assert aggregate_values([0.0, 0.97, 0.0], how="min") == pytest.approx(0.97)

    def test_zeros_count_when_asked_to(self):
        assert aggregate_values([0.0, 0.97, 0.0], how="min", ignore_zero=False) == 0.0

    @pytest.mark.parametrize(
        ("how", "expected"),
        [
            ("first", 1.00),
            ("min", 0.96),
            ("max", 1.00),
            ("mean", 0.98),
            ("spread", 0.04),
        ],
    )
    def test_aggregators(self, how, expected):
        assert aggregate_values([1.00, 0.98, 0.96], how=how) == pytest.approx(expected)

    def test_missing_data_yields_none(self):
        assert aggregate_values([None, None], how="min") is None
        assert aggregate_values([], how="min") is None

    def test_unknown_aggregator_warns_and_falls_back(self, capsys):
        assert aggregate_values([2.0, 1.0], how="mediana") == 2.0
        assert "mediana" in capsys.readouterr().out


class TestNodeData:
    @pytest.fixture
    def sim(self):
        simulator = Simulator()
        simulator.eid = "topo"
        simulator.server = SimpleNamespace(
            topology={
                "nodes": [
                    {"name": "DSS-0.Bus-800", "type": "Bus"},
                    {"name": "DSS-0.Bus-822", "type": "Bus"},
                    {"name": "DSS-0.Load-s1", "type": "Load"},
                ]
            }
        )
        simulator.set_etypes(
            {
                "Bus": {
                    "attrs": ["V1_pu", "V2_pu", "V3_pu"],
                    "aggregate": "min",
                    "default": 1.0,
                }
            }
        )
        return simulator

    def test_each_phase_is_sent_along_with_the_aggregate(self, sim):
        inputs = {
            "V1_pu": {"DSS-0.Bus-800": 1.01, "DSS-0.Bus-822": 0.0},
            "V2_pu": {"DSS-0.Bus-800": 0.99, "DSS-0.Bus-822": 0.93},
            "V3_pu": {"DSS-0.Bus-800": 1.00, "DSS-0.Bus-822": 0.0},
        }

        data = sim._node_data(inputs)

        assert data["DSS-0.Bus-800"]["values"] == [1.01, 0.99, 1.00]
        assert data["DSS-0.Bus-800"]["value"] == pytest.approx(0.99)
        # A barra monofásica é colorida pela fase que ela tem, não por zero.
        assert data["DSS-0.Bus-822"]["value"] == pytest.approx(0.93)

    def test_node_without_data_falls_back_to_the_default(self, sim):
        data = sim._node_data({})
        assert data["DSS-0.Bus-800"]["value"] == 1.0

    def test_unconfigured_type_is_still_reported(self, sim):
        data = sim._node_data({})
        assert data["DSS-0.Load-s1"] == {"value": 0, "values": []}

    def test_zero_is_a_real_value_for_single_attribute_types(self, sim):
        """A load at 0 kW is not an absent phase; it must not fall back to the default."""
        sim.set_etypes({"Load": {"attrs": ["P_out_mw"], "default": 99}})

        data = sim._node_data({"P_out_mw": {"DSS-0.Load-s1": 0.0}})

        assert data["DSS-0.Load-s1"]["value"] == 0.0

    def test_zero_is_an_absent_phase_for_per_phase_types(self, sim):
        data = sim._node_data(
            {
                "V1_pu": {"DSS-0.Bus-822": 0.93},
                "V2_pu": {"DSS-0.Bus-822": 0.0},
                "V3_pu": {"DSS-0.Bus-822": 0.0},
            }
        )

        assert data["DSS-0.Bus-822"]["value"] == pytest.approx(0.93)


class TestNormalizePositions:
    def test_maps_into_the_unit_square(self):
        norm = normalize_positions({"a": (100, 200), "b": (300, 200), "c": (200, 400)})

        assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in norm.values())

    def test_y_is_flipped_for_the_screen(self):
        norm = normalize_positions({"sul": (0, 0), "norte": (0, 100)})
        assert norm["norte"][1] < norm["sul"][1]

    def test_aspect_ratio_is_preserved(self):
        """A long, thin feeder must not be stretched into a square."""
        norm = normalize_positions({"a": (0, 0), "b": (1000, 0), "c": (0, 100)})

        width = norm["b"][0] - norm["a"][0]
        height = abs(norm["c"][1] - norm["a"][1])
        assert height == pytest.approx(width / 10)

    def test_single_point_does_not_divide_by_zero(self):
        assert normalize_positions({"a": (5, 5)}) == {"a": (0.5, 0.5)}

    def test_empty(self):
        assert normalize_positions({}) == {}


class TestD3Topology:
    def test_links_reference_nodes_by_index(self, sim):
        sim.start_date = to_iso_local("2025-01-01 00:00:00")
        sim.step_size = 600
        nxg = make_graph(
            {"DSS-0.Bus-650": "Bus", "DSS-0.Bus-632": "Bus"},
            [("DSS-0.Bus-650", "DSS-0.Bus-632")],
        )

        topology = sim._make_d3js_topology(nxg)

        names = [node["name"] for node in topology["nodes"]]
        link = topology["links"][0]
        assert {names[link["source"]], names[link["target"]]} == set(names)
        assert topology["update_interval"] == 600
        assert all(node["value"] == 0 for node in topology["nodes"])

    def test_known_positions_reach_the_nodes(self, sim):
        sim.start_date = to_iso_local("2025-01-01 00:00:00")
        sim.step_size = 600
        sim.set_node_positions({"DSS-0.Bus-800": (0, 0), "DSS-0.Bus-802": (400, 0)})

        topology = sim._make_d3js_topology(
            make_graph(
                {"DSS-0.Bus-800": "Bus", "DSS-0.Bus-802": "Bus", "DSS-0.Load-s1": "Load"}, []
            )
        )

        by_name = {node["name"]: node for node in topology["nodes"]}
        assert by_name["DSS-0.Bus-800"]["x"] == pytest.approx(0.0)
        assert by_name["DSS-0.Bus-802"]["x"] == pytest.approx(1.0)
        # Sem coordenada, o nó fica a cargo do layout de forças.
        assert "x" not in by_name["DSS-0.Load-s1"]

    def test_positions_of_hidden_nodes_do_not_skew_the_scale(self, sim):
        """A bus removed by the filters must not stretch the drawing."""
        sim.start_date = to_iso_local("2025-01-01 00:00:00")
        sim.step_size = 600
        sim.set_node_positions(
            {"DSS-0.Bus-800": (0, 0), "DSS-0.Bus-802": (400, 0), "DSS-0.Bus-fora": (99999, 0)}
        )

        topology = sim._make_d3js_topology(
            make_graph({"DSS-0.Bus-800": "Bus", "DSS-0.Bus-802": "Bus"}, [])
        )

        by_name = {node["name"]: node for node in topology["nodes"]}
        assert by_name["DSS-0.Bus-802"]["x"] == pytest.approx(1.0)

    def test_etypes_are_forwarded_to_the_browser(self, sim):
        sim.start_date = to_iso_local("2025-01-01 00:00:00")
        sim.step_size = 600
        sim.set_etypes({"Bus": {"cls": "pqbus", "attr": "V1_pu"}})

        topology = sim._make_d3js_topology(make_graph({"DSS-0.Bus-650": "Bus"}, []))

        assert topology["etypes"]["Bus"]["attr"] == "V1_pu"
