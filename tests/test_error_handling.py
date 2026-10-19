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
from simulators.opendss.element_specs import build_meta
from simulators.opendss.opendss_wrapper import OpenDSS, OpenDSSException

DATA = (pathlib.Path(__file__).parent.parent / "data").resolve()
IEEE13 = DATA / "13Bus" / "IEEE13Nodeckt.dss"
IEEE13_PV = DATA / "13Bus" / "run_ieee13_cosim_pv_5min.dss"

# Curvas MyEff e MyPvsT de data/13Bus/ieee13_pv.dss.
DECLARED_EFF = [0.86, 0.90, 0.93, 0.97]
DECLARED_PT = [1.2, 1.0, 0.8, 0.6]


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
        """Validating first gives an error that lists the valid properties.

        With OpenDSS dialogs enabled, a bad property also opened a Windows dialog
        box that hung non-interactive runs.
        """
        commands = []
        monkeypatch.setattr(dss, "run_command", lambda cmd: commands.append(cmd))

        with pytest.raises(OpenDSSException, match="has no property"):
            dss.set_property("671", "nao_existe", 1, element="Load")

        assert commands == [], f"a bad edit reached the engine: {commands}"

    def test_the_error_lists_valid_properties(self, dss):
        with pytest.raises(OpenDSSException, match="Valid options"):
            dss.set_property("671", "nao_existe", 1, element="Load")


class TestSetPower:
    """`set_power` atende Load, Generator e Storage; PVSystem tem caminho próprio."""

    @pytest.mark.parametrize("element", ["PVSystem", "pvsystem", "PV"])
    def test_a_pvsystem_is_refused_before_the_engine(self, dss, monkeypatch, element):
        """A classe não tem `kW`: o motor recusaria com `Unknown parameter "kW"`.

        `"PV"` era aceito como apelido de `PVSystem`, e o comando falhava.
        """
        commands = []
        monkeypatch.setattr(dss, "run_command", lambda cmd: commands.append(cmd))

        with pytest.raises(OpenDSSException, match="set_pvsystem_pq"):
            dss.set_power("pv", p=100.0, q=0.0, element=element)

        assert commands == [], f"o comando chegou ao motor: {commands}"

    def test_a_pvsystem_is_refused_even_with_the_error_off(self, dss, monkeypatch):
        """É erro de uso, não do motor: o `fail_on_error` não o alcança."""
        monkeypatch.setattr(dss, "fail_on_error", False)

        with pytest.raises(OpenDSSException, match="set_pvsystem_pq"):
            dss.set_power("pv", p=100.0, element="PVSystem")

    def test_a_load_is_still_written(self, dss):
        # Os valores declarados no IEEE13: a fixture é compartilhada.
        dss.set_power("671", p=1155.0, q=660.0, element="Load")

        assert dss.get_property("671", "kW", "Load") == pytest.approx(1155.0)
        assert dss.get_property("671", "kvar", "Load") == pytest.approx(660.0)


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


class TestPvSystemsLoadWithIdealConversion:
    """O carregamento troca a conversão DC/AC nativa dos PVSystems por uma ideal.

    A potência chega pronta ao OpenDSS — calculada pelo inversor ou pela curva
    de multiplicadores — e tem de sair igual: sem a eficiência e o derating
    térmico aplicados por cima, e sem o ``%cutin`` de 20 % do kVA zerando a
    geração nas pontas do dia.
    """

    def _build(self):
        if not IEEE13_PV.exists():
            pytest.skip("IEEE13 PV fixture not found")
        return OpenDSS(
            topofile=str(IEEE13_PV),
            time_step=dt.timedelta(seconds=300),
            start_time=dt.datetime(2025, 1, 1),
        )

    def _inject(self, wrapper, p_kw, temperature=25.0):
        """Comanda ``p_kw`` no PV-2, com os demais desligados, e devolve o medido."""
        for name in wrapper.get_all_pvsystems_info():
            wrapper.set_pvsystem_pq(name, 0.0, 0.0)
        wrapper.run_command(f"Edit PVSystem.pv-2 temperature={temperature}")
        wrapper.set_pvsystem_pq("pv-2", p_kw, 0.0)
        wrapper.run_dss()
        return wrapper.get_pvsystem_power("pv-2")[0]

    @pytest.mark.parametrize(
        "p_kw",
        [
            pytest.param(50.0, id="abaixo-do-cutin-declarado"),
            pytest.param(300.0, id="meia-carga"),
            pytest.param(900.0, id="perto-da-placa"),
        ],
    )
    def test_the_commanded_power_is_injected(self, p_kw):
        assert self._inject(self._build(), p_kw) == pytest.approx(p_kw, rel=1e-4)

    def test_temperature_does_not_derate(self):
        """A 60 °C, a P-TCurve declarada cortaria 14 % da geração."""
        injected = self._inject(self._build(), 300.0, temperature=60.0)
        assert injected == pytest.approx(300.0, rel=1e-4)

    def test_the_constructor_solve_is_already_ideal(self):
        """A troca faz parte do carregamento, antes da primeira solução.

        Com as curvas nativas, os 800 kW do ``.dss`` (Pmpp=1000, irrad=0.8)
        sairiam multiplicados pela eficiência a 0,8 pu, cerca de 0,96.
        """
        wrapper = self._build()
        assert wrapper.get_pvsystem_power("pv")[0] == pytest.approx(800.0, rel=1e-4)

    def test_the_declared_curves_are_still_reported(self):
        """Um inversor modelado fora aplica essas perdas, e precisa recebê-las."""
        info = self._build().get_all_pvsystems_info()["pv"]

        assert info["eff_curve_y"] == pytest.approx(DECLARED_EFF)
        assert info["pt_curve_y"] == pytest.approx(DECLARED_PT)
        assert info["pct_cutin"] == pytest.approx(20.0)  # padrão do OpenDSS

    def test_a_recompile_idealizes_again(self):
        """O ``Compile`` traz de volta as curvas declaradas."""
        wrapper = self._build()
        wrapper.redirect(str(IEEE13_PV))
        # O master declara `mode=daily`, e o redirect, ao contrário do
        # construtor, não volta ao snapshot: a hora 0 da curva `daily` do PV
        # zeraria a geração, com ou sem as curvas ideais.
        wrapper.run_command("set mode=snapshot")

        assert self._inject(wrapper, 50.0, temperature=60.0) == pytest.approx(50.0, rel=1e-4)
        info = wrapper.get_all_pvsystems_info()["pv"]
        assert info["eff_curve_y"] == pytest.approx(DECLARED_EFF)


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


class TestEngineErrorsAfterLoading:
    """Depois de compilar, todo erro do motor passa pelo `fail()`, sem caixa de diálogo.

    O OpenDSS abre uma caixa de diálogo no Windows a cada comando recusado, e ela
    trava a execução até alguém clicar — com ou sem `fail_on_error`. Fora da
    compilação as caixas ficam desligadas, e o erro volta como código e texto.
    Antes só o texto era conferido, à procura da palavra "error", que a maioria
    das mensagens do motor não contém.
    """

    @pytest.fixture
    def wrapper(self):
        if not IEEE13.exists():
            pytest.skip("IEEE13 fixture not found")
        wrapper = OpenDSS(
            topofile=str(IEEE13),
            time_step=dt.timedelta(seconds=300),
            start_time=dt.datetime(2025, 1, 1),
        )
        # Guarda: com as caixas ligadas, os comandos inválidos destes testes
        # travariam a suíte esperando um clique.
        if wrapper.dss.dssinterface.allow_forms:
            pytest.fail("as caixas de diálogo continuam ligadas depois da compilação")
        return wrapper

    def test_dialogs_are_off_after_loading(self, wrapper):
        assert wrapper.dss.dssinterface.allow_forms == 0

    def test_dialogs_are_on_while_compiling(self, wrapper, monkeypatch):
        """Um erro no meio do `.dss` só aparece pela caixa de diálogo.

        O `Redirect` informa só o erro da última linha executada; sem a caixa,
        um erro de digitação no arquivo passaria em silêncio.
        """
        durante = {}
        original = wrapper.dss.text

        def text(cmd):
            if cmd.lower().startswith("compile"):
                durante["allow_forms"] = wrapper.dss.dssinterface.allow_forms
            return original(cmd)

        monkeypatch.setattr(wrapper.dss, "text", text)
        wrapper.redirect(str(IEEE13))

        assert durante["allow_forms"] == 1
        assert wrapper.dss.dssinterface.allow_forms == 0

    @pytest.mark.parametrize(
        ("cmd", "code"),
        [
            pytest.param("Edit Load.671 naoexiste=1", 580, id="parametro-inexistente"),
            pytest.param("comando_invalido", 302, id="comando-inexistente"),
            pytest.param(
                "New Line.x bus1=671 bus2=692 linecode=nao_existe", 180, id="linecode-inexistente"
            ),
            pytest.param("Edit Load.671 kW=abc", 303, id="valor-invalido"),
        ],
    )
    def test_a_refused_command_stops(self, wrapper, cmd, code):
        """Só o último caso tem "error" no texto; os outros passavam como aviso."""
        with pytest.raises(OpenDSSException, match=rf"\[OpenDSS {code}\]"):
            wrapper.run_command(cmd)

    def test_the_message_carries_the_engine_text(self, wrapper):
        with pytest.raises(OpenDSSException, match='Unknown parameter "naoexiste"'):
            wrapper.run_command("Edit Load.671 naoexiste=1")

    def test_with_the_error_off_it_only_reports(self, wrapper, capsys):
        wrapper.fail_on_error = False
        wrapper.run_command("Edit Load.671 naoexiste=1")

        assert "Unknown parameter" in capsys.readouterr().out

    def test_a_valid_command_is_not_flagged(self, wrapper):
        wrapper.run_command("Edit Load.671 kW=1000")

        assert wrapper.get_property("671", "kW", "Load") == pytest.approx(1000.0)


class TestFailOnErrorFromTheScenario:
    """`fail_on_error` como parâmetro do `init()`, e não só do wrapper.

    Sem ele, o caminho de "seguir e marcar" que a documentação recomendava —
    desligar o erro e registrar `converged` pelo modelo `Circuit` — não estava ao
    alcance do cenário: a flag passada ao `world.start` caía em `**sim_params` e
    era ignorada em silêncio.
    """

    def _start(self, **kwargs):
        if not IEEE13.exists():
            pytest.skip("IEEE13 fixture not found")
        simulator = OpenDSSSimulator()
        simulator.init("DSS-0", 1.0, topofile=str(IEEE13), step_size=300, **kwargs)
        return simulator

    def test_it_reaches_the_wrapper(self):
        assert self._start(fail_on_error=False).dss_wrapper.fail_on_error is False

    def test_it_is_on_by_default(self):
        assert self._start().dss_wrapper.fail_on_error is True

    def test_it_is_declared_in_meta(self):
        assert "fail_on_error" in build_meta()["models"]["Grid"]["params"]

    def test_follow_and_mark(self, capsys):
        """O passo que não converge segue adiante, e fica marcado no `Circuit`."""
        simulator = self._start(max_iterations=1, fail_on_error=False)
        simulator.create(1, "Grid")
        simulator.step(0, {"Load-671": {"S_mult": {"csv": 0.1}}}, 300)
        data = simulator.get_data({"Circuit-0": ["converged"]})["Circuit-0"]

        assert data["converged"] is False
        assert "nao convergiu" in capsys.readouterr().out

    def test_by_default_the_same_circuit_stops(self):
        with pytest.raises(OpenDSSException, match="nao convergiu"):
            self._start(max_iterations=1)
