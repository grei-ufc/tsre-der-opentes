# Serviços Docker

## Portas e mapeamentos

| Serviço | Porta TCP | Comando | Módulo |
|---|---|---|---|
| `opendss` | 5771 | `python -m simulators.opendss.api_opendss --remote 0.0.0.0:5771` | Adaptador OpenDSS |
| `battery` | 5772 | `python -m simulators.battery.battery_sim --remote 0.0.0.0:5772` | Simulador de bateria |
| `collector` | 5773 | `python -m simulators.collector.collector --remote 0.0.0.0:5773` | Coletor de dados |
| `controller` | 5774 | `python -m simulators.controller.controller_sim --remote 0.0.0.0:5774` | Controlador de bateria |
| `csv-data-1` | 5775 | `python -m simulators.collector.csv_sim_pandas --remote 0.0.0.0:5775` | Leitor CSV 1 |
| `csv-data-2` | 5776 | `python -m simulators.collector.csv_sim_pandas --remote 0.0.0.0:5776` | Leitor CSV 2 |
| `inverter-std` | 5777 | `python -m simulators.inverter.inverter_simulator --remote 0.0.0.0:5777` | Inversor padrão |
| `pv-panel` | 5778 | `python -m simulators.pv.pv_panel_simulator --remote 0.0.0.0:5778` | Simulador PV |
| `regulator` | 5779 | `python -m simulators.controller.regulator_control --remote 0.0.0.0:5779` | Regulador de tensão |
| `smart-inverter` | 5780 | `python -m simulators.inverter.smart_inverter_simulator --remote 0.0.0.0:5780` | Inversor smart |

## Volumes montados

| Volume | Conteúdo |
|---|---|
| `./src:/app/src` | Código-fonte do projeto |
| `./data:/app/data` | Arquivos de dados IEEE (13/34/123-bus) |
| `./output:/app/output` | Resultados da simulação (CSV) |

!!! info "Serviços com volumes diferentes"
    Nem todos os serviços montam todos os volumes. Por exemplo, o `collector` monta `./output:/app/output` para escrever resultados, mas não precisa de `./data`.

## Imagem Docker

A imagem base é `python:3.12-slim` com:

- `build-essential` e `libgl1` (compilação C++)
- Dependências Python via `requirements.txt`
- `PYTHONPATH=/app/src`

## Comandos úteis

```bash
# Construir imagem
docker build -t opentes-simulador .

# Subir todos os serviços (foreground)
docker compose up

# Subir em background
docker compose up -d

# Parar todos os serviços
docker compose down

# Ver logs de um serviço
docker compose logs opendss

# Ver status
docker compose ps
```

## Cenários Docker disponíveis

| Cenário | Inversor | Portas utilizadas |
|---|---|---|
| `cenariodocker.py` | Padrão (5777) | 5771, 5773, 5775, 5776, 5777, 5778 |
| `scenario_13bus_smart_pv_docker.py` | Smart (5780) | 5771, 5773, 5775, 5776, 5778, 5780 |
| `scenario_13bus_pv_all_data.py` | Smart (5780) | 5771, 5773, 5775, 5776, 5778, 5780 |
