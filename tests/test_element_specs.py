"""Tests for the declarative model registry.

The point of the registry is that META cannot drift from the implementation.
These tests hold that line: every declared attribute must actually be produced
(outputs) or accepted (inputs) by the simulator.
"""

import math
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss._utils import ABSENT
from simulators.opendss.api_opendss import OpenDSSSimulator
from simulators.opendss.element_specs import (
    BUS_AGGREGATES,
    LINE_LOADING_OUTPUTS,
    MODEL_SPECS,
    build_meta,
    bus_aggregates,
    phase_attr_map,
    single_value,
    sum_values,
)

DATA_DIR = (pathlib.Path(__file__).parent.parent / "data" / "13Bus").resolve()
MASTER = DATA_DIR / "run_ieee13_cosim_pv_5min.dss"


@pytest.fixture(scope="module")
def sim():
    if not MASTER.exists():
        pytest.skip(f"IEEE13 PV fixture not found at {MASTER}")

    simulator = OpenDSSSimulator()
    simulator.init("DSS-0", 1.0, topofile=str(MASTER), step_size=300)
    if simulator.dss_wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    simulator.create(1, "Grid")
    simulator.step(0, {}, 300)
    return simulator


class TestAggregators:
    def test_sum_adds_contributions(self):
        assert sum_values("P_set", "Storage-x", [10.0, 5.0, 2.5]) == 17.5

    def test_single_passes_one_value_through(self):
        assert single_value("tap", "RegControl-x", [3]) == 3

    def test_single_warns_on_conflict(self, capsys):
        result = single_value("tap", "RegControl-x", [3, 7])

        assert result == 3
        assert "concorrentes" in capsys.readouterr().out

    def test_conflicting_inputs_are_not_silently_dropped(self, capsys):
        """The old code took [0] with no trace; that is the regression guarded here."""
        single_value("tap", "RegControl-x", [3, 7])
        assert capsys.readouterr().out != ""


class TestBusAggregates:
    """One number per bus, for scenarios and for the heatmap of the web view.

    ``get_bus_vmag_pu`` always returns three values, with ``NaN`` where the bus
    has no phase. Counting those would report a single-phase lateral as being at
    a third of its voltage; contá-las como zero, que era a convenção anterior,
    confundia a fase ausente com a barra em curto.
    """

    def test_absent_phases_do_not_count(self):
        result = bus_aggregates([ABSENT, 0.97, ABSENT], BUS_AGGREGATES)

        assert result["V_min_pu"] == pytest.approx(0.97)
        assert result["V_max_pu"] == pytest.approx(0.97)
        assert result["V_mean_pu"] == pytest.approx(0.97)
        assert result["V_unb_pct"] == pytest.approx(0.0)

    def test_a_collapsed_phase_counts(self):
        """0.0 pu é um curto franco, não uma fase ausente.

        Enquanto a ausência era 0.0 as duas eram indistinguíveis, e a barra em
        curto — justamente a que o mapa de calor deve destacar — saía da conta.
        """
        result = bus_aggregates([0.0, 0.97, 0.98], BUS_AGGREGATES)

        assert result["V_min_pu"] == 0.0

    def test_three_phase_bus(self):
        result = bus_aggregates([1.00, 0.98, 0.96], BUS_AGGREGATES)

        assert result["V_min_pu"] == pytest.approx(0.96)
        assert result["V_max_pu"] == pytest.approx(1.00)
        assert result["V_mean_pu"] == pytest.approx(0.98)
        # NEMA: maior desvio (0.02) sobre a média (0.98).
        assert result["V_unb_pct"] == pytest.approx(100 * 0.02 / 0.98)

    def test_bus_without_any_phase_is_absent_not_an_error(self):
        result = bus_aggregates([ABSENT, ABSENT, ABSENT], BUS_AGGREGATES)

        assert set(result) == set(BUS_AGGREGATES)
        assert all(math.isnan(v) for v in result.values())

    def test_a_fully_collapsed_bus_reads_zero(self):
        """Três fases em 0.0 pu existem e valem zero — não são ausência."""
        result = bus_aggregates([0.0, 0.0, 0.0], BUS_AGGREGATES)

        assert result["V_min_pu"] == 0.0
        assert result["V_max_pu"] == 0.0

    def test_only_requested_attributes_are_computed(self):
        assert set(bus_aggregates([1.0, 1.0, 1.0], ["V_min_pu"])) == {"V_min_pu"}

    def test_reader_serves_them_from_the_circuit(self, sim):
        eid = next(e for e in sim._eids_by_type["Bus"])
        data = sim.get_data({eid: [*BUS_AGGREGATES, "V1_pu", "V2_pu", "V3_pu"]})[eid]

        phases = [v for v in (data["V1_pu"], data["V2_pu"], data["V3_pu"]) if not math.isnan(v)]
        assert data["V_min_pu"] == pytest.approx(min(phases))
        assert data["V_max_pu"] == pytest.approx(max(phases))


class TestPhaseAttrMap:
    def test_sign_applies_to_power_not_current(self):
        mapping = phase_attr_map(p=("P1",), i_mag=("I1_A",), p_total=("P_meas",), sign=-1)

        assert mapping["P1"] == ("p", 0, -1.0)
        assert mapping["I1_A"] == ("i_mag", 0, 1.0)
        assert mapping["P_meas"] == ("p_sum", 0, -1.0)

    def test_scale_applies_to_totals(self):
        mapping = phase_attr_map(p_total=("P_out_mw",), scale=1 / 1000.0)
        assert mapping["P_out_mw"] == ("p_sum", 0, 0.001)

    def test_losses_ignore_sign_and_scale(self):
        """Perda é dissipação: não é injeção que se inverta nem total que se reescale.

        O nome do atributo de perda já traz a unidade, então herdar o `scale`
        dos totais faria um `Ploss_kw` sair em MW.
        """
        mapping = phase_attr_map(
            p_loss=("Ploss1_kw",),
            p_loss_total=("Ploss_kw",),
            sign=-1,
            scale=1 / 1000.0,
        )

        assert mapping["Ploss1_kw"] == ("p_loss", 0, 1.0)
        assert mapping["Ploss_kw"] == ("p_loss_sum", 0, 1.0)


class TestLosses:
    """As perdas chegando ao cenário pelo caminho do mosaik."""

    @pytest.mark.parametrize("model", ["Line", "Transformer"])
    def test_series_models_expose_losses(self, model):
        attrs = set(build_meta()["models"][model]["attrs"])

        assert {"Ploss_kw", "Qloss_kvar", "Ploss1_kw", "Qloss1_kvar"} <= attrs

    @pytest.mark.parametrize("model", ["Load", "PVSystem", "Storage", "Bus"])
    def test_shunt_models_do_not(self, model):
        """Num elemento de um terminal o mesmo cálculo devolve a potência dele.

        Seria uma "perda" do tamanho da carga — um número plausível e errado.
        """
        assert not [a for a in build_meta()["models"][model]["attrs"] if "loss" in a.lower()]

    def test_line_loss_is_the_power_that_does_not_arrive(self, sim):
        """Confere a unidade contra as potências do próprio adaptador."""
        eid = "Line-650632"
        data = sim.get_data({eid: ["P1_w", "P2_w", "P3_w", "Ploss_kw", "Ploss1_kw"]})[eid]
        # Em módulo: com os PVs do circuito despachando, o fluxo desta linha se
        # inverte, e o que interessa aqui é a ordem de grandeza.
        passante = abs(
            sum(v for v in (data["P1_w"], data["P2_w"], data["P3_w"]) if not math.isnan(v))
        )

        # A linha 650632 carrega o alimentador inteiro: a perda é uma fração
        # pequena do que passa por ela, e não da ordem dela.
        assert 0 < data["Ploss_kw"] < 0.1 * passante
        assert data["Ploss1_kw"] <= data["Ploss_kw"]

    def test_absent_phases_are_absent_not_zero(self, sim):
        """Mesma convenção do resto do adaptador: a fase que não existe é NaN."""
        # Line.684652 é monofásica na fase 1.
        data = sim.get_data({"Line-684652": ["Ploss1_kw", "Ploss2_kw", "Ploss3_kw"]})["Line-684652"]

        assert not math.isnan(data["Ploss1_kw"])
        assert math.isnan(data["Ploss2_kw"])
        assert math.isnan(data["Ploss3_kw"])


class TestGeneratedMeta:
    def test_meta_has_every_model(self):
        meta = build_meta()
        assert set(meta["models"]) == {"Grid", *MODEL_SPECS}

    def test_no_duplicate_attrs(self):
        for model, spec in build_meta()["models"].items():
            attrs = spec["attrs"]
            assert len(attrs) == len(set(attrs)), f"{model} has duplicate attrs"

    def test_tap_is_both_input_and_output_but_listed_once(self):
        attrs = build_meta()["models"]["RegControl"]["attrs"]
        assert attrs.count("tap") == 1

    def test_writable_models_declare_a_writer(self):
        for model, spec in MODEL_SPECS.items():
            if spec.inputs:
                assert spec.writer is not None, f"{model} declares inputs but no writer"

    def test_inputs_without_writer_are_rejected(self):
        for model, spec in MODEL_SPECS.items():
            if spec.writer is None:
                assert not spec.inputs, f"{model} has a writer-less input"


class TestMetaMatchesImplementation:
    """Every declared output must actually come back from get_data."""

    @pytest.mark.parametrize(
        "model", ["Bus", "Load", "Line", "PVSystem", "RegControl", "Transformer"]
    )
    def test_all_declared_outputs_are_produced(self, sim, model):
        spec = MODEL_SPECS[model]
        eids = sim._eids_by_type.get(model, [])
        assert eids, f"no {model} entities in the fixture"

        eid = eids[0]
        declared = list(spec.outputs)
        produced = sim.get_data({eid: declared})[eid]

        missing = [a for a in declared if a not in produced]
        assert missing == [], f"{model} declares but does not produce: {missing}"

    def test_no_unrequested_attrs_are_returned(self, sim):
        eid = sim._eids_by_type["Line"][0]
        produced = sim.get_data({eid: ["I1_A"]})[eid]
        assert set(produced) == {"I1_A"}

    def test_unknown_entity_is_skipped(self, sim):
        assert sim.get_data({"Nope-1": ["P1"]}) == {}

    def test_unknown_attr_is_ignored(self, sim):
        eid = sim._eids_by_type["Bus"][0]
        assert sim.get_data({eid: ["nao_existe"]})[eid] == {}


class TestInputRouting:
    # Single-phase PV on 611.3 — exercises setpoint routing and phase placement
    # in one go.
    PV = "PVSystem-pv-5"

    def test_every_pv_tracks_its_setpoint(self, sim):
        """Guards the fixture: a wrong kV makes a PV ignore its setpoint.

        PVSystem.pv was declared kV=0.277 (the line-to-neutral base of a 0.48 kV
        bus) while a three-phase wye element takes line-to-line, and it injected
        102 kW when asked for 42.
        """
        off_target = []
        for eid in sim._eids_by_type["PVSystem"]:
            sim.step(0, {eid: {"P_des": {"c": 42.0}, "Q_des": {"c": 0.0}}}, 300)
            measured = sim.get_data({eid: ["P_meas"]})[eid]["P_meas"]
            if abs(measured - 42.0) > 0.05:
                off_target.append((eid, measured))

        assert off_target == []

    def test_pvsystem_inputs_reach_the_circuit(self, sim):
        sim.step(0, {self.PV: {"P_des": {"ctrl": 42.0}, "Q_des": {"ctrl": 0.0}}}, 300)

        measured = sim.get_data({self.PV: ["P_meas"]})[self.PV]["P_meas"]
        assert measured == pytest.approx(42.0, rel=1e-3)

    def test_concurrent_power_setpoints_are_summed(self, sim):
        """Two controllers on one element: summed, not silently dropped."""
        sim.step(0, {self.PV: {"P_des": {"a": 20.0, "b": 22.0}, "Q_des": {"a": 0.0}}}, 300)

        measured = sim.get_data({self.PV: ["P_meas"]})[self.PV]["P_meas"]
        assert measured == pytest.approx(42.0, rel=1e-3)

    def test_single_phase_pv_setpoint_lands_on_its_own_phase(self, sim):
        sim.step(0, {self.PV: {"P_des": {"ctrl": 30.0}, "Q_des": {"ctrl": 0.0}}}, 300)

        data = sim.get_data({self.PV: ["P1", "P2", "P3"]})[self.PV]
        assert math.isnan(data["P1"])
        assert math.isnan(data["P2"])
        assert data["P3"] == pytest.approx(30.0, rel=1e-3)

    def test_inputs_for_read_only_models_are_ignored(self, sim):
        eid = sim._eids_by_type["Bus"][0]
        sim.step(0, {eid: {"V1_pu": {"src": 1.0}}}, 300)  # must not raise

    def test_regulator_tap_is_applied(self, sim):
        eid = sim._eids_by_type["RegControl"][0]
        sim.step(0, {eid: {"tap": {"ctrl": 4}}}, 300)

        assert sim.get_data({eid: ["tap"]})[eid]["tap"] == 4


class TestGenerationInPerUnit:
    """Geração normalizada pela placa, que torna PVs diferentes comparáveis.

    Uma escala de cor da visualização é compartilhada por todos os PVs do
    alimentador. Em kW isso não fecha: os seis PVs do IEEE13 têm a mesma placa
    de 1000 kW, mas os trifásicos entregam ~333 kW por fase e os monofásicos
    1000 kW. Em pu da própria placa os dois marcam o mesmo.

    Fica antes das baterias de propósito: a fixture ``storage_sim`` compila
    outro circuito, e todas as instâncias do ``py_dss_interface`` dividem um
    único motor — depois dela, ``PVSystem.pv`` não existe mais no circuito ativo.
    """

    TRIFASICO = "PVSystem-pv"
    MONOFASICO = "PVSystem-pv-5"
    DESPACHO = 100.0  # 10% da placa de 1000 kW dos dois

    @pytest.fixture
    def despachados(self, sim):
        sim.step(
            0,
            {
                eid: {"P_des": {"c": self.DESPACHO}, "Q_des": {"c": 0.0}}
                for eid in (self.TRIFASICO, self.MONOFASICO)
            },
            300,
        )
        pedidos = ["P_pu", "P1_pu", "P2_pu", "P3_pu", "P1", "P2", "P3"]
        return (
            sim.get_data({self.TRIFASICO: pedidos})[self.TRIFASICO],
            sim.get_data({self.MONOFASICO: pedidos})[self.MONOFASICO],
        )

    def test_pu_outputs_are_declared(self):
        attrs = set(build_meta()["models"]["PVSystem"]["attrs"])

        assert {"P_pu", "P1_pu", "P2_pu", "P3_pu"} <= attrs

    def test_nameplate_is_the_rating_and_not_the_setpoint(self, sim):
        """``write_pvsystem`` reescreve o ``pmpp`` do elemento a cada passo.

        Se a normalização relesse o ``pmpp`` do motor, ela dividiria a geração
        por ela mesma e todo inversor marcaria 1.0 o tempo todo.
        """
        sim.step(0, {self.TRIFASICO: {"P_des": {"c": 42.0}, "Q_des": {"c": 0.0}}}, 300)

        assert sim.pv_nameplate("pv") == (1000.0, 3)

    def test_the_same_fraction_reads_the_same_pu(self, despachados):
        tri, mono = despachados

        assert tri["P_pu"] == pytest.approx(0.1, rel=1e-2)
        assert mono["P_pu"] == pytest.approx(0.1, rel=1e-2)

    def test_each_phase_is_normalized_by_its_own_share(self, despachados):
        """A parcela é ``Pmpp / fases``, então plena geração é 1.0 nos dois."""
        tri, mono = despachados

        assert tri["P1_pu"] == pytest.approx(0.1, rel=1e-2)
        assert mono["P3_pu"] == pytest.approx(0.1, rel=1e-2)

    def test_the_same_pu_comes_from_very_different_kw(self, despachados):
        """O motivo de existir o pu: em kW estes dois não cabem numa escala."""
        tri, mono = despachados

        assert tri["P1"] == pytest.approx(self.DESPACHO / 3, rel=1e-2)
        assert mono["P3"] == pytest.approx(self.DESPACHO, rel=1e-2)

    def test_absent_phases_are_absent_not_zero(self, despachados):
        """Zero seria lido como "nao esta gerando"; a fase nem existe."""
        _, mono = despachados

        assert math.isnan(mono["P1_pu"])
        assert math.isnan(mono["P2_pu"])

    def test_generation_is_positive(self, despachados):
        """Injetar é positivo, como no resto do adaptador (PV_SIGN)."""
        tri, mono = despachados

        assert tri["P_pu"] > 0
        assert mono["P_pu"] > 0

    def test_unknown_pv_has_no_nameplate(self, sim):
        assert sim.pv_nameplate("nao-existe") == (0.0, 0)


class TestLineLoading:
    """Carregamento por fase: a corrente em % da ampacidade da linha.

    Em amperes não dá para dizer se uma linha está folgada ou no limite. O
    carregamento põe tronco e ramal na mesma escala — desde que o denominador
    seja um dado do alimentador, o que nos circuitos deste repositório não é.
    """

    def test_it_is_the_current_over_the_rating(self, sim):
        eid = "Line-650632"
        data = sim.get_data({eid: ["I1_A", "I2_A", "I3_A", *LINE_LOADING_OUTPUTS]})[eid]
        norm_amps = sim.get_extra_info()[eid]["norm_amps"]

        for phase, (corrente, carga) in enumerate(
            zip(["I1_A", "I2_A", "I3_A"], LINE_LOADING_OUTPUTS, strict=True), start=1
        ):
            assert data[carga] == pytest.approx(100.0 * data[corrente] / norm_amps), f"fase {phase}"

    def test_absent_phases_are_absent_not_zero(self, sim):
        """Zero seria lido como linha descarregada; a fase nem existe."""
        # Line.684652 é monofásica na fase 1.
        data = sim.get_data({"Line-684652": LINE_LOADING_OUTPUTS})["Line-684652"]

        assert not math.isnan(data["Loading1_pct"])
        assert math.isnan(data["Loading2_pct"])
        assert math.isnan(data["Loading3_pct"])

    def test_the_ratings_reach_the_scenario(self, sim):
        """Sem o denominador à vista, não dá para saber o que o % significa."""
        info = sim.get_extra_info()["Line-650632"]

        assert info["norm_amps"] > 0
        assert info["emerg_amps"] > 0

    def test_a_line_without_a_rating_is_absent_not_an_error(self, sim):
        """Denominador zero: ausência de referência, não divisão por zero."""
        eid = "Line-650632"
        original = sim._line_ampacity["650632"]
        sim._line_ampacity["650632"] = (0.0, 0.0)
        try:
            data = sim.get_data({eid: LINE_LOADING_OUTPUTS})[eid]
        finally:
            sim._line_ampacity["650632"] = original

        assert all(math.isnan(v) for v in data.values())

    def test_reading_the_loading_costs_no_extra_engine_visit(self, sim):
        """As correntes já estão no snapshot; o rating veio na criação."""
        wrapper = sim.dss_wrapper
        wrapper.invalidate_snapshot()
        sim.get_data({"Line-650632": ["I1_A"]})

        calls = []
        original = wrapper.set_element
        wrapper.set_element = lambda *a, **k: (calls.append(a), original(*a, **k))[1]
        try:
            sim.get_data({"Line-650632": LINE_LOADING_OUTPUTS})
        finally:
            wrapper.set_element = original

        assert calls == [], "o elemento foi reativado só para calcular o carregamento"


DECLARED_AMPACITY_CIRCUIT = """\
Redirect "{master}"
New LineCode.limitada nphases=3 baseFreq=60 rmatrix=[0.1|0.03 0.1|0.03 0.03 0.1] \
xmatrix=[0.2|0.09 0.2|0.09 0.09 0.2] units=kft normamps=100 emergamps=150
New Line.herda bus1=671 bus2=680 linecode=limitada length=0.5 units=kft
New Line.declara bus1=671 bus2=680 linecode=limitada length=0.5 units=kft normamps=250
"""


@pytest.fixture(scope="module")
def declared_sim(tmp_path_factory):
    """IEEE13 com duas linhas que têm ampacidade de verdade.

    Os alimentadores que acompanham o projeto não declaram nenhuma, então é
    aqui que se verifica que um ``normamps`` declarado — e um herdado do
    ``LineCode`` — chega mesmo ao carregamento.
    """
    master = DATA_DIR / "IEEE13Nodeckt.dss"
    if not master.exists():
        pytest.skip(f"IEEE13 fixture not found at {master}")

    path = tmp_path_factory.mktemp("ampacity") / "limites.dss"
    path.write_text(DECLARED_AMPACITY_CIRCUIT.format(master=master.as_posix()))

    simulator = OpenDSSSimulator()
    simulator.init("DSS-0", 1.0, topofile=str(path), step_size=300)
    if simulator.dss_wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    simulator.create(1, "Grid")
    simulator.step(0, {}, 300)
    return simulator


class TestDeclaredAmpacity:
    def test_a_rating_inherited_from_the_linecode_is_used(self, declared_sim):
        """O motor resolve a herança: não é preciso procurar o LineCode."""
        assert declared_sim.line_ampacity("herda") == (100.0, 150.0)

    def test_a_rating_declared_on_the_line_overrides_the_linecode(self, declared_sim):
        assert declared_sim.line_ampacity("declara") == (250.0, 150.0)

    def test_the_same_current_reads_a_lower_loading_on_the_larger_rating(self, declared_sim):
        """Duas linhas idênticas entre as mesmas barras: só o limite difere.

        250/100 = 2.5, então a que tem o limite maior tem de marcar 2.5 vezes
        menos — é o que prova que o denominador é mesmo o da linha, e não um
        valor comum a todas.
        """
        herda = declared_sim.get_data({"Line-herda": ["Loading1_pct", "I1_A"]})["Line-herda"]
        declara = declared_sim.get_data({"Line-declara": ["Loading1_pct", "I1_A"]})["Line-declara"]

        assert declara["I1_A"] == pytest.approx(herda["I1_A"], rel=1e-6)
        assert herda["Loading1_pct"] == pytest.approx(2.5 * declara["Loading1_pct"], rel=1e-6)


STORAGE_CIRCUIT = """\
Redirect "{master}"
New Storage.bat1 phases=3 bus1=675 kV=4.16 kWrated=500 kWhrated=1000 %stored=60 State=IDLING
New Storage.bat2 phases=1 bus1=611.3 kV=2.4 kWrated=100 kWhrated=200 %stored=45 State=IDLING
"""


@pytest.fixture(scope="module")
def storage_sim(tmp_path_factory):
    """IEEE13 plus two batteries; the shipped circuits have no Storage."""
    master = DATA_DIR / "IEEE13Nodeckt.dss"
    if not master.exists():
        pytest.skip(f"IEEE13 fixture not found at {master}")

    path = tmp_path_factory.mktemp("storage") / "bat.dss"
    path.write_text(STORAGE_CIRCUIT.format(master=master.as_posix()))

    simulator = OpenDSSSimulator()
    simulator.init("DSS-0", 1.0, topofile=str(path), step_size=300)
    if simulator.dss_wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    simulator.create(1, "Grid")
    simulator.step(0, {}, 300)
    return simulator


class TestStorage:
    def test_soc_is_read(self, storage_sim):
        assert storage_sim.get_data({"Storage-bat1": ["SoC"]})["Storage-bat1"]["SoC"] == (
            pytest.approx(0.60)
        )
        assert storage_sim.get_data({"Storage-bat2": ["SoC"]})["Storage-bat2"]["SoC"] == (
            pytest.approx(0.45)
        )

    def test_soc_set_is_applied(self, storage_sim):
        """Declared as an input since the start, but it used to do nothing."""
        storage_sim.step(300, {"Storage-bat2": {"SoC_set": {"ctrl": 0.9}}}, 300)
        soc = storage_sim.get_data({"Storage-bat2": ["SoC"]})["Storage-bat2"]["SoC"]
        assert soc == pytest.approx(0.9)

    def test_soc_set_is_clamped(self, storage_sim):
        storage_sim.step(600, {"Storage-bat2": {"SoC_set": {"ctrl": 5.0}}}, 300)
        soc = storage_sim.get_data({"Storage-bat2": ["SoC"]})["Storage-bat2"]["SoC"]
        assert soc == pytest.approx(1.0)

    def test_single_phase_battery_reports_on_its_phase(self, storage_sim):
        # Room to charge: a full battery refuses the setpoint and just idles.
        storage_sim.step(900, {"Storage-bat2": {"SoC_set": {"ctrl": 0.5}}}, 300)
        storage_sim.step(1200, {"Storage-bat2": {"P_set": {"ctrl": -40.0}}}, 300)
        data = storage_sim.get_data({"Storage-bat2": ["P1", "P2", "P3", "P_act"]})

        # bat2 sits on 611.3
        assert math.isnan(data["Storage-bat2"]["P1"])
        assert math.isnan(data["Storage-bat2"]["P2"])
        assert data["Storage-bat2"]["P3"] == pytest.approx(-40.0, rel=1e-2)

    def test_all_declared_storage_outputs_are_produced(self, storage_sim):
        declared = list(MODEL_SPECS["Storage"].outputs)
        produced = storage_sim.get_data({"Storage-bat1": declared})["Storage-bat1"]
        assert [a for a in declared if a not in produced] == []


@pytest.fixture(scope="module")
def switch_sim():
    """IEEE13 **sem** PV, para a manobra de chave ser um problema bem-posto.

    A fixture ``sim`` não serve aqui. Nela a barra 692 tem um ``PVSystem``, e
    abrir a ``671692`` deixa uma ilha alimentada só por uma fonte de potência
    constante, **sem referência de tensão**: o fluxo não tem solução e diverge —
    ver :class:`TestIslandWithoutReference`. Sem o PV, a barra simplesmente se
    desenergiza e o circuito continua resolvível.

    Fica no fim do arquivo, com as demais fixtures que compilam outro circuito:
    todas as instâncias do ``py_dss_interface`` dividem um motor só.
    """
    master = DATA_DIR / "IEEE13Nodeckt.dss"
    if not master.exists():
        pytest.skip(f"IEEE13 fixture not found at {master}")

    simulator = OpenDSSSimulator()
    simulator.init("DSS-0", 1.0, topofile=str(master), step_size=300)
    if simulator.dss_wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    simulator.create(1, "Grid")
    simulator.step(0, {}, 300)
    return simulator


class TestSwitchCommanding:
    """Abrir e fechar a chave do IEEE13 pelo caminho do mosaik.

    ``Line.671692`` liga 671 a 692; abri-la desliga a barra 692 e as cargas
    penduradas nela. É a manobra que prova que o comando chega ao motor e
    sobrevive ao ``Solve`` do passo seguinte.
    """

    SWITCH = "Switch-671692"
    JUSANTE = "Bus-692"

    # A corrente de um terminal aberto não zera exatamente: sobra o resíduo
    # numérico da solução (da ordem de 1e-9 A).
    ABERTA_A = 1e-6

    @pytest.fixture
    def fechada(self, switch_sim):
        """Garante o estado fechado antes e depois de cada teste da classe."""
        switch_sim.step(0, {self.SWITCH: {"is_open": {"c": False}}}, 300)
        yield
        switch_sim.step(0, {self.SWITCH: {"is_open": {"c": False}}}, 300)

    def test_it_starts_closed(self, switch_sim, fechada):
        data = switch_sim.get_data({self.SWITCH: ["is_open"]})[self.SWITCH]
        assert data["is_open"] is False

    def test_opening_is_read_back(self, switch_sim, fechada):
        switch_sim.step(300, {self.SWITCH: {"is_open": {"ctrl": True}}}, 300)

        data = switch_sim.get_data({self.SWITCH: ["is_open"]})[self.SWITCH]
        assert data["is_open"] is True

    def test_opening_stops_the_current(self, switch_sim, fechada):
        antes = switch_sim.get_data({self.SWITCH: ["I1_A"]})[self.SWITCH]["I1_A"]
        assert antes > 1.0

        switch_sim.step(300, {self.SWITCH: {"is_open": {"ctrl": True}}}, 300)

        depois = switch_sim.get_data({self.SWITCH: ["I1_A"]})[self.SWITCH]["I1_A"]
        assert depois < self.ABERTA_A

    def test_opening_de_energizes_the_bus_downstream(self, switch_sim, fechada):
        """O que prova que a manobra é elétrica, e não só um flag.

        Sem geração própria a jusante, a barra isolada vai a zero — e o circuito
        continua convergindo, porque o problema segue bem-posto.
        """
        antes = switch_sim.get_data({self.JUSANTE: ["V1_pu"]})[self.JUSANTE]["V1_pu"]
        assert antes > 0.9

        switch_sim.step(300, {self.SWITCH: {"is_open": {"ctrl": True}}}, 300)
        aberta = switch_sim.get_data({self.JUSANTE: ["V1_pu"]})[self.JUSANTE]["V1_pu"]

        switch_sim.step(600, {self.SWITCH: {"is_open": {"ctrl": False}}}, 300)
        refechada = switch_sim.get_data({self.JUSANTE: ["V1_pu"]})[self.JUSANTE]["V1_pu"]

        assert aberta == pytest.approx(0.0, abs=1e-9)
        # Refechar não devolve o bit exato: com a tolerância padrão do motor
        # (1e-4) a solução pousa em qualquer ponto dentro da banda, e a
        # diferença medida fica na ordem de 1e-8 pu.
        assert refechada == pytest.approx(antes, abs=1e-6)

    def test_the_manoeuvre_converges(self, switch_sim, fechada):
        """A tensão acima só significa alguma coisa se o passo convergiu."""
        switch_sim.step(300, {self.SWITCH: {"is_open": {"ctrl": True}}}, 300)

        data = switch_sim.get_data({"Circuit-0": ["converged", "iterations"]})["Circuit-0"]
        assert data["converged"] is True
        assert data["iterations"] > 0

    def test_closing_undoes_an_opening_made_on_the_other_terminal(self, switch_sim, fechada):
        """A armadilha: o circuito pode ter aberto a chave pelo terminal 1.

        É o caso das chaves normalmente abertas do IEEE123, que o ``.dss`` abre
        com ``terminal=2``. Se fechar mexesse num terminal só, o comando falharia
        em silêncio — com a corrente seguindo em zero.
        """
        switch_sim.dss_wrapper.set_is_open("671692", open=True, element="Line", term=1)
        switch_sim.step(300, {}, 300)
        assert switch_sim.get_data({self.SWITCH: ["is_open"]})[self.SWITCH]["is_open"] is True

        switch_sim.step(600, {self.SWITCH: {"is_open": {"ctrl": False}}}, 300)

        data = switch_sim.get_data({self.SWITCH: ["is_open", "I1_A"]})[self.SWITCH]
        assert data["is_open"] is False
        assert data["I1_A"] > 1.0

    def test_an_open_switch_is_still_read(self, switch_sim, fechada):
        """Aberta, ela continua na coleta — com zero, que é uma medição."""
        switch_sim.step(300, {self.SWITCH: {"is_open": {"ctrl": True}}}, 300)

        data = switch_sim.get_data({self.SWITCH: ["I1_A", "Loading1_pct"]})[self.SWITCH]

        assert data["I1_A"] < self.ABERTA_A
        assert data["Loading1_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_concurrent_commands_warn(self, switch_sim, fechada, capsys):
        """Somar comandos de chave não faz sentido; o conflito não some."""
        switch_sim.step(300, {self.SWITCH: {"is_open": {"a": True, "b": False}}}, 300)

        assert "concorrentes" in capsys.readouterr().out

    def test_the_model_declares_is_open_once(self):
        """Entrada e saída, como o `tap` do RegControl — listado uma só vez."""
        attrs = build_meta()["models"]["Switch"]["attrs"]

        assert attrs.count("is_open") == 1
        assert "is_open" in MODEL_SPECS["Switch"].inputs

    def test_a_line_takes_no_commands(self):
        """Só a chave manobra: a linha continua somente de leitura."""
        assert MODEL_SPECS["Line"].writer is None
        assert MODEL_SPECS["Line"].inputs == {}


@pytest.fixture(scope="module")
def pv_sim():
    """O circuito com PV, recompilado para os testes de ilhamento.

    Não reusa ``sim``: estes testes deixam o circuito sem convergir de propósito,
    e a fixture de módulo é compartilhada.
    """
    if not MASTER.exists():
        pytest.skip(f"IEEE13 PV fixture not found at {MASTER}")

    simulator = OpenDSSSimulator()
    simulator.init("DSS-0", 1.0, topofile=str(MASTER), step_size=300)
    if simulator.dss_wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    simulator.create(1, "Grid")
    simulator.step(0, {}, 300)
    return simulator


class TestIslandWithoutReference:
    """Ilhar geração sem referência de tensão não tem solução — e agora acusa.

    Abrir a ``671692`` no circuito com PV deixa a barra 692 alimentada apenas
    por um ``PVSystem``, que é fonte de potência constante: não há barra de folga
    na ilha, e o fluxo diverge em vez de convergir devagar. Medido: 2,1 pu em 15
    iterações, 1,0 em 100 e **6,4 em 1000** com tolerância de 1e-8.

    Este teste existe porque o caso passou despercebido. Antes de ``run_dss``
    conferir ``converged``, uma versão anterior desta suíte afirmava sobre a
    tensão dessa barra como se fosse uma ilha energizada pelo inversor — o
    número era a iteração 15 de um solve divergente.
    """

    def test_it_raises_instead_of_reporting_garbage(self, pv_sim):
        from simulators.opendss.opendss_wrapper import OpenDSSException

        with pytest.raises(OpenDSSException, match="nao convergiu"):
            pv_sim.step(300, {"Switch-671692": {"is_open": {"c": True}}}, 300)

    def test_with_the_error_off_the_circuit_model_records_it(self, pv_sim):
        """Quem prefere seguir e marcar desliga o erro e lê `converged`."""
        pv_sim.dss_wrapper.fail_on_error = False
        try:
            pv_sim.step(600, {"Switch-671692": {"is_open": {"c": True}}}, 300)
            data = pv_sim.get_data({"Circuit-0": ["converged"]})["Circuit-0"]
        finally:
            pv_sim.dss_wrapper.fail_on_error = True

        assert data["converged"] is False


class TestExtraInfoIsolation:
    def test_child_extra_info_is_a_copy(self, sim):
        """A local scenario must not hold a live reference into simulator state."""
        eid = sim._eids_by_type["PVSystem"][0]
        child = next(c for c in sim._children if c["eid"] == eid)

        assert child["extra_info"] is not sim._extra_info[eid]

        sim._extra_info[eid]["pmpp"] = 999999
        assert child["extra_info"]["pmpp"] != 999999
