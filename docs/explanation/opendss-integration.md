# Integração com OpenDSS

## Visão geral

O OpenDSS é o motor de fluxo de potência que simula a rede elétrica. Neste projeto, ele é acessado exclusivamente através de `opendss_wrapper.py`, que encapsula toda a interação com `py-dss-interface`.

!!! warning "Regra importante"
    Nunca chame `py_dss_interface` diretamente dos simuladores. Use sempre `opendss_wrapper.py` como interface.

    O wrapper segue o padrão de projeto **Fachada** (*Facade*, de *Design
    Patterns*, Gamma et al., 1994): uma interface única e simples na frente de
    um subsistema complexo. Os módulos por dispositivo (`opendss_pv`,
    `opendss_bus`, `opendss_loadshape`...) recebem o motor, mas quem os chama é
    a própria fachada: ficam atrás dela. O adaptador e o registry não podem
    acessar `dss_wrapper.dss` — o teste
    `tests/test_wrapper_layers.py::TestFacadeIsNotBypassed` garante isso.

## Compilação do circuito

Quando o adaptador OpenDSS é iniciado, ele compila o arquivo `.dss` master que define o circuito:

```python
# Em api_opendss.py → init()
dss = OpenDSS(topofile="data/123Bus/run_ieee123_cosim_pv_5min.dss",
              time_step=datetime.timedelta(seconds=300),
              start_time=datetime.datetime(2025, 1, 1))
```

!!! warning "Um circuito por processo"
    O construtor recebe **um** arquivo. Todas as instâncias de
    `py_dss_interface.DSS()` compartilham o mesmo motor OpenDSS no processo:
    compilar um segundo circuito repõe o primeiro em silêncio, e os dois
    wrappers passam a ler o mesmo estado. Arquivos auxiliares do alimentador
    (cargas, curvas, coordenadas) entram pelos `Redirect` do próprio master.

O wrapper:

1. Instancia `py_dss_interface.DSS()`, capturando antes o diretório de
   trabalho — o construtor da biblioteca o muda para o `DataPath` do motor
2. Confere se o arquivo existe e compila o master (que pode redirecionar para
   outros `.dss`), com as **caixas de diálogo do OpenDSS ligadas só durante a
   compilação**: o `Redirect` informa apenas o erro da última linha do arquivo,
   e um erro no meio dele só aparece pela caixa
3. Prepara o circuito, a cada compilação e antes da primeira solução:
    - reaplica `tolerance` e `max_iterations`, que o `Compile` repõe no padrão;
    - troca a conversão DC/AC de todo PVSystem por uma ideal (curvas de
      eficiência e de temperatura planas, `%cutin`/`%cutout` quase nulos);
    - abre a faixa `Vminpu`/`Vmaxpu` de todo Generator;
    - trava o controle automático de todo RegControl (`MaxTapChange=0`), sem
      mexer na posição do tap

    O que o `.dss` declara (curvas, faixa, tap) continua disponível no
    `extra_info` das entidades. Ver [Decisões de Projeto](design-decisions.md).
4. Põe o motor em modo *snapshot* e ajusta a hora inicial
5. Resolve uma primeira vez e define o passo de tempo

## Auto-descoberta de elementos

O adaptador `api_opendss.py` descobre automaticamente todos os elementos do
circuito, sempre pela fachada (`get_all_buses_info()`,
`get_all_pvsystems_info()`, `get_all_generators_info()`,
`get_all_regulators_info()`, ...). Para cada um cria uma entidade mosaik filha
do `Grid`, nesta ordem: `Circuit`, `Bus`, `Load`, `Line`/`Switch`,
`Transformer`, `RegControl`, `Storage`, `PVSystem` e `Generator`.

Cargas e geradores que declaram curva (`daily`/`yearly`) têm a curva lida uma
vez, por `get_loadshape()`, para o laço de curvas do passo.

## Resolução do fluxo de potência

A cada passo de simulação (`step`), o adaptador:

1. **Aplica as entradas** (`_apply_inputs`): para cada atributo recebido, o
   agregador declarado no registry reduz os valores dos simuladores conectados
   a um só (soma, para potências; valor único, para tap, chave e
   multiplicadores), confere a faixa declarada e entrega ao escritor do modelo,
   que traduz em chamadas à fachada (`set_power`, `set_pvsystem_pq`,
   `set_tap`, ...). Cada escrita esvazia o cache da solução e edita o elemento
   no motor — sem resolver nada ainda.
2. **Reproduz as curvas do `.dss`**: em snapshot o motor ignora as curvas
   `daily`/`yearly`, então o adaptador aplica o ponto do instante a cargas e
   geradores — exceto os que receberam qualquer entrada externa no passo, que
   tem precedência.
3. **Resolve uma única vez**, com `run_dss()`: esvazia o cache, chama
   `solve()`, roda o `UpdateStorage` (que integra a energia das baterias no
   passo) e confere a convergência.

Os resultados não são lidos no `step`: o mosaik os pede depois, no
`get_data()`, e o leitor de cada modelo os serve do cache da solução, indo ao
motor numa leitura em bloco só na primeira vez. Ler nunca resolve o circuito.

!!! note "Uma solução por passo — do lado do adaptador"
    Dentro do `solve()`, o fluxo é iterativo, e o laço de controle do motor
    pode repeti-lo se algum controle agir. Os reguladores estão travados, mas
    outros controles declarados no `.dss` (como `CapControl`) continuam
    automáticos.

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
| `Loading1_pct`..`Loading3_pct` | Corrente em % da ampacidade da linha (fora do `attr_map`; ver adiante) |

O `sign=-1` de PVSystem, Storage e Generator inverte a convenção do OpenDSS,
em que gerar é potência negativa. O `scale` é aplicado só aos totais: é assim que `P_out_mw`
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

### Normalizar pela placa do próprio elemento

O carregamento das linhas (`Loading1_pct`..`Loading3_pct`) segue esse mesmo
caminho, e pelo mesmo motivo: o fator varia de elemento para elemento, então não
cabe num mapa de constantes. `read_line` divide a corrente de cada fase pela
ampacidade daquela linha, como `read_pvsystem` divide a geração pela placa
daquele inversor.

O denominador é lido uma vez, na criação das entidades, e guardado no simulador
(`line_ampacity`, espelhando `pv_nameplate`). É dado do circuito compilado, não
da solução: relê-lo a cada passo seria uma ida ao motor por linha para devolver
sempre o mesmo número. As correntes já estão no `ElementSnapshot`, então o
carregamento não custa nenhuma leitura extra.

A diferença em relação ao PVSystem é o motivo de a placa ficar em cache. No PV,
o `pmpp` do elemento é reescrito a cada passo pelo setpoint, e reler o motor
daria a geração comandada no lugar da capacidade. A ampacidade ninguém reescreve
— o cache ali é por custo, não por correção.

## Chave: uma `Line` no motor, um modelo próprio no mosaik

O OpenDSS não tem classe de chave: é uma `Line` com `switch=yes`, de impedância
desprezível e comprimento quase nulo. Misturada às demais, ela distorce qualquer
estatística de linha — entra na média de carregamento com um valor que não
significa nada, e no total de comprimento com um milésimo de quilômetro.

Por isso `_add_lines` lê a propriedade e roteia entre dois modelos, `Line` e
`Switch`, ambos com `dss_class="Line"`: a separação é do mosaik, não do motor. As
duas specs compartilham o `LINE_ATTR_MAP`, porque eletricamente a chave é uma
linha e lê as mesmas grandezas.

O `topology_builder` não participa dessa separação — fala direto com `dss.lines`,
e para o grafo a chave é uma aresta como qualquer elemento série, marcada com
`metadata["open"]`.

### O estado é do elemento, não do terminal

Uma chave está aberta ou fechada; o OpenDSS guarda um estado por terminal. A
diferença não é acadêmica: o IEEE123 abre as suas chaves normalmente abertas com
`open Line.Sw7 terminal=2`, e uma leitura do terminal 1 as daria por fechadas —
com a corrente em zero, o que pareceria uma chave fechada sem carga.

`get_is_open` percorre os terminais; `set_is_open` abre pelo terminal 2 e fecha
os dois. Fechar um só deixaria aberta a chave que outro caminho tivesse aberto
pelo outro lado, e o comando falharia sem nada acusando.

## Controle de PVSystem

O adaptador aceita `P_des` e `Q_des` em kW/kvar, de um simulador de inversor,
ou `P_mult` de 0 a 1 sobre o `Pmpp` da placa, de uma curva (com a reativa vinda
do `pf` declarado, `Q = P·tan(acos(pf))`). Os dois caminhos são exclusivos.
Ambos chegam ao OpenDSS por:

```python
# Em opendss_pv.py
set_pvsystem_pq(dss, name, p_des, q_des)
```

Internamente:

- Se `P_des > 0.001`: define `PMPP = abs(P_des)`, `Irradiance = 1.0`, `kvar = q_des`
- Se `P_des <= 0.001`: define `Irradiance = 0.0` (desliga o PV)

O PVSystem não tem propriedade `kW`: a saída é calculada de `Pmpp` e
irradiância. Por isso a escrita de potência genérica, `set_power`, recusa
PVSystem e aponta para `set_pvsystem_pq`.

Para que o `PMPP` escrito seja a potência injetada, o carregamento do circuito
troca as curvas de eficiência (`EffCurve`) e de derating térmico (`P-TCurve`) de
todo PVSystem por curvas planas de fator 1, e zera na prática o `%cutin` e o
`%cutout`. As curvas declaradas continuam disponíveis em `extra_info`, para o
inversor aplicar essas perdas do lado dele.

## Controle de Generator

O adaptador aceita `P_set`/`Q_set` em kW/kvar, ou `P_mult` de 0 a 1 sobre o `kW`
nominal, e aplica ao OpenDSS com `edit Generator.<nome> kW=... kvar=...`:

- `P_mult`: ativa e reativa escaladas pelo mesmo fator, preservando o `pf`
  declarado.
- `P_set` sem `Q_set`: a reativa acompanha pelo `pf` declarado, calculada da
  placa guardada na criação.
- `Q_set` sozinho: ajusta só a reativa.

Um gerador com curva `daily`/`yearly` no `.dss` a segue no `step`, pelo mesmo
laço que move as cargas; uma entrada externa no passo tem precedência. Ao
carregar o circuito, a faixa `Vminpu`/`Vmaxpu` é aberta, para que a potência
comandada seja a entregue mesmo com a tensão fora de 0,9–1,1 pu.

## Controle de Storage

Para elementos Storage, o adaptador aceita `P_set`/`Q_set` em kW/kvar, ou
`P_mult` de −1 a 1 sobre a potência nominal (negativo carrega), além de
`SoC_set`:

- `P_set > 0`: descarga (modo gerador)
- `P_set < 0`: carga (modo motor)
- O wrapper calcula automaticamente o estado (`Charging`, `Discharging`, `Idling`)
- `SoC_set` força o estado de carga, para o padrão em que um modelo de bateria
  externo é dono da física e o elemento do OpenDSS só o espelha

!!! warning "Limitações conhecidas"
    - Um `Q_set` sem `P_set` no mesmo passo é **descartado sem aviso**: a
      escrita da bateria só acontece quando há potência ativa.
    - O `setup_done()` resolve o circuito antes do primeiro passo, e o
      `UpdateStorage` dessa solução integra um passo de energia. Uma bateria
      declarada carregando ou descarregando no `.dss` começa o estudo com um
      passo a menos (ou a mais) de energia. Baterias declaradas `IDLING`, ou
      comandadas pelo cenário, não são afetadas.

## Controle de Regulador

O adaptador aceita `tap` (posição inteira de -16 a +16) e o aplica ao RegControl do OpenDSS:

```python
dss_wrapper.set_tap(name, tap, max_tap=16)
```

O controle automático dos reguladores do OpenDSS é **travado no carregamento**
(`MaxTapChange=0`): os taps ficam na posição que o `.dss` declara durante todo
o estudo e só mudam por um controlador externo, e o tap comandado permanece até
o próximo comando. A posição declarada aparece em `extra_info["tap_ini"]` — é
com ela que o cenário deve iniciar o controlador externo, que envia a própria
posição a cada passo. Ver [Configurar Regulador](../how-to-guides/configure-regulator.md).

## Topologia do circuito

O módulo `topology_builder.py` constrói um grafo topológico a partir do circuito compilado:

```python
# Pela fachada: monta o grafo, grava o JSON e devolve o grafo
graph = dss_wrapper.grafo_tsdq("output/topologia.json")
# graph.nodes: dict[str, NetworkNode]
# graph.edges: dict[str, NetworkEdge]
# graph.elements: dict[str, NetworkElement]
```

Cada nó é classificado, nesta ordem de precedência, como: `refbus`,
`regulator_bus`, `pv`, `storage`, `load`, `transformer_bus` ou `bus`. Os
elementos ligados a uma só barra — PVSystems, Storages e Generators — entram no
vetor `elements` e no índice `attached` de cada barra; o gerador não muda o tipo
da barra.

A exportação para JSON pode ser ativada passando `output_graph_path` ao iniciar
o adaptador, ou de forma avulsa por `util.topologia.exportar_topologia`, que
também passa pela fachada.
