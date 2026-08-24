# tsre-der-opentes

Power grid co-simulation project using mosaik + OpenDSS.
Simulates DER (PV, batteries, inverters, regulators) on IEEE test feeders.

## Quick Reference

```sh
# Install deps
uv sync

# Run a scenario locally
uv run --no-sync python scenarios/cenariodocker.py

# Run Docker co-simulation
docker build -t opentes-simulador .
docker compose up -d
# Then in another terminal:
uv run --no-sync python scenarios/cenariodocker.py

# Run tests
uv run --no-sync python -m pytest tests/ -v

# Lint + format
uv run ruff check src/simulators/ scenarios/ tests/
uv run ruff format src/simulators/ scenarios/ tests/

# Docs (mkdocs lives in the `docs` group, not installed by a plain `uv sync`)
uv sync --group docs                      # once
uv run --group docs mkdocs serve          # live preview at http://127.0.0.1:8000
uv run --group docs mkdocs build --strict # fail on broken links

# Add a dependency
uv add <package>
```

## Project Layout

```
├── main.py                  # CLI entry point → scenarios.base_scenario.run_cosimul
├── scenarios/               # Standalone scenario scripts (each wires simulators together)
├── src/
│   └── simulators/          # Mosaik adapters (api_v3) + domain models
│       ├── opendss/         # OpenDSS wrapper, adapters, and helpers
│       │   ├── opendss_wrapper.py   # Core OpenDSS interface via py-dss-interface
│       │   ├── api_opendss.py       # Mosaik adapter wrapping opendss_wrapper
│       │   ├── opendss_pv.py        # PVSystem operations (standalone functions)
│       │   ├── opendss_storage.py   # Storage operations
│       │   ├── opendss_regulator.py # Regulator operations
│       │   ├── _utils.py            # Shared helpers (to_3phase, extract_3phase_pq)
│       │   ├── topology_builder.py  # Circuit graph builder
│       │   └── graph_model.py       # Graph data classes
│       ├── inverter/        # Smart inverter (IEEE 1547 via OpenDER)
│       │   ├── config.py                # Validated control config (curves, mode, nameplate)
│       │   ├── opender_factory.py       # ONLY place that builds DERCommonFileFormat / DER_PV
│       │   ├── smart_inverter.py        # SmartInverterModel: P_dc + V → P_ac, Q_ac
│       │   ├── smart_inverter_simulator.py # The single mosaik adapter (META derived)
│       │   ├── inverter_simulator.py    # Compatibility shim → smart_inverter_simulator
│       │   └── inverter.py              # Legacy InverterModel, no OpenDER
│       ├── battery/         # Battery model and adapter
│       │   ├── battery_model.py  # OpenDSSBattery physics model
│       │   └── battery_sim.py    # Mosaik adapter
│       ├── collector/       # Data collection adapters
│       │   ├── collector.py      # Event-based CSV collector
│       │   └── csv_sim_pandas.py # Time-based CSV reader
│       ├── controller/      # Control adapters
│       │   ├── controller_sim.py    # SE controller
│       │   └── regulator_control.py # Voltage regulator control
│       ├── pv/              # PV panel simulator
│       │   └── pv_panel_simulator.py # Irradiance/temperature → DC power
│       ├── util/            # Standalone utilities
│       │   ├── pv_creator.py   # PV system creator for OpenDSS
│       │   └── topologia.py    # Topology export to JSON
│       └── old/             # Deprecated simulator code (do not modify)
├── data/                    # IEEE test case files (.dss, .csv) per bus count
├── notebooks/               # Jupyter notebooks for analysis
├── output/                  # Simulation CSV results (gitignored)
├── tests/                   # Unit tests
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── AGENTS.md
```

## Key Conventions

- **All simulators use mosaik API v3** (`mosaik_api_v3`, `api_version: '3.0'`). Do not use `mosaik_api` (v2).
- **Every simulator module** must have a `META` dict with `api_version`, `type`, and `models`. See `simulators/inverter/inverter_simulator.py` for the minimal pattern.
- **Docker containers** run simulators with `--remote 0.0.0.0:<port>`. Each container maps to a fixed port (5671-5680). The scenario script connects via `connect: 'localhost:PORT'`.
- **PYTHONPATH** is set to `/app/src` in Docker; locally, use `uv run` from project root.
- **Sign convention**: OpenDSS generation is negative. The codebase inverts signs at the adapter boundary (see `extract_3phase_pq(sign=-1)`).
- **SIM_CONFIG paths** in scenarios must use the full sub-package path, e.g. `'python': 'simulators.opendss.api_opendss:OpenDSSSimulator'`.
- **Data files** live in `data/` at project root (not inside `src/`). Docker mounts `./data:/app/data`.

## Common Pitfalls

- `mosaik/` is a gitignored local clone — never edit framework code there for project changes.
- Scenarios are standalone scripts, not importable modules. Each defines its own `SIM_CONFIG` and `run_scenario()`.
- The `opendss/opendss_wrapper.py` is the single source of truth for all OpenDSS interactions. Do not call `py_dss_interface` directly from simulators.
- Tests: `uv run --no-sync python -m pytest tests/ -v`. Lint: `uv run ruff check`. Format: `uv run ruff format`.

## OpenDER (smart inverter) gotchas

The OpenDER library validates settings in property *setters* that only
`logging.warning` — they never raise. Several of its behaviours are silent
traps; `inverter/config.py` and `inverter/opender_factory.py` exist to contain
them. Read those two modules before touching inverter control.

- **Never mutate `der.der_file` after construction.** The `NP_VA_MAX` setter
  re-runs `initialize_NP_Q_CAPABILTY_BY_P_CURVE()` from the *current*
  `NP_Q_MAX_INJ`. Scaling only the rating leaves reactive capability pinned at
  the 44 kvar default. Build the full parameter dict, pass it to the
  constructor, done. `build_der` asserts the resulting curve.
- **`DER.t_s` is a class attribute**, global to the process. Set it once from
  the mosaik step size via `opender_factory.set_time_step`. Left unset, the
  100 000 s default makes every OLRT, ramp and trip timer inert.
- **Reactive modes are mutually exclusive**, resolved by fixed priority
  (`CONST_PF > VOLT_VAR > WATT_VAR > CONST_Q`). Volt-watt is a *P* function and
  is orthogonal. Hence `ReactiveMode` is an enum, not flags.
- **`ConditionalDelay` starts its timer at `math.inf`**, so the first true
  evaluation satisfies any duration. To disable trip, move the *thresholds*
  out of range — stretching `*_TRIP_T` does nothing.
- **The low-pass filter short-circuits when `t_olrt < 1.15 * t_s`.** With a
  300 s step, every IEEE-compliant OLRT gives an instantaneous response, so the
  delayed voltage feedback has no damping. `olrt ≈ 2 × step` is the deliberate
  numerical relaxation.
- **A three-phase DER returns total P/Q, never per-phase.** Real single-phase
  injection needs `NP_PHASE='SINGLE'`, one DER per element.
- **Parameter write order matters** (setters cross-reference): `NP_V_DC` before
  `NP_AC_V_NOM`; `NP_VA_MAX` before the `NP_Q_MAX_*` pair; `QV_CURVE_V2`/`V3`
  before `V1`/`V4`; `PV_CURVE_P2` before `P1`.
