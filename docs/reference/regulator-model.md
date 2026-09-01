# VR_Model — Referência

`simulators.controller.regulator_control.py` — Modelo de regulador de tensão (tap changer).

## Construtor

```python
VR_Model(
    name,
    Ts,
    Td_ctrl=30,
    Td_tap=2,
    Vref=120,
    db=2,
    PT_Ratio=20,
    CT_Primary=700,
    LDC_R=0,
    LDC_X=0,
    tap_max=16,
    tap_min=-16,
    tap_ini=0
)
```

### Parâmetros

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `name` | `str` | — | Nome do regulador |
| `Ts` | `float` | — | Passo de tempo da simulação (segundos) |
| `Td_ctrl` | `float` | 30 | Atraso de controle (segundos) — tempo contínuo de OV/UV antes de agir |
| `Td_tap` | `float` | 2 | Atraso entre taps (segundos) — tempo mínimo entre mudanças |
| `Vref` | `float` | 120 | Tensão de referência no secundário (Volts) |
| `db` | `float` | 2 | Largura da faixa morta (Volts) |
| `PT_Ratio` | `float` | 20 | Razão do potencial transformador (PT) |
| `CT_Primary` | `float` | 700 | Corrente nominal do transformador de corrente (CT, Amperes) |
| `LDC_R` | `float` | 0 | Resistência da compensação de queda de linha (Ohms) |
| `LDC_X` | `float` | 0 | Reatância da compensação de queda de linha (Ohms) |
| `tap_max` | `int` | 16 | Posição máxima do tap |
| `tap_min` | `int` | -16 | Posição mínima do tap |
| `tap_ini` | `int` | 0 | Posição inicial do tap |

## Método principal

### `run(V_meas, I_meas=0)`

Executa um passo de controle de tap.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `V_meas` | `complex` | Tensão complexa medida no bus alvo (Volts) |
| `I_meas` | `complex` | Corrente complexa medida no primário (Amperes) — default: 0 |

**Retorno**: `int` — nova posição do tap.

### Lógica interna

1. **Conversão PT**: `Vsec = |V_meas| / PT_Ratio`
2. **Compensação LDC**: `Vdrop = (I_meas / CT_Primary) × (LDC_R + j×LDC_X)`
3. **Tensão regulada**: `Vreg = |Vsec - Vdrop|`
4. **Histerese**:
   - Se `Vreg > Vref + db/2` → Overvoltage (OV)
   - Se `Vreg < Vref - db/2` → Undervoltage (UV)
   - Caso contrário → Idle
5. **Timer de controle**: espera `Td_ctrl` segundos de OV/UV contínuo
6. **Timer de tap**: espera `Td_tap` segundos desde a última mudança
7. **Ação**:
   - OV → diminui tap (step -1)
   - UV → aumenta tap (step +1)
8. **Clamp**: tap limitado a `[tap_min, tap_max]`

### Exemplo de uso

```python
vr = VR_Model(name="Reg1", Ts=300, Vref=120, db=2, PT_Ratio=20, CT_Primary=700)

# Tensão alta: tap deve diminuir
tap = vr.run(V_meas=2500+0j, I_meas=100+0j)  # Vsec = 125V > 121V → OV

# Tensão normal: tap permanece
tap = vr.run(V_meas=2380+0j, I_meas=0)  # Vsec = 119V → dentro da faixa morta
```
