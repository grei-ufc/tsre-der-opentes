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
        topofile=str(IEEE13),
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


class TestSolutionSettings:
    """`tolerance` e `max_iterations`, e a convergência que ninguém conferia.

    Os padrões do motor — 1e-4 e 15 iterações — são folgados para co-simulação,
    onde cada passo pode ser um salto grande de ponto de operação. E, até esta
    versão, um solve que parava no limite seguia adiante em silêncio, com
    tensões que não resolvem o circuito e têm a mesma cara das que resolvem.
    """

    def _build(self, **kwargs):
        return OpenDSS(
            topofile=str(IEEE13),
            time_step=dt.timedelta(seconds=900),
            start_time=dt.datetime(2025, 1, 1),
            **kwargs,
        )

    def test_none_keeps_the_engine_defaults(self):
        """Quem não pede nada continua com o comportamento anterior."""
        wrapper = self._build()

        assert wrapper.dss.solution.tolerance == pytest.approx(1e-4)
        assert wrapper.dss.solution.max_iterations == 15

    def test_the_settings_reach_the_engine(self):
        wrapper = self._build(tolerance=1e-8, max_iterations=100)

        assert wrapper.dss.solution.tolerance == pytest.approx(1e-8)
        assert wrapper.dss.solution.max_iterations == 100

    def test_they_survive_a_recompile(self):
        """O `Compile` do OpenDSS repõe os dois no padrão — medido.

        Sem reaplicá-los, um wrapper que recompilasse o circuito passaria a
        resolver com uma precisão que ninguém pediu, sem nada avisando.
        """
        wrapper = self._build(tolerance=1e-8, max_iterations=100)
        wrapper.redirect(str(IEEE13))

        assert wrapper.dss.solution.tolerance == pytest.approx(1e-8)
        assert wrapper.dss.solution.max_iterations == 100

    def test_a_truncated_solve_raises(self):
        """Um salto grande de ponto de operação com uma iteração só tem de acusar.

        A carga é multiplicada antes do solve de propósito: resolver de novo a
        partir da solução anterior converge em uma iteração, e é justamente o
        salto — o primeiro passo depois do setup, uma manobra de chave — que
        esgota o limite em co-simulação.
        """
        wrapper = self._build(fail_on_error=False)
        wrapper.run_command("edit Load.671 kW=5000")
        wrapper.dss.solution.max_iterations = 1
        wrapper.fail_on_error = True

        with pytest.raises(OpenDSSException, match="nao convergiu"):
            wrapper.run_dss()

    def test_the_constructor_refuses_a_circuit_it_cannot_solve(self):
        """O construtor também resolve; falhar ali é melhor que na primeira leitura."""
        with pytest.raises(OpenDSSException, match="nao convergiu"):
            self._build(max_iterations=1)

    def test_the_message_names_the_limits(self):
        """A mensagem precisa dizer o que ajustar, não só que falhou."""
        with pytest.raises(OpenDSSException) as erro:
            self._build(max_iterations=1)

        assert "max_iterations=1" in str(erro.value)
        assert "tolerance=" in str(erro.value)

    def test_with_the_error_off_it_only_reports(self, capsys):
        wrapper = self._build(max_iterations=1, fail_on_error=False)
        wrapper.run_dss()

        assert "nao convergiu" in capsys.readouterr().out
        assert wrapper.dss.solution.converged == 0

    def test_a_normal_solve_converges(self):
        wrapper = self._build()
        wrapper.run_dss()

        assert wrapper.dss.solution.converged
        assert 0 < wrapper.dss.solution.iterations <= 15
