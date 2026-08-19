"""Unit tests for VR_Model (controller.regulator_control)."""

import sys

sys.path.insert(0, "src")

from simulators.controller.regulator_control import VR_Model


class TestInitDefaults:
    def test_vref(self):
        vr = VR_Model(name="reg1", Ts=5.0)
        assert vr.Vref == 120

    def test_tap_starts_zero(self):
        vr = VR_Model(name="reg1", Ts=5.0)
        assert vr.tap == 0

    def test_state_idle(self):
        vr = VR_Model(name="reg1", Ts=5.0)
        assert vr.state == "Idle"

    def test_tap_limits(self):
        vr = VR_Model(name="reg1", Ts=5.0, tap_max=10, tap_min=-10)
        assert vr.tap_max == 10
        assert vr.tap_min == -10


class TestHighVoltage:
    def test_ov_reduces_tap(self):
        vr = VR_Model(name="reg1", Ts=5.0, Vref=120, db=2, Td_ctrl=0, Td_tap=0)
        # With PT_Ratio=20: V_meas=2600 → Vsec=130 > Vref+db/2=121 → OV → tap decreases
        for _ in range(20):
            vr.run(V_meas=2600.0)
        assert vr.tap < 0


class TestLowVoltage:
    def test_uv_increases_tap(self):
        vr = VR_Model(name="reg1", Ts=5.0, Vref=120, db=2, Td_ctrl=0, Td_tap=0)
        # V_meas=2000 → Vsec=100 < Vref-db/2=119 → UV → tap increases
        for _ in range(20):
            vr.run(V_meas=2000.0)
        assert vr.tap > 0


class TestNormalVoltage:
    def test_no_change_in_band(self):
        vr = VR_Model(name="reg1", Ts=5.0, Vref=120, db=2, Td_ctrl=0, Td_tap=0)
        # V_meas=2400 → Vsec=120 → within deadband [119, 121] → no change
        for _ in range(10):
            vr.run(V_meas=2400.0)
        assert vr.tap == 0


class TestLDC:
    def test_ldc_compensates(self):
        vr = VR_Model(
            name="reg1", Ts=5.0, Vref=120, db=2,
            PT_Ratio=20, CT_Primary=700, LDC_R=2, LDC_X=0,
            Td_ctrl=0, Td_tap=0,
        )
        # With current flowing, LDC should compensate voltage
        vr.run(V_meas=120.0, I_meas=0)
        vr.tap = 0  # reset
        vr.run(V_meas=120.0, I_meas=100)
        # Just verify it runs without error


class TestTapLimits:
    def test_tap_clamped_to_max(self):
        vr = VR_Model(name="reg1", Ts=5.0, Vref=120, tap_max=3, tap_min=-3, Td_ctrl=0, Td_tap=0)
        for _ in range(50):
            vr.run(V_meas=2000.0)  # UV → tap increases
        assert vr.tap <= 3

    def test_tap_clamped_to_min(self):
        vr = VR_Model(name="reg1", Ts=5.0, Vref=120, tap_max=3, tap_min=-3, Td_ctrl=0, Td_tap=0)
        for _ in range(50):
            vr.run(V_meas=2600.0)  # OV → tap decreases
        assert vr.tap >= -3
