# Integração com OpenDSS

## Visão geral

O OpenDSS é o motor de fluxo de potência que simula a rede elétrica. Neste projeto, ele é acessado exclusivamente através de `opendss_wrapper.py`, que encapsula toda a interação com `py-dss-interface`.

!!! warning "Regra importante"
    Nunca chame `py_dss_interface` diretamente dos simuladores. Use sempre `opendss_wrapper.py` como interface.

## Compilação do circuito

Quando o adaptador OpenDSS é iniciado, ele compila o arquivo `.dss` master que define o circuito:

```python
# Em api_opendss.py → init()
dss = OpenDSS(topofile="data/123Bus/run_ieee123_cosim_pv_5min.dss",
              time_step=300,
              start_time="2026-01-01 00:00:00")
```

!!! warning "Um circuito por processo"
    O construtor recebe **um** arquivo. Todas as instâncias de
    `py_dss_interface.DSS()` compartilham o mesmo motor OpenDSS no processo:
    compilar um segundo circuito repõe o primeiro em silêncio, e os dois
    wrappers passam a ler o mesmo estado. Arquivos auxiliares do alimentador
    (cargas, curvas, coordenadas) entram pelos `Redirect` do próprio master.

O wrapper:

1. Instancia `py_dss_interface.DSS()`
2. Compila o master file (que pode redirecionar para outros `.dss`)
3. Detecta quais classes de elementos existem (`Load`, `PVSystem`, `Generator`, `Storage`)
4. Configura o modo de solução (`Snap` ou `Daily`)
5. Define o passo de tempo e a hora inicial

## Auto-descoberta de elementos

O adaptador `api_opendss.py` descobre automaticamente todos os elementos do circuito:

```python
# Detecta PVSystems
pvsystems = dss_wrapper.get_all_pvsystems_info()

# Detecta Regulators
regulators = dss_wrapper.get_all_regulators_info()

# Detecta Storages
storages = dss_wrapper.get_all_storages_info()
```

Para cada elemento detectado, entidades mosaik são criadas automaticamente.

## Resolução do fluxo de potência

A cada passo de simulação, o adaptador:

1. Processa os inputs recebidos (tap, P/Q de PV e Storage)
2. Atualiza perfis de carga (LoadShapes)
3. Chama `dss_wrapper.run_dss()` que resolve o snapshot
4. Extrai os resultados para cada elemento (tensões, correntes, potências)

O comando `run_dss()` executa internamente:

```
Solve          # Se não há Storage
SolveNoControl  # Se há Storage (para controle manual)
```

## Extração de dados trifásicos

O OpenDSS devolve as grandezas de um elemento ordenadas **por condutor**, não
por fase. Um elemento monofásico ligado em `bus.3` reporta um único valor, e
empacotá-lo à esquerda o transformaria na fase 1.

`map_to_phases()`, em `_utils.py`, usa os números de nó do elemento
(`cktelement.node_order`) para pôr cada valor na posição real:

```python
map_to_phases([3, 0], [163.5, 0.0])   # -> [nan, nan, 163.5]
```

O nó `0` é o neutro e é descartado, assim como nós acima de 3.

### Fase ausente é `NaN`, não zero

A fase que o elemento não tem vale `NaN`. A distinção existe porque `0.0` é uma
medição legítima: um inversor ao amanhecer gera zero, e uma barra em curto
franco está mesmo em 0.0 pu. Se os dois casos dividissem o mesmo número, quem
consome os dados teria de escolher entre esconder os dois, perdendo a medição,
ou mostrar os dois, e aí a fase inexistente pareceria uma tensão colapsada.

Duas consequências práticas:

- **Somas usam `sum_phases()`, nunca o `sum` embutido.** Um único `NaN`
  contaminaria o total, e `P_meas` deixaria de existir em todo elemento não
  trifásico.
- **No CSV, a fase ausente é uma célula vazia**, que as ferramentas de análise
  já ignoram ao calcular médias.

### Do condutor ao atributo mosaik

O `attr_map` de cada `ModelSpec` liga o nome do atributo à fonte, ao índice da
fase e a um fator:

```python
attr_map=phase_attr_map(
    p=("P1", "P2", "P3"),
    q=("Q1", "Q2", "Q3"),
    i_mag=("I1_A", "I2_A", "I3_A"),
    p_total=("P_meas",),
    q_total=("Q_meas",),
    sign=-1,     # injeção positiva
)
```

| Nome | Descrição |
|---|---|
| `P1`, `P2`, `P3` | Potência ativa por fase |
| `Q1`, `Q2`, `Q3` | Potência reativa por fase |
| `I1_A`..`I3_A` | Magnitude da corrente por fase |
| `I1_ang`..`I3_ang` | Ângulo da corrente por fase |
| `P_meas`, `Q_meas` | Total somado nas fases presentes |
| `Ploss1_kw`..`Ploss3_kw` | Perda ativa por fase (`Line`, `Transformer`) |
| `Ploss_kw`, `Qloss_kvar` | Perda total do elemento, lida do motor |

O `sign=-1` de PVSystem e Storage inverte a convenção do OpenDSS, em que gerar
é potência negativa. O `scale` é aplicado só aos totais: é assim que `P_out_mw`
da carga sai em MW a partir dos kW do motor.

As perdas dos elementos série entram pelo mesmo mapa, com os parâmetros
`p_loss`, `q_loss`, `p_loss_total` e `q_loss_total`. Nem o `sign` nem o `scale`
se aplicam a elas: perda é dissipação — não é injeção que se inverta —, e o
nome do atributo (`Ploss1_kw`, `Ploss_kw`) já traz a unidade em que ele sai.

As perdas também não são buscadas junto com as potências: são duas leituras a
mais por elemento, que só as linhas e os transformadores expõem, e num
alimentador de 123 barras isso pesaria em toda leitura. O `ElementSnapshot` as
preenche na primeira vez que um atributo de perda é pedido, dentro do mesmo
cache de solução.

Um modelo que precise de algo fora desse mapa declara um *reader* próprio e o
anuncia em `extra_outputs`. É o caso do `SoC` do `Storage` e da geração em pu da
placa do `PVSystem` (`P_pu`, `P1_pu`..`P3_pu`), que divide pela capacidade de
cada inversor e não por um fator constante.

## Controle de PVSystem

O adaptador aceita `P_des` e `Q_des` de entidades externas (inversores) e aplica ao OpenDSS:

```python
# Em opendss_pv.py
set_pvsystem_pq(dss, name, p_des, q_des)
```

Internamente:

- Se `P_des > 0.001`: define `PMPP = abs(P_des)`, `Irradiance = 1.0`, `kvar = q_des`
- Se `P_des <= 0.001`: define `Irradiance = 0.0` (desliga o PV)

Isso sobrepõe o controle nativo do OpenDSS, permitindo que o inversor mosaik controle a geração.

## Controle de Storage

Para elementos Storage, o adaptador aceita `P_set`, `Q_set` e `SoC_set`:

- `P_set > 0`: descarga (modo gerador)
- `P_set < 0`: carga (modo motor)
- O wrapper calcula automaticamente o estado (`Charging`, `Discharging`, `Idling`)

## Controle de Regulador

O adaptador aceita `tap` (posição inteira de -16 a +16) e o aplica ao RegControl do OpenDSS:

```python
dss_wrapper.set_tap(name, tap, max_tap=16)
```

## Topologia do circuito

O módulo `topology_builder.py` constrói um grafo topológico a partir do circuito compilado:

```python
from simulators.opendss.topology_builder import build_graph

graph = build_graph(dss_wrapper)
# graph.nodes: dict[str, NetworkNode]
# graph.edges: dict[str, NetworkEdge]
```

Cada nó é classificado como: `refbus`, `virtual_bus`, `regulator_bus`, `pv`, `load`, `transformer_bus` ou `bus`.

A exportação para JSON pode ser ativada passando `output_graph_path` ao iniciar o adaptador.
