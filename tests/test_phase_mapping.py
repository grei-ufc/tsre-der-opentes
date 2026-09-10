"""Unit tests for node-aware phase mapping (opendss._utils).

Duas convenções são fixadas aqui. A primeira é posicional: o valor de um
condutor vai para o índice da fase a que ele pertence, e não para a esquerda da
lista. A segunda é a ausência: a fase que o elemento não tem é ``NaN``, e não
``0.0`` — do contrário não haveria como distinguir um inversor que gera zero ao
amanhecer de uma fase que não existe, e o consumidor teria de escolher entre
esconder os dois ou desenhar os dois.
"""

import math
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss._utils import ABSENT, map_to_phases, present_phases, sum_phases

# Legível nas comparações abaixo: `nan == nan` é falso, então a igualdade de
# listas não serve para conferir a ausência.
A = ABSENT


def same(actual, expected):
    """Compara listas por fase tratando ``NaN`` como igual a ``NaN``."""
    return len(actual) == len(expected) and all(
        (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y)
        for x, y in zip(actual, expected, strict=True)
    )


class TestThreePhase:
    def test_wye_three_phase_with_neutral(self):
        # Load.671 @ 671.1.2.3 → node_order [1, 2, 3]
        assert same(map_to_phases([1, 2, 3], [385.4, 396.0, 373.6]), [385.4, 396.0, 373.6])

    def test_neutral_conductor_is_skipped(self):
        # PVSystem 3ph @ 634 → node_order [1, 2, 3, 0]; neutral must not shift anything
        assert same(map_to_phases([1, 2, 3, 0], [10.0, 20.0, 30.0, 0.5]), [10.0, 20.0, 30.0])


class TestSinglePhase:
    """The regression this whole change is about."""

    def test_phase_1(self):
        # Load.652 @ 652.1 → node_order [1, 0]
        assert same(map_to_phases([1, 0], [121.9, 0.0]), [121.9, A, A])

    def test_phase_2_does_not_land_on_phase_1(self):
        # Load.645 @ 645.2 → node_order [2, 0]
        assert same(map_to_phases([2, 0], [170.0, 0.0]), [A, 170.0, A])

    def test_phase_3_does_not_land_on_phase_1(self):
        # Load.611 @ 611.3 → node_order [3, 0]
        assert same(map_to_phases([3, 0], [163.5, 0.0]), [A, A, 163.5])

    def test_not_padded_to_the_right(self):
        """The old helper padded to the right, putting phase 3 on P1."""
        assert not same(map_to_phases([3, 0], [163.5, 0.0]), [163.5, A, A])
        assert same(map_to_phases([3, 0], [163.5, 0.0]), [A, A, 163.5])


class TestAbsenceIsNotZero:
    """A distinção que o ``0.0`` não conseguia expressar."""

    def test_missing_phases_are_nan(self):
        phases = map_to_phases([2, 0], [170.0, 0.0])

        assert math.isnan(phases[0])
        assert math.isnan(phases[2])

    def test_a_measured_zero_survives(self):
        """O inversor ao amanhecer: gera 0 kW nas três fases, e isso é um dado."""
        phases = map_to_phases([1, 2, 3], [0.0, 0.0, 0.0])

        assert phases == [0.0, 0.0, 0.0]
        assert not any(math.isnan(v) for v in phases)

    def test_a_measured_zero_is_not_filtered_as_absent(self):
        assert present_phases(map_to_phases([1, 2, 3], [0.0, 0.0, 0.0])) == [0.0, 0.0, 0.0]

    def test_absent_phases_are_filtered(self):
        assert present_phases(map_to_phases([2, 0], [170.0, 0.0])) == [170.0]


class TestSumPhases:
    """O total não pode ser contaminado pela ausência."""

    def test_single_phase_total_is_its_only_phase(self):
        """Com o ``sum`` embutido isto daria NaN, e P_meas sumiria do cenário."""
        assert sum_phases(map_to_phases([3, 0], [163.5, 0.0])) == pytest.approx(163.5)

    def test_three_phase_total(self):
        assert sum_phases([10.0, 20.0, 30.0]) == pytest.approx(60.0)

    def test_measured_zeros_sum_to_zero(self):
        assert sum_phases([0.0, 0.0, 0.0]) == 0.0

    def test_no_phase_at_all_is_absent(self):
        assert math.isnan(sum_phases([A, A, A]))


class TestDelta:
    def test_two_node_delta_fills_both_phases(self):
        # Load.646 @ 646.2.3 → node_order [2, 3], both conductors are phases
        assert same(map_to_phases([2, 3], [157.4, 77.2]), [A, 157.4, 77.2])

    def test_delta_total_is_not_truncated(self):
        # Slicing by num_phases kept only the first conductor, losing ~33% of P
        phases = map_to_phases([2, 3], [157.4, 77.2])
        assert sum_phases(phases) == pytest.approx(234.6)

    def test_reversed_node_order(self):
        # Load.692 @ 692.3.1 → node_order [3, 1]
        assert same(map_to_phases([3, 1], [123.9, 42.8]), [42.8, A, 123.9])


class TestEdgeCases:
    def test_all_ground_terminal(self):
        # Capacitor.cap1 terminal 2 @ 675.0.0.0 → node_order [0, 0, 0]
        assert same(map_to_phases([0, 0, 0], [1.0, 2.0, 3.0]), [A, A, A])

    def test_nodes_above_three_are_skipped(self):
        assert same(map_to_phases([1, 4, 7], [10.0, 20.0, 30.0]), [10.0, A, A])

    def test_empty(self):
        assert same(map_to_phases([], []), [A, A, A])

    def test_extra_nodes_without_values_are_ignored(self):
        assert same(map_to_phases([1, 2, 3], [10.0]), [10.0, A, A])
