# Catálogo de Cenários

Todos os cenários estão em `scenarios/`. Cada um é um script standalone.

## Resumo comparativo

| Cenário | Caso de Teste | Execução | DER | Inversor | Passo | Arquivo de saída |
|---|---|---|---|---|---|---|
| `opendss_scenario.py` | IEEE 13-bus | Local | Nenhum | — | 600s | `output/result_opendss.csv` |
| `opendss_scenario_pv.py` | teste-pv (custom) | Local | PV | Padrão | 3600s | `output/result_opendss_pv.csv` |
| `opendss_scenario_34bus.py` | IEEE 34-bus | Local | Regulador | — | 300s | `output/result_opendss_34bus_regcontrol.csv` |
| `opendss_scenario_123bus.py` | IEEE 123-bus | Local | Nenhum | — | 300s | `output/result_run_ieee123_cosim_5min_edited.csv` |
| `opendss_scenario_123bus_pv.py` | IEEE 123-bus | Local | PV | Padrão | 300s | `output/result_run_ieee123_cosim_pv_5min.csv` |
| `opendss_scenario_123bus_pv_export_json.py` | IEEE 123-bus | Local | PV | Padrão | 300s | acima + `output/topologia_*.json` |
| `opendss_scenario_123bus_smart_pv.py` | IEEE 123-bus | Local | PV | Smart (Volt-Var) | 300s | `output/result_run_ieee123_cosim_smart_pv_5min.csv` |
| `cenariodocker.py` | IEEE 123-bus | **Docker** | PV | Padrão | 300s | `output/result_run_ieee123_cosim_pv_5min.csv` |
| `scenario_13bus_smart_pv_docker.py` | IEEE 13-bus | **Docker** | PV | Smart | 300s | `output/result_run_ieee13_cosim_pv_5min.csv` |
| `base_scenario.py` | LV-rural (pandapower) | Local | PV (legado) | Controller VV/VW | 60s | `output/base_scenario.csv` |

## Simuladores utilizados por cenário

### Cenários com OpenDSS (2 simuladores)

```
opendss_scenario.py
opendss_scenario_123bus.py
```

Simuladores: `DSS` + `Collector`

### Cenários com PV + Inversor padrão (5 simuladores)

```
opendss_scenario_pv.py
opendss_scenario_123bus_pv.py
opendss_scenario_123bus_pv_export_json.py
cenariodocker.py (Docker)
```

Simuladores: `DSS` + `CSV` + `PVSimulator` + `InverterSim` + `Collector`

### Cenário com Regulador (3 simuladores)

```
opendss_scenario_34bus.py
```

Simuladores: `DSS` + `RegControl` + `Collector`

### Cenários com Inversor Smart (5-6 simuladores)

```
opendss_scenario_123bus_smart_pv.py (local)
scenario_13bus_smart_pv_docker.py (Docker)
```

Simuladores: `DSS` + `CSV` + `PVSimulator` + `InverterSim` (smart) + `Collector`

### Cenário legado (pandapower)

```
base_scenario.py
```

Simuladores: `Grid` (pandapower) + `CSV` + `PV` (legado) + `Ctrl` (legado) + `Collector`

## Como executar

### Local (todos os cenários)

```bash
uv run --no-sync python scenarios/<nome_do_cenario>.py
```

### Docker (apenas cenariodocker.py e scenario_13bus_smart_pv_docker.py)

```bash
docker build -t opentes-simulador .
docker compose up -d
uv run --no-sync python scenarios/cenariodocker.py
```

## Configuração dos cenários locais

Os cenários locais definem `SIM_CONFIG` com chaves `"python"`:

```python
SIM_CONFIG = {
    "DSS":       {"python": "simulators.opendss.api_opendss:OpenDSSSimulator"},
    "PVSim":     {"python": "simulators.pv.pv_panel_simulator:PVPanelSim"},
    "InverterSim": {"python": "simulators.inverter.inverter_simulator:InverterSim"},
    "CSV":       {"python": "simulators.collector.csv_sim_pandas:CSV"},
    "Collector": {"python": "simulators.collector.collector:Collector"},
}
```

## Configuração dos cenários Docker

Os cenários Docker definem `SIM_CONFIG` com chaves `"connect"`:

```python
SIM_CONFIG = {
    "DSS":         {"connect": "localhost:5671"},
    "PVSimulator": {"connect": "localhost:5678"},
    "InverterSim": {"connect": "localhost:5677"},
    "CSV_Irr":     {"connect": "localhost:5675"},
    "CSV_Temp":    {"connect": "localhost:5676"},
    "Collector":   {"connect": "localhost:5673"},
}
```
