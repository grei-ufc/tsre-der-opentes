"""Integration tests for the per-solution results cache.

The risk with caching engine reads is staleness: serving a value from a
superseded solution. These tests pin the invalidation contract.
"""

import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss.opendss_wrapper import OpenDSS

DATA_DIR = (pathlib.Path(__file__).parent.parent / "data" / "13Bus").resolve()
MASTER = DATA_DIR / "IEEE13Nodeckt.dss"


@pytest.fixture
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


class TestBulkVoltagesMatchPerBusReads:
    """The bulk read must agree with the per-bus path it replaces."""

    def test_every_bus_and_phase_agrees(self, dss_13bus):
        divergences = []
        for bus in dss_13bus.get_all_buses():
            ref_mag, ref_ang = dss_13bus.get_bus_voltage(bus, pu=True, mag_only=False, polar=True)
            mags, angs = dss_13bus.get_bus_voltage_pu(bus)
            for phase in range(3):
                if abs(mags[phase] - ref_mag[phase]) > 1e-9:
                    divergences.append((bus, phase, "mag"))
                if abs(angs[phase] - ref_ang[phase]) > 1e-6:
                    divergences.append((bus, phase, "ang"))

        assert divergences == []

    def test_bus_name_with_node_suffix_is_accepted(self, dss_13bus):
        assert dss_13bus.get_bus_voltage_pu("675") == dss_13bus.get_bus_voltage_pu("675.1")

    def test_unknown_bus_raises(self, dss_13bus):
        from simulators.opendss.opendss_wrapper import OpenDSSException

        with pytest.raises(OpenDSSException, match="not found"):
            dss_13bus.get_bus_voltage_pu("no_such_bus")


class TestCachingIsTransparent:
    """The contract of this cache: it must not change a single value.

    Each quantity is read twice — once served from the cache, once with the
    cache dropped immediately before — and the two must agree exactly.
    """

    @staticmethod
    def _fresh(wrapper, read, *args, **kwargs):
        """Same read, but with the cache dropped first."""
        wrapper.invalidate_snapshot()
        return read(*args, **kwargs)

    def test_every_element_power_and_current(self, dss_13bus):
        classes = {
            "Load": dss_13bus.dss.loads.names,
            "Line": dss_13bus.dss.lines.names,
            "Transformer": dss_13bus.dss.transformers.names,
            "PVSystem": dss_13bus.dss.pvsystems.names,
        }

        divergences = []
        checked = 0
        for element, names in classes.items():
            for name in names:
                if not name or name.lower() == "none":
                    continue
                for read in (dss_13bus.get_phase_powers, dss_13bus.get_phase_currents):
                    cached = read(name, element=element)
                    fresh = self._fresh(dss_13bus, read, name, element=element)
                    checked += 1
                    if cached != fresh:
                        divergences.append((element, name, read.__name__, cached, fresh))

        assert checked > 0
        assert divergences == []

    def test_every_bus_voltage(self, dss_13bus):
        divergences = []
        for bus in dss_13bus.get_all_buses():
            cached = dss_13bus.get_bus_voltage_pu(bus)
            fresh = self._fresh(dss_13bus, dss_13bus.get_bus_voltage_pu, bus)
            if cached != fresh:
                divergences.append((bus, cached, fresh))

        assert divergences == []

    def test_repeated_reads_within_a_solution_are_stable(self, dss_13bus):
        readings = [dss_13bus.get_phase_powers("671", element="Load") for _ in range(5)]
        assert all(r == readings[0] for r in readings)


class TestLazyReads:
    """Magnitudes and angles are separate engine calls; only fetch what is asked."""

    def test_magnitude_read_does_not_fetch_angles(self, dss_13bus):
        dss_13bus.get_bus_vmag_pu("675")

        assert dss_13bus._snapshot.bus_vmag_pu is not None
        assert dss_13bus._snapshot.bus_volts is None, "angles were read but not requested"

    def test_angle_read_does_not_fetch_magnitudes(self, dss_13bus):
        dss_13bus.get_bus_vang("675")

        assert dss_13bus._snapshot.bus_volts is not None
        assert dss_13bus._snapshot.bus_vmag_pu is None

    def test_node_index_survives_a_solve(self, dss_13bus):
        """Node layout belongs to the circuit, not to a solution."""
        index = dss_13bus.node_index
        dss_13bus.run_dss()

        assert dss_13bus.node_index is index

    def test_node_index_covers_every_bus(self, dss_13bus):
        buses = {b.lower().split(".")[0] for b in dss_13bus.get_all_buses()}
        assert buses <= set(dss_13bus.node_index)


class TestCacheIsPopulatedAndReused:
    def test_second_read_is_served_from_cache(self, dss_13bus, monkeypatch):
        first = dss_13bus.get_bus_vmag_pu("675")

        def explode(*_a, **_k):
            raise AssertionError("bulk array should have been served from cache")

        monkeypatch.setattr(type(dss_13bus.dss.circuit), "buses_vmag_pu", property(explode))
        assert dss_13bus.get_bus_vmag_pu("675") == first

    def test_element_snapshot_is_reused_across_quantities(self, dss_13bus):
        dss_13bus.get_phase_powers("671", element="Load")
        assert ("load", "671") in dss_13bus._snapshot.elements

        calls = []
        original = dss_13bus.set_element
        dss_13bus.set_element = lambda *a, **k: (calls.append(a), original(*a, **k))[1]
        dss_13bus.get_phase_currents("671", element="Load")

        assert calls == [], "currents should reuse the snapshot taken for powers"


class TestInvalidation:
    def test_solve_clears_the_cache(self, dss_13bus):
        dss_13bus.get_bus_voltage_pu("675")
        dss_13bus.get_phase_powers("671", element="Load")

        dss_13bus.run_dss()

        assert dss_13bus._snapshot.bus_vmag_pu is None
        assert dss_13bus._snapshot.bus_volts is None
        assert dss_13bus._snapshot.elements == {}

    def test_run_command_clears_the_cache(self, dss_13bus):
        dss_13bus.get_bus_vmag_pu("675")
        dss_13bus.run_command("edit Load.671 kW=1000")
        assert dss_13bus._snapshot.bus_vmag_pu is None

    def test_set_tap_clears_the_cache(self, dss_13bus):
        dss_13bus.get_bus_vmag_pu("675")
        dss_13bus.set_tap("reg1", 3)
        assert dss_13bus._snapshot.bus_vmag_pu is None

    def test_set_pvsystem_pq_clears_the_cache(self, dss_13bus):
        dss_13bus.get_bus_vmag_pu("675")
        dss_13bus.set_pvsystem_pq("nao_existe", 0.0, 0.0)
        assert dss_13bus._snapshot.bus_vmag_pu is None

    def test_edit_then_solve_yields_new_values(self, dss_13bus):
        """End-to-end staleness check: a real change must be observable."""
        before, _ = dss_13bus.get_phase_powers("671", element="Load")

        dss_13bus.set_power("671", p=50.0, q=10.0, element="Load")
        dss_13bus.run_dss()
        after, _ = dss_13bus.get_phase_powers("671", element="Load")

        assert sum(after) < sum(before), f"load change not reflected: {before} -> {after}"

    def test_voltages_change_after_a_load_change(self, dss_13bus):
        bus = "675"
        before, _ = dss_13bus.get_bus_voltage_pu(bus)

        dss_13bus.run_command("edit Load.675a kW=5000")
        dss_13bus.run_dss()
        after, _ = dss_13bus.get_bus_voltage_pu(bus)

        assert after[0] != before[0], "bulk voltages served a stale solution"
