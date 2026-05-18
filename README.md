# tsre-der-opentes

Repositório de código para armazenar as soluções desenvolvidas de simulação de recursos energéticos distribuídos.

## Como executar o projeto?

**Execução recomendada (via Docker)**

O projeto foi dockerizado: cada simulador roda em um container próprio e o cenário principal (`cenariodocker.py`) é executado no host, conectando-se aos simuladores via `localhost`.

Passos rápidos:

1. Construa a imagem (apenas na primeira vez ou após mudanças no Dockerfile/requirements):

```bash
docker build -t opentes-simulador .
```

2. Suba os serviços com o Docker Compose:

```bash
docker compose up -d
```

3. Em outro terminal (no host), rode o cenário Docker:

```bash
uv run --no-sync python src/scenarios/cenariodocker.py
```

Observações importantes:

- Os containers expõem portas TCP fixas (por exemplo `5671` para o `opendss`) para o handshake com o Mosaik. O cenário conecta-se em `localhost:<porta>`.
- Volumes principais montados: `./src:/app/src` e `./output:/app/output`. Os resultados gerados dentro do container em `/app/output` aparecem no host em `output/`.
- Arquivo de saída principal do cenário 123Bus: `output/result_run_ieee123_cosim_pv_5min.csv`.

### Execução em segundo plano - Preferencialmente, execute dessa forma

Se preferir deixar os containers rodando em background e iniciar o cenário imediatamente, execute ambos os comandos em sequência no mesmo terminal:

```bash
docker compose up -d
uv run --no-sync python src/scenarios/cenariodocker.py
```

**Execução sem Docker (opcional / legado)**

Ainda é possível executar localmente usando `uv` e ambientes Python, quando necessário. Para criar o ambiente com `uv`:

```sh
uv sync
```

Para executar cenários locais (modo legado), use `uv run` apontando para o script de cenário desejado. Note que alguns simuladores esperam o modo remoto via TCP quando dockerizados.

## Desenvolvedores

Sempre que for necessário adicionar alguma biblioteca Python nova no projeto, faça isso via comando `uv add nome-da-lib`.

Aos desenvolvedores que não são membros oficiais do time de desenvolvimento e queira contribuir de alguma forma com o projeto, podem fazer isso via pull requests.

## ⚡ Instruções para executar a simulação OpenDSS

Este projeto contém um cenário específico (`opendss_scenario.py`) que utiliza o OpenDSS através da biblioteca `py-dss-interface`.

### 🐧 Configuração Específica para Linux (WSL/Ubuntu)

O OpenDSS é nativo do Windows. Para utilizá-lo no Linux via `py-dss-interface`, é necessário compilar a *engine* C++ localmente caso a instalação padrão via pip não encontre os binários compatíveis.

**Pré-requisitos de sistema**: Você precisará de ferramentas de compilação C++ instaladas (ex: `g++`, `cmake`). No Ubuntu/WSL:

```bash
sudo apt update && sudo apt install build-essential cmake
```

### Passo 1: Clonar e Compilar a Engine

Execute os passos abaixo (fora da pasta do projeto ou em um diretório temporário):

1. Clone o repositório da interface:

```bash
# Na pasta tsre-der-opentes, acesse o diretório imediatamente acima
cd ..
git clone https://github.com/PauloRadatz/py_dss_interface.git
cd py_dss_interface
```

2. Compile a engine do OpenDSS:

```bash
bash OpenDSSLinuxCPPForRepo.sh
```

**Nota**: Isso criará os binários necessários dentro da pasta clonada.

3. Instale o pacote compilado no ambiente do seu projeto: Volte para a raiz do projeto `tsre-der-opentes` e utilize o `uv` para instalar a partir da pasta compilada:

```bash
# Volta para a pasta do seu projeto
cd ../tsre-der-opentes
# Exemplo (ajuste o caminho '../py_dss_interface' conforme onde você clonou no Passo 1):
uv pip install ../py_dss_interface
```

### ▶️ Como rodar o Cenário OpenDSS

Após configurar o ambiente, utilize o comando abaixo para rodar o cenário específico do OpenDSS. Usamos o `uv run` para garantir o carregamento correto das variáveis de ambiente:

```Bash
uv run --no-sync python src/scenarios/opendss_scenario.py
```

Os resultados específicos desta simulação serão gerados na pasta `src/output`.