"""Unit tests for node-aware phase mapping (opendss._utils)."""

import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss._utils import map_to_phases


class TestThreePhase:
    def test_wye_three_phase_with_neutral(self):
        # Load.671 @ 671.1.2.3 → node_order [1, 2, 3]
        assert map_to_phases([1, 2, 3], [385.4, 396.0, 373.6]) == [385.4, 396.0, 373.6]

    def test_neutral_conductor_is_skipped(self):
        # PVSystem 3ph @ 634 → node_order [1, 2, 3, 0]; neutral must not shift anything
        assert map_to_phases([1, 2, 3, 0], [10.0, 20.0, 30.0, 0.5]) == [10.0, 20.0, 30.0]


class TestSinglePhase:
    """The regression this whole change is about."""

    def test_phase_1(self):
        # Load.652 @ 652.1 → node_order [1, 0]
        assert map_to_phases([1, 0], [121.9, 0.0]) == [121.9, 0.0, 0.0]

    def test_phase_2_does_not_land_on_phase_1(self):
        # Load.645 @ 645.2 → node_order [2, 0]
        assert map_to_phases([2, 0], [170.0, 0.0]) == [0.0, 170.0, 0.0]

    def test_phase_3_does_not_land_on_phase_1(self):
        # Load.611 @ 611.3 → node_order [3, 0]
        assert map_to_phases([3, 0], [163.5, 0.0]) == [0.0, 0.0, 163.5]

    def test_not_padded_to_the_right(self):
        """The old helper padded to the right, putting phase 3 on P1."""
        assert map_to_phases([3, 0], [163.5, 0.0]) != [163.5, 0.0, 0.0]
        assert map_to_phases([3, 0], [163.5, 0.0]) == [0.0, 0.0, 163.5]


class TestDelta:
    def test_two_node_delta_fills_both_phases(self):
        # Load.646 @ 646.2.3 → node_order [2, 3], both conductors are phases
        assert map_to_phases([2, 3], [157.4, 77.2]) == [0.0, 157.4, 77.2]

    def test_delta_total_is_not_truncated(self):
        # Slicing by num_phases kept only the first conductor, losing ~33% of P
        phases = map_to_phases([2, 3], [157.4, 77.2])
        assert sum(phases) == pytest.approx(234.6)

    def test_reversed_node_order(self):
        # Load.692 @ 692.3.1 → node_order [3, 1]
        assert map_to_phases([3, 1], [123.9, 42.8]) == [42.8, 0.0, 123.9]


class TestEdgeCases:
    def test_all_ground_terminal(self):
        # Capacitor.cap1 terminal 2 @ 675.0.0.0 → node_order [0, 0, 0]
        assert map_to_phases([0, 0, 0], [1.0, 2.0, 3.0]) == [0.0, 0.0, 0.0]

    def test_nodes_above_three_are_skipped(self):
        assert map_to_phases([1, 4, 7], [10.0, 20.0, 30.0]) == [10.0, 0.0, 0.0]

    def test_empty(self):
        assert map_to_phases([], []) == [0.0, 0.0, 0.0]

    def test_extra_nodes_without_values_are_ignored(self):
        assert map_to_phases([1, 2, 3], [10.0]) == [10.0, 0.0, 0.0]
