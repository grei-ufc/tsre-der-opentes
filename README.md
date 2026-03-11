# tsre-der-opentes

Repositório de código para armazenar as soluções desenvolvidas de simulação de recursos energéticos distribuídos.

## Como executar o projeto?

Para executar esse projeto, recomendamos a utilização da ferramenta `uv`, tanto para executar seus scripts quanto para gerenciar de forma segura e eficiente suas dependências.

Depois de clonar o respositório, entre na pasta em que o repositório foi clonado e digite o seguinte comando para criar o ambiente de execução com `uv`:

```sh
uv sync
```

Automaticamente o `uv`criará o ambiente virtual Python com a versão correta do Python e de todas as bibliotecas necessárias.

Após o término da instalação dos requisitos necessários, para executar a co-simulação propriamente dita, digite no terminal:

```sh
uv run tsre
```

Se tudo ocorrer conforme o esperado a co-simulação deve ser iniciada. Os resultados gerados serão armazenados no arquivo `results.csv` que ficará armazenado na pasta `src/output`.

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


### Executar o plot com o streamlit:

1. Verifique se está na pasta base (tsre-der-opente).

2. Rode o seguinte comando no terminal:

uv run streamlit run src/simulators/Plot_PVsystem_streamlit.py