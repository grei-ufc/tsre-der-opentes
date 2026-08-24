# Primeira Simulação

Este tutorial conduz passo a passo para executar a primeira co-simulação e gerar um arquivo de resultados CSV.

## Objetivo

Executar o cenário de co-simulação com Docker no caso IEEE 123-bus com sistemas fotovoltaicos e verificar o arquivo de saída.

## Pré-requisitos

- Docker e Docker Compose instalados ([Instalação](../getting-started/installation.md))
- uv instalado
- Repositório clonado

## Passo 1: Construir a imagem Docker

Na raiz do repositório:

```bash
docker build -t opentes-simulador .
```

Isso cria a imagem base utilizada por todos os simuladores. O processo leva alguns minutos na primeira vez.

!!! info "Quando refazer o build?"
    Apenas quando houver alterações no `dockerfile`, `requirements.txt` ou no código-fonte em `src/`.

## Passo 2: Subir os containers

```bash
docker compose up -d
```

Isso inicia 10 containers, cada um com um simulador diferente. Os containers aguardam conexões TCP nas portas 5671–5680.

Para verificar que todos estão rodando:

```bash
docker compose ps
```

Todos os serviços devem estar com status `Up`.

## Passo 3: Executar o cenário

Em outro terminal, na raiz do repositório:

```bash
uv run --no-sync python scenarios/cenariodocker.py
```

!!! warning "Caminho do cenário"
    O cenário está em `scenarios/cenariodocker.py` (na raiz), não em `src/scenarios/`. O README pode mencionar `src/scenarios/` em versões anteriores — o caminho correto é `scenarios/`.

A execução pode levar alguns minutos. Durante a simulação, o terminal exibirá mensagens de progresso do mosaik.

## Passo 4: Verificar o resultado

O arquivo de saída é gerado em:

```
output/result_run_ieee123_cosim_pv_5min.csv
```

Cada linha contém um timestamp e os valores medidos de tensão, corrente e potência para os elementos monitorados.

Para inspecionar rapidamente:

```python
import pandas as pd

df = pd.read_csv("output/result_run_ieee123_cosim_pv_5min.csv")
print(df.head())
print(f"Colunas: {list(df.columns)}")
```

## O que aconteceu por baixo dos panos

1. O Mosaik conectou a 6 simuladores via TCP (portas 5671–5678)
2. O adaptador OpenDSS compilou o circuito IEEE 123-bus e descobriu automaticamente os PVSystems definidos no arquivo `.dss`
3. Para cada PVSystem, foi criada uma cadeia: CSV (irradiância/temperatura) → Painel PV → Inversor → OpenDSS
4. Em cada passo de tempo (5 minutos), o fluxo de potência foi resolvido e os resultados coletados

Consulte [Arquitetura](../explanation/architecture.md) para uma explicação detalhada.

## Próximos passos

- [Tutorial: Pipeline PV Local](../tutorials/pv-pipeline-local.md) — entenda cada componente da cadeia
- [Tutorial: Co-Simulação Docker](../tutorials/docker-co-simulation.md) — aprofunde no Docker
- [Catálogo de Cenários](../reference/scenarios.md) — veja todos os cenários disponíveis
