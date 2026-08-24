# Configurar um Inversor Inteligente (Volt-Var / Volt-Watt)

## Visão geral

O inversor inteligente aplica as funções de suporte à rede da IEEE 1547-2018 via
[OpenDER](https://github.com/epri-dev/OpenDER). O OpenDSS fica responsável só
pelo fluxo de potência: o controle vive no simulador de inversor, e a injeção
resultante é escrita nos `PVSystem` do circuito.

A referência completa dos parâmetros está em
[Inversor Inteligente — Referência](../reference/inverter-model.md).

## Quando usar

- Estudos de capacidade de hospedagem com controle de tensão
- Comparação entre volt-var, volt-watt e fator de potência fixo
- Avaliação do efeito do controle sobre reguladores e perdas

## Pré-requisitos

- Circuito com ao menos um `PVSystem` definido
- `opender` instalado (já está em `pyproject.toml`)

---

## 1. Escolher o controle

```python
from simulators.inverter.config import (
    ControlConfig, ReactiveMode, VoltVarCurve, VoltWattCurve,
)

STEP_SIZE = 60 * 5

CONTROLE = ControlConfig(
    reactive_mode=ReactiveMode.VOLT_VAR,
    volt_var=VoltVarCurve.ieee1547_cat_b(olrt=2 * STEP_SIZE),
    volt_watt=VoltWattCurve.ieee1547_default(olrt=2 * STEP_SIZE),
    trip_enabled=False,
    priority="REACTIVE",
)
```

Para uma curva própria, informe os quatro pontos:

```python
VoltVarCurve(
    v=(0.90, 0.99, 1.01, 1.06),   # pu da tensão nominal
    q=(0.44, 0.0, 0.0, -0.44),    # pu de S_nom; positivo injeta
    olrt=2 * STEP_SIZE,
)
```

!!! tip "Ajuste a banda morta ao seu alimentador"
    A banda morta padrão (0.98–1.02 pu) é larga. Num alimentador cuja tensão já
    fica dentro dela, o volt-var nunca atua e o resultado é indistinguível de
    fator de potência unitário. Rode primeiro sem controle, olhe a faixa de
    tensão real e só então dimensione a curva.

### Só volt-watt

```python
ControlConfig(volt_watt=VoltWattCurve.ieee1547_default(olrt=2 * STEP_SIZE))
```

Volt-watt é função de potência ativa: é ortogonal ao modo de reativo e não
precisa de `reactive_mode`.

### Fator de potência fixo, como base de comparação

```python
from simulators.inverter.config import ConstPF

ControlConfig(
    reactive_mode=ReactiveMode.CONST_PF,
    const_pf=ConstPF(pf=0.95, excitation="ABS"),
)
```

---

## 2. Descrever as unidades físicas

Cada `PVSystem` do circuito vira uma `InverterUnit`, e cada unidade ganha seu
próprio objeto OpenDER.

```python
from simulators.inverter.config import InverterUnit

def build_units(lista_pvs):
    units = []
    for pv in lista_pvs:
        info = pv.extra_info          # topologia já resolvida pelo simulador DSS
        phases = int(info.get("phases") or 3)
        units.append(
            InverterUnit(
                name=info["name"],
                kva=info["kva"],
                kw=info["pmpp"],
                kv=info["kv"],        # linha-linha se trifásico, linha-neutro se monofásico
                phases=phases,
                node=info["nodes"][0] if phases == 1 else None,
            )
        )
    return units
```

Uma entidade `Inverter` comporta **até três** unidades — o suficiente para as
três fases de uma barra. Acima disso, crie entidades separadas.

---

## 3. Instanciar e ligar no cenário

```python
inv_sim = world.start("InverterSim", step_size=STEP_SIZE)

inv_obj = inv_sim.Inverter.create(
    1,
    units=[u.to_dict() for u in units],
    ctrl_config=CONTROLE.to_dict(),
    eff_curve_x=info["eff_curve_x"],
    eff_curve_y=info["eff_curve_y"],
    pct_cutin=info["pct_cutin"],
    pct_cutout=info["pct_cutout"],
)[0]

# Painel -> inversor
world.connect(pv_panel_obj, inv_obj, ("P_dc", "P_dc"))

# IDA: tensão da barra, atrasada de um passo para quebrar o ciclo do grafo
world.connect(
    bus_obj, inv_obj,
    ("V1_pu", "V_meas_1"), ("V2_pu", "V_meas_2"), ("V3_pu", "V_meas_3"),
    time_shifted=True,
    initial_data={"V1_pu": 1.0, "V2_pu": 1.0, "V3_pu": 1.0},
)

# VOLTA: injeção de cada unidade para o PVSystem correspondente
for idx, pv_dss_obj in enumerate(lista_pvs, start=1):
    world.connect(inv_obj, pv_dss_obj, (f"P_ac_{idx}", "P_des"), (f"Q_ac_{idx}", "Q_des"))
```

!!! warning "`P_ac_k` é a k-ésima unidade, não a k-ésima fase"
    A ordem é a de `units`. Para grandezas por fase da barra, use
    `P_phase_1..3` / `Q_phase_1..3`.

Atalho para o caso de um único `PVSystem` trifásico, sem montar a lista:

```python
inv_sim.Inverter.create(1, kVA=1000.0, kv=4.16, ctrl_config=CONTROLE.to_dict())
```

---

## 4. Monitorar o controle

Sem as saídas de diagnóstico não há como auditar por que Q vale o que vale num
resultado de 288 passos.

```python
world.connect(
    inv_obj, monitor,
    "P_ac", "Q_ac",
    "V_meas_pu",       # tensão que o controle enxergou
    "der_status",      # Continuous Operation / Trip / Entering Service / ...
    "q_desired_pu",    # reativo pedido pela curva, antes dos limites
    "p_pv_limit_pu",   # limite imposto pelo volt-watt
)
```

Comparar `q_desired_pu` com `Q_ac / kVA` mostra na hora se a curva foi limitada
pela capacidade reativa ou pelo círculo de potência aparente.

---

## Armadilhas

| Sintoma | Causa provável |
|---|---|
| `Q_ac` sempre zero | Tensão dentro da banda morta; ou `reactive_mode` ficou em `NONE` |
| `Q_ac` zero à noite | `q_capability_low_p="REDUCED"` (padrão): sem P, sem capacidade de reativo |
| Inversor desliga no início e no fim do dia | `pct_cutin` do circuito (20% por padrão no OpenDSS) |
| Potência some depois de uma sobretensão | Trip da IEEE 1547; use `trip_enabled=False` em estudo de hospedagem |
| `Q` alternando de sinal a cada passo | Ciclo limite; aumente o `olrt` da curva |
| `OpenDERSetupError` falando de `kv` | Falta a tensão nominal na `InverterUnit` |
| `OpenDERSetupError` falando de `V_meas_k` | A fase da unidade não foi ligada a partir da barra |

## Verificar que a malha fechou

Rode o mesmo circuito duas vezes — com `ControlConfig()` vazio e com o controle
— e compare a tensão da barra. Se o volt-var estiver atuando, o pico de tensão
cai e a energia ativa total permanece praticamente a mesma:

```
                     Q min     Q max    V max   Energia
  sem controle         0.0       0.0   1.0088   4216.6 kWh
      volt-var      -296.7     340.1   1.0024   4216.6 kWh
```

## Cenário de referência

`scenarios/opendss_scenario_123bus_smart_pv.py` liga todas as pontas no IEEE 123
barras.
