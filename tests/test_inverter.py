"""Unit tests for InverterModel (inverter.inverter)."""

import math
import sys

sys.path.insert(0, "src")

from simulators.inverter.inverter import InverterModel


class TestInitDefaults:
    def test_default_kva(self):
        inv = InverterModel(kVA=10.0)
        assert inv.kVA == 10.0

    def test_default_priority(self):
        inv = InverterModel(kVA=10.0)
        assert inv.priority == "Active"

    def test_starts_off(self):
        inv = InverterModel(kVA=10.0)
        assert inv.is_on is False

    def test_zero_outputs(self):
        inv = InverterModel(kVA=10.0)
        assert inv.P_ac == 0.0
        assert inv.Q_ac == 0.0
        assert inv.P_ac_out == [0.0, 0.0, 0.0]
        assert inv.Q_ac_out == [0.0, 0.0, 0.0]

    def test_phase_mode_upper(self):
        inv = InverterModel(kVA=10.0, phase_mode="indep")
        assert inv.phase_mode == "INDEP"


class TestCutInOut:
    def test_below_cutin_stays_off(self):
        inv = InverterModel(kVA=10.0, pct_cutin=20.0, pct_cutout=20.0)
        inv.P_dc = 1.0  # 10% of kVA < 20% cutin
        inv.calculate_step()
        assert inv.is_on is False
        assert inv.P_ac == 0.0

    def test_above_cutin_turns_on(self):
        inv = InverterModel(kVA=10.0, pct_cutin=20.0, pct_cutout=20.0)
        inv.P_dc = 3.0  # 30% of kVA > 20% cutin
        inv.calculate_step()
        assert inv.is_on is True
        assert inv.P_ac > 0.0

    def test_cutout_turns_off(self):
        inv = InverterModel(kVA=10.0, pct_cutin=20.0, pct_cutout=20.0)
        # Turn on first
        inv.P_dc = 3.0
        inv.calculate_step()
        assert inv.is_on is True
        # Now drop below cutout
        inv.P_dc = 1.0
        inv.calculate_step()
        assert inv.is_on is False
        assert inv.P_ac == 0.0


class TestEfficiency:
    def test_flat_efficiency(self):
        inv = InverterModel(
            kVA=10.0,
            eff_curve_x=[0.0, 1.0],
            eff_curve_y=[0.95, 0.95],
            pct_cutin=0.0,
            pct_cutout=0.0,
        )
        inv.P_dc = 5.0
        inv.calculate_step()
        assert abs(inv.P_ac - 5.0 * 0.95) < 1e-6


class TestPriority:
    def test_active_priority_clamps_q(self):
        inv = InverterModel(kVA=10.0, priority="Active", pct_cutin=0.0, pct_cutout=0.0)
        inv.P_dc = 8.0
        inv.Q_des = 10.0
        inv.calculate_step()
        # P_ac ~ 8 * eff, Q should be clamped
        q_max = math.sqrt(max(0, 10.0**2 - inv.P_ac**2))
        assert abs(inv.Q_ac) <= q_max + 1e-6

    def test_reactive_priority_clamps_p(self):
        inv = InverterModel(kVA=10.0, priority="Reactive", pct_cutin=0.0, pct_cutout=0.0)
        inv.P_dc = 15.0
        inv.Q_des = 5.0
        inv.calculate_step()
        # P should be clamped within kVA circle
        assert inv.P_ac <= 10.0 + 1e-6


class TestZeroKVA:
    def test_zero_kva_no_output(self):
        inv = InverterModel(kVA=0.0)
        inv.P_dc = 5.0
        inv.calculate_step()
        assert inv.P_ac == 0.0


class TestThreePhaseOutput:
    def test_three_phase_sum(self):
        inv = InverterModel(kVA=10.0, pct_cutin=0.0, pct_cutout=0.0)
        inv.P_dc = 5.0
        inv.calculate_step()
        assert len(inv.P_ac_out) == 3
        assert abs(sum(inv.P_ac_out) - inv.P_ac) < 1e-6
        assert all(abs(p - inv.P_ac / 3) < 1e-6 for p in inv.P_ac_out)
