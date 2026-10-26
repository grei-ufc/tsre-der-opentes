# Exportar Topologia para JSON

## Visão geral

O projeto pode exportar a topologia do circuito OpenDSS como um grafo JSON com
nós (barras), arestas (linhas, chaves e transformadores) e elementos (o que fica
ligado a uma só barra: fonte, cargas, capacitores, PVSystems, Storages e
Generators).

O JSON informa e não classifica. Ele diz o que o modelo compilado declara em
cada barra; decidir se uma barra é "de carga", "de geração" ou "regulada" fica
a critério de quem o consome — a plataforma `tsdq-dataview-opentes`, por
exemplo.

## Quando usar

- Para visualizar a estrutura da rede
- Para análise topológica em ferramentas externas
- Para documentar o circuito simulado

## Como ativar

### Nos cenários

Passe `output_graph_path` ao iniciar o adaptador OpenDSS:

```python
graph_path = str(output_dir / "topologia.json")

grid = world.start("DSS",
    topofile="data/123Bus/run_ieee123_cosim_pv_5min.dss",
    step_size=300,
    output_graph_path=graph_path
).Grid()
```

O cenário `opendss_scenario_123bus_pv_export_json.py` demonstra isso.

### Diretamente via wrapper

```python
from simulators.opendss.opendss_wrapper import OpenDSS

dss = OpenDSS(
    topofile="data/123Bus/run_ieee123_cosim_pv_5min.dss",
    time_step=300,
    start_time="2026-01-01 00:00:00"
)

dss.grafo_tsdq("output/topologia.json")
```

## Estrutura do JSON

Três vetores e a versão do formato. Cada dado aparece num lugar só: nada no
JSON pode ser obtido de dois jeitos diferentes.

```json
{
  "version": 2,
  "nodes": [
    {"name": "646", "kv_base": 2.4017771198288433, "nodes": [2, 3], "x": 400.0, "y": 250.0}
  ],
  "edges": [
    {"type": "Line", "name": "650632", "source": "rg60", "target": "632",
     "phases": 3, "open": false, "regcontrols": []},
    {"type": "Transformer", "name": "reg1", "source": "650", "target": "rg60",
     "phases": 1, "open": false, "regcontrols": [{"name": "reg1", "bus": "rg60"}]}
  ],
  "elements": [
    {"type": "Vsource",  "name": "source", "bus": "sourcebus", "nodes": [1, 2, 3], "phases": 3},
    {"type": "Load",     "name": "646",    "bus": "646",       "nodes": [2, 3],    "phases": 1},
    {"type": "PVSystem", "name": "pv-4",   "bus": "646",       "nodes": [2],       "phases": 1}
  ]
}
```

### Barras (`nodes`)

| Campo | Descrição |
|---|---|
| `name` | Nome da barra, em minúsculas e sem sufixo de nós. É por ele que arestas e elementos a referenciam |
| `kv_base` | Tensão base, em kV |
| `nodes` | Nós (fases) presentes na barra |
| `x`, `y` | Coordenadas do `BusCoords`, ou `null` |

As coordenadas vêm do arquivo referenciado no `.dss` principal do alimentador
(comando `BusCoords`). Uma barra que não consta desse arquivo sai com
`"x": null, "y": null`. O OpenDSS reporta `(0, 0)` para ela, mas esse zero não
é uma posição: desenhá-la ali a poria na origem do diagrama.

### Arestas (`edges`)

| Campo | Descrição |
|---|---|
| `type` | `Line`, `Switch` ou `Transformer` |
| `name` | Nome do elemento no OpenDSS |
| `source`, `target` | Barras dos dois terminais |
| `phases` | Número de fases |
| `open` | Se algum terminal está aberto |
| `regcontrols` | RegControls que comandam o transformador, cada um com a barra que regula (`bus`); vazio nas demais arestas |

Só elementos habilitados viram aresta, e a identidade vem do **nome do
elemento**, não do par de barras: os três reguladores de fase do IEEE 13 ligam
`650` a `rg60` e colapsariam numa aresta só.

No OpenDSS, chave e linha são a mesma classe `Line`; a aresta de uma linha
declarada com `switch=yes` sai com `type: "Switch"`, a mesma divisão que o
adaptador mosaik faz. Uma chave aberta continua no grafo, com `open: true` —
ela existe fisicamente ainda que não conduza, e o consumidor pode desenhá-la
tracejada em vez de fazê-la sumir. Basta um terminal aberto: as chaves
normalmente abertas do IEEE123 são abertas pelo terminal 2.

`regcontrols` é uma lista porque nada impede dois RegControls no mesmo
transformador. A barra regulada é a do enrolamento que o RegControl declara.

### Elementos (`elements`)

| Campo | Descrição |
|---|---|
| `type` | `Vsource`, `Load`, `Capacitor`, `PVSystem`, `Storage` ou `Generator` |
| `name` | Nome do elemento no OpenDSS |
| `bus` | Barra a que está ligado, com a mesma normalização de `nodes[].name` |
| `nodes` | Nós da barra em que está ligado |
| `phases` | Número de fases |

Enquanto a aresta liga duas barras, o elemento pendura-se numa só. Três PVs
monofásicos numa barra trifásica são três elementos, cada um com a sua fase.
`phases` e `nodes` não se repetem: a carga 646 do IEEE 13 é monofásica em
delta, com uma fase e dois nós (`[2, 3]`).

Elementos desabilitados (`enabled=no`) ficam de fora. Os parâmetros nominais
(`pmpp`, `kva`, `kwh_rated`) trafegam pelo `extra_info` das entidades mosaik, e
não por este grafo.

## Identidade e junção com os resultados

Uma barra é identificada pelo `name`; uma aresta ou um elemento, pelo par
`type` + `name`. Os valores de `type` são os nomes dos modelos do adaptador
mosaik, então `f"{type}-{name}"` — e `f"Bus-{name}"` para as barras — é o eid
da entidade, que prefixa as colunas do CSV de resultados:

| No JSON | Eid | Coluna do CSV |
|---|---|---|
| barra `rg60` | `Bus-rg60` | `DSS-0.Bus-rg60-V1_pu` |
| `Line` `650632` | `Line-650632` | `DSS-0.Line-650632-I1_A` |
| `PVSystem` `pv-4` | `PVSystem-pv-4` | `DSS-0.PVSystem-pv-4-P_meas` |
| `regcontrols[].name` `creg1a` | `RegControl-creg1a` | `DSS-0.RegControl-creg1a-tap` |

`DSS-0` é o id do simulador no cenário. `Vsource` e `Capacitor` não têm modelo
no adaptador e, portanto, não têm colunas.

## Classificar é da plataforma

O JSON não traz tipo de barra. Uma barra com carga e PV lista os dois
elementos, e quem consome decide o que ela é. Para obter o que está pendurado em
cada barra, agrupe os elementos pelo campo `bus`:

```python
from collections import defaultdict

tipos_por_barra = defaultdict(set)
for elemento in grafo["elements"]:
    tipos_por_barra[elemento["bus"]].add(elemento["type"])

barras_reguladas = {
    regcontrol["bus"] for aresta in grafo["edges"] for regcontrol in aresta["regcontrols"]
}

# tipos_por_barra["646"] == {"Load", "PVSystem"}: a precedência é sua.
```

A barra alimentadora é a do elemento `Vsource`; a de um transformador, qualquer
extremo de uma aresta `Transformer`.

## Módulos envolvidos

| Módulo | Função |
|---|---|
| `opendss/topology_builder.py` | Constrói o grafo a partir do circuito |
| `opendss/graph_model.py` | Dataclasses `NetworkNode`, `NetworkEdge`, `NetworkElement`, `NetworkGraph` e `serialize_graph` |
| `util/topologia.py` | Exportação avulsa, sem co-simulação. Compila pela fachada `OpenDSS` e grava com o mesmo `grafo_tsdq` do adaptador |
