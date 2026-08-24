# Ambiente de Desenvolvimento

## Pré-requisitos

- Python 3.12+
- uv
- Git

## Configuração inicial

```bash
# Clonar o repositório
git clone https://github.com/<org>/tsre-der-opentes.git
cd tsre-der-opentes

# Instalar dependências (inclui dev: pytest, ruff)
uv sync

# Verificar instalação
uv run --no-sync python -m pytest tests/ -v
```

## Estrutura do projeto

```
src/simulators/    # Código-fonte principal
scenarios/         # Scripts de cenário
tests/             # Testes unitários
data/              # Dados de teste (IEEE feeders, estações solares)
output/            # Resultados (gitignored)
```

## Ferramentas de desenvolvimento

### Ruff (linter + formatter)

```bash
# Verificar erros
uv run ruff check src/simulators/ scenarios/ tests/

# Corrigir formatação
uv run ruff format src/simulators/ scenarios/ tests/
```

Configuração em `pyproject.toml`:

- `line-length = 100`
- `target-version = "py312"`
- Regras: Pyflakes, pycodestyle, isort, pyupgrade, bugbear, simplify, ruff-specific

### Pytest

```bash
# Todos os testes
uv run --no-sync python -m pytest tests/ -v

# Arquivo específico
uv run --no-sync python -m pytest tests/test_inverter.py -v

# Classe específica
uv run --no-sync python -m pytest tests/test_battery.py::TestDischarge -v
```

### Adicionar dependências

```bash
# Dependência de produção
uv add nome-da-lib

# Dependência de desenvolvimento
uv add --group dev nome-da-lib
```

## Convenções de código

Consulte [Convenções de Código](code-conventions.md) para detalhes.

## Estrutura de um adaptador mosaik

Todo adaptador deve ter:

1. Import `import mosaik_api_v3`
2. Classe que herda de `mosaik_api_v3.Simulator`
3. `META` dict com `api_version: "3.0"`, `type` e `models`
4. Métodos: `init()`, `create()`, `step()`, `get_data()`
5. Bloco `if __name__ == "__main__":` para execução via `--remote`

## Testar localmente

```bash
# Rodar cenário simples (13-bus)
uv run --no-sync python scenarios/opendss_scenario.py

# Rodar cenário com PV
uv run --no-sync python scenarios/opendss_scenario_123bus_pv.py

# Rodar com Docker
docker build -t opentes-simulador .
docker compose up -d
uv run --no-sync python scenarios/cenariodocker.py
```

## Submeter alterações

1. Crie uma branch a partir de `main`
2. Faça suas alterações
3. Execute lint e testes
4. Abra um pull request

Consulte [Convenções de Código](code-conventions.md) para mais detalhes.
