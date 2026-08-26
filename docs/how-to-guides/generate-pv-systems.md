# Gerar PVSystems Automaticamente

## Visão geral

A ferramenta `PVCreator` (`simulators/util/pv_creator.py`) mapeia barras elegíveis de um circuito OpenDSS, sorteia posições para novos `PVSystem`s e gera curvas de irradiância/temperatura interpoladas a partir de dados reais de estações solares brasileiras (`data/InfoPV/`).

!!! warning "Ferramenta de bootstrap do circuito 13 barras, não um gerador genérico"
    Apesar de aceitar qualquer circuito via `SCRIPT_DSS`, a saída é sempre escrita em `data/13Bus/`, com nomes de arquivo fixos (`ieee13_pv.dss`, `ieee13_shape_pv_5min.csv`, `ieee13_temperature_5min.csv`). Esta é a própria ferramenta que gerou os arquivos PV do circuito IEEE 13 barras já versionados no repositório — rodá-la **sobrescreve** esses três arquivos, seja qual for o circuito usado para mapear as barras.

## Quando usar

- Para regenerar o conjunto de PVSystems do circuito 13 barras com uma amostragem diferente
- Para experimentar um `PV_dictionaries_list` manual (barras e potências específicas) combinado a preenchimento aleatório
- Como referência de como as curvas de `data/InfoPV/` foram interpoladas para os `.dss` do projeto

## Pré-requisitos

- Dados de estações solares em `data/InfoPV/solar_station/`
- Arquivo `data/InfoPV/power_station_metadata.csv`
- Um circuito OpenDSS compilável (padrão: `data/13Bus/IEEE13Nodeckt.dss`)

## Uso básico

```python
import sys
sys.path.insert(0, "src")

from simulators.util.pv_creator import PVCreator, PVGenerator

# Sorteia 2 PVSystems no circuito padrão (13 barras), evitando as barras 650 e 670
pvs = PVCreator(QtdPVs=2, ignore_buses=["650", "670"])

# A geração de arquivos é um passo separado
PVGenerator.GenerateCSV(pvs)
PVGenerator.GenerateDSS(pvs)
```

Verificado rodando o exemplo acima: produz uma lista de `PVGenerator` (ex.: `PV1` na barra `632.1.2.3`, 15000 kVA; `PV2` na barra `634.1.2.3`, 3000 kVA) e sobrescreve os três arquivos de saída em `data/13Bus/`. A amostragem usa `my_seed` (padrão `25`), então a mesma chamada sempre escolhe as mesmas barras.

!!! warning "Sobrescreve dados versionados"
    Os três arquivos de saída têm os mesmos nomes já versionados em `data/13Bus/` (veja [Arquivos de Dados](../reference/data-files.md)). Rode `git diff` antes de commitar, ou restaure com `git checkout -- data/13Bus/` se a intenção era só validar a ferramenta.

## Parâmetros de `PVCreator`

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `QtdPVs` | `int` | — | Número de PVSystems a alocar aleatoriamente |
| `SCRIPT_DSS` | `str \| Path` | `data/13Bus/IEEE13Nodeckt.dss` | Circuito a compilar para mapear barras elegíveis |
| `PV_list` | `pd.DataFrame` | metadados de `data/InfoPV/power_station_metadata.csv` | Metadados das estações solares |
| `step` | `str` | `"5min"` | Passo de tempo de saída (alias do pandas: `"5min"`, `"1h"`, ...) |
| `PV_dictionaries_list` | `list[dict] \| None` | `None` | Definições manuais (chaves `PV_phases`, `PV_bus`, `PV_kv`, `PV_kva`, `PV_curve_id`); instaladas antes do preenchimento aleatório |
| `my_seed` | `int` | `25` | Semente para reprodutibilidade da amostragem |
| `bus_multi_PV` | `bool` | `False` | Se `True`, permite mais de um PV na mesma barra |
| `npts_origin` | `int` | `96` (24h a 15 min) | Número de pontos na resolução original dos dados |
| `ignore_buses` | `str \| list[str] \| None` | `None` | Barra(s) a excluir do sorteio (ex.: `["650", "670"]`) |

**Retorno**: `list[PVGenerator]`. A escrita de arquivo (CSV/DSS) **não** é automática — chame `PVGenerator.GenerateCSV(pvs)` e `PVGenerator.GenerateDSS(pvs)` depois.

## O que a ferramenta faz

1. Compila `SCRIPT_DSS` no OpenDSS
2. Identifica como elegíveis as barras com nome puramente numérico
3. Sorteia `QtdPVs` barras entre as elegíveis (menos as já usadas por `PV_dictionaries_list` e as de `ignore_buses`)
4. Para cada PV (manual ou sorteado), mapeia uma estação solar de `data/InfoPV/` (por `PV_curve_id`, ou pela posição do PV como fallback) e já interpola a curva de 15 min para `step` — isso acontece dentro de `PVCreator`, via `PVGenerator.CurveLinearInterpolation`, sem chamada manual
5. Retorna a lista de `PVGenerator`; nada é escrito em disco ainda nesse ponto

## Saída gerada

Chamar `PVGenerator.GenerateCSV(pvs)` e `PVGenerator.GenerateDSS(pvs)` grava, sempre em `data/13Bus/`:

| Arquivo | Conteúdo |
|---|---|
| `ieee13_pv.dss` | Definições `New PVSystem.` para cada PV |
| `ieee13_shape_pv_5min.csv` | Curvas de irradiância normalizada, uma coluna por PV |
| `ieee13_temperature_5min.csv` | Curvas de temperatura, uma coluna por PV |

## Classes internas

### `PVGenerator`

Modela uma estação solar mapeada para um PV do circuito.

| Atributo | Descrição |
|---|---|
| `name` | Identificador (`PV1`, `PV2`, ...) |
| `curve_id` | Índice da estação no metadata (1–51) |
| `curve` | ID real da estação (ex.: `"PS_004"`), usado no nome do CSV de origem em `data/InfoPV/solar_station/` |
| `bus`, `phases`, `kv`, `kva` | Ponto de conexão e potência |
| `irrad_curve`, `temperature_curve` | `DataFrame` com a curva já interpolada para `step`, indexado por data |

### Método

#### `CurveLinearInterpolation(new_rate, npts_base_15min, start_date)`

Método de instância de `PVGenerator`, chamado automaticamente dentro de `PVCreator` — não precisa ser chamado manualmente. Reamostra `irrad_curve`/`temperature_curve` de 15 min para `new_rate` por interpolação linear.

### Funções estáticas de `PVGenerator`

- `GenerateCSV(PVGen, OUTPUT_DIR=...)`: exporta os CSVs consolidados de irradiância/temperatura
- `GenerateDSS(PVGen, OUTPUT_DIR=...)`: exporta o script `.dss` com as definições `New PVSystem.`
