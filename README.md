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
