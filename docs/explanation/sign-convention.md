# Convenção de Sinais

## O problema

O OpenDSS usa a convenção de que **potência gerada é negativa**. Isso significa:

- Um gerador fotovoltaico que injeta 5 kW aparece como `P = -5 kW` no OpenDSS
- Uma carga que consome 3 kW aparece como `P = 3 kW`

Para os demais módulos do projeto (inversor, bateria, controladores), é mais natural trabalhar com valores positivos para geração.

## Solução implementada

A inversão de sinais acontece na **fronteira** do adaptador OpenDSS, e é
declarada no registry de modelos (`element_specs.py`): o `phase_attr_map` de
cada modelo recebe um `sign`, aplicado às potências por fase e aos totais.

```python
# Em element_specs.py → MODEL_SPECS["Generator"] (igual em PVSystem e Storage)
attr_map=phase_attr_map(
    p=("P1", "P2", "P3"),
    q=("Q1", "Q2", "Q3"),
    p_total=("P_meas",),
    q_total=("Q_meas",),
    sign=-1,     # injeção na rede é positiva para o cenário
)
```

Onde é aplicado:

| Elemento | Atributos | Efeito |
|---|---|---|
| PVSystem | `P1..P3`, `Q1..Q3`, `P_meas`, `Q_meas`, `P_pu` | P/Q aparecem positivos para geração |
| Storage | `P1..P3`, `Q1..Q3`, `P_act`, `Q_act` | P/Q aparecem positivos para descarga |
| Generator | `P1..P3`, `Q1..Q3`, `P_meas`, `Q_meas` | P/Q aparecem positivos para geração |
| Circuit | `P_mw`, `Q_mvar` | O total visto pela subestação sai positivo quando o alimentador consome |

As correntes são magnitudes e não recebem sinal.

## Fluxo do sinal

```
OpenDSS: P_gen = -5 kW  →  registry (sign=-1): P_meas = 5 kW  →  cenário: P_meas = 5 kW
```

## Para elementos de carga

Elementos de carga (Load) mantêm a convenção nativa, `sign=1`.

O atributo `P_out_mw` da carga é declarado no registry, e o fator de escala faz a
conversão de kW para MW:

```python
# Em element_specs.py → MODEL_SPECS["Load"]
attr_map=phase_attr_map(
    p_total=("P_out_mw",),
    q_total=("Q_out_mvar",),
    scale=1 / 1000.0,
)
```

Loads no OpenDSS já têm sinal positivo (consomem potência), então nenhuma inversão é necessária — o `sign` fica no seu padrão, `1`.

## Linhas e barras

Para linhas (Line) e barras (Bus), os valores são extraídos diretamente sem inversão de sinal:

- **Linhas**: correntes (I1_A, I2_A, I3_A) e potências (P1_w, Q1_var, etc.)
- **Barras**: tensões por fase (V1_pu, V2_pu, V3_pu)

Esses valores não representam geração, então não precisam de inversão.

## Perdas

As perdas de linhas e transformadores (`Ploss_kw`, `Qloss_kvar` e as parcelas
por fase) também saem sem inversão: perda é dissipação, e o total é positivo
qualquer que seja o sentido do fluxo — inclusive quando a geração distribuída
inverte o fluxo do trecho.

A exceção aparente é a parcela de **uma** fase, que pode sair negativa em
linhas com acoplamento mútuo forte e correntes desequilibradas: parte da perda
é atribuída à fase vizinha. Isso é repartição, não sinal — o total continua
positivo.
