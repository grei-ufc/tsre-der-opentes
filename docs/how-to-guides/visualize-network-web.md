# Visualizar a Rede no Navegador

## Visão geral

O simulador `simulators.webvis` desenha a rede durante a simulação: as barras
aparecem como nós coloridos pela tensão, as linhas e os transformadores como
arestas, e um clique em qualquer nó abre a linha do tempo daquela grandeza, com
uma curva por fase.

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

Inicie o simulador como qualquer outro:

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

### Ligar ao OpenDSS numa chamada

```python
from simulators.opendss.visualization import attach_webvis

grid = dss_sim.Grid()
attach_webvis(world, dss_sim, grid, webvis)
```

Isso configura o desenho, declara como cada tipo é colorido, conecta as
entidades e fixa as barras nas coordenadas do circuito. Por padrão desenha
barras, PVs e baterias. As cargas ficam de fora porque num alimentador grande
elas encobrem o traçado, e os reguladores porque a representação deles no
desenho ainda não está definida.

O que aparece é escolhido em `show`. Uma lista usa os presets:

```python
attach_webvis(world, dss_sim, grid, webvis, show=["Bus", "Load", "RegControl"])
```

Um dicionário é usado como está, e é assim que se recalibra um tipo:

```python
from simulators.opendss.visualization import PRESETS

attach_webvis(world, dss_sim, grid, webvis, show={
    "Bus": {**PRESETS["Bus"], "min": 0.93, "max": 1.05},
    "PVSystem": PRESETS["PVSystem"],
})
```

| Preset | Grandeza | Escala |
|---|---|---|
| `Bus` | Tensão por fase (`V1_pu`..`V3_pu`) | 0.90 a 1.10 pu |
| `Load` | Potência ativa total (`P_out_mw`) | 0 a 0.1 MW; quase sempre vale recalibrar |
| `PVSystem` | Geração por fase em pu da placa (`P1_pu`..`P3_pu`) | 0 a 1, fixa em qualquer circuito |
| `Storage` | Estado de carga (`SoC`) | 0 a 1 |
| `RegControl` | Posição do tap (`tap`), desenhado como elemento série | −16 a 16 |

Os presets ficam em `simulators/opendss/visualization.py`, e não dentro de
`webvis/`, porque dependem dos nomes de atributo do adaptador OpenDSS. O webvis
continua um fork genérico.

### O que aparece no desenho

Só os tipos declarados são desenhados. Todo o resto da simulação fica de fora
sem precisar ser listado: o `Grid`, os controladores de regulador, painéis,
inversores, leitores de CSV e coletores de dados.

!!! info "Por que isso importa"
    O mosaik acrescenta ao grafo de entidades uma aresta para cada
    `world.connect`, e o webvis desenha a partir desse grafo. Um simulador
    auxiliar que entrasse no desenho apareceria pendurado no alimentador,
    ligado a tudo o que ele lê ou escreve.

Linhas e transformadores entram como `merge_types`: viram **arestas** entre as
barras, em vez de nós. `ignore_names` ainda serve para esconder uma entidade
específica pelo `full_id`, e `ignore_types` continua aceito.

### Elementos série

Um regulador de tensão fica **entre** duas barras, e é desenhado assim: um
losango sobre o trecho do transformador que ele comanda. Os reguladores de um
mesmo banco (três monofásicos, tipicamente) ficam lado a lado, cada um com o
seu tap e a sua linha do tempo.

Quem habilita isso é a chave `"layout": "series"` do tipo, que já vem no preset
do `RegControl`. Ela é genérica: qualquer tipo cujas entidades tenham
exatamente dois vizinhos no grafo pode usá-la. Com vizinhança diferente de
dois, o nó é desenhado como um nó comum e um aviso é impresso.

### O que cada tipo mostra

As chaves de configuração de um tipo, para quem montar o seu próprio:

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
| `layout` | `"series"` para desenhar o nó sobre o trecho entre seus dois vizinhos |

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

    Por isso o preset do `PVSystem` usa `P1_pu`/`P2_pu`/`P3_pu`, a geração em
    pu da placa do próprio inversor, com `min: 0` e `max: 1` fixos em qualquer
    circuito. Nem é preciso variar a potência para o problema aparecer: os seis
    PVs do IEEE13 têm a mesma placa de 1000 kW, mas os trifásicos entregam cerca
    de 333 kW por fase e os monofásicos 1000 kW.

### Sem o `attach_webvis`

Para uma simulação que não use o adaptador OpenDSS, a configuração é feita
direto no webvis:

```python
webvis.set_config(merge_types=["Line"])
webvis.set_etypes({"Bus": {"cls": "pqbus", "attrs": ["V1_pu"], "min": 0.9, "max": 1.1}})
vis_topo = webvis.Topology()
connect_many_to_one(world, buses, vis_topo, "V1_pu")
```

### Desenhar nas coordenadas reais

Com as coordenadas das barras o alimentador sai igual ao diagrama do circuito,
em vez do arranjo que a simulação de forças inventa, e não muda de forma a cada
carregamento. O `attach_webvis` já aplica as coordenadas que o circuito tiver.

Vários alimentadores do IEEE trazem o arquivo de coordenadas mas não o carregam
no `.dss` principal, como o `ieee34Mod1_w_loadcurve.dss`. Para esses, passe o
arquivo ao iniciar o OpenDSS:

```python
dss_sim = world.start(
    "DSS",
    topofile=str(CIRCUITO_DSS),
    step_size=300,
    buscoords=str(DATA_DIR / "IEEE34_BusXY.csv"),
)
```

Barras sem coordenada continuam posicionadas pelo layout de forças.

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

- **Deixar as cargas de fora**, que já é o padrão do `attach_webvis`. No
  IEEE123 são 91 dos 231 nós. Elas pesam mais do que o número sugere: como não
  têm coordenada, cada uma é semeada num anel de 34 a 50 px em volta da sua
  barra. Esse anel é maior que o vão mediano entre barras, então cada carga cai
  dentro do território da barra vizinha.
- **Reduzir o `radius`** dos tipos. Tem um limite: com nó pequeno demais os
  três setores de fase deixam de ser distinguíveis, que é o motivo de o padrão
  ser 9 e não menos.
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
| Um tipo pedido não aparece | O nome em `show` não bate com o tipo mosaik (`PVSystem`, não `PV`). Com lista, um nome sem preset levanta erro; com dicionário, o tipo simplesmente não casa com nenhuma entidade |
| Todos os nós de um tipo cinza | Os nomes em `attrs` não são atributos que o simulador publica |
| Aviso "Nao foi possivel fundir ... numa aresta" | Um elemento de `merge_types` não tem exatamente duas barras, como uma linha com barra ausente. O nó é desenhado como está |
| Aviso "... e um elemento serie mas tem N vizinho(s)" | Um tipo com `layout: "series"` não está entre exatamente duas barras. O nó é desenhado como um nó comum |
| A página não abre | A porta 8000 já está em uso; passe outra em `port=` |
