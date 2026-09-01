# Primeira Simulação

Este tutorial executa a co-simulação mais simples do projeto — inteiramente em Python, sem Docker — e mostra como ler o resultado.

## O que você vai obter

Ao final, um arquivo CSV com tensão (p.u.) e corrente (A) de um ponto do alimentador IEEE 13 barras, a cada 10 minutos, ao longo de 24 horas simuladas (144 linhas). Estas são as duas primeiras linhas reais desse resultado:

| date | DSS-0.Bus-rg60-V1_pu | DSS-0.Bus-rg60-V2_pu | DSS-0.Bus-rg60-V3_pu | DSS-0.Line-650632-I1_A |
|---|---|---|---|---|
| 2025-01-01 00:00:00 | 0.999991 | 1.000043 | 0.999993 | 242.41 |
| 2025-01-01 00:10:00 | 1.000000 | 1.000050 | 1.000003 | 227.71 |

O arquivo real tem 12 colunas — correntes e ângulos das 3 fases da linha `650632`, tensões e ângulos das 3 fases da barra `rg60`. A seção [Colunas do resultado](#colunas-do-resultado) explica cada uma.

## Objetivo

Executar `scenarios/opendss_scenario.py`: compilar o alimentador IEEE 13 barras no OpenDSS, resolver o fluxo de potência a cada 10 minutos por 24 horas, e gravar tensão/corrente de um ponto do circuito em CSV.

!!! info "Por que este cenário, e não outro?"
    É o cenário mais simples do catálogo (veja [Catálogo de Cenários](../reference/scenarios.md)): apenas dois simuladores (`DSS` + `Collector`), sem geração fotovoltaica e sem Docker — o caminho mais curto até o primeiro resultado. Depois deste tutorial, [Pipeline PV Local](../tutorials/pv-pipeline-local.md) mostra como adicionar geração distribuída, ainda em Python puro, e [Co-Simulação Docker](../tutorials/docker-co-simulation.md) mostra o modo recomendado para cenários completos — com cada simulador em seu próprio container. Nenhum dos dois é necessário para este primeiro contato.

## Pré-requisitos

- Ambiente instalado (`uv sync`) — veja [Instalação](installation.md)
- Repositório clonado

Docker **não** é necessário para este tutorial.

## Passo 1: Executar o cenário

Na raiz do repositório:

```bash
uv run --no-sync python scenarios/opendss_scenario.py
```

A execução é quase instantânea — o alimentador tem 13 barras e cada passo resolve em frações de segundo. O terminal mostra algo como:

```text
DSS: Compiling...
DSS: Compiled Circuit: ieee13nodeckt
[OpenTES] Regulador detectado: reg1 @ rg60.1
[OpenTES] Regulador detectado: reg2 @ rg60.2
[OpenTES] Regulador detectado: reg3 @ rg60.3
Monitorando Linha: 'Line-650632'
Monitorando Barra: 'Bus-rg60'
Iniciando simulação de 144 passos (Step=600s)...
Simulação concluída.
```

## Passo 2: O que aconteceu por baixo dos panos

1. O adaptador OpenDSS (`simulators.opendss.api_opendss`) compilou `data/13Bus/IEEE13Nodeckt_w_loadcurve.dss` e detectou automaticamente os 3 reguladores de tensão do circuito (`reg1`, `reg2`, `reg3`, todos na barra `rg60`).
2. O cenário conectou dois pontos do circuito ao `Collector`: a linha `650632` (correntes e ângulos das 3 fases) e a barra `rg60` (tensões e ângulos das 3 fases).
3. O Mosaik avançou 144 passos de 600 segundos (10 minutos) — 24 horas simuladas — resolvendo o fluxo de potência a cada passo.
4. A cada passo, o `Collector` gravou uma linha no CSV.

Consulte [Arquitetura](../explanation/architecture.md) para o funcionamento geral de um cenário, e [Conceitos de Co-Simulação](../explanation/co-simulation-concepts.md) para o papel do `step_size` e do Mosaik.

## Passo 3: Verificar o resultado

O arquivo é gravado em `output/result_opendss.csv`. Para inspecionar:

```python
import pandas as pd

df = pd.read_csv("output/result_opendss.csv", index_col="date", parse_dates=True)
print(df.head())
print(f"Colunas: {list(df.columns)}")
```

### Colunas do resultado

O nome de cada coluna segue o padrão `<simulador>.<entidade>-<atributo>`:

| Coluna | Descrição |
|---|---|
| `DSS-0.Bus-rg60-V1_pu`, `V2_pu`, `V3_pu` | Tensão por fase na barra `rg60`, em p.u. |
| `DSS-0.Bus-rg60-V1_ang`, `V2_ang`, `V3_ang` | Ângulo de tensão por fase, em graus |
| `DSS-0.Line-650632-I1_A`, `I2_A`, `I3_A` | Corrente por fase na linha `650632`, em Amperes |
| `DSS-0.Line-650632-I1_ang`, `I2_ang`, `I3_ang` | Ângulo de corrente por fase, em graus |

## Variações

- **Mudar a duração ou o passo de tempo**: `STEP_SIZE`, `N_PASSOS` e `END_TIME` estão no topo de `opendss_scenario.py`. O padrão usado nos demais cenários do projeto está em [Executar Cenário Local](../how-to-guides/run-scenario-locally.md).
- **Monitorar outro ponto do circuito**: o cenário só conecta a linha `650632` e a barra `rg60` ao `Collector` porque foi assim que o script foi escrito — não é uma limitação do adaptador. Qualquer `Bus`, `Line`, `Load`, `PVSystem`, `Storage` ou `RegControl` do circuito pode ser conectado da mesma forma; veja os atributos disponíveis de cada modelo em [Adaptadores Mosaik](../reference/mosaik-adapters.md).
- **Simular outro alimentador**: este script está fixo no IEEE 13 barras. Para 34 ou 123 barras, use os cenários prontos do catálogo — veja [Catálogo de Cenários](../reference/scenarios.md).

## Erros comuns

Consulte [Solução de Problemas Comuns](../how-to-guides/troubleshoot-common-issues.md) — os erros mais frequentes neste passo são `ModuleNotFoundError` (executar sem `uv run`) e `FileNotFoundError` para o arquivo `.dss` (executar fora da raiz do repositório).

## Próximos passos

- [Tutorial: Pipeline PV Local](../tutorials/pv-pipeline-local.md) — adicione geração fotovoltaica e um inversor à mesma base, ainda em Python puro
- [Tutorial: Cenário Inversor Inteligente](../tutorials/smart-inverter-scenario.md) — controle Volt-Var via IEEE 1547
- [Tutorial: Co-Simulação Docker](../tutorials/docker-co-simulation.md) — rode cada simulador em seu próprio container, o modo recomendado para cenários completos
- [Catálogo de Cenários](../reference/scenarios.md) — veja todos os cenários disponíveis