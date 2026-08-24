"""Integration tests: per-phase reads against the real IEEE13 circuit.

IEEE13 is a good fixture because it has single-phase loads on every phase
(``652.1``, ``645.2``, ``611.3``) plus delta loads on two nodes (``646.2.3``,
``692.3.1``), which is exactly what the node-aware mapping has to get right.
"""

import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss.opendss_wrapper import OpenDSS

DATA_DIR = (pathlib.Path(__file__).parent.parent / "data" / "13Bus").resolve()
MASTER = DATA_DIR / "IEEE13Nodeckt.dss"


@pytest.fixture(scope="module")
def dss_13bus():
    if not MASTER.exists():
        pytest.skip(f"IEEE13 fixture not found at {MASTER}")

    wrapper = OpenDSS(
        redirects=str(MASTER),
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
        assert all(v == 0.0 for v in others), f"Load.{load} leaked onto other phases: {p}"

    @pytest.mark.parametrize(
        ("load", "phase_idx"),
        [("652", 0), ("645", 1), ("611", 2)],
    )
    def test_current_lands_on_the_right_phase(self, dss_13bus, load, phase_idx):
        i_mag, _ = dss_13bus.get_phase_currents(load, element="Load")

        assert i_mag[phase_idx] > 0
        others = [v for i, v in enumerate(i_mag) if i != phase_idx]
        assert all(v == 0.0 for v in others)


class TestDeltaLoads:
    def test_two_node_load_fills_both_its_phases(self, dss_13bus):
        # Load.646 @ 646.2.3
        p, _ = dss_13bus.get_phase_powers("646", element="Load")

        assert p[0] == 0.0
        assert p[1] > 0
        assert p[2] > 0

    def test_total_includes_both_conductors(self, dss_13bus):
        """Slicing by num_phases used to drop the second conductor entirely."""
        p, _ = dss_13bus.get_phase_powers("646", element="Load")

        # Load.646 is a 230 kW nominal delta load; truncating to one conductor
        # would report roughly two thirds of it.
        assert sum(p) > 200


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
        assert sum(p1) > 0
        assert sum(p2) < 0

    def test_out_of_range_terminal_raises(self, dss_13bus):
        from simulators.opendss.opendss_wrapper import OpenDSSException

        with pytest.raises(OpenDSSException, match="out of range"):
            dss_13bus.get_phase_powers("650632", element="Line", terminal=3)


class TestTransformerWindings:
    def test_single_phase_regulator_reports_on_its_phase(self, dss_13bus):
        # Transformer.reg3 @ 650.3 / rg60.3 — 1-phase on phase 3
        p, _ = dss_13bus.get_phase_powers("reg3", element="Transformer", terminal=1)

        assert p[0] == 0.0
        assert p[1] == 0.0
        assert p[2] != 0.0


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

        assert data["P1"] == 0.0
        assert data["P2"] == 0.0
        assert data["P3"] > 0
        assert data["P_meas"] == pytest.approx(data["P3"])
