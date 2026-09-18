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

Um wrapper atende a **um** circuito: o motor OpenDSS é único no processo, então
compilar um segundo circuito substituiria o primeiro. Passar uma lista de
caminhos levanta `TypeError`; arquivos auxiliares vão nos `Redirect` do master.

Detecta automaticamente quais classes de elementos existem no circuito: `Load`, `PVSystem`, `Generator`, `Storage`.

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

#### `redirect(filename)`

Compila um arquivo `.dss` específico.

#### `run_dss(no_controls=False)`

Executa a solução do fluxo de potência e **confere se ela convergiu**.

- `no_controls=False` (default): executa `Solve`
- `no_controls=True`: executa `SolveNoControl`
- Se existem elementos Storage, chama `UpdateStorage` após a solução

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

Executa fluxo de potência e retorna um dicionário com o resumo completo.

**Retorno**: `dict[str, float]` com chaves como `Total P/MW`, `Total Loss P/MW`, `Load P/MW`, `PVSystem P/MW`, etc.

---

### Barras

#### `get_all_buses()`

**Retorno**: `list[str]` — lista de nomes de todas as barras.

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

#### `set_power(name, p, q, element, size=1000)`

Define potência P/Q em um elemento Load, PVSystem ou Storage.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `name` | `str` | Nome do elemento |
| `p` | `float` | Potência ativa (W ou kW dependendo de `size`) |
| `q` | `float` | Potência reativa |
| `element` | `str` | Classe do elemento |
| `size` | `int` | Fator de escala (default: 1000, converte kW→W) |

Para Storage, determina automaticamente o estado (Charging/Discharging/Idling) com base no sinal de `p`.

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

Delega para `opendss_regulator.py`. Retorna lista de dicts com dados estáticos de todos os RegControls.

#### `get_regulator_measurements(reg_info)`

Delega para `opendss_regulator.py`. Retorna dict com `v` (tensão complexa), `i` (corrente complexa), `tap` (int).

---

### PVSystem

#### `get_all_pvsystems_info()`

Delega para `opendss_pv.py`. Retorna dict de todos os PVSystems com: `pmpp`, `kva`, `irradiance`, `daily`, `cutin`, `cutout`, `pt_curve`, `eff_curve`, `bus`.

#### `set_pvsystem_pq(name, p_des, q_des)`

Delega para `opendss_pv.py`. Força P/Q: se `p_des > 0.001`, define PMPP, Irradiance=1.0 e kvar; senão Irradiance=0.0.

#### `get_pvsystem_power(name)`

Delega para `opendss_pv.py`. Retorna `(P_kW, Q_kvar)` invertendo sinal.

---

### Storage

#### `get_all_storages_info()`

Delega para `opendss_storage.py`. Retorna dict de todos os Storages com: `kw_rated`, `kwh_rated`, `kwh_stored`, `pct_reserve`, eficiências, etc.

---

### Topologia

#### `grafo_tsdq(output_path)`

Exporta o grafo topológico do circuito para JSON usando `topology_builder.build_graph()`.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `output_path` | `str` | Caminho do arquivo JSON de saída |

---

## Exceções

### `OpenDSSException`

Exceção levantada quando um comando DSS falha e `fail_on_error=True`.

## Exceçãoes e erros

O wrapper levanta `OpenDSSException` quando:

- Um comando DSS retorna erro
- Um elemento não é encontrado
- Uma propriedade não existe
