# OpenDSSBattery — Referência

`simulators.battery.battery_model.py` — Modelo de armazenamento de energia (bateria).

## Construtor

```python
OpenDSSBattery(
    name,
    kw_rated,
    kwh_rated,
    kwh_stored,
    pct_reserve=20.0,
    pct_eff_charge=90.0,
    pct_eff_discharge=90.0,
    pct_idling_kw=2.0,
    kva_rated=None,
    max_charge_kw=None,
    max_discharge_kw=None,
    eff_curve_x=None,
    eff_curve_y=None
)
```

### Parâmetros

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `name` | `str` | — | Nome da bateria |
| `kw_rated` | `float` | — | Potência nominal de descarga (kW) |
| `kwh_rated` | `float` | — | Capacidade total (kWh) |
| `kwh_stored` | `float` | — | Energia inicial armazenada (kWh) |
| `pct_reserve` | `float` | 20.0 | Reserva mínima (%) — não descarga abaixo disso |
| `pct_eff_charge` | `float` | 90.0 | Eficiência de carga (%) |
| `pct_eff_discharge` | `float` | 90.0 | Eficiência de descarga (%) |
| `pct_idling_kw` | `float` | 2.0 | Consumo em idle (% da nominal) |
| `kva_rated` | `float \| None` | `None` | Potência aparente nominal (kVA). Se None, usa `kw_rated` |
| `max_charge_kw` | `float \| None` | `None` | Limite máximo de carga (kW). Se None, usa `kw_rated` |
| `max_discharge_kw` | `float \| None` | `None` | Limite máximo de descarga (kW). Se None, usa `kw_rated` |
| `eff_curve_x` | `list[float]` | `None` | Pontos X da curva de eficiência do inversor (%) |
| `eff_curve_y` | `list[float]` | `None` | Pontos Y da curva de eficiência (0–1) |

## Estados

| Constante | Valor | Descrição |
|---|---|---|
| `STATE_IDLING` | 0 | Inativo |
| `STATE_DISCHARGING` | 1 | Descarregando (injetando potência) |
| `STATE_CHARGING` | -1 | Carregando (absorvendo potência) |

## Método principal

### `calculate_step(p_request, q_request, dt_seconds)`

Executa um passo completo de simulação da bateria.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `p_request` | `float` | Potência ativa solicitada (kW). Positivo = descarga, Negativo = carga |
| `q_request` | `float` | Potência reativa solicitada (kvar) |
| `dt_seconds` | `float` | Duração do passo em segundos |

**Retorno**: `dict` com:

| Chave | Tipo | Descrição |
|---|---|---|
| `p_kw` | `float` | Potência ativa efetiva (kW) |
| `q_kvar` | `float` | Potência reativa efetiva (kvar) |
| `soc_pct` | `float` | Estado de carga (0–100%) |
| `state` | `int` | Estado (0=idling, 1=descarga, -1=carga) |

### Lógica interna

1. **Clamp de potência**: limita `p_request` dentro de `[-max_charge_kw, max_discharge_kw]`
2. **Círculo kVA**: limita Q para manter `sqrt(P² + Q²) <= kva_rated` (prioridade P)
3. **Determinação de estado**: compara `p_request` com threshold de 0.001
4. **Energia DC**: calcula `delta_energy = P × dt / 3600` aplicando eficiência
5. **Limites de SoC**:
   - Se descarregando: `kwh_stored >= kwh_rated × (pct_reserve / 100)`
   - Se carregando: `kwh_stored <= kwh_rated`
6. **Aplica delta**: `kwh_stored += delta_energy`

## Convencional de sinais

- `p_request > 0`: descarga (injeta potência na rede)
- `p_request < 0`: carga (absorve potência da rede)
- Compatível com a convenção de geração do OpenDSS (positivo = injetando)

## Eficiência

A eficiência do inversor (conversão DC→AC) é calculada por interpolação linear da curva fornecida:

```python
battery.get_inverter_efficiency(p_kw)
```

Eficiência mínima garantida: 0.1 (10%).

A eficiência química (carga/descarga da bateria) é aplicada separadamente via `pct_eff_charge` e `pct_eff_discharge`.
