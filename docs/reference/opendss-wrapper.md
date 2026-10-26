# OpenDSS Wrapper — Referência da API

`simulators.opendss.opendss_wrapper.py` é a interface central com o motor OpenDSS.

## Classe `OpenDSS`

### Construtor

```python
OpenDSS(topofile, time_step, start_time, fail_on_error=True,
        tolerance=None, max_iterations=None)
```

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `topofile` | `str \| os.PathLike` | Caminho do arquivo `.dss` master a compilar |
| `time_step` | `int` | Passo de tempo em segundos |
| `start_time` | `str` | Data/hora de início no formato `"YYYY-MM-DD HH:MM:SS"` |
| `fail_on_error` | `bool` | Se `True`, erros do DSS lançam exceção (default: `True`) |
| `tolerance` | `float \| None` | Critério de convergência. `None` mantém o padrão do motor, `1e-4` |
| `max_iterations` | `int \| None` | Limite de iterações. `None` mantém o padrão do motor, `15` |

Os dois são reaplicados a **cada** compilação: o `Compile` do OpenDSS repõe
ambos no padrão, e um wrapper que recompilasse o circuito perderia o ajuste sem
nada avisando.

Também a cada compilação, antes da primeira solução, todo PVSystem troca a
`EffCurve` e a `P-TCurve` por curvas planas de fator 1 e o `%cutin`/`%cutout`
por `0.0001`. A potência escrita por `set_pvsystem_pq` é a que sai: sem isso o
OpenDSS aplicaria a eficiência e o derating térmico sobre um valor que já os
inclui, e desligaria o inversor abaixo de 20 % do kVA.

Também a cada compilação, antes da primeira solução, o controle automático de
todo RegControl é travado (`MaxTapChange=0`), sem mexer na posição: os taps
ficam no que o `.dss` declara até um controlador externo mudá-los por
`set_tap`.

As caixas de diálogo do OpenDSS ficam ligadas só durante a compilação — aqui e
em `redirect()` —, para que um erro no meio do `.dss` apareça. Fora dela ficam
desligadas, e os erros de comando chegam a `run_command` como código e texto.

Pelo mesmo motivo das curvas, todo Generator tem a faixa de tensão aberta para
`Vminpu=0.001` e `Vmaxpu=10`: fora da faixa declarada o OpenDSS o troca por uma
impedância constante, e a potência entregue deixa de ser a comandada.

Um wrapper atende a **um** circuito: o motor OpenDSS é único no processo, então
compilar um segundo circuito substituiria o primeiro. Passar uma lista de
caminhos levanta `TypeError`; arquivos auxiliares vão nos `Redirect` do master.

A cada solução roda o `UpdateStorage`, que integra a energia das baterias no
passo — em snapshot o motor não o faz sozinho. Sem bateria o comando não faz
nada.

---

### Comandos fundamentais

#### `run_command(cmd)`

Executa um comando de texto DSS bruto.

```python
dss.run_command("New Load.L1 Bus1=bus.1.2.3 kW=100 kvar=50")
```

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `cmd` | `str` | Comando DSS a executar |

Levanta `OpenDSSException` em caso de erro (quando `fail_on_error=True`).
O erro é detectado pelo código do motor (`errorinterface.error_code`), e a
mensagem traz o código e o texto: `Status (cmd): [OpenDSS 580] Unknown
parameter ...`. A descrição do erro (`error_desc`) não é lida: no
`py-dss-interface` 2.3.0 ela derruba o processo.

#### `redirect(filename)`

Compila um arquivo `.dss` específico.

#### `load_buscoords(path)`

Carrega um arquivo de coordenadas de barras (`barra, x, y` por linha) no
circuito compilado. É o que o parâmetro `buscoords` do adaptador usa.

- Arquivo inexistente: aviso, e devolve `False` — as coordenadas servem ao
  desenho, e o estudo não depende delas.
- Arquivo presente: o comando segue por `run_command`, com a detecção de erro
  do motor, e devolve `True`. O caminho é resolvido contra o diretório de
  trabalho.

!!! warning "O motor não confere o conteúdo"
    Medido: um arquivo malformado ou vazio passa sem código de erro e não muda
    coordenada nenhuma.

#### `run_dss(no_controls=False)`

Executa a solução do fluxo de potência e **confere se ela convergiu**.

- `no_controls=False` (default): executa `Solve`
- `no_controls=True`: executa `SolveNoControl`
- Depois da solução, sempre chama `UpdateStorage`, que integra a energia das
  baterias no passo; sem bateria o comando não faz nada

!!! warning "Um solve truncado não se denuncia sozinho"
    Parar no limite de iterações devolve tensões que **não resolvem o circuito**
    e têm a mesma aparência das corretas; o motor não reclama, é preciso
    consultar `converged`. Desde esta versão o método consulta, e a falha
    respeita `fail_on_error`: por padrão levanta `OpenDSSException`, com o erro
    desligado apenas registra a mensagem.

    Quem precisa tolerar um passo ruim — em vez de perder a execução inteira —
    desliga o erro e acompanha o estado pelo modelo mosaik `Circuit`, que expõe
    `converged` e `iterations`.

---

### Consulta do circuito

#### `get_circuit_power()`

Retorna a potência total do circuito.

**Retorno**: `tuple[float, float]` — `(P_kW, Q_kvar)`

!!! info "Convenção de sinais"
    Geração é retornada como negativa (convenção OpenDSS).

#### `get_losses()`

Retorna as perdas totais do circuito.

**Retorno**: `tuple[float, float]` — `(P_kW, Q_kvar)`

#### `get_element_losses(name, element="Line")`

Retorna a perda total de **um** elemento — o que entra por um terminal e não
sai pelo outro. Só faz sentido físico em elementos série (`Line`,
`Transformer`); num elemento shunt de um terminal o mesmo cálculo devolve a
própria potência do elemento.

```python
dss.get_element_losses("650632", "Line")        # (kW, kvar)
dss.get_element_losses("xfm1", "Transformer")
```

**Retorno**: `tuple[float, float]` — `(P_kW, Q_kvar)`

!!! warning "Unidades"
    O motor reporta este par em **W/var** e o de `get_phase_losses()` em
    **kW/kvar**. A conversão acontece no wrapper, e as duas leituras saem daqui
    na mesma unidade.

#### `get_phase_losses(name, element="Line")`

Mesma perda, repartida por fase. Não tem argumento `terminal`: a perda é do
elemento inteiro.

**Retorno**: `tuple[list[float], list[float]]` — `([P1, P2, P3], [Q1, Q2, Q3])`
em kW e kvar; a fase que o elemento não tem é `NaN`.

O total do motor conta também o neutro, que as parcelas por fase não percorrem
— com neutro solidamente aterrado os dois coincidem. A parcela de uma fase pode
sair negativa sob acoplamento mútuo forte com correntes desequilibradas.

#### `get_total_power(element)`

Retorna a potência agregada de todos os elementos de uma classe.

```python
dss.get_total_power("Load")      # soma de todas as cargas
dss.get_total_power("PVSystem")  # soma de todos os PVSystems
```

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `element` | `str` | Nome da classe (`"Load"`, `"PVSystem"`, `"Storage"`) |

**Retorno**: `tuple[float, float]` — `(P_kW, Q_kvar)`

#### `get_circuit_info()`

Retorna um dicionário com o resumo da **última solução** — não resolve o
circuito; resolva antes com `run_dss()`.

**Retorno**: `dict[str, float]` com os totais do circuito e das perdas, e os de
cada classe (`Load`, `PV`, `Generator`, `Storage`), com zero para as ausentes.

#### `get_circuit_summary()`

Dados estáticos do circuito compilado e os ajustes do solucionador.

**Retorno**: `dict` com `name`, `num_buses`, `num_nodes`, `tolerance` e
`max_iterations`. É o `extra_info` da entidade `Circuit` do adaptador.

#### `get_solution_state()`

Se a última solução convergiu, e em quantas iterações. Lido do motor, e não do
cache.

**Retorno**: `tuple[bool, int]` — `(converged, iterations)`.

---

### Barras

#### `get_all_buses()`

**Retorno**: `list[str]` — lista de nomes de todas as barras.

#### `get_all_buses_info()`

Dados estáticos de todas as barras, na ordem do circuito. É a mesma leitura que
o grafo da topologia faz (`opendss_bus.read_bus_info`).

**Retorno**: `dict[str, dict]` — por barra, `kv_base`, `nodes`, `num_nodes`,
`x`, `y` e `coord_defined`. As coordenadas saem cruas: sem `BusCoords` o motor
reporta (0, 0), e só o `coord_defined` distingue esse zero de uma barra que fica
de fato na origem.

#### `get_bus_vmag_pu(bus)`

Módulo da tensão por fase, em pu.

```python
dss.get_bus_vmag_pu("675")      # [0.9835, 1.0553, 0.9758]
dss.get_bus_vmag_pu("611")      # [nan, nan, 0.9738] -- monofásica na fase 3
```

**Retorno**: `list[float]` — sempre três valores, indexados por fase; a fase que
a barra não tem é `NaN`.

Aceita o nome com ou sem sufixo de nó (`"675"` ou `"675.1"`). Servido de uma
leitura única de todo o circuito (`circuit.buses_vmag_pu`), em cache até a
próxima solução: monitorar duas barras não custa as 130.

#### `get_bus_vang(bus)`

Ângulo da tensão por fase, em graus. Mesma forma de retorno. Vem de uma chamada
distinta ao motor, com cache próprio — pedir só o módulo nunca paga o ângulo.

#### `get_bus_voltage_pu(bus)`

Conveniência sobre as duas anteriores; lê os dois vetores.

**Retorno**: `tuple[list[float], list[float]]` — `([|V1|, |V2|, |V3|], [ang1, ang2, ang3])`.

---

### Elementos (potência, corrente, propriedades)

#### `get_phase_powers(name, element="Load", terminal=1)`

Potência ativa e reativa por fase, posicionadas pelos nós do elemento.

```python
dss.get_phase_powers("671", element="Load")
dss.get_phase_powers("650632", element="Line", terminal=2)
```

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `name` | `str` | Nome do elemento |
| `element` | `str` | Classe (`"Load"`, `"PVSystem"`, `"Line"`, ...) |
| `terminal` | `int` | 1 para elementos shunt; 1 ou 2 para linhas; enrolamento para transformadores |

**Retorno**: `tuple[list[float], list[float]]` — `([P1, P2, P3], [Q1, Q2, Q3])` em
kW e kvar, na convenção do OpenDSS (carga positiva).

A forma do retorno **não** depende do número de fases: são sempre três valores,
indexados por fase, com `NaN` onde o elemento não tem condutor. O OpenDSS ordena
por condutor, não por fase — um elemento monofásico em `bus.3` reporta um valor
só, e empacotá-lo à esquerda o transformaria na fase 1; o posicionamento usa o
`node_order` do elemento.

#### `get_phase_currents(name, element="Load", terminal=1)`

Módulo e ângulo da corrente por fase. Mesmos parâmetros e mesma forma de
retorno: `([|I1|, |I2|, |I3|], [ang1, ang2, ang3])`, em amperes e graus.

#### `get_power_total(name, element="Load", terminal=1)`

O escalar que acompanha `get_phase_powers`.

**Retorno**: `tuple[float, float]` — `(P, Q)` somados **nas fases presentes**.
Separar os dois métodos é o que dispensa uma bandeira `total` que mudaria o
formato do retorno.

#### `set_power(name, p=None, q=None, element="Load")`

Define potência P/Q em um elemento Load, Generator ou Storage.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `name` | `str` | Nome do elemento |
| `p` | `float \| None` | Potência ativa (kW); `None` deixa como está |
| `q` | `float \| None` | Potência reativa (kvar); `None` deixa como está |
| `element` | `str` | `"Load"`, `"Generator"` ou `"Storage"` |

Para Storage, determina o estado pelo sinal de `p` (`> 0` descarrega, `< 0`
carrega, `0` fica ociosa). Sem `p` nada é escrito, e sem `q` a reativa vai a
zero.

PVSystem é **recusado** com `OpenDSSException`, antes de chegar ao motor: a
classe não tem `kW` — a saída é calculada de `Pmpp` e irradiância. Use
`set_pvsystem_pq`.

#### `get_is_open(name, element="Line", term=None)`

Se o elemento está aberto. Com `term=None` (padrão) responde pelo **elemento**:
aberto se qualquer terminal estiver aberto.

```python
dss.get_is_open("671692")          # o elemento
dss.get_is_open("671692", term=2)  # um terminal específico
```

**Retorno**: `bool`.

!!! warning "Não confie na docstring do py-dss-interface"
    Ela diz que `is_terminal_open` responde *"if any terminal is open"*, mas ele
    responde pelo terminal que recebe — verificado. Ler só o terminal 1 daria
    por fechadas as chaves normalmente abertas do IEEE123, que o `.dss` abre com
    `terminal=2`.

#### `set_is_open(name, open=True, element="Line", term=None)`

Abre ou fecha. Com `term=None` (padrão) trata o elemento como uma chave de um
estado só:

- **abrir** usa o **terminal 2**, a convenção do próprio IEEE123
  (`open Line.Sw7 terminal=2`). Assim o estado produzido aqui fica
  indistinguível do que vem declarado no circuito;
- **fechar** fecha os **dois** terminais — fechar só o terminal 2 deixaria
  aberta a chave que alguém tivesse aberto pelo terminal 1, e o comando falharia
  em silêncio, com a corrente seguindo em zero.

Passe `term` para comandar um terminal específico. Não é preciso invalidar o
cache: `run_command` já o faz.

#### `get_ampacity(name, element="Line")`

Retorna os limites de corrente do elemento — o denominador do carregamento.

```python
dss.get_ampacity("650632", "Line")   # (400.0, 600.0)
```

**Retorno**: `tuple[float, float]` — `(normal, emergencial)` em amperes.

O valor é estático: pertence ao circuito compilado, não a uma solução. Quem
precisa dele a cada passo deve guardá-lo, como faz o adaptador mosaik, em vez de
reler daqui. A herança do `LineCode` é resolvida pelo motor — não é preciso
procurar o linecode nem interpretar a propriedade como texto.

!!! warning "O padrão do OpenDSS é 400 A"
    Quando ninguém declara `normamps` — nem a linha nem o `LineCode` —, o motor
    entrega 400 A normais e 600 A emergenciais para qualquer linha. Nenhum dos
    alimentadores que acompanham o projeto declara ampacidade, então é esse o
    valor que sai em todos eles. Ver o aviso em
    [Adaptadores Mosaik](mosaik-adapters.md#atributos-de-saida-get_data).

---

### Propriedades

#### `get_all_properties(name, element)`

Lista todas as propriedades disponíveis de um elemento.

#### `get_property(name, property_name, element)`

Lê o valor de uma propriedade específica.

#### `set_property(name, property_name, value, element)`

Define uma propriedade e verifica a escrita.

---

### Reguladores

#### `set_tap(name, tap, max_tap=16)`

Define a posição do tap de um RegControl, com clamp em `[-max_tap, max_tap]`.

#### `get_tap(name)`

Retorna a posição atual do tap (inteiro).

#### `get_all_regulators_info()`

Delega para `opendss_regulator.py`. Retorna lista de dicts com dados estáticos de todos os RegControls. Só lê: `tap_ini` é o tap no momento da leitura, e chamar o método não mexe nos taps.

#### `get_regulator_measurements(reg_info)`

Delega para `opendss_regulator.py`. Retorna dict com `v` (tensão complexa), `i` (corrente complexa), `tap` (int).

---

### PVSystem

#### `get_all_pvsystems_info()`

Delega para `opendss_pv.py`. Retorna dict de todos os PVSystems com: `pmpp`, `kva`, `kv`, `pf`, `irradiance`, `daily`, `pct_cutin`, `pct_cutout`, `pt_curve_x`/`_y`, `eff_curve_x`/`_y`, `bus`, `num_phases`.

As curvas e os limiares são os declarados no `.dss`, lidos antes de a compilação
os trocar pelos ideais — e não os que o motor usa de fato.

#### `set_pvsystem_pq(name, p_des, q_des)`

Delega para `opendss_pv.py`. Força P/Q: se `p_des > 0.001`, define PMPP, Irradiance=1.0 e kvar; senão Irradiance=0.0.

#### `get_pvsystem_power(name)`

Delega para `opendss_pv.py`. Retorna `(P_kW, Q_kvar)` invertendo sinal.

---

### Generator

#### `get_all_generators_info()`

Delega para `opendss_generator.py`. Retorna dict de todos os Generators com: `name`, `bus`, `num_phases`, `kv`, `kw`, `kvar`, `pf`, `kva`, `model`, `conn`, `status`, `daily`, `yearly`, `vminpu`, `vmaxpu`.

A faixa de tensão é a declarada no `.dss`, lida antes de a compilação a abrir — e não a que o motor usa de fato.

O despacho passa por `set_power(name, p, q, element="Generator")`.

---

### Storage

#### `get_all_storages_info()`

Delega para `opendss_storage.py`. Retorna dict de todos os Storages com: `kw_rated`, `kwh_rated`, `kwh_stored`, `pct_reserve`, eficiências, etc.

---

### Curvas (LoadShape)

#### `get_loadshape(name)`

Delega para `opendss_loadshape.py`. Retorna os multiplicadores de uma
LoadShape com as peculiaridades do motor já resolvidas:

| Chave | Conteúdo |
|---|---|
| `p_mult`, `q_mult` | Multiplicadores; `q_mult` repete `p_mult` quando a curva não declara reativa |
| `npts` | Número de pontos, já conciliado com o vetor que o motor de fato entrega |
| `interval_s` | Intervalo entre pontos em segundos, buscado em s, min e h; `None` com pontos explícitos por hora (`interval=0`). Sem declaração, o OpenDSS assume 1 h |
| `use_actual` | Se os valores são absolutos, e não multiplicadores |

Levanta `OpenDSSException` se a curva não existe — a interface do motor
manteria ativa a curva anterior e devolveria os pontos dela — ou não tem
pontos.

---

### Topologia

#### `grafo_tsdq(output_path)`

Exporta o grafo topológico do circuito para JSON usando `topology_builder.build_graph()`.
O JSON (formato v2) traz barras, arestas e elementos ligados às barras, sem
classificar barra nenhuma; ver [Exportar Topologia para JSON](../how-to-guides/export-topology-json.md).

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `output_path` | `str` | Caminho do arquivo JSON de saída |

**Retorno**: o `NetworkGraph` exportado, para inspecioná-lo sem reler o arquivo.

---

## Exceções

### `OpenDSSException`

Exceção levantada quando um comando DSS falha e `fail_on_error=True`.

## Exceçãoes e erros

O wrapper levanta `OpenDSSException` quando:

- Um comando DSS retorna erro
- Um elemento não é encontrado
- Uma propriedade não existe
