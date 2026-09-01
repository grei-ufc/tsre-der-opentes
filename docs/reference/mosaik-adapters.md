# Adaptadores Mosaik — Referência

Este documento lista os META dicts, atributos e parâmetros de todos os adaptadores mosaik do projeto.

---

## OpenDSS Simulator

**Módulo**: `simulators.opendss.api_opendss`
**Classe**: `OpenDSSSimulator`
**Tipo**: `time-based`

### META

A `META` abaixo não é escrita à mão: é **derivada** do registro declarativo `MODEL_SPECS` em `opendss/element_specs.py` (`META = build_meta()`), o mesmo padrão usado pelo `Inverter` (veja adiante). O roteamento de entrada em `step()` e as leituras em `get_data()` vêm do mesmo registro, então um atributo não pode ser declarado aqui sem o código que o implementa — para adicionar um, veja [Decisões de Projeto](../explanation/design-decisions.md).

```python
{
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "Grid": {
            "public": True,
            "params": ["topofile"],
            "attrs": [],
        },
        "Load": {
            "public": False,
            "params": [],
            "attrs": ["P_mw", "Q_mvar", "P_out_mw", "Q_out_mvar"],
        },
        "Line": {
            "public": False,
            "params": [],
            "attrs": ["is_open", "I1_A", "I1_ang", "I2_A", "I2_ang", "I3_A", "I3_ang",
                       "P1_w", "Q1_var", "P2_w", "Q2_var", "P3_w", "Q3_var"],
        },
        "Bus": {
            "public": False,
            "params": [],
            "attrs": ["V1_pu", "V1_ang", "V2_pu", "V2_ang", "V3_pu", "V3_ang",
                       "V_min_pu", "V_max_pu", "V_mean_pu", "V_unb_pct"],
        },
        "Transformer": {
            "public": False,
            "params": [],
            "attrs": ["P1_kw", "P2_kw", "P3_kw", "Q1_kvar", "Q2_kvar", "Q3_kvar",
                       "I1_A", "I2_A", "I3_A", "I1_ang", "I2_ang", "I3_ang",
                       "P_total_kw", "Q_total_kvar"],
        },
        "RegControl": {
            "public": False,
            "params": [],
            "attrs": ["tap", "v_meas", "i_meas"],
        },
        "Storage": {
            "public": True,
            "params": [],
            "attrs": ["P_set", "Q_set", "SoC_set", "P_act", "Q_act", "SoC",
                       "P1", "P2", "P3", "Q1", "Q2", "Q3", "I1_A", "I2_A", "I3_A"],
        },
        "PVSystem": {
            "public": True,
            "params": [],
            "attrs": ["P_des", "Q_des", "P_meas", "Q_meas",
                       "P1", "P2", "P3", "Q1", "Q2", "Q3", "I1_A", "I2_A", "I3_A"],
        },
    },
    "extra_methods": ["get_dss_wrapper", "get_extra_info", "get_detected_regulators",
                       "get_detected_pvsystems", "get_detected_storages",
                       "get_detected_transformers", "get_bus_positions"],
}
```

### init()

```python
def init(self, sid, time_resolution, topofile, step_size=900, output_graph_path=None,
         bypass_native_pv_curves=True, buscoords=None)
```

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `topofile` | `str` | — | Caminho do arquivo `.dss` master. Um circuito por simulação: o motor OpenDSS é único no processo, então um segundo circuito substituiria o primeiro |
| `step_size` | `int` | 900 | Passo de tempo em segundos |
| `output_graph_path` | `str \| None` | `None` | Se fornecido, exporta topologia JSON |
| `bypass_native_pv_curves` | `bool` | `True` | Neutraliza as curvas de eficiência e derating dos PVSystems, quando o inversor é modelado por outro simulador |
| `buscoords` | `str \| None` | `None` | Arquivo `Buscoords` a carregar após o circuito. Vários alimentadores do IEEE trazem o arquivo mas não o carregam no `.dss` principal |

### create()

Apenas o modelo `Grid` pode ser criado. Ao criar o Grid, todas as entidades Load, Line, Bus, Transformer, RegControl, Storage e PVSystem são criadas automaticamente.

O `Transformer` existe por causa da topologia: bancos de reguladores e elevadoras de subestação ligam duas barras sem que haja linha entre elas. Sem essas entidades, o grafo montado a partir de `rel` se parte em ilhas — no IEEE34, cinco delas.

### Atributos de entrada (step)

| Modelo | Atributo | Tipo | Descrição |
|---|---|---|---|
| RegControl | `tap` | `int` | Posição do tap (-16 a +16) |
| Storage | `P_set` | `float` | Potência ativa solicitada (kW) |
| Storage | `Q_set` | `float` | Potência reativa solicitada (kvar) |
| Storage | `SoC_set` | `float` | SoC alvo (%) |
| PVSystem | `P_des` | `float` | Potência ativa desejada (kW) |
| PVSystem | `Q_des` | `float` | Potência reativa desejada (kvar) |

### Atributos de saída (get_data)

| Modelo | Atributo | Tipo | Descrição |
|---|---|---|---|
| Load | `P_out_mw` | `float` | Potência ativa da carga (MW) |
| Load | `Q_out_mvar` | `float` | Potência reativa da carga (MVar) |
| Line | `I1_A..I3_A` | `float` | Corrente por fase (A) |
| Line | `P1_w..P3_w` | `float` | Potência ativa por fase (W) |
| Line | `Q1_var..Q3_var` | `float` | Potência reativa por fase (var) |
| Bus | `V1_pu..V3_pu` | `float` | Tensão por fase (p.u.); `0.0` na fase que a barra não tem |
| Bus | `V1_ang..V3_ang` | `float` | Ângulo por fase (graus) |
| Bus | `V_min_pu`, `V_max_pu`, `V_mean_pu` | `float` | Extremos e média entre as **fases presentes** |
| Bus | `V_unb_pct` | `float` | Desequilíbrio NEMA: maior desvio em relação à média, em % |
| Transformer | `P1_kw..P3_kw` | `float` | Potência ativa por fase no enrolamento 1 (kW) |
| Transformer | `Q1_kvar..Q3_kvar` | `float` | Potência reativa por fase no enrolamento 1 (kvar) |
| Transformer | `I1_A..I3_A` | `float` | Corrente por fase (A) |
| Transformer | `P_total_kw`, `Q_total_kvar` | `float` | Soma das fases |
| RegControl | `v_meas` | `complex` | Tensão medida no alvo |
| RegControl | `i_meas` | `complex` | Corrente medida no primário |
| RegControl | `tap` | `int` | Posição atual do tap |
| PVSystem | `P_meas` | `float` | Potência ativa medida (kW) |
| PVSystem | `Q_meas` | `float` | Potência reativa medida (kvar) |
| Storage | `P_act` | `float` | Potência ativa atual (kW) |
| Storage | `Q_act` | `float` | Potência reativa atual (kvar) |
| Storage | `SoC` | `float` | Estado de carga (%) |

---

## Inverter

**Módulo**: `simulators.inverter.smart_inverter_simulator`
**Classe**: `SmartInverterSim` (alias histórico: `InverterSim`)
**Tipo**: `time-based`

Adaptador único de inversor do projeto. Sem `ctrl_config`, nenhuma função do
OpenDER é ativada e o inversor segue o `Q_des` recebido — o comportamento do
antigo adaptador padrão. `simulators.inverter.inverter_simulator` continua
resolvendo como shim de compatibilidade.

A `META` é **derivada** dos registros `INPUT_SPECS` e `OUTPUT_GETTERS` do
módulo, então não pode declarar um atributo sem o código que o implementa.

### Parâmetros de criação

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `units` | `list[dict]` | Unidades físicas (`InverterUnit.to_dict()`), até 3 |
| `ctrl_config` | `dict \| None` | `ControlConfig.to_dict()`; ausente = sem OpenDER |
| `eff_curve_x` | `list[float]` | Pontos X da curva de eficiência (pu da potência nominal) |
| `eff_curve_y` | `list[float]` | Eficiência correspondente (0-1) |
| `pct_cutin` | `float` | Limiar de entrada (% do kVA total) |
| `pct_cutout` | `float` | Limiar de saída (% do kVA total) |
| `kVA`, `kW`, `kv`, `phases`, `node`, `name` | — | Atalho para uma única unidade, no lugar de `units` |
| `priority` | `str` | Compatibilidade: `"Active"` / `"Reactive"`, mapeado para `ControlConfig.priority` |

### Atributos

| Atributo | Direção | Tipo | Descrição |
|---|---|---|---|
| `P_dc` | entrada | `float` | Potência DC do painel (kW); somada entre as fontes |
| `Q_des` | entrada | `float` | Reativo desejado (kvar); usado só sem controle de reativo |
| `V_meas_1..3` | entrada | `float` | Tensão de fase da barra (pu) |
| `V_ang_1..3` | entrada | `float` | Ângulo de fase (graus); só usado com `v_meas_unbalance="POS"` |
| `f_meas` | entrada | `float` | Frequência (Hz) |
| `P_ac`, `Q_ac` | saída | `float` | Injeção total da entidade (kW, kvar) |
| `P_ac_1..3`, `Q_ac_1..3` | saída | `float` | Injeção **por unidade**, na ordem de `units` |
| `P_phase_1..3`, `Q_phase_1..3` | saída | `float` | Injeção **por fase** da barra |
| `V_meas_pu` | saída | `float` | Tensão que o controle enxergou |
| `der_status` | saída | `str` | `Continuous Operation`, `Trip`, `Entering Service`, ... |
| `q_desired_pu` | saída | `float` | Reativo pedido pela curva, antes dos limites |
| `p_avl_pu` | saída | `float` | Potência disponível (pu) |
| `p_pv_limit_pu` | saída | `float` | Limite imposto pelo volt-watt (pu) |
| `is_on` | saída | `bool` | Estado do corte de entrada |

!!! warning "`P_ac_k` é a k-ésima unidade, não a k-ésima fase"
    Para grandezas por fase da barra, use `P_phase_k` / `Q_phase_k`.

### `init()`

`init(sid, time_resolution, step_size)` fixa `DER.t_s = step_size × time_resolution`.
Esse é um atributo de **classe** do OpenDER: vale para todos os DERs do
processo, e é ele que dita OLRT, rampa de entrada em serviço e temporizadores de
trip. Sem defini-lo, o default de 100 000 s torna todos eles inertes.

Ver [Inversor Inteligente — Referência](inverter-model.md) para os parâmetros de
controle.

---

## PV Panel Simulator

**Módulo**: `simulators.pv.pv_panel_simulator`
**Classe**: `PVPanelSim`
**Tipo**: `time-based`

### META

```python
{
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "PVPanel": {
            "public": True,
            "params": ["P_mpp", "irradiance_base", "pt_curve_x", "pt_curve_y"],
            "attrs": ["irradiance", "temperature", "P_dc"],
        }
    }
}
```

### Parâmetros de criação

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `P_mpp` | `float` | Potência máxima do ponto de operação (kW) |
| `irradiance_base` | `float` | Irradiância de referência (W/m²) |
| `pt_curve_x` | `list[float]` | Temperaturas de referência (°C) |
| `pt_curve_y` | `list[float]` | Fatores de correção de potência |

### Atributos

| Atributo | Direção | Tipo | Descrição |
|---|---|---|---|
| `irradiance` | entrada | `float` | Irradiância normalizada (0–1) |
| `temperature` | entrada | `float` | Temperatura ambiente (°C) |
| `P_dc` | saída | `float` | Potência DC disponível (kW) |

---

## Battery Simulator

**Módulo**: `simulators.battery.battery_sim`
**Classe**: `BatterySim`
**Tipo**: `time-based`

### META

```python
{
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "Battery": {
            "public": True,
            "params": ["kw_rated", "kwh_rated", "kwh_stored", "pct_reserve",
                        "pct_eff_charge", "pct_eff_discharge", "pct_idling_kw",
                        "kva_rated"],
            "attrs": ["P_ref", "Q_ref", "P_out", "Q_out", "SoC", "State"],
        }
    }
}
```

### Parâmetros de criação

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `kw_rated` | `float` | — | Potência nominal de descarga (kW) |
| `kwh_rated` | `float` | — | Capacidade nominal (kWh) |
| `kwh_stored` | `float` | — | Energia inicial armazenada (kWh) |
| `pct_reserve` | `float` | 20.0 | Reserva mínima (%) |
| `pct_eff_charge` | `float` | 90.0 | Eficiência de carga (%) |
| `pct_eff_discharge` | `float` | 90.0 | Eficiência de descarga (%) |
| `pct_idling_kw` | `float` | 2.0 | Consumo em idle (% da nominal) |
| `kva_rated` | `float` | — | Potência aparente nominal (kVA) |

### Atributos

| Atributo | Direção | Tipo | Descrição |
|---|---|---|---|
| `P_ref` | entrada | `float` | Potência referência do controlador (kW) |
| `Q_ref` | entrada | `float` | Potência reativa referência (kvar) |
| `P_out` | saída | `float` | Potência ativa de saída (kW) |
| `Q_out` | saída | `float` | Potência reativa de saída (kvar) |
| `SoC` | saída | `float` | Estado de carga (0–100%) |
| `State` | saída | `str` | `"Charging"`, `"Discharging"` ou `"Idling"` |

---

## Battery Controller

**Módulo**: `simulators.controller.controller_sim`
**Classe**: `BatteryControllerSim`
**Tipo**: `time-based`

### META

```python
{
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "Controller": {
            "public": True,
            "params": ["target_battery", "kw_rated", "charge_trigger",
                        "discharge_trigger", "pct_charge", "pct_discharge",
                        "time_charge_trigger"],
            "attrs": ["SoC_in", "curve_value", "P_ref", "Q_ref"],
        }
    }
}
```

### Atributos

| Atributo | Direção | Tipo | Descrição |
|---|---|---|---|
| `SoC_in` | entrada | `float` | Estado de carga da bateria (%) |
| `curve_value` | entrada | `float` | Valor da curva de despacho (ex: carga do sistema) |
| `P_ref` | saída | `float` | Referência de potência para a bateria (kW) |
| `Q_ref` | saída | `float` | Referência de potência reativa (kvar) |

---

## Regulator Controller

**Módulo**: `simulators.controller.regulator_control`
**Classe**: `RegulatorSimulator`
**Tipo**: `time-based`

### META

```python
{
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "RegController": {
            "public": True,
            "params": ["vreg", "band", "pt_ratio", "ct_primary", "R", "X",
                        "delay", "tap_delay", "tap_ini"],
            "attrs": ["v_meas", "i_meas", "tap_cmd"],
        }
    }
}
```

### Atributos

| Atributo | Direção | Tipo | Descrição |
|---|---|---|---|
| `v_meas` | entrada | `complex` | Tensão medida no bus alvo |
| `i_meas` | entrada | `complex` | Corrente medida no primário |
| `tap_cmd` | saída | `int` | Comando de tap (-16 a +16) |

---

## Collector

**Módulo**: `simulators.collector.collector`
**Classe**: `Collector`
**Tipo**: `event-based`

### META

```python
{
    "api_version": "3.0",
    "type": "event-based",
    "models": {
        "Monitor": {
            "public": True,
            "any_inputs": True,
            "params": [],
            "attrs": [],
        }
    }
}
```

### init()

```python
def init(self, sid, time_resolution, start_date, date_format,
         output_file, print_results)
```

---

## CSV Reader

**Módulo**: `simulators.collector.csv_sim_pandas`
**Classe**: `CSV`
**Tipo**: `hybrid` (definido dinamicamente)

### init()

```python
def init(self, sid, time_resolution, sim_start, datafile,
         date_format, continuous=True)
```

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `sim_start` | `str` | — | Data/hora de início da simulação |
| `datafile` | `str` | — | Caminho do arquivo CSV |
| `date_format` | `str` | — | Formato da data no CSV |
| `continuous` | `bool` | `True` | Se `True`, interpola entre timestamps |
