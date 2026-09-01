# Implantar com Docker

## Visão geral

A dockerização permite que cada simulador rode em seu próprio container Docker, conectando-se via TCP. Este é o **modo recomendado** para cenários completos.

## Arquitetura

Cada container:

1. Executa um simulador com `--remote 0.0.0.0:<porta>`
2. Abre um servidor TCP aguardando conexão do mosaik
3. Executa a simulação quando o cenário conecta
4. Compartilha volumes com o host para dados e resultados

## Pré-requisitos

- Docker e Docker Compose instalados
- uv instalado

## Serviços e portas

| Serviço | Porta | Módulo |
|---|---|---|
| `opendss` | 5671 | `simulators.opendss.api_opendss` |
| `battery` | 5672 | `simulators.battery.battery_sim` |
| `collector` | 5673 | `simulators.collector.collector` |
| `controller` | 5674 | `simulators.controller.controller_sim` |
| `csv-data-1` | 5675 | `simulators.collector.csv_sim_pandas` |
| `csv-data-2` | 5676 | `simulators.collector.csv_sim_pandas` |
| `inverter-std` | 5677 | `simulators.inverter.inverter_simulator` |
| `pv-panel` | 5678 | `simulators.pv.pv_panel_simulator` |
| `regulator` | 5679 | `simulators.controller.regulator_control` |
| `smart-inverter` | 5680 | `simulators.inverter.smart_inverter_simulator` |

## Passo 1: Construir a imagem

```bash
docker build -t opentes-simulador .
```

A imagem base é `python:3.12-slim` com:

- Dependências de sistema: `build-essential`, `libgl1`
- Dependências Python: `requirements.txt`
- `PYTHONPATH=/app/src`

Refazer o build apenas quando houver alterações em:

- `dockerfile`
- `requirements.txt`
- Código-fonte em `src/`

## Passo 2: Subir os containers

```bash
# Foreground (para debug)
docker compose up

# Background (recomendado)
docker compose up -d
```

## Passo 3: Executar o cenário

Em outro terminal:

```bash
# Cenário padrão (123-bus, inversor padrão)
uv run --no-sync python scenarios/cenariodocker.py

# Cenário smart inverter (13-bus)
uv run --no-sync python scenarios/scenario_13bus_smart_pv_docker.py
```

## Passo 4: Parar

```bash
docker compose down
```

## Volumes

| Volume | Montagem | Conteúdo |
|---|---|---|
| `./src:/app/src` | Código-fonte | Todos os containers |
| `./data:/app/data` | Dados IEEE | opendss, csv-data-1, csv-data-2 |
| `./output:/app/output` | Resultados | collector |

## Cenários Docker

### cenariodocker.py (123-bus, inversor padrão)

```python
SIM_CONFIG = {
    "DSS":         {"connect": "localhost:5671"},
    "PVSimulator": {"connect": "localhost:5678"},
    "InverterSim": {"connect": "localhost:5677"},  # padrão
    "CSV_Irr":     {"connect": "localhost:5675"},
    "CSV_Temp":    {"connect": "localhost:5676"},
    "Collector":   {"connect": "localhost:5673"},
}
```

### scenario_13bus_smart_pv_docker.py (13-bus, inversor smart)

```python
SIM_CONFIG = {
    "DSS":         {"connect": "localhost:5671"},
    "PVSimulator": {"connect": "localhost:5678"},
    "InverterSim": {"connect": "localhost:5680"},  # smart
    "CSV_Irr":     {"connect": "localhost:5675"},
    "CSV_Temp":    {"connect": "localhost:5676"},
    "Collector":   {"connect": "localhost:5673"},
}
```

## Onde ficam os arquivos

| Caminho no container | Caminho no host | Conteúdo |
|---|---|---|
| `/app/src` | `./src` | Código-fonte |
| `/app/data` | `./data` | Dados IEEE |
| `/app/output` | `./output` | Resultados CSV |

Arquivo de saída principal: `output/result_run_ieee123_cosim_pv_5min.csv`

## Problemas comuns

Consulte [Solução de Problemas](troubleshoot-common-issues.md) para erros específicos do Docker.
