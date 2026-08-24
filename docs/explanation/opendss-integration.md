# Integração com OpenDSS

## Visão geral

O OpenDSS é o motor de fluxo de potência que simula a rede elétrica. Neste projeto, ele é acessado exclusivamente através de `opendss_wrapper.py`, que encapsula toda a interação com `py-dss-interface`.

!!! warning "Regra importante"
    Nunca chame `py_dss_interface` diretamente dos simuladores. Use sempre `opendss_wrapper.py` como interface.

## Compilação do circuito

Quando o adaptador OpenDSS é iniciado, ele compila um ou mais arquivos `.dss` que definem o circuito:

```python
# Em api_opendss.py → init()
dss = OpenDSS(redirects=["data/123Bus/run_ieee123_cosim_pv_5min.dss"],
              time_step=300,
              start_time="2026-01-01 00:00:00")
```

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

A função `extract_3phase_pq()` normaliza os dados trifásicos do OpenDSS para o formato do mosaik:

```python
# Em _utils.py
extract_3phase_pq(dss_wrapper, name="PVSystem.97",
                  element="PVSystem",
                  attrs=["P_meas", "Q_meas"],
                  sign=-1,  # inverte sinal de geração
                  line_bus=1)
```

Mapeamento de atributos:

| Suffix | Tipo | Descrição |
|---|---|---|
| `_1`, `_2`, `_3` | float | Valores por fase (1, 2, 3) |
| `_A` | float | Magnitude da corrente |
| `_ang` | float | Ângulo da corrente |

Para PVSystem e Storage, o adaptador usa `sign=-1` para inverter o sinal de geração.

## Controle de PVSystem

O adaptador接受 `P_des` e `Q_des` de entidades externas (inversores) e aplica ao OpenDSS:

```python
# Em opendss_pv.py
set_pvsystem_pq(dss, name, p_des, q_des)
```

Internamente:

- Se `P_des > 0.001`: define `PMPP = abs(P_des)`, `Irradiance = 1.0`, `kvar = q_des`
- Se `P_des <= 0.001`: define `Irradiance = 0.0` (desliga o PV)

Isso sobrepõe o controle nativo do OpenDSS, permitindo que o inversor mosaik controle a geração.

## Controle de Storage

Para elementos Storage, o adaptador接受 `P_set`, `Q_set` e `SoC_set`:

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
