# Adicionar Armazenamento ao Cenário

## Visão geral

O módulo `battery/` fornece um modelo de bateria e um adaptador mosaik para simular armazenamento de energia. Este guia explica como integrá-los em um cenário.

## Componentes

| Módulo | Classe | Função |
|---|---|---|
| `battery/battery_model.py` | `OpenDSSBattery` | Modelo de física da bateria |
| `battery/battery_sim.py` | `BatterySim` | Adaptador mosaik |
| `controller/controller_sim.py` | `BatteryControllerSim` | Controlador de despacho |

## Configuração no SIM_CONFIG

```python
SIM_CONFIG = {
    "DSS":         {"python": "simulators.opendss.api_opendss:OpenDSSSimulator"},
    "Battery":     {"python": "simulators.battery.battery_sim:BatterySim"},
    "Controller":  {"python": "simulators.controller.controller_sim:BatteryControllerSim"},
    "CSV":         {"python": "simulators.collector.csv_sim_pandas:CSV"},
    "Collector":   {"python": "simulators.collector.collector:Collector"},
}
```

## Criar entidades

```python
# Bateria
battery = world.start("Battery").Battery(
    kw_rated=100.0,
    kwh_rated=400.0,
    kwh_stored=200.0,      # 50% SoC inicial
    pct_reserve=20.0,
    pct_eff_charge=90.0,
    pct_eff_discharge=90.0,
    kva_rated=120.0
)

# Controlador
ctrl = world.start("Controller").Controller(
    target_battery="Battery_0",
    kw_rated=100.0,
    charge_trigger=50.0,      # carga quando curve_value < 50
    discharge_trigger=150.0,  # descarga quando curve_value > 150
    pct_charge=80.0,
    pct_discharge=80.0,
    time_charge_trigger=2     # carga agendada às 2h
)
```

## Conexões

```python
# Controlador → Bateria
world.connect(ctrl, battery, ("P_ref", "P_ref"))
world.connect(ctrl, battery, ("Q_ref", "Q_ref"))

# Bateria → Controlador (feedback de SoC)
world.connect(battery, ctrl, ("SoC", "SoC_in"))

# Bateria → OpenDSS
world.connect(battery, dss_grid, ("P_out", "P_set"))
world.connect(battery, dss_grid, ("Q_out", "Q_set"))

# CSV → Controlador (curva de despacho)
world.connect(csv, ctrl, ("load_curve", "curve_value"))
```

## Lógica do controlador

O `BatteryControllerSim` segue a lógica padrão do OpenDSS:

1. Se `curve_value > discharge_trigger` → descarga a `pct_discharge` da potência nominal
2. Se `curve_value < charge_trigger` → carga a `pct_charge` da potência nominal
3. Caso contrário, verifica `time_charge_trigger` (hora do dia)
4. Segurança: para de carregar se SoC >= 99.99%

## Atributos da bateria

| Atributo | Direção | Descrição |
|---|---|---|
| `P_ref` | entrada | Potência solicitada (kW). Positivo=descarga, Negativo=carga |
| `Q_ref` | entrada | Potência reativa solicitada (kvar) |
| `P_out` | saída | Potência efetiva de saída (kW) |
| `Q_out` | saída | Potência reativa efetiva (kvar) |
| `SoC` | saída | Estado de carga (0–100%) |
| `State` | saída | `"Charging"`, `"Discharging"` ou `"Idling"` |
