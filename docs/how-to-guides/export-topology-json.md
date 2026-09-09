# Exportar Topologia para JSON

## Visão geral

O projeto pode exportar a topologia do circuito OpenDSS como um grafo JSON com nós (barras), arestas (linhas/transformadores) e elementos (PVSystems/Storages conectados às barras).

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

Três vetores no topo. As chaves são descartadas na serialização — a plataforma
indexa pelo campo `id` de cada item.

```json
{
  "nodes": [
    {
      "id": "646",
      "label": "646.2.3",
      "node_type": "pv",
      "voltage_pu": null,
      "metadata": {
        "kv_base": 2.4017771198288433,
        "num_nodes": 2,
        "nodes": [2, 3],
        "x": 400.0,
        "y": 250.0,
        "coord_defined": true,
        "attached": { "pv": ["pv_pv-4"], "storage": [] }
      }
    }
  ],
  "edges": [
    {
      "id": "line_650632",
      "source": "rg60",
      "target": "632",
      "edge_type": "line",
      "metadata": { "name": "650632", "phases": 3, "open": false }
    }
  ],
  "elements": [
    {
      "id": "pv_pv-4",
      "name": "pv-4",
      "element_type": "pv",
      "bus": "646",
      "nodes": [2],
      "phases": 1,
      "metadata": {}
    }
  ]
}
```

`voltage_pu` sai sempre `null`: o grafo é estático e nada escreve tensão nele.

## Classificação de nós

O `topology_builder.py` classifica cada barra pelo que está de fato ligado a
ela, lendo o modelo compilado — não o nome da barra. Uma barra pode satisfazer
mais de um critério, e vence o primeiro da tabela (uma barra com carga e PV é
classificada como `pv`).

| Tipo | Descrição |
|---|---|
| `refbus` | Barra alimentadora, lida do `Vsource` |
| `regulator_bus` | Barra regulada, derivada dos `RegControl` e seus transformadores |
| `pv` | Barra com PVSystem conectado |
| `storage` | Barra com Storage conectado |
| `load` | Barra com carga |
| `transformer_bus` | Barra que é terminal de algum transformador |
| `bus` | Barra genérica |

## Tipos de aresta

Só elementos habilitados viram aresta, e o identificador vem do **nome do
elemento**, não do par de barras: os três reguladores de fase do IEEE 13 ligam
`650` a `rg60` e colapsariam numa aresta só.

| Tipo | Descrição |
|---|---|
| `line` | Linha de distribuição |
| `transformer` | Transformador |

Uma chave aberta continua no grafo, com `metadata.open = true` — ela existe
fisicamente ainda que não conduza, e o consumidor pode desenhá-la tracejada em
vez de fazê-la sumir.

## Elementos conectados

Enquanto a aresta liga duas barras, o elemento pendura-se numa só. O
`node_type` diz apenas que existe geração fotovoltaica na barra; é o vetor
`elements` que diz quantos inversores são, como se chamam e em que fases estão
— três PVs monofásicos numa barra trifásica são indistinguíveis de um único PV
trifásico olhando só o tipo da barra.

| Tipo | Descrição |
|---|---|
| `pv` | PVSystem |
| `storage` | Storage |

O campo `bus` usa a mesma normalização de `node.id` (minúsculas, sem sufixo de
nós), então o join elemento → barra é direto. Para o caminho inverso, cada
barra traz `metadata.attached` com os identificadores agrupados por tipo; a
chave existe em **todas** as barras, com listas vazias quando não há nada, para
que o consumidor itere sem antes checar.

Elementos desabilitados (`enabled=no`) ficam de fora, e `metadata` está
reservado para os parâmetros nominais (`pmpp`, `kva`, `kwh_rated`), que hoje
trafegam pelo `extra_info` das entidades mosaik e não por este grafo.

## Módulos envolvidos

| Módulo | Função |
|---|---|
| `opendss/topology_builder.py` | Constrói o grafo a partir do circuito |
| `opendss/graph_model.py` | Dataclasses `NetworkNode`, `NetworkEdge`, `NetworkElement`, `NetworkGraph` e `serialize_graph` |
| `util/topologia.py` | Script standalone para exportação |
