"""Integration tests: per-phase reads against the real IEEE13 circuit.

IEEE13 is a good fixture because it has single-phase loads on every phase
(``652.1``, ``645.2``, ``611.3``) plus delta loads on two nodes (``646.2.3``,
``692.3.1``), which is exactly what the node-aware mapping has to get right.
"""

import datetime as dt
import math
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss._utils import sum_phases
from simulators.opendss.opendss_wrapper import OpenDSS

DATA_DIR = (pathlib.Path(__file__).parent.parent / "data" / "13Bus").resolve()
MASTER = DATA_DIR / "IEEE13Nodeckt.dss"


@pytest.fixture(scope="module")
def dss_13bus():
    if not MASTER.exists():
        pytest.skip(f"IEEE13 fixture not found at {MASTER}")

    wrapper = OpenDSS(
        topofile=str(MASTER),
        time_step=dt.timedelta(seconds=900),
        start_time=dt.datetime(2025, 1, 1),
    )
    if wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    wrapper.run_dss()
    return wrapper


class TestSinglePhaseLoads:
    """A single-phase load must report on its own phase, not on phase 1."""

    @pytest.mark.parametrize(
        ("load", "phase_idx"),
        [("652", 0), ("645", 1), ("611", 2)],
    )
    def test_power_lands_on_the_right_phase(self, dss_13bus, load, phase_idx):
        p, _ = dss_13bus.get_phase_powers(load, element="Load")

        assert p[phase_idx] > 0, f"Load.{load} reported nothing on phase {phase_idx + 1}"
        others = [v for i, v in enumerate(p) if i != phase_idx]
        assert all(math.isnan(v) for v in others), f"Load.{load} leaked onto other phases: {p}"

    @pytest.mark.parametrize(
        ("load", "phase_idx"),
        [("652", 0), ("645", 1), ("611", 2)],
    )
    def test_current_lands_on_the_right_phase(self, dss_13bus, load, phase_idx):
        i_mag, _ = dss_13bus.get_phase_currents(load, element="Load")

        assert i_mag[phase_idx] > 0
        others = [v for i, v in enumerate(i_mag) if i != phase_idx]
        assert all(math.isnan(v) for v in others)


class TestDeltaLoads:
    def test_two_node_load_fills_both_its_phases(self, dss_13bus):
        # Load.646 @ 646.2.3
        p, _ = dss_13bus.get_phase_powers("646", element="Load")

        assert math.isnan(p[0])
        assert p[1] > 0
        assert p[2] > 0

    def test_total_includes_both_conductors(self, dss_13bus):
        """Slicing by num_phases used to drop the second conductor entirely."""
        p, _ = dss_13bus.get_phase_powers("646", element="Load")

        # Load.646 is a 230 kW nominal delta load; truncating to one conductor
        # would report roughly two thirds of it.
        assert sum_phases(p) > 200


class TestThreePhaseLoads:
    def test_all_three_phases_present(self, dss_13bus):
        p, q = dss_13bus.get_phase_powers("671", element="Load")

        assert all(v > 0 for v in p), f"expected power on all phases, got {p}"
        assert len(p) == 3
        assert len(q) == 3


class TestLineTerminals:
    def test_both_terminals_readable(self, dss_13bus):
        p1, _ = dss_13bus.get_phase_powers("650632", element="Line", terminal=1)
        p2, _ = dss_13bus.get_phase_powers("650632", element="Line", terminal=2)

        # Power flows in at terminal 1 and out at terminal 2, so signs oppose.
        assert sum_phases(p1) > 0
        assert sum_phases(p2) < 0

    def test_out_of_range_terminal_raises(self, dss_13bus):
        from simulators.opendss.opendss_wrapper import OpenDSSException

        with pytest.raises(OpenDSSException, match="out of range"):
            dss_13bus.get_phase_powers("650632", element="Line", terminal=3)


class TestTransformerWindings:
    def test_single_phase_regulator_reports_on_its_phase(self, dss_13bus):
        # Transformer.reg3 @ 650.3 / rg60.3 — 1-phase on phase 3
        p, _ = dss_13bus.get_phase_powers("reg3", element="Transformer", terminal=1)

        assert math.isnan(p[0])
        assert math.isnan(p[1])
        assert p[2] != 0.0


class TestElementLosses:
    """Perdas por elemento: a repartição por fase e o total.

    As duas leituras do motor saem em unidades diferentes — ``losses`` em W/var
    e ``phase_losses`` em kW/kvar —, e nada no valor denuncia a troca: um erro
    de mil vezes nas perdas de uma linha ainda parece um número plausível de
    potência. Por isso os testes abaixo ancoram em identidades físicas, e não em
    valores esperados.
    """

    def test_loss_is_what_does_not_come_out_the_other_end(self, dss_13bus):
        """A perda da linha é o que entra por um terminal e não sai pelo outro."""
        p_in, _ = dss_13bus.get_phase_powers("650632", element="Line", terminal=1)
        p_out, _ = dss_13bus.get_phase_powers("650632", element="Line", terminal=2)
        p_loss, _ = dss_13bus.get_element_losses("650632", element="Line")

        assert p_loss == pytest.approx(sum_phases(p_in) + sum_phases(p_out), rel=1e-9)

    def test_total_is_in_kw_like_the_phases(self, dss_13bus):
        """O motor entrega este total em W; o wrapper converte.

        Sem a conversão as duas leituras sairiam com mil vezes de diferença uma
        da outra — e o erro passaria por um valor de potência qualquer.
        """
        p_phase, q_phase = dss_13bus.get_phase_losses("650632", element="Line")
        p_total, q_total = dss_13bus.get_element_losses("650632", element="Line")

        assert p_total == pytest.approx(sum_phases(p_phase), rel=1e-9)
        assert q_total == pytest.approx(sum_phases(q_phase), rel=1e-9)

    def test_circuit_losses_are_the_sum_of_the_series_elements(self, dss_13bus):
        """Fecha o balanço do alimentador inteiro, na unidade do circuito."""
        total = sum(
            dss_13bus.get_element_losses(name, element="Line")[0]
            for name in dss_13bus.dss.lines.names
        )
        total += sum(
            dss_13bus.get_element_losses(name, element="Transformer")[0]
            for name in dss_13bus.dss.transformers.names
        )

        assert total == pytest.approx(dss_13bus.get_losses()[0], rel=1e-6)

    @pytest.mark.parametrize(
        ("line", "present"),
        [
            ("650632", {0, 1, 2}),
            # 645646 fica em 645.3.2 / 646.3.2: as fases são 2 e 3, e a primeira
            # parcela que o motor devolve é a da fase 3, não a da fase 1.
            ("645646", {1, 2}),
            ("684652", {0}),
        ],
    )
    def test_phase_losses_land_on_the_lines_own_phases(self, dss_13bus, line, present):
        p_loss, _ = dss_13bus.get_phase_losses(line, element="Line")

        assert {i for i, v in enumerate(p_loss) if not math.isnan(v)} == present

    def test_a_single_phase_regulator_reports_on_its_phase(self, dss_13bus):
        # Transformer.reg3 regula a fase 3; o neutro entra no total, não nas fases.
        p_loss, _ = dss_13bus.get_phase_losses("reg3", element="Transformer")

        assert math.isnan(p_loss[0])
        assert math.isnan(p_loss[1])
        assert not math.isnan(p_loss[2])

    def test_losses_are_not_fetched_with_the_powers(self, dss_13bus):
        """Duas leituras a mais por elemento que quase nenhum cenário pede."""
        dss_13bus.invalidate_snapshot()
        dss_13bus.get_phase_powers("650632", element="Line")

        assert dss_13bus._snapshot.elements[("line", "650632")].losses is None

    def test_the_second_loss_read_is_served_from_the_cache(self, dss_13bus):
        dss_13bus.invalidate_snapshot()
        first = dss_13bus.get_phase_losses("650632", element="Line")

        calls = []
        original = dss_13bus.set_element
        dss_13bus.set_element = lambda *a, **k: (calls.append(a), original(*a, **k))[1]
        try:
            assert dss_13bus.get_phase_losses("650632", element="Line") == first
            assert dss_13bus.get_element_losses("650632", element="Line")
            assert calls == [], "o elemento foi reativado para uma leitura já em cache"
        finally:
            dss_13bus.set_element = original


class TestSwitchState:
    """Uma chave tem um estado; o OpenDSS tem um por terminal.

    ``Line.671692`` é a única chave do IEEE13. Os testes restauram o estado
    fechado no fim, porque a fixture é de módulo.
    """

    SWITCH = "671692"

    @pytest.fixture(autouse=True)
    def fechada(self, dss_13bus):
        yield
        dss_13bus.set_is_open(self.SWITCH, open=False, element="Line")
        dss_13bus.run_dss()

    def test_is_terminal_open_answers_for_the_terminal_it_is_given(self, dss_13bus):
        """A docstring do py-dss-interface diz "any terminal"; não é o caso.

        É essa a razão de `get_is_open` percorrer os terminais em vez de confiar
        num só: aberta pelo 2, a chave continua "fechada" pelo 1.
        """
        dss_13bus.set_is_open(self.SWITCH, open=True, element="Line", term=2)
        dss_13bus.set_element(self.SWITCH, "Line")

        assert not dss_13bus.dss.cktelement.is_terminal_open(1)
        assert dss_13bus.dss.cktelement.is_terminal_open(2)

    def test_open_on_any_terminal_reads_as_open(self, dss_13bus):
        for term in (1, 2):
            dss_13bus.set_is_open(self.SWITCH, open=False, element="Line")
            dss_13bus.set_is_open(self.SWITCH, open=True, element="Line", term=term)

            assert dss_13bus.get_is_open(self.SWITCH, element="Line"), (
                f"aberta pelo terminal {term} e lida como fechada"
            )

    def test_opening_uses_terminal_2(self, dss_13bus):
        """A convenção do próprio IEEE123 (``open Line.Sw7 terminal=2``).

        Adotá-la faz o estado produzido aqui ficar indistinguível do que vem
        declarado no circuito.
        """
        dss_13bus.set_is_open(self.SWITCH, open=True, element="Line")

        assert dss_13bus.get_is_open(self.SWITCH, element="Line", term=2)
        assert not dss_13bus.get_is_open(self.SWITCH, element="Line", term=1)

    def test_closing_clears_both_terminals(self, dss_13bus):
        dss_13bus.set_is_open(self.SWITCH, open=True, element="Line", term=1)
        dss_13bus.set_is_open(self.SWITCH, open=True, element="Line", term=2)

        dss_13bus.set_is_open(self.SWITCH, open=False, element="Line")

        assert not dss_13bus.get_is_open(self.SWITCH, element="Line")

    def test_a_line_is_closed_by_default(self, dss_13bus):
        assert not dss_13bus.get_is_open("650632", element="Line")


class TestAmpacity:
    """O limite de corrente da linha — o denominador do carregamento."""

    def test_it_is_the_same_field_the_lines_api_reports(self, dss_13bus):
        """`cktelement` e `lines` leem o mesmo campo; a via usada aqui é a primeira."""
        dss_13bus.dss.lines.name = "650632"

        assert dss_13bus.get_ampacity("650632", "Line") == (
            dss_13bus.dss.lines.norm_amps,
            dss_13bus.dss.lines.emerg_amps,
        )

    def test_the_shipped_feeders_declare_none(self, dss_13bus):
        """Documenta em código a ressalva que a referência destaca.

        Nenhum ``.dss`` do IEEE13 declara ``normamps``, então toda linha cai no
        padrão do motor — 400 A do tronco ao ramal monofásico. Se algum dia o
        circuito passar a declarar ampacidade, este teste falha e aponta para a
        documentação que precisa acompanhar.
        """
        ratings = {dss_13bus.get_ampacity(name, "Line") for name in dss_13bus.dss.lines.names}

        assert ratings == {(400.0, 600.0)}


class TestMosaikAttributeExtraction:
    def test_registry_reader_uses_real_phase(self, dss_13bus):
        """The registry reader maps to the element's node, not to position."""
        from simulators.opendss.element_specs import ModelSpec, phase_attr_map, read_phases

        spec = ModelSpec(
            dss_class="Load",
            reader=read_phases,
            attr_map=phase_attr_map(p=("P1", "P2", "P3"), p_total=("P_meas",)),
        )

        class FakeSim:
            dss_wrapper = dss_13bus

        data = read_phases(FakeSim(), "611", ["P1", "P2", "P3", "P_meas"], spec)

        assert math.isnan(data["P1"])
        assert math.isnan(data["P2"])
        assert data["P3"] > 0
        # O total soma só as fases presentes: com o `sum` embutido, uma única
        # fase ausente tornaria P_meas NaN em todo elemento não trifásico.
        assert data["P_meas"] == pytest.approx(data["P3"])
