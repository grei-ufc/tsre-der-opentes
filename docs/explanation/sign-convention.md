# Convenção de Sinais

## O problema

O OpenDSS usa a convenção de que **potência gerada é negativa**. Isso significa:

- Um gerador fotovoltaico que injeta 5 kW aparece como `P = -5 kW` no OpenDSS
- Uma carga que consome 3 kW aparece como `P = 3 kW`

Para os demais módulos do projeto (inversor, bateria, controladores), é mais natural trabalhar com valores positivos para geração.

## Solução implementada

A inversão de sinais acontece na **fronteira** do adaptador OpenDSS, usando a função `extract_3phase_pq()` com `sign=-1`:

```python
# Em _utils.py
def extract_3phase_pq(dss_wrapper, name, element, attrs, sign=-1, line_bus=1):
    """
    Extrai P, Q e correntes trifásicas de um elemento.
    O parâmetro 'sign' inverte o sinal: sign=-1 converte geração negativa
    do OpenDSS para valores positivos.
    """
```

Onde é aplicado:

| Elemento | Onde no código | Efeito |
|---|---|---|
| PVSystem | `api_opendss.py` → `get_data()` | P/Q aparecem positivos para geração |
| Storage | `api_opendss.py` → `get_data()` | P/Q aparecem positivos para descarga |

## Fluxo do sinal

```
OpenDSS: P_gen = -5 kW  →  extract_3phase_pq(sign=-1): P_act = 5 kW  →  Inversor: P_ac = 5 kW
```

## Paraelementos de carga

Elementos de carga (Load) não passam por `extract_3phase_pq`. Seus valores são extraídos diretamente:

```python
# Em api_opendss.py → get_data()
"Load", ent["name"], "P_out_mw": dss_wrapper.get_power(name, "Load", total=True)[0] / 1000
```

Loads no OpenDSS já têm sinal positivo (consomem potência), então nenhuma inversão é necessária.

## Linhas e barras

Para linhas (Line) e barras (Bus), os valores são extraídos diretamente sem inversão de sinal:

- **Linhas**: correntes (I1_A, I2_A, I3_A) e potências (P1_w, Q1_var, etc.)
- **Barras**: tensões por fase (V1_pu, V2_pu, V3_pu)

Esses valores não representam geração, então não precisam de inversão.
