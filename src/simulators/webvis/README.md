# webvis — visualização web da co-simulação

Fork do [mosaik-web](https://gitlab.com/mosaik/components/data/mosaik-web)
0.5.0, commit `28c1ca1` (2026-08-25), adaptado para as redes trifásicas
modeladas no OpenDSS.

## Licença

O código original é **LGPL-2.1** (`LICENSE.txt`) e assim permanece — este
diretório é a única parte do repositório que não está sob a licença MIT do
projeto. O `d3.min.js` embutido é ISC (`LICENSE-THIRD-PARTY`). Autores
originais: Stefan Scherfke e Gunnar Jeddeloh (OFFIS).

## Uso

```python
SIM_CONFIG = {
    "WebVis": {"python": "simulators.webvis:Simulator"},
}

webvis = world.start("WebVis", start_date="2025-01-01 00:00:00", step_size=300)
webvis.set_config(ignore_types=["Grid", "Topology", "Monitor"], merge_types=["Line"])
webvis.set_etypes(
    {
        "Bus": {
            "cls": "pqbus",
            "attr": "V1_pu",
            "unit": "V [pu]",
            "default": 1.0,
            "min": 0.93,
            "max": 1.05,
        }
    }
)
topo = webvis.Topology()
connect_many_to_one(world, buses, topo, "V1_pu")
```

A visualização fica em `http://127.0.0.1:8000/` (o endereço é impresso no
início da simulação). Use `host="0.0.0.0"` para expô-la fora da máquina.

## Mudanças em relação ao upstream

Todas marcadas com `[OpenTES]` no código.

### Fase 0 — base

- **Roda in-process.** O original só obtinha o endereço do servidor via
  `configure()`, chamado apenas no modo `cmd` (subprocesso). Agora `init()`
  aceita `host`/`port`, então o simulador funciona com
  `{"python": "simulators.webvis:Simulator"}` — sem depender de um console
  script instalado no PATH, o que também simplifica o uso no Windows.
- **Sem dependência de `arrow`.** Era usada em uma única linha; a biblioteca
  padrão produz o mesmo ISO 8601 com fuso local.
- **`step()` sem entradas não quebra.** O original fazia `inputs[self.eid]` e
  levantava `KeyError` no passo em que nenhum simulador conectado tivesse dado
  novo.
- **Fusão de nós tolerante a falhas.** O original abortava com
  `AssertionError` se um nó de `merge_types` não tivesse exatamente dois
  vizinhos — comum numa rede real (linha com barra ausente, elemento também
  ligado ao coletor). Agora o nó é mantido e o caso é avisado.
- **Configuração por instância.** `set_config` escrevia no dicionário de
  módulo `default_config`, vazando a configuração entre simuladores criados no
  mesmo processo.
- **Encerramento limpo** (`finalize`) e tarefa de difusão referenciada, para
  que o coletor de lixo não a recolha no meio da simulação.
- **Estáticos confinados** ao diretório `html/` (o servidor montava o caminho
  do arquivo sem validar `..`).

### Trifásico — backend

- **Vários atributos por nó.** `set_etypes` aceita `attrs` (uma entrada por
  fase) além do `attr` único do original. Cada nó passa a levar `values` — um
  valor por atributo — junto do `value` agregado, e é isso que permite ao
  navegador alternar entre as fases sem refazer a simulação.
- **Agregação configurável** (`aggregate`): `first`, `min`, `max`, `mean` ou
  `spread`.
- **`ignore_zero`.** O OpenDSS reporta `0.0` na fase que a barra não tem; sem
  descartá-la, todo ramal monofásico apareceria como tensão colapsada. Ligado
  por padrão só quando há mais de um atributo, porque num atributo único (uma
  potência, um tap) o zero é um valor legítimo.
- **`set_node_positions`.** Coordenadas reais das barras, normalizadas para o
  quadrado unitário **sem distorcer a proporção** — normalizar cada eixo pela
  sua própria extensão esticaria um alimentador longo e estreito até virar um
  quadrado.

### Trifásico — frontend

- **Seletor de série** (`A`/`B`/`C`/`mín`/`máx`/`méd`/`desb`) no canto superior
  direito, repintando o mapa de calor sem esperar novos dados. Não aparece
  quando há um atributo só.
- **Fase ausente em cinza** (classe `.absent`), em vez da cor do extremo
  inferior da escala.
- **Linha do tempo com uma curva por fase**, com legenda e interrupção da linha
  onde a fase não existe.
- **Nós fixados nas coordenadas do circuito**, com os demais ainda a cargo da
  simulação de forças. Um nó fixado permanece onde o usuário o arrastar — sua
  posição é informação do circuito, não do desenho.
- **Escala própria para o desequilíbrio** (`spread_max`): zero é o ideal, e não
  o extremo inferior de uma escala de tensão.
