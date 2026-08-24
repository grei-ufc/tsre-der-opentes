# Executar Cenário Local

## Visão geral

Todos os cenários em `scenarios/` podem ser executados localmente usando `uv run`.

## Comando geral

```bash
uv run --no-sync python scenarios/<nome_do_cenario>.py
```

## Cenários disponíveis

| Cenário | Comando | Requisitos |
|---|---|---|
| 13-bus (debug) | `uv run --no-sync python scenarios/opendss_scenario.py` | Nenhum |
| 123-bus (baseline) | `uv run --no-sync python scenarios/opendss_scenario_123bus.py` | Nenhum |
| 123-bus + PV | `uv run --no-sync python scenarios/opendss_scenario_123bus_pv.py` | Nenhum |
| 123-bus + PV + JSON | `uv run --no-sync python scenarios/opendss_scenario_123bus_pv_export_json.py` | Nenhum |
| 123-bus + smart PV | `uv run --no-sync python scenarios/opendss_scenario_123bus_smart_pv.py` | Nenhum |
| 34-bus + regulador | `uv run --no-sync python scenarios/opendss_scenario_34bus.py` | Nenhum |
| teste-pv (custom) | `uv run --no-sync python scenarios/opendss_scenario_pv.py` | Nenhum |
| LV-rural (legado) | `uv run --no-sync python scenarios/base_scenario.py` | Nenhum |

## Onde ficam os resultados

Todos os cenários escrevem CSVs na pasta `output/`:

```bash
ls output/*.csv
```

## Configurar parâmetros

Os parâmetros de simulação estão definidos no topo de cada cenário:

```python
STEP_SIZE = 300      # segundos (5 minutos)
N_PASSOS = 288       # 24 horas / 5 min
END_TIME = 86400     # segundos totais
START_DATE = "2026-01-01 00:00:00"
```

Para alterar a duração, modifique `N_PASSOS` e `END_TIME` no arquivo do cenário.

## Troubleshooting

### `ModuleNotFoundError: No module named 'simulators'`

Execute sempre com `uv run` na raiz do repositório. O `PYTHONPATH` é configurado automaticamente pelo `uv run`.

### `FileNotFoundError` para arquivos `.dss`

Verifique se os arquivos de dados existem em `data/`. Os cenários validam a existência antes de iniciar.

### Lentidão na execução

Cenários com 123 barras e 288 passos podem levar alguns minutos. Para testes rápidos, use `opendss_scenario.py` (13-bus, 144 passos).
