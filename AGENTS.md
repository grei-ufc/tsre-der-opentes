# tsre-der-opentes

Power grid co-simulation project using mosaik + OpenDSS.
Simulates DER (PV, batteries, inverters, regulators) on IEEE test feeders.

## Quick Reference

```sh
# Install deps
uv sync

# Run a scenario locally
uv run --no-sync python src/scenarios/cenariodocker.py

# Run Docker co-simulation
docker build -t opentes-simulador .
docker compose up -d
# Then in another terminal:
uv run --no-sync python src/scenarios/cenariodocker.py

# Add a dependency
uv add <package>
```

## Project Layout

```
src/
  main.py                  # CLI entry point → scenarios.base_scenario.run_cosimul
  scenarios/               # Standalone scenario scripts (each wires simulators together)
  simulators/              # Mosaik adapters (api_v3) + domain models
    opendss/               # OpenDSS wrapper, adapters, and helpers
      opendss_wrapper.py   # Core OpenDSS interface via py-dss-interface
      api_opendss.py       # Mosaik adapter wrapping opendss_wrapper
      opendss_pv.py        # PVSystem operations (standalone functions)
      opendss_storage.py   # Storage operations
      opendss_regulator.py # Regulator operations
      _utils.py            # Shared helpers (to_3phase, extract_3phase_pq)
      topology_builder.py  # Circuit graph builder
      graph_model.py       # Graph data classes
    inverter/              # Inverter model and adapters
      inverter.py          # Unified InverterModel (cut-in/out, efficiency, priority, OpenDER)
      inverter_simulator.py      # Mosaik adapter (standard control)
      smart_inverter_simulator.py # Compatibility shim → inverter.py
      smart_inverter_simulator_2.py # Mosaik adapter (smart control)
    battery/               # Battery model and adapter
      battery_model.py     # OpenDSSBattery physics model
      battery_sim.py       # Mosaik adapter
    collector/             # Data collection adapters
      collector.py         # Event-based CSV collector
      csv_sim_pandas.py    # Time-based CSV reader
    controller/            # Control adapters
      controller_sim.py    # SE controller
      regulator_control.py # Voltage regulator control
    pv/                    # PV panel simulator
      pv_panel_simulator.py # Irradiance/temperature → DC power
    old/                   # Deprecated simulator code (do not modify)
  data/                    # IEEE test case files (.dss, .csv) per bus count
  output/                  # Simulation CSV results
mosaik/                    # Local mosaik framework clone (gitignored, for debugging only)
```

## Key Conventions

- **All simulators use mosaik API v3** (`mosaik_api_v3`, `api_version: '3.0'`). Do not use `mosaik_api` (v2).
- **Every simulator module** must have a `META` dict with `api_version`, `type`, and `models`. See `simulators/inverter/inverter_simulator.py` for the minimal pattern.
- **Docker containers** run simulators with `--remote 0.0.0.0:<port>`. Each container maps to a fixed port (5671-5680). The scenario script connects via `connect: 'localhost:PORT'`.
- **PYTHONPATH** is set to `/app/src` in Docker; locally, use `uv run` from project root.
- **Sign convention**: OpenDSS generation is negative. The codebase inverts signs at the adapter boundary (see `extract_3phase_pq(sign=-1)`).
- **SIM_CONFIG paths** in scenarios must use the full sub-package path, e.g. `'python': 'simulators.opendss.api_opendss:OpenDSSSimulator'`.

## Common Pitfalls

- `mosaik/` is a gitignored local clone — never edit framework code there for project changes.
- Scenarios are standalone scripts, not importable modules. Each defines its own `SIM_CONFIG` and `run_scenario()`.
- The `opendss/opendss_wrapper.py` is the single source of truth for all OpenDSS interactions. Do not call `py_dss_interface` directly from simulators.
- `inverter/smart_inverter_simulator.py` is a compatibility shim — its logic lives in `inverter/inverter.py`.
- No test suite or linter is configured. Verify changes with `python -c "import py_compile; py_compile.compile('<file>', doraise=True)"`.
