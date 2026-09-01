# Serviços Docker

## Portas e mapeamentos

| Serviço | Porta TCP | Comando | Módulo |
|---|---|---|---|
| `opendss` | 5671 | `python -m simulators.opendss.api_opendss --remote 0.0.0.0:5671` | Adaptador OpenDSS |
| `battery` | 5672 | `python -m simulators.battery.battery_sim --remote 0.0.0.0:5672` | Simulador de bateria |
| `collector` | 5673 | `python -m simulators.collector.collector --remote 0.0.0.0:5673` | Coletor de dados |
| `controller` | 5674 | `python -m simulators.controller.controller_sim --remote 0.0.0.0:5674` | Controlador de bateria |
| `csv-data-1` | 5675 | `python -m simulators.collector.csv_sim_pandas --remote 0.0.0.0:5675` | Leitor CSV 1 |
| `csv-data-2` | 5676 | `python -m simulators.collector.csv_sim_pandas --remote 0.0.0.0:5676` | Leitor CSV 2 |
| `inverter-std` | 5677 | `python -m simulators.inverter.inverter_simulator --remote 0.0.0.0:5677` | Inversor padrão |
| `pv-panel` | 5678 | `python -m simulators.pv.pv_panel_simulator --remote 0.0.0.0:5678` | Simulador PV |
| `regulator` | 5679 | `python -m simulators.controller.regulator_control --remote 0.0.0.0:5679` | Regulador de tensão |
| `smart-inverter` | 5680 | `python -m simulators.inverter.smart_inverter_simulator --remote 0.0.0.0:5680` | Inversor smart |

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
| `cenariodocker.py` | Padrão (5677) | 5671, 5673, 5675, 5676, 5677, 5678 |
| `scenario_13bus_smart_pv_docker.py` | Smart (5680) | 5671, 5673, 5675, 5676, 5678, 5680 |
