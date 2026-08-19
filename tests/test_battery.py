"""Unit tests for OpenDSSBattery (battery.battery_model)."""

import math
import sys

sys.path.insert(0, "src")

from simulators.battery.battery_model import OpenDSSBattery


class TestInitDefaults:
    def test_basic_attrs(self):
        bat = OpenDSSBattery(name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0)
        assert bat.name == "bat1"
        assert bat.kw_rated == 10.0
        assert bat.kwh_rated == 20.0

    def test_state_is_idling(self):
        bat = OpenDSSBattery(name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0)
        assert bat.state == OpenDSSBattery.STATE_IDLING
        assert bat.get_state_str() == "Idling"

    def test_efficiencies(self):
        bat = OpenDSSBattery(
            name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0,
            pct_eff_charge=85.0, pct_eff_discharge=95.0,
        )
        assert abs(bat.eff_charge - 0.85) < 1e-6
        assert abs(bat.eff_discharge - 0.95) < 1e-6

    def test_reserve(self):
        bat = OpenDSSBattery(
            name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0,
            pct_reserve=25.0,
        )
        assert abs(bat.kwh_reserve - 5.0) < 1e-6


class TestDischarge:
    def test_discharge_state(self):
        bat = OpenDSSBattery(name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0)
        result = bat.calculate_step(p_request=5.0, q_request=0.0, dt_seconds=3600)
        assert bat.state == OpenDSSBattery.STATE_DISCHARGING
        assert result["state"] == "Discharging"
        assert result["p_kw"] > 0

    def test_soc_decreases(self):
        bat = OpenDSSBattery(name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0)
        soc_before = bat.kwh_stored
        bat.calculate_step(p_request=5.0, q_request=0.0, dt_seconds=3600)
        bat.calculate_step(p_request=5.0, q_request=0.0, dt_seconds=3600)
        assert bat.kwh_stored < soc_before


class TestCharge:
    def test_charge_state(self):
        bat = OpenDSSBattery(name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0)
        result = bat.calculate_step(p_request=-5.0, q_request=0.0, dt_seconds=3600)
        assert bat.state == OpenDSSBattery.STATE_CHARGING
        assert result["state"] == "Charging"
        assert result["p_kw"] < 0

    def test_soc_increases(self):
        bat = OpenDSSBattery(name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0)
        soc_before = bat.kwh_stored
        bat.calculate_step(p_request=-5.0, q_request=0.0, dt_seconds=3600)
        bat.calculate_step(p_request=-5.0, q_request=0.0, dt_seconds=3600)
        assert bat.kwh_stored > soc_before


class TestIdle:
    def test_idle_state(self):
        bat = OpenDSSBattery(name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0)
        result = bat.calculate_step(p_request=0.0, q_request=0.0, dt_seconds=3600)
        assert bat.state == OpenDSSBattery.STATE_IDLING
        assert result["state"] == "Idling"


class TestSoCLimits:
    def test_soc_floor(self):
        bat = OpenDSSBattery(
            name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=0.5,
            pct_reserve=0.0,
        )
        bat.calculate_step(p_request=10.0, q_request=0.0, dt_seconds=7200)
        assert bat.kwh_stored >= 0.0

    def test_soc_ceiling(self):
        bat = OpenDSSBattery(
            name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=19.5,
        )
        bat.calculate_step(p_request=-10.0, q_request=0.0, dt_seconds=7200)
        assert bat.kwh_stored <= bat.kwh_rated


class TestKVALimit:
    def test_q_clamped(self):
        bat = OpenDSSBattery(
            name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0,
            kva_rated=10.0,
        )
        result = bat.calculate_step(p_request=8.0, q_request=10.0, dt_seconds=3600)
        s = math.sqrt(result["p_kw"] ** 2 + result["q_kvar"] ** 2)
        assert s <= 10.0 + 1e-6


class TestEfficiencyCurve:
    def test_efficiency_interpolation(self):
        bat = OpenDSSBattery(
            name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0,
            eff_curve_x=[0.2, 0.5, 1.0],
            eff_curve_y=[0.85, 0.92, 0.97],
        )
        eff = bat.get_inverter_efficiency(5.0)  # 50% pu
        assert abs(eff - 0.92) < 1e-6

    def test_efficiency_at_zero(self):
        bat = OpenDSSBattery(name="bat1", kw_rated=10.0, kwh_rated=20.0, kwh_stored=10.0)
        eff = bat.get_inverter_efficiency(0.0)
        assert eff == 0.0
