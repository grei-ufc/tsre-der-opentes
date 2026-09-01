"""Smoke test: the simplest local scenario must run end to end.

Every other test in this suite exercises a model, an adapter or the OpenDSS
wrapper directly. None of them catches a scenario script itself breaking —
which is exactly the gap that let docs/reference/scenarios.md drift from the
real output filename of ``opendss_scenario.py`` unnoticed. This runs that
scenario for real and checks the CSV it promises in
docs/getting-started/first-simulation.md.
"""

import sys

import pandas as pd
import pytest

sys.path.insert(0, ".")

from scenarios.opendss_scenario import ARQUIVO_RESULTADOS_CSV, CIRCUITO_DSS, run_scenario


@pytest.fixture(scope="module")
def result_df():
    if not CIRCUITO_DSS.exists():
        pytest.skip(f"IEEE13 fixture not found at {CIRCUITO_DSS}")

    run_scenario()
    return pd.read_csv(ARQUIVO_RESULTADOS_CSV, index_col="date", parse_dates=True)


class TestOpenDSSScenarioSmoke:
    def test_runs_all_144_steps(self, result_df):
        assert len(result_df) == 144

    def test_bus_voltages_are_near_one_pu(self, result_df):
        v_cols = [c for c in result_df.columns if c.endswith("_pu")]
        assert v_cols, "no voltage columns in the output"
        assert result_df[v_cols].to_numpy().min() > 0.8
        assert result_df[v_cols].to_numpy().max() < 1.2

    def test_line_currents_are_reported(self, result_df):
        i_cols = [c for c in result_df.columns if c.endswith("_A")]
        assert i_cols, "no current columns in the output"
        assert (result_df[i_cols].to_numpy() >= 0).all()
