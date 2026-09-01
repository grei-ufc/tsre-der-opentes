# PVPanelModel — Referência

`simulators.pv.pv_panel_simulator.py` — Modelo de painel fotovoltaico.

## Construtor

```python
PVPanelModel(
    p_mpp,
    irradiance_base,
    pt_curve_x=None,
    pt_curve_y=None
)
```

### Parâmetros

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `p_mpp` | `float` | — | Potência máxima no ponto de operação (kW) |
| `irradiance_base` | `float` | — | Irradiância de referência (W/m²) — tipicamente 1000 |
| `pt_curve_x` | `list[float]` | `None` | Temperaturas de referência (°C) para curva P-T |
| `pt_curve_y` | `list[float]` | `None` | Fatores de correção de potência para cada temperatura |

## Atributos

| Atributo | Tipo | Unidade | Descrição |
|---|---|---|---|
| `irradiance` | `float` | 0–1 | Irradiância normalizada (recebida do CSV) |
| `temperature` | `float` | °C | Temperatura ambiente (recebida do CSV) |
| `P_dc` | `float` | kW | Potência DC calculada (saída) |

## Método principal

### `calculate_step()`

Calcula a potência DC disponível:

```python
pt_factor = np.interp(temperature, pt_curve_x, pt_curve_y)
P_dc = max(0.0, p_mpp * irradiance_base * irradiance * pt_factor)
```

**Componentes**:

1. **Irradiância**: fator multiplicativo normalizado (0 = sem luz, 1 = plena irradiância)
2. **Temperatura**: fator de correção P-T interpolado da curva — geralmente reduz a potência em temperaturas altas
3. **P_dc**: resultado nunca é negativo (`max(0.0, ...)`)

### Exemplo

```python
panel = PVPanelModel(
    p_mpp=5.0,           # 5 kW pico
    irradiance_base=1000, # W/m²
    pt_curve_x=[25, 50],  # °C
    pt_curve_y=[1.0, 0.92]  # fatores
)

panel.irradiance = 0.7   # 70% da irradiância nominal
panel.temperature = 37.5  # °C
panel.calculate_step()
# P_dc ≈ 5.0 × 1000 × 0.7 × 0.94 ≈ 3.29 kW
```

## Integração com mosaik

No adaptador `PVPanelSim`, os atributos `irradiance` e `temperature` são recebidos como entradas mosaik (tipicamente de um CSV Reader) e `P_dc` é enviado como saída para o Inversor.
