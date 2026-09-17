# Arquivos de Dados

## Estrutura

```
data/
├── 13Bus/          # IEEE 13-Node Test Feeder
├── 34Bus/          # IEEE 34-Node Test Feeder
├── 123Bus/         # IEEE 123-Node Test Feeder (principal)
├── InfoPV/         # Dados reais de estações solares brasileiras
├── CriarRede.py    # Script para gerar rede SimBench
├── rede_1-LV-rural2--0-sw.json  # Rede SimBench LV rural
└── solar_data_Bremen_minutes.csv  # Irradiância DNI de Bremen (1 min)
```

## IEEE 13-Node Test Feeder

| Arquivo | Descrição |
|---|---|
| `IEEE13Nodeckt.dss` | Definição do circuito: fonte 115kV, transformador, reguladores, linhas, cargas |
| `IEEE13Nodeckt_w_loadcurve.dss` | Variante com suporte a curvas de carga |
| `IEEELineCodes.dss` | Códigos de impedância de linha |
| `ieee13_pv.dss` | Definição de 6 PVSystems (1000 kVA cada) |
| `ieee13_shape_pv_5min.dss` | LoadShapes de PV em 5 min (288 pontos/dia) |
| `ieee13_shape_pv_5min.csv` | Versão CSV das LoadShapes |
| `ieee13_temperature_5min.csv` | Série temporal de temperatura (5 min) |
| `run_ieee13_cosim_pv_5min.dss` | Runner: compila circuito, configura modo diário, 288 passos |

## IEEE 34-Node Test Feeder

| Arquivo | Descrição |
|---|---|
| `ieee34Mod1.dss` | Modelo 1: fonte 69kV, transformador, linhas com cargas distribuídas |
| `ieee34Mod1_w_loadcurve.dss` | Modelo 1 com curvas de carga |
| `ieee34Mod2.dss` | Modelo 2 (conta melhor cargas distribuídas) |
| `IEEELineCodes.DSS` | Códigos de impedância |
| `LoadShape34Bus_5min.dss` | LoadShapes em 5 min |

## IEEE 123-Node Test Feeder (principal)

| Arquivo | Descrição |
|---|---|
| `IEEE123Master.dss` | Definição principal: fonte 4.16kV, reguladores, 118 linhas, 8 chaves, capacitores |
| `IEEE123Loads.DSS` | 91 cargas definidas |
| `IEEE123Regulators.DSS` | Controles de regulador |
| `IEEE123Switches.dss` | Master alternativo do IEEE, do qual veio o bloco de chaves adotado (ver abaixo); não é usado pelos runners |
| `IEEELineCodes.DSS` | Códigos de impedância |
| `run_ieee123_cosim_5min.dss` | Runner base (sem PV) |
| `run_ieee123_cosim_pv_5min.dss` | Runner com PV + monitor |
| `ieee123_pv.dss` | PVSystem único: 1000 kVA trifásico na barra 97 |
| `ieee123_shape_pv_5min.dss` | LoadShapes PV (2 formas: my_shape1_pv, my_shape2_pv) |
| `ieee123_shape_pv_5min.csv` | Versão CSV das LoadShapes PV |
| `ieee123_shape_load_5min.dss` | 25 LoadShapes de carga em 5 min |
| `ieee123_temperature_5min.csv` | Temperatura em 5 min |
| `edit_load.dss` | Mapeamento das 91 cargas para suas LoadShapes |

!!! note "As chaves do IEEE123 e uma edição no master"
    O IEEE123 original define as oito chaves (`Sw1`–`Sw8`) como linhas curtas
    quaisquer, e o próprio arquivo observa que "could also be defined by setting
    the Switch=Yes property". Sem essa propriedade não há como distinguir uma
    chave de um trecho curto de linha.

    O bloco de chaves do `IEEE123Switches.dss` — que as declara com
    `switch=yes` — foi adotado no `IEEE123Master.dss`, em vez de repontar os 12
    runners que o compilam. O circuito é numericamente o mesmo: a maior
    divergência de tensão entre as duas versões é 3e-11 pu.

    **A ordem importa**: `switch=yes` sobrescreve a impedância da linha por um
    padrão do OpenDSS, então `r1`/`x1`/`c1`/`Length` vêm depois dele na mesma
    linha, repondo os valores originais. Inverter a ordem muda o circuito sem
    que nada acuse.

    Efeito colateral bem-vindo: as normalmente abertas (`Sw7`, `Sw8`) passaram a
    ligar as barras reais `300` e `94.1`, abertas com `terminal=2`, em vez das
    fictícias `300_OPEN`/`94_OPEN`. Como `300` e `94` constam do
    `BusCoords.dat`, o alimentador deixou de ter barras sem coordenada.

## InfoPV — Dados reais de estações solares

### power_station_metadata.csv

Metadados de 51 estações solares brasileiras (PS_001 a PS_051):

| Campo | Descrição |
|---|---|
| Estado | UF (SP, RJ, GO, MG, PR, MS, BA) |
| Potência nominal | 1–5 MW |
| Número de painéis | — |
| Área do painel | m² |
| Bifacial | Sim/Não |
| Coeficiente de bifacialidade | — |
| Eficiência do painel | — |
| Coeficiente de temperatura | — |
| Tipo de estrutura | FIXED ou TRACKER |

### solar_station/

51 arquivos CSV (PS_001.csv a PS_051.csv), cada um com 1441 linhas (14 dias, 15 min de intervalo):

| Coluna | Unidade | Descrição |
|---|---|---|
| `datetime` | — | Data/hora |
| `GHI` | W/m² | Irradiância global horizontal |
| `POA` | W/m² | Irradiância no plano do arranjo |
| `ambient_temperature` | °C | Temperatura ambiente |
| `panel_temperature` | °C | Temperatura do painel |
| `wind_speed` | m/s | Velocidade do vento |
| `wind_direction` | ° | Direção do vento |
| `precipitation` | mm | Precipitação |

## solar_data_Bremen_minutes.csv

Irradiância DNI (Direct Normal Irradiance) de Bremen, Alemanha, em resolução de 1 minuto para 2016. Utilizada pelo cenário `base_scenario.py`.

## Rede SimBench LV rural

`rede_1-LV-rural2--0-sw.json`: Rede de baixa tensão rural europeia gerada pelo script `CriarRede.py` usando `pandapower` + `simbench`. Utilizada pelo cenário `base_scenario.py`.
