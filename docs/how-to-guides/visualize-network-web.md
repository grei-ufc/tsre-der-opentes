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

Há quatro cenários prontos:

| Cenário | O que mostra |
|---|---|
| `opendss_scenario_13bus_web.py` | IEEE13, o caminho mínimo: só as barras, para verificar que a visualização sobe |
| `opendss_scenario_34bus_web.py` | IEEE34 completo: três fases, coordenadas reais e reguladores em malha fechada |
| `opendss_scenario_123bus_web.py` | IEEE123: 132 barras, 91 cargas e 7 reguladores |
| `opendss_scenario_123bus_pv_web.py` | IEEE123 com geração fotovoltaica em malha fechada (painel + inversor) |

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
| `radius` | Raio do nó em pixels; por padrão 9. É como as cargas ficam menores que as barras |

!!! info "Fase ausente e zero medido são coisas diferentes"
    A fase que o elemento não tem chega como `NaN` e é pintada de cinza. O zero
    medido chega como `0.0` e é tratado como qualquer outro valor: um inversor
    ao amanhecer aparece no gráfico desde o primeiro passo, no fundo da escala,
    e não só quando a geração começa a subir.

    Não há nada a configurar. A distinção vem do adaptador.

!!! warning "A escala é do tipo, não da entidade"
    `min`/`max` valem para **todos** os elementos daquele tipo. Num alimentador
    com inversores de tamanhos diferentes, uma escala em kW deixa o pequeno
    sempre verde e satura o grande.

    Por isso o `PVSystem` deve ser desenhado com `P1_pu`/`P2_pu`/`P3_pu`, a
    geração em pu da placa do próprio inversor, com `min: 0` e `max: 1` fixos em
    qualquer circuito. Nem é preciso variar a potência para o problema aparecer:
    os seis PVs do IEEE13 têm a mesma placa de 1000 kW, mas os trifásicos
    entregam cerca de 333 kW por fase e os monofásicos 1000 kW.

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

### Alimentadores grandes ficam apertados

O desenho é ajustado **uma vez** ao tamanho da janela, e não há zoom nem
deslocamento. Quanto mais barras, menos espaço para cada uma:

| | IEEE13 | IEEE123 |
|---|---|---|
| Barras desenhadas | 16 | 130 |
| Vão mediano entre barras vizinhas | 166 px | 48 px |
| Diâmetro do nó | 21 px | 21 px |
| Pares de barras que se sobrepõem | 0 | 8 |

Em ordem de efeito:

- **Esconder as cargas**: `ignore_types=[..., "Load"]`. No IEEE123 são 91 dos
  231 nós. Elas pesam mais do que o número sugere: como não têm coordenada,
  cada uma é semeada num anel de 34 a 50 px em volta da sua barra. Esse anel é
  maior que o vão mediano entre barras, então cada carga cai dentro do
  território da barra vizinha.
- **Reduzir o `radius`** dos tipos no `set_etypes`. Tem um limite: com nó
  pequeno demais os três setores de fase deixam de ser distinguíveis, que é o
  motivo de o padrão ser 9 e não menos.
- **Maximizar a janela** antes de a simulação começar; o ajuste é feito no
  primeiro passo.

!!! note "Escalar as coordenadas do circuito não adianta"
    Multiplicar todas as coordenadas por uma constante não muda nada. O caminho
    normaliza pela extensão duas vezes, em `normalize_positions` (Python) e ao
    encaixar no canvas (JavaScript), então qualquer fator é exatamente
    cancelado. O que limita é o número de pixels da janela, não a unidade do
    `BusCoords`.

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
