"""Tests for failure reporting.

A silent failure in a power-flow co-simulation produces a full day of subtly
wrong data with nothing in the output to indicate it. These tests pin the
places that used to swallow errors.
"""

import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss._writer import _values_match
from simulators.opendss.api_opendss import OpenDSSSimulator
from simulators.opendss.opendss_wrapper import OpenDSS, OpenDSSException

DATA = (pathlib.Path(__file__).parent.parent / "data").resolve()
IEEE13 = DATA / "13Bus" / "IEEE13Nodeckt.dss"
IEEE13_PV = DATA / "13Bus" / "run_ieee13_cosim_pv_5min.dss"


@pytest.fixture(scope="module")
def dss():
    if not IEEE13.exists():
        pytest.skip("IEEE13 fixture not found")
    wrapper = OpenDSS(
        redirects=str(IEEE13),
        time_step=dt.timedelta(seconds=300),
        start_time=dt.datetime(2025, 1, 1),
    )
    wrapper.run_dss()
    return wrapper


class TestValueComparison:
    """set_property used to compare str(read_back) == str(written)."""

    @pytest.mark.parametrize(
        ("read_back", "written"),
        [(1100.0, 1100), (1100.0, "1100"), (1100.0, 1100.0), (0.5, 0.5000001)],
    )
    def test_numeric_forms_match(self, read_back, written):
        assert _values_match(read_back, written)

    @pytest.mark.parametrize(
        ("read_back", "written"),
        [("constant", "Constant"), ("wye", "WYE")],
    )
    def test_text_is_case_insensitive(self, read_back, written):
        assert _values_match(read_back, written)

    @pytest.mark.parametrize(
        ("read_back", "written"),
        [(1100.0, 1200.0), ("wye", "delta")],
    )
    def test_real_mismatches_are_caught(self, read_back, written):
        assert not _values_match(read_back, written)


class TestSetProperty:
    @pytest.mark.parametrize("value", [1100, 1100.0, "1100"])
    def test_accepts_equivalent_numeric_forms(self, dss, value):
        """Writing an int used to raise AssertionError: '1100' != '1100.0'."""
        dss.set_property("671", "kW", value, element="Load")
        assert dss.get_property("671", "kW", "Load") == pytest.approx(1100.0)

    def test_unknown_property_is_rejected_before_reaching_the_engine(self, dss, monkeypatch):
        """Sending a bad property to OpenDSS opens a Windows dialog box.

        Validating first keeps non-interactive runs from hanging on it.
        """
        commands = []
        monkeypatch.setattr(dss, "run_command", lambda cmd: commands.append(cmd))

        with pytest.raises(OpenDSSException, match="has no property"):
            dss.set_property("671", "nao_existe", 1, element="Load")

        assert commands == [], f"a bad edit reached the engine: {commands}"

    def test_the_error_lists_valid_properties(self, dss):
        with pytest.raises(OpenDSSException, match="Valid options"):
            dss.set_property("671", "nao_existe", 1, element="Load")


class TestRegulatorMeasurements:
    """The phase current used to be indexed at position ``phase - 1``.

    For a single-phase regulator off phase 1 that raised IndexError, which a
    bare ``except`` turned into a silent zero — disabling line drop
    compensation on those phases.
    """

    def test_every_phase_reports_current(self, dss):
        zeros = []
        for info in dss.get_all_regulators_info():
            measurements = dss.get_regulator_measurements(info)
            if abs(measurements["i"]) == 0.0:
                zeros.append((info["name"], info["target_phase"]))

        assert zeros == [], f"regulators reporting zero current: {zeros}"

    def test_every_phase_reports_voltage(self, dss):
        for info in dss.get_all_regulators_info():
            assert abs(dss.get_regulator_measurements(info)["v"]) > 0

    def test_phases_two_and_three_are_not_zero(self, dss):
        """IEEE13 has reg1/reg2/reg3 on phases 1, 2 and 3."""
        by_phase = {
            info["target_phase"]: abs(dss.get_regulator_measurements(info)["i"])
            for info in dss.get_all_regulators_info()
        }

        assert by_phase[2] > 0
        assert by_phase[3] > 0

    def test_bad_phase_raises_instead_of_returning_zero(self, dss):
        info = dict(dss.get_all_regulators_info()[0])
        info["target_phase"] = 9

        with pytest.raises(OpenDSSException, match="phase 9"):
            dss.get_regulator_measurements(info)

    def test_bad_winding_raises(self, dss):
        info = dict(dss.get_all_regulators_info()[0])
        info["winding"] = 99

        with pytest.raises(OpenDSSException, match="out of range"):
            dss.get_regulator_measurements(info)

    def test_no_regcontrols_returns_empty(self, dss, monkeypatch):
        monkeypatch.setattr(type(dss.dss.regcontrols), "count", property(lambda _s: 0))
        assert dss.get_all_regulators_info() == []


@pytest.fixture(scope="module")
def sim():
    if not IEEE13_PV.exists():
        pytest.skip("IEEE13 PV fixture not found")
    simulator = OpenDSSSimulator()
    simulator.init("DSS-0", 1.0, topofile=str(IEEE13_PV), step_size=300)
    simulator.create(1, "Grid")
    simulator.setup_done()
    return simulator


class TestControlWritesAreNotSwallowed:
    def test_a_failing_write_stops_the_step(self, sim):
        """A lost control action makes the run diverge from what was commanded."""
        eid = sim._eids_by_type["RegControl"][0]

        with pytest.raises(OpenDSSException, match="Failed to apply"):
            sim.step(0, {eid: {"tap": {"ctrl": "nao_e_numero"}}}, 300)

    def test_the_error_names_the_entity(self, sim):
        eid = sim._eids_by_type["RegControl"][0]

        with pytest.raises(OpenDSSException) as excinfo:
            sim.step(0, {eid: {"tap": {"ctrl": object()}}}, 300)

        assert eid in str(excinfo.value)

    def test_valid_writes_still_pass(self, sim):
        eid = sim._eids_by_type["RegControl"][0]
        sim.step(0, {eid: {"tap": {"ctrl": 2}}}, 300)
        assert sim.get_data({eid: ["tap"]})[eid]["tap"] == 2


class TestSetupDone:
    def test_setup_done_solves(self, sim):
        sim.dss_wrapper.invalidate_snapshot()
        sim.setup_done()

        # Uma solução válida deixa as tensões em faixa plausível.
        mags = sim.dss_wrapper.get_bus_vmag_pu("675")
        assert any(0.8 < m < 1.2 for m in mags)


class TestPvCurveBypassIsOptional:
    def _build(self, **kwargs):
        simulator = OpenDSSSimulator()
        simulator.init("DSS-0", 1.0, topofile=str(IEEE13_PV), step_size=300, **kwargs)
        simulator.create(1, "Grid")
        return simulator

    def test_bypass_is_on_by_default(self):
        simulator = self._build()
        cutin = simulator.dss_wrapper.dss.text("? PVSystem.pv.%cutin")
        assert float(cutin) == pytest.approx(0.0001)

    def test_bypass_can_be_disabled(self):
        """Deixa o OpenDSS aplicar suas próprias curvas de eficiência."""
        simulator = self._build(bypass_native_pv_curves=False)
        curve = simulator.dss_wrapper.dss.text("? PVSystem.pv.EffCurve")
        assert curve.lower() != "effideal_cosim"
