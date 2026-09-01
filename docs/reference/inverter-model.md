# Inversor Inteligente — Referência

Modelagem de inversor fotovoltaico com as funções de suporte à rede da IEEE
1547-2018, implementadas pela biblioteca [OpenDER](https://github.com/epri-dev/OpenDER)
da EPRI.

## Camadas

| Módulo | Papel |
|---|---|
| `simulators.inverter.config` | Configuração declarativa e validada (curvas, modo, placa) |
| `simulators.inverter.opender_factory` | Tradução para o `DERCommonFileFormat` do OpenDER |
| `simulators.inverter.smart_inverter` | Modelo de domínio: `P_dc` + tensão → `P_ac`, `Q_ac` |
| `simulators.inverter.smart_inverter_simulator` | Adaptador mosaik (único do projeto) |
| `simulators.inverter.inverter` | Modelo antigo, sem OpenDER — mantido por compatibilidade |

---

## Divisão de responsabilidades com o OpenDER

Cada grandeza tem um dono só. Duplicar a modelagem faz duas políticas
divergentes disputarem o mesmo limite.

| Grandeza | Dono |
|---|---|
| Corte de entrada/saída (`%cutin` / `%cutout`) | `SmartInverterModel` |
| Curva de eficiência DC→AC | `SmartInverterModel` |
| Volt-var, volt-watt, fator de potência, Q constante | OpenDER |
| Círculo de potência aparente e curva Q(P) | OpenDER (`CapabilityPriority`) |
| Trip, entrada em serviço e ride-through | OpenDER |

Por isso `NP_EFFICIENCY` é fixado em 1.0 e `NP_P_MIN_PU` em 0: o rendimento e o
limiar de partida já foram aplicados antes de a potência chegar ao OpenDER.

---

## `ReactiveMode`

Os quatro modos de reativo da IEEE 1547 são **mutuamente exclusivos**. O
OpenDER os resolve por prioridade fixa (`CONST_PF > VOLT_VAR > WATT_VAR >
CONST_Q`), de modo que habilitar dois desliga um deles em silêncio. Aqui é um
enum, para tornar a escolha explícita.

| Valor | Efeito |
|---|---|
| `ReactiveMode.NONE` | Sem controle de reativo; o inversor segue `Q_des` recebido de fora |
| `ReactiveMode.VOLT_VAR` | Volt-var (exige `volt_var=`) |
| `ReactiveMode.CONST_PF` | Fator de potência constante (exige `const_pf=`) |
| `ReactiveMode.CONST_Q` | Potência reativa constante (exige `const_q=`) |

!!! note "Volt-watt é ortogonal"
    Volt-watt é uma função de **potência ativa** e não aparece no enum. Pode
    operar junto com qualquer modo de reativo, ou sozinho.

---

## `VoltVarCurve`

Curva de quatro pontos da Cláusula 5.3.3.

```python
VoltVarCurve(
    v=(0.92, 0.98, 1.02, 1.08),   # pu da tensão nominal
    q=(0.44, 0.0, 0.0, -0.44),    # pu de S_nom; positivo injeta
    olrt=5.0,                     # s
    vref=1.0,
    vref_auto=False,
    vref_time=300.0,
    vref_min=0.95,
    vref_max=1.05,
    strict_ieee1547=False,
)
```

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `v` | `tuple[float, ...]` | `(0.92, 0.98, 1.02, 1.08)` | V1..V4, não decrescentes |
| `q` | `tuple[float, ...]` | `(0.44, 0.0, 0.0, -0.44)` | Q1..Q4, não crescentes |
| `olrt` | `float` | `5.0` | Tempo de resposta em malha aberta |
| `vref` | `float` | `1.0` | Desloca a curva inteira por `vref - 1` |
| `vref_auto` | `bool` | `False` | `vref` acompanha a média móvel da tensão medida |
| `strict_ieee1547` | `bool` | `False` | Transforma os avisos de faixa em erro |

### Presets

```python
VoltVarCurve.ieee1547_cat_b()   # (0.92, 0.98, 1.02, 1.08) / (0.44, 0, 0, -0.44)
VoltVarCurve.ieee1547_cat_a()   # (0.90, 1.00, 1.00, 1.10) / (0.25, 0, 0, -0.25)
```

### Validação

Erro estrutural levanta `ConfigError` na construção do cenário:

- número de pontos diferente de 4;
- `v` decrescente, ou `V1 >= V2` / `V3 >= V4` (segmento inclinado sem largura);
- `q` crescente — um droop invertido realimenta a tensão positivamente e diverge;
- `|q| > 1`, `Q1 < 0` ou `Q4 > 0`.

A banda morta pode ter largura zero (`V2 == V3`), que é o caso da curva padrão
da Categoria A.

Desvios das *faixas* da IEEE 1547 são informados no log, não bloqueados — a menos
que `strict_ieee1547=True`.

### Consultas

```python
curve.q_at(1.05)                  # Q em pu, ignorando OLRT e vref
curve.relaxation_factor(300)      # fração da variação aplicada por passo
```

---

## `VoltWattCurve`

Curva de dois pontos da Cláusula 5.4.2. Produz um **limite** de potência ativa:
o OpenDER calcula `p_desired = min(p_disponível, p_entrada_em_serviço, p_limite_vw, 1)`.

```python
VoltWattCurve(
    v=(1.06, 1.10),   # pu
    p=(1.0, 0.2),     # pu de P_nom
    olrt=10.0,
)
```

Preset: `VoltWattCurve.ieee1547_default()`. Consulta: `curve.p_limit_at(v_pu)`.

---

## `ConstPF` e `ConstQ`

```python
ConstPF(pf=0.95, excitation="ABS")   # excitation: "INJ" injeta, "ABS" absorve
ConstQ(q=-0.3)                        # pu de S_nom
```

---

## `InverterUnit`

Uma unidade física — tipicamente um `PVSystem` do circuito.

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `name` | `str` | — | Nome do elemento no OpenDSS |
| `kva` | `float` | — | Potência aparente nominal (kVA) |
| `kv` | `float \| None` | `None` | Tensão nominal: **linha-linha** se trifásica, **linha-neutro** se monofásica. Obrigatória quando o OpenDER está ativo |
| `phases` | `int` | `3` | 1 ou 3 |
| `node` | `int \| None` | `None` | Nó da barra (1, 2 ou 3); obrigatório se `phases=1` |
| `kw` | `float \| None` | `None` | Potência ativa nominal; `None` usa `kva` |
| `q_inj_pu` | `float` | `0.44` | Capacidade de injeção de reativo, em pu de `kva` |
| `q_abs_pu` | `float` | `0.44` | Capacidade de absorção de reativo, em pu de `kva` |

!!! warning "`kv` importa"
    `kv` é a base de `v_pu` das curvas. Errar essa tensão desloca a curva
    inteira sem produzir nenhum erro visível.

---

## `ControlConfig`

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `reactive_mode` | `ReactiveMode` | `NONE` | Modo de reativo ativo |
| `volt_var` | `VoltVarCurve \| None` | `None` | Curva volt-var |
| `volt_watt` | `VoltWattCurve \| None` | `None` | Curva volt-watt (ortogonal ao modo) |
| `const_pf` | `ConstPF \| None` | `None` | Ajuste de fator de potência |
| `const_q` | `ConstQ \| None` | `None` | Ajuste de reativo constante |
| `trip_enabled` | `bool` | `True` | Proteção de sub/sobretensão e frequência |
| `priority` | `str` | `"REACTIVE"` | `"REACTIVE"` reduz P para caber em S; `"ACTIVE"` reserva a Q mínima da Tabela 7 |
| `v_meas_unbalance` | `str` | `"AVG"` | `"AVG"` (média das fases) ou `"POS"` (sequência positiva) |
| `normal_op_cat` | `str` | `"CAT_B"` | Categoria de capacidade de reativo |
| `abnormal_op_cat` | `str` | `"CAT_II"` | Categoria de ride-through |
| `q_capability_low_p` | `str` | `"REDUCED"` | `"REDUCED"` zera a capacidade abaixo de 0.05 pu de P; `"SAME"` mantém a capacidade plena |
| `frequency_hz` | `float` | `60.0` | Frequência aplicada às entradas |
| `p_min_pu` | `float` | `0.0` | `NP_P_MIN_PU` |
| `efficiency` | `float` | `1.0` | `NP_EFFICIENCY` |
| `extra_der_params` | `dict` | `{}` | Escape para qualquer parâmetro do `DERCommonFileFormat` |

Toda a configuração é serializável: `to_dict()` / `from_dict()` permitem passá-la
como parâmetro de `create()` também para um simulador em container remoto.

### Trip com passo longo

Com passo de 5 min, um único instante acima de `OV1_TRIP_V` (1.1 pu) derruba o
inversor por cerca de 15 minutos — o tempo de `ES_DELAY` mais a rampa de entrada
em serviço. Estudos de capacidade de hospedagem normalmente querem
`trip_enabled=False`.

Desativar o trip afeta apenas a **desconexão**: os modos de ride-through
continuam ativos e ainda bloqueiam a saída em tensões extremas (acima de
~1.2 pu), que é o comportamento fisicamente correto.

### Reativo à noite

Com `q_capability_low_p="REDUCED"` (o padrão do OpenDER), a capacidade de
reativo é zero abaixo de 0.05 pu de potência ativa — ou seja, **o inversor não
faz volt-var à noite**. Para modelar operação noturna, use `"SAME"` *e*
`pct_cutin=0` no adaptador, senão o corte de entrada desliga o inversor antes.

---

## `SmartInverterModel`

```python
SmartInverterModel(
    units,             # Sequence[InverterUnit]
    ctrl=None,         # ControlConfig | dict | None
    eff_curve_x=None,
    eff_curve_y=None,
    pct_cutin=0.0,     # % do kVA total (convenção do OpenDSS)
    pct_cutout=0.0,
    step_size=None,
)
```

Cada unidade recebe seu **próprio objeto OpenDER**, que é como o padrão modela
um inversor: cada um mede a tensão do próprio terminal e responde por conta
própria. Uma unidade trifásica é o caso comum; três monofásicas representam uma
instalação distribuída entre as fases de uma barra.

### Entradas

| Atributo | Tipo | Descrição |
|---|---|---|
| `P_dc` | `float` | Potência DC disponível, total da entidade (kW) |
| `Q_des` | `float` | Reativo desejado (kvar) — usado só com `ReactiveMode.NONE` |
| `V_meas` | `list[float \| None]` | Tensões de fase da barra em pu, índices 0..2 |
| `V_ang` | `list[float]` | Ângulos de fase em graus (só importam com `"POS"`) |
| `f_meas` | `float` | Frequência (Hz) |

### Saídas

| Atributo | Tipo | Descrição |
|---|---|---|
| `P_ac`, `Q_ac` | `float` | Injeção total da entidade (kW, kvar) |
| `unit_p`, `unit_q` | `list[float]` | Injeção por unidade, na ordem de `units` |
| `phase_p`, `phase_q` | `list[float]` | Injeção por fase da barra |
| `is_on` | `bool` | Estado do corte de entrada |
| `der_status` | `str` | Estado operativo mais restritivo entre as unidades |
| `v_meas_pu` | `float` | Tensão que o controle enxergou |
| `q_desired_pu` | `float` | Reativo pedido pela função, antes dos limites |
| `p_avl_pu` | `float` | Potência disponível em pu |
| `p_pv_limit_pu` | `float` | Limite imposto pelo volt-watt |

### Rateio da potência disponível

`P_dc` é a potência do arranjo consolidado da barra. Cada unidade recebe uma
fatia proporcional à própria potência nominal, que é como um arranjo
compartilhado se divide entre os inversores que o atendem.

### Erros propositais

- Tensão ausente no nó de uma unidade levanta `OpenDERSetupError`. Substituir
  por 1.0 em silêncio esconderia um erro de ligação do cenário exatamente na
  grandeza que comanda o controle.
- Duas unidades monofásicas no mesmo nó levantam `ValueError`: somadas, a
  injeção não poderia ser roteada de volta para cada `PVSystem`.

---

## Convergência da malha

A tensão do OpenDSS volta ao inversor atrasada de um passo
(`time_shifted=True`). Se o ganho da curva volt-var superar a sensibilidade
dV/dQ da barra, Q alterna de sinal a cada passo em vez de convergir.

O amortecimento é o próprio filtro de primeira ordem do OpenDER — o equivalente
ao `delta_q=0.2` que o `OpenDER_interface` da EPRI aplica ao iterar dentro do
passo:

| `olrt` | Fator de relaxação | Comportamento |
|---|---|---|
| `< 1.15 × passo` | 1.00 | Filtro curto-circuitado; resposta instantânea |
| `≈ 2 × passo` | ≈ 0.37 | Estável na maioria dos alimentadores |
| `≈ 4 × passo` | ≈ 0.22 | Equivalente ao default da EPRI |

```python
ctrl.relaxation_factor(step_size)   # 1.0 = sem amortecimento
```

!!! warning "Fora da faixa da norma"
    A IEEE 1547 limita `QV_OLRT` a 1–90 s e `PV_OLRT` a 0.5–60 s. Com passo de
    300 s, qualquer valor dentro da norma cai abaixo de `1.15 × passo` e não
    amortece nada. Usar 600 s é uma escolha **numérica** deliberada, não um
    tempo de resposta físico — o OpenDER registra um aviso, emitido uma única
    vez.

O modelo detecta ciclo limite: se Q alternar de sinal por seis passos seguidos
com amplitude relevante, um aviso sugere aumentar o `olrt`.
