# Exportar Topologia para JSON

## Visão geral

O projeto pode exportar a topologia do circuito OpenDSS como um grafo JSON com nós (barras) e arestas (linhas/transformadores).

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

```json
{
  "nodes": {
    "Bus.1.2.3": {
      "id": "Bus.1.2.3",
      "label": "Bus.1.2.3",
      "node_type": "load",
      "metadata": {}
    },
    ...
  },
  "edges": {
    "Line.L1": {
      "id": "Line.L1",
      "source": "Bus.1.2.3",
      "target": "Bus.4.5.6",
      "edge_type": "line",
      "metadata": {}
    },
    ...
  }
}
```

## Classificação de nós

O `topology_builder.py` classifica cada barra:

| Tipo | Descrição |
|---|---|
| `refbus` | Barra de referência (sourcebus) |
| `virtual_bus` | Barra intermediária (nome contém "mid") |
| `regulator_bus` | Barra de regulador (nome termina em "r") |
| `pv` | Barra com PVSystem conectado |
| `load` | Barra com carga |
| `transformer_bus` | Barra conectada a transformador |
| `bus` | Barra genérica |

## Tipos de aresta

| Tipo | Descrição |
|---|---|
| `line` | Linha de distribuição |
| `transformer` | Transformador |

## Módulos envolvidos

| Módulo | Função |
|---|---|
| `opendss/topology_builder.py` | Constrói o grafo a partir do circuito |
| `opendss/graph_model.py` | Dataclasses `NetworkNode`, `NetworkEdge`, `NetworkGraph` |
| `util/topologia.py` | Script standalone para exportação |
