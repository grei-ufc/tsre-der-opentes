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
    PV = "PVSystem-pv-5_bus611"

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

    TRIFASICO = "PVSystem-pv_bus634"
    MONOFASICO = "PVSystem-pv-5_bus611"
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


class TestExtraInfoIsolation:
    def test_child_extra_info_is_a_copy(self, sim):
        """A local scenario must not hold a live reference into simulator state."""
        eid = sim._eids_by_type["PVSystem"][0]
        child = next(c for c in sim._children if c["eid"] == eid)

        assert child["extra_info"] is not sim._extra_info[eid]

        sim._extra_info[eid]["pmpp"] = 999999
        assert child["extra_info"]["pmpp"] != 999999
