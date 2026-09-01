# Comandos Disponíveis (CLI)

## Comando `tsre`

Registrado em `pyproject.toml` como script de console:

```bash
tsre
```

Executa `main.py` → `scenarios.base_scenario.run_cosimul()` (cenário legado com pandapower).

!!! warning "Cenário legado"
    O comando `tsre` executa o cenário base com pandapower, não com OpenDSS. Para cenários com OpenDSS, use os comandos abaixo.

## Executar cenários

### Local

```bash
# Cenário 123-bus com PV (recomendado para teste local)
uv run --no-sync python scenarios/opendss_scenario_123bus_pv.py

# Cenário 123-bus sem PV (baseline)
uv run --no-sync python scenarios/opendss_scenario_123bus.py

# Cenário 13-bus sem PV (debug)
uv run --no-sync python scenarios/opendss_scenario.py

# Cenário 34-bus com regulador
uv run --no-sync python scenarios/opendss_scenario_34bus.py

# Cenário com inversor smart (123-bus)
uv run --no-sync python scenarios/opendss_scenario_123bus_smart_pv.py

# Cenário com inversor smart (13-bus, Docker)
uv run --no-sync python scenarios/scenario_13bus_smart_pv_docker.py
```

### Docker

```bash
# Build da imagem (apenas na primeira vez ou após mudanças)
docker build -t opentes-simulador .

# Subir containers
docker compose up -d

# Executar cenário (em outro terminal)
uv run --no-sync python scenarios/cenariodocker.py

# Parar containers
docker compose down
```

## Gerenciamento de dependências

```bash
# Sincronizar ambiente virtual
uv sync

# Adicionar dependência
uv add nome-da-lib

# Adicionar dependência de desenvolvimento
uv add --group dev nome-da-lib
```

## Qualidade de código

```bash
# Linter (verificar erros)
uv run ruff check src/simulators/ scenarios/ tests/

# Formatter (corrigir formatação)
uv run ruff format src/simulators/ scenarios/ tests/

# Ambos
uv run ruff check src/simulators/ scenarios/ tests/ && uv run ruff format src/simulators/ scenarios/ tests/
```

## Testes

```bash
# Rodar todos os testes
uv run --no-sync python -m pytest tests/ -v

# Rodar um arquivo específico
uv run --no-sync python -m pytest tests/test_battery.py -v

# Rodar uma classe de teste
uv run --no-sync python -m pytest tests/test_inverter.py::TestCutInOut -v
```
