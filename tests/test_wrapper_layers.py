"""Tests for the wrapper's layer split (engine / reader / writer / legacy).

The split only pays off if the boundaries hold: readers must not mutate the
circuit, writers must invalidate the cache, and the public API must stay flat
so existing scenarios and notebooks keep working.
"""

import datetime as dt
import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, "src")

from simulators.opendss import _engine, _legacy, _reader, _writer
from simulators.opendss.opendss_wrapper import OpenDSS, OpenDSSException

DATA_DIR = (pathlib.Path(__file__).parent.parent / "data" / "13Bus").resolve()
MASTER = DATA_DIR / "run_ieee13_cosim_pv_5min.dss"


@pytest.fixture(scope="module")
def dss():
    if not MASTER.exists():
        pytest.skip(f"IEEE13 PV fixture not found at {MASTER}")

    wrapper = OpenDSS(
        topofile=str(MASTER),
        time_step=dt.timedelta(seconds=300),
        start_time=dt.datetime(2025, 1, 1),
    )
    if wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")

    wrapper.run_dss()
    return wrapper


def _public_methods(module):
    cls = next(
        value
        for value in vars(module).values()
        if inspect.isclass(value) and value.__module__ == module.__name__
    )
    return {name for name in vars(cls) if not name.startswith("_")}


class TestLayerBoundaries:
    def test_every_layer_is_populated(self):
        for module in (_engine, _reader, _writer, _legacy):
            assert _public_methods(module), f"{module.__name__} is empty"

    def test_no_method_is_defined_twice(self):
        seen = {}
        for module in (_engine, _reader, _writer, _legacy):
            for name in _public_methods(module):
                assert name not in seen, f"{name} defined in {seen.get(name)} and {module}"
                seen[name] = module.__name__

    def test_writer_holds_only_mutators(self):
        for name in _public_methods(_writer):
            assert name.startswith(("set_", "remove_")), f"{name} is not a mutator"

    def test_reader_holds_no_mutators(self):
        for name in _public_methods(_reader):
            assert not name.startswith("set_"), f"{name} mutates but lives in the reader"


class TestPublicApiIsPreserved:
    """Scenarios and notebooks call these on the facade; the split must be invisible."""

    @pytest.mark.parametrize(
        "method",
        [
            "run_dss",
            "run_command",
            "set_element",
            "get_all_buses",
            "get_all_elements",
            "get_phase_powers",
            "get_phase_currents",
            "get_bus_vmag_pu",
            "get_bus_vang",
            "get_property",
            "set_property",
            "set_power",
            "set_tap",
            "set_pvsystem_pq",
            "get_all_pvsystems_info",
            "get_all_storages_info",
            "get_all_regulators_info",
            "grafo_tsdq",
            # legadas, ainda chamadas por notebooks de analise
            "get_power",
            "get_current",
            "get_bus_voltage",
        ],
    )
    def test_method_is_reachable_on_the_facade(self, dss, method):
        assert callable(getattr(dss, method))

    def test_exception_is_importable_from_the_facade(self):
        assert issubclass(OpenDSSException, Exception)


class TestPowerTotal:
    def test_matches_the_sum_of_phases(self, dss):
        phases_p, phases_q = dss.get_phase_powers("671", element="Load")
        total_p, total_q = dss.get_power_total("671", element="Load")

        assert total_p == pytest.approx(sum(phases_p))
        assert total_q == pytest.approx(sum(phases_q))

    def test_single_phase_element(self, dss):
        total_p, _ = dss.get_power_total("611", element="Load")
        assert total_p > 0

    def test_terminal_is_honoured(self, dss):
        """Power enters one terminal and leaves the other, whatever the direction.

        The absolute sign depends on whether the PVs are exporting, so the
        invariant to assert is the opposition, not a fixed direction.
        """
        first, _ = dss.get_power_total("650632", element="Line", terminal=1)
        second, _ = dss.get_power_total("650632", element="Line", terminal=2)

        assert first * second < 0, f"terminals not opposed: {first}, {second}"
        # A diferença entre eles são as perdas da linha: pequena face ao fluxo.
        assert abs(first + second) < 0.1 * abs(first)


class TestCompileIsRobust:
    """``py_dss_interface.DSS()`` chdir's the process to its stored DataPath.

    Every relative path the caller then resolves silently points at the wrong
    directory, and ``Redirect`` on the resulting missing file does not raise —
    the simulation just runs on an empty circuit.
    """

    def test_constructing_does_not_leave_the_process_elsewhere(self):
        import os

        before = os.getcwd()
        OpenDSS(
            topofile=str(MASTER),
            time_step=dt.timedelta(seconds=300),
            start_time=dt.datetime(2025, 1, 1),
        )
        assert os.getcwd() == before

    def test_relative_paths_resolve_against_the_callers_directory(self):
        relative = MASTER.relative_to(pathlib.Path.cwd())
        wrapper = OpenDSS(
            topofile=str(relative),
            time_step=dt.timedelta(seconds=300),
            start_time=dt.datetime(2025, 1, 1),
        )
        assert wrapper.dss.circuit.num_buses > 0

    def test_missing_file_raises_instead_of_compiling_nothing(self):
        with pytest.raises(OpenDSSException, match="not found"):
            OpenDSS(
                topofile="nao_existe_em_lugar_nenhum.dss",
                time_step=dt.timedelta(seconds=300),
                start_time=dt.datetime(2025, 1, 1),
            )

    def test_a_list_of_paths_is_rejected(self):
        """A assinatura antiga aceitava lista; um segundo circuito nunca coexistiu.

        Todas as instâncias DSS() compartilham um motor só, entao compilar o
        segundo repunha o primeiro em silêncio. Melhor recusar do que fingir.
        """
        with pytest.raises(TypeError, match=r"single \.dss file"):
            OpenDSS(
                topofile=[str(MASTER), str(MASTER)],
                time_step=dt.timedelta(seconds=300),
                start_time=dt.datetime(2025, 1, 1),
            )

    def test_error_names_the_resolved_path(self):
        with pytest.raises(OpenDSSException) as excinfo:
            OpenDSS(
                topofile="nao_existe.dss",
                time_step=dt.timedelta(seconds=300),
                start_time=dt.datetime(2025, 1, 1),
            )
        # O caminho reportado deve ser o do chamador, sem duplicar diretórios.
        assert str(pathlib.Path.cwd() / "nao_existe.dss") in str(excinfo.value)


class TestReadersDoNotMutate:
    def test_circuit_info_does_not_solve(self, dss, monkeypatch):
        """It used to call run_dss(), so a getter advanced the simulation."""

        def explode(*_a, **_k):
            raise AssertionError("get_circuit_info must not solve")

        monkeypatch.setattr(dss, "run_dss", explode)
        info = dss.get_circuit_info()

        assert "Total P (MW)" in info

    def test_reads_leave_the_cache_populated(self, dss):
        dss.run_dss()
        dss.get_bus_vmag_pu("675")
        dss.get_phase_powers("671", element="Load")

        assert dss._snapshot.bus_vmag_pu is not None
        assert dss._snapshot.elements

    def test_writes_clear_the_cache(self, dss):
        dss.run_dss()
        dss.get_bus_vmag_pu("675")
        dss.set_property("650632", "Length", 2500.0, element="Line")

        assert dss._snapshot.bus_vmag_pu is None
