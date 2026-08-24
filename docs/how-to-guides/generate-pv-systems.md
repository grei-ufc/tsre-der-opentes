# Gerar PVSystems Automaticamente

## Visão geral

A ferramenta `PVCreator` (`simulators/util/pv_creator.py`) gera automaticamente definições de PVSystems e LoadShapes para o OpenDSS a partir de dados de estações solares reais.

## Quando usar

- Quando precisa adicionar múltiplos PVSystems a um circuito
- Para gerar LoadShapes de irradiância e temperatura a partir de dados reais
- Para criar cenários com distribuição geográfica de PV

## Pré-requisitos

- Dados de estações solares em `data/InfoPV/solar_station/`
- Arquivo `data/InfoPV/power_station_metadata.csv`
- Circuito OpenDSS compilável

## Uso básico

```python
from simulators.util.pv_creator import PVCreator

# Criar 10 PVSystems no circuito IEEE 123-bus
pvs = PVCreator(
    QtdPVs=10,
    dss_path="data/123Bus/IEEE123Master.dss",
    output_dir="output/pv_generated"
)
```

## O que a ferramenta faz

1. Compila o circuito no OpenDSS
2. Identifica barras elegíveis para conexão de PV
3. Amostra aleatoriamente barras para os PVSystems
4. Mapeia estações solares para cada PVSystem
5. Interpola dados de 15 min para o passo de tempo desejado
6. Gera:
   - Arquivo `.dss` com definições de PVSystem
   - Arquivos CSV com LoadShapes de irradiância e temperatura

## Saída gerada

| Arquivo | Conteúdo |
|---|---|
| `pv_systems.dss` | Definições `New PVSystem.` para cada PV |
| `irradiance_<nome>.csv` | Curva de irradiância normalizada |
| `temperature_<nome>.csv` | Curva de temperatura |

## Classes internas

### `PVGenerator`

Modela uma estação solar individual:

- `name`: identificador
- `station_id`: ID da estação no metadata
- `irradiance`: array normalizado (0–1)
- `temperature`: array em °C
- `p_mpp`: potência nominal (kW)

### Funções auxiliares

- `CurveLinearInterpolation(new_rate, npts_base, start_date)`: reamostra de 15 min para o passo desejado
- `GenerateCSV(PVGen, OUTPUT_DIR)`: exporta CSVs de irradiância/temperatura
- `GenerateDSS(PVGen, OUTPUT_DIR)`: exporta script DSS dos PVSystems
