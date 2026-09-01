# Instalação

## Pré-requisitos

| Requisito | Versão mínima | Observação |
|---|---|---|
| Python | 3.12+ | Exigido por `pyproject.toml` (`requires-python = ">=3.12"`) |
| [uv](https://docs.astral.sh/uv/) | Qualquer | Gerenciador de dependências e ambientes virtuais |
| Docker + Docker Compose | Qualquer | Apenas para execução via Docker |
| Git | Qualquer | Para clonar o repositório |

## Clonar o repositório

```bash
git clone https://github.com/<org>/tsre-der-opentes.git
cd tsre-der-opentes
```

## Configurar o ambiente Python

```bash
# Criar ambiente virtual e instalar dependências
uv sync
```

Isso cria o diretório `.venv/` e instala todas as dependências listadas em `pyproject.toml`.

### Dependências principais

| Pacote | Versão | Finalidade |
|---|---|---|
| `mosaik` | 3.5.0 | Framework de co-simulação |
| `mosaik-pandapower` | 0.2.2 | Adaptador panda power (cenário legado) |
| `py-dss-interface` | >=2.0.0 | Interface com o OpenDSS |
| `opender` | 2.1.6 | Biblioteca de controle IEEE 1547 |
| `pandas` | >=2.3.2 | Manipulação de dados |

### Dependências de desenvolvimento

| Pacote | Versão | Finalidade |
|---|---|---|
| `pytest` | >=8.4.2 | Execução de testes |
| `ruff` | >=0.16.3 | Linter e formatter |

### Adicionar novas dependências

```bash
uv add nome-da-lib
```

!!! warning "Não adicione dependências manualmente"
    Sempre use `uv add` em vez de editar `pyproject.toml` manualmente para manter o `uv.lock` sincronizado.

## Instalar Docker (opcional)

A execução via Docker é o modo recomendado para rodar cenários completos.

=== "Windows"

    1. Baixe e instale o [Docker Desktop](https://www.docker.com/products/docker-desktop/)
    2. Inicie o Docker Desktop e aguarde o daemon ficar ativo
    3. Verifique:
       ```bash
       docker --version
       docker compose version
       ```

=== "Linux (Ubuntu/Debian)"

    ```bash
    sudo apt update
    sudo apt install ca-certificates curl gnupg lsb-release
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
      sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) \
      signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt update
    sudo apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo systemctl enable --now docker
    ```

    Verifique:
    ```bash
    docker --version
    docker compose version
    ```

## Configuração específica para Linux (WSL/Ubuntu)

O OpenDSS é nativo do Windows. Para utilizá-lo no Linux via `py-dss-interface`, é necessário compilar a engine C++ localmente.

### Pré-requisitos de compilação

```bash
sudo apt update && sudo apt install build-essential cmake
```

### Compilar a engine

```bash
# Fora da pasta do projeto
cd ..
git clone https://github.com/PauloRadatz/py_dss_interface.git
cd py_dss_interface
bash OpenDSSLinuxCPPForRepo.sh
```

### Instalar no ambiente do projeto

```bash
cd ../tsre-der-opentes
uv pip install ../py_dss_interface
```

## Verificar a instalação

```bash
# Rodar testes unitários
uv run --no-sync python -m pytest tests/ -v

# Verificar lint
uv run ruff check src/simulators/ scenarios/ tests/
```

## Próximos passos

- [Primeira Simulação](first-simulation.md) — execute seu primeiro cenário
- [Tutoriais](../tutorials/pv-pipeline-local.md) — entenda o pipeline de simulação
