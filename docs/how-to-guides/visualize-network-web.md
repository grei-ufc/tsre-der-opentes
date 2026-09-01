# Visualizar a Rede no Navegador

## Visão geral

O simulador `simulators.webvis` desenha a rede durante a simulação: as barras
aparecem como nós coloridos pela tensão, as linhas e os transformadores como
arestas, e um clique em qualquer nó abre a linha do tempo daquela grandeza —
com uma curva por fase.

É um fork do [mosaik-web](https://gitlab.com/mosaik/components/data/mosaik-web)
adaptado para redes trifásicas. Uma barra tem três tensões, não uma; o original
só sabia mostrar um número por nó.

!!! note "Licença"
    O diretório `src/simulators/webvis/` é LGPL-2.1, herdada do mosaik-web —
    a única parte do repositório fora da licença MIT do projeto.

## Rodar um cenário com visualização

```bash
python scenarios/opendss_scenario_34bus_web.py
```

Abra `http://127.0.0.1:8000/` no navegador. O endereço também é impresso no
início da simulação. O desenho aparece no primeiro passo.

Há dois cenários prontos:

| Cenário | O que mostra |
|---|---|
| `opendss_scenario_13bus_web.py` | IEEE13, o caminho mínimo (um atributo por nó) |
| `opendss_scenario_34bus_web.py` | IEEE34 completo: três fases, coordenadas reais e reguladores em malha fechada |

## Usar a interface

- **Botões no canto superior direito** — trocam a grandeza que colore o mapa:
  `A`, `B`, `C` para cada fase, `mín`/`máx`/`méd` para as agregações e `desb`
  para o desequilíbrio (a amplitude entre as fases presentes). A troca é
  instantânea, sem refazer a simulação.
- **Clique num nó** — abre a linha do tempo embaixo, com uma curva por fase e a
  legenda das cores. Clicar de novo fecha.
- **Arraste um nó** — reposiciona. Nós presos às coordenadas do circuito ficam
  onde você os largar.
- **Nó cinza tracejado** — a barra não tem a fase selecionada.

## Configurar no cenário

```python
SIM_CONFIG = {
    "WebVis": {"python": "simulators.webvis:Simulator"},
}

webvis = world.start(
    "WebVis",
    start_date="2025-01-01 00:00:00",
    step_size=300,
    host="127.0.0.1",   # use "0.0.0.0" para expor fora da máquina
    port=8000,
)
```

### O que aparece no desenho

```python
webvis.set_config(
    ignore_types=["Grid", "Topology", "RegController"],
    merge_types=["Line", "Transformer"],
    timeline_hours=24,
)
```

- `ignore_types` — modelos que somem do desenho. O `Grid` é só o contêiner das
  entidades e o `RegController` é o controlador Python, não parte da rede.
  Acrescente `"Load"` para um desenho mais limpo em circuitos grandes.
- `merge_types` — modelos que viram **aresta** em vez de nó: uma linha liga duas
  barras, então é isso que ela deve desenhar.
- `ignore_names` — remove entidades específicas, pelo `full_id`.

!!! warning "Toda conexão vira aresta"
    O mosaik acrescenta ao grafo de entidades uma aresta para cada
    `world.connect`, e não apenas as declaradas em `rel`. Se o coletor de dados
    não estiver em `ignore_types`, ele aparece no meio da rede ligado a tudo que
    monitora.

### O que cada tipo mostra

```python
webvis.set_etypes({
    "Bus": {
        "cls": "pqbus",
        "attrs": ["V1_pu", "V2_pu", "V3_pu"],
        "series": ["A", "B", "C"],
        "aggregate": "min",
        "unit": "V [pu]",
        "default": 1.0,
        "min": 0.90,
        "max": 1.10,
        "spread_max": 0.05,
    },
})
```

| Chave | Efeito |
|---|---|
| `attrs` | Atributos publicados pelo nó, um por fase. Substitui o `attr` do mosaik-web, que continua funcionando para um valor só |
| `series` | Rótulos dos botões e da legenda; por padrão, os próprios nomes dos atributos |
| `aggregate` | Agregação inicial: `first`, `min`, `max`, `mean` ou `spread` |
| `min`, `max` | Extremos da escala de cor: o centro é verde e os extremos vermelhos |
| `spread_max` | Topo da escala do botão `desb` |
| `unit` | Rótulo do eixo Y da linha do tempo |
| `default` | Valor exibido enquanto o nó não recebe dado |
| `cls` | Classe CSS do nó (`pqbus`, `refbus`, `load`, `gen`, `storage`, `special`) |
| `ignore_zero` | Trata `0.0` como "sem leitura". Ligado por padrão quando há mais de um atributo |

!!! tip "Por que `ignore_zero`"
    O OpenDSS reporta `0.0` nas fases que a barra não tem. Sem essa regra, todo
    ramal monofásico apareceria como tensão colapsada — vermelho — justamente a
    cor reservada aos nós em problema. Num atributo único (uma potência, um tap)
    o zero é um valor legítimo, e por isso a regra não se aplica.

Conecte as entidades à topologia como a qualquer outro simulador:

```python
vis_topo = webvis.Topology()
buses = [e for e in grid.children if e.type == "Bus"]
connect_many_to_one(world, buses, vis_topo, "V1_pu", "V2_pu", "V3_pu")
```

### Desenhar nas coordenadas reais

Com as coordenadas das barras o alimentador sai igual ao diagrama do circuito,
em vez do arranjo que a simulação de forças inventa — e não muda de forma a cada
carregamento.

```python
dss_sim = world.start(
    "DSS",
    topofile=str(CIRCUITO_DSS),
    step_size=300,
    buscoords=str(DATA_DIR / "IEEE34_BusXY.csv"),
)

positions = dss_sim.get_bus_positions()
webvis.set_node_positions(
    {e.full_id: positions[e.eid] for e in grid.children if e.eid in positions}
)
```

O parâmetro `buscoords` existe porque vários alimentadores do IEEE trazem o
arquivo de coordenadas mas não o carregam no `.dss` principal — é o caso do
`ieee34Mod1_w_loadcurve.dss`. Barras sem coordenada continuam posicionadas pelo
layout de forças.

## Dentro do Docker

Use `host="0.0.0.0"` e publique a porta:

```yaml
ports:
  - "8000:8000"
```

## Problemas comuns

| Sintoma | Causa |
|---|---|
| A rede aparece em pedaços separados | Faltam entidades ligando as barras. Confira se `merge_types` inclui `"Transformer"`: bancos de reguladores e elevadoras de subestação não são linhas |
| Um nó no meio da rede ligado a tudo | Um simulador não listado em `ignore_types` — em geral o coletor de dados |
| Todos os nós cinza | Nenhum atributo conectado à `Topology`, ou nomes em `attrs` diferentes dos atributos conectados |
| Aviso "Nao foi possivel fundir ... numa aresta" | Um elemento de `merge_types` não tem exatamente duas barras — uma linha com barra ausente, ou um elemento também ligado ao coletor. O nó é desenhado como está |
| A página não abre | A porta 8000 já está em uso; passe outra em `port=` |
