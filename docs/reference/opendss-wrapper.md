# OpenDSS Wrapper — Referência da API

`simulators.opendss.opendss_wrapper.py` é a interface central com o motor OpenDSS.

## Classe `OpenDSS`

### Construtor

```python
OpenDSS(topofile, time_step, start_time, fail_on_error=True)
```

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `topofile` | `str \| os.PathLike` | Caminho do arquivo `.dss` master a compilar |
| `time_step` | `int` | Passo de tempo em segundos |
| `start_time` | `str` | Data/hora de início no formato `"YYYY-MM-DD HH:MM:SS"` |
| `fail_on_error` | `bool` | Se `True`, erros do DSS lançam exceção (default: `True`) |

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

Executa a solução do fluxo de potência.

- `no_controls=False` (default): executa `Solve`
- `no_controls=True`: executa `SolveNoControl`
- Se existem elementos Storage, chama `UpdateStorage` após a solução

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

#### `get_bus_voltage(bus, phase=None, pu=True, polar=True, mag_only=False, average=False, zero_voltage_error=False)`

Obtém tensão de uma barra com opções flexíveis.

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `bus` | `str` | — | Nome da barra |
| `phase` | `int \| None` | `None` | Fase específica (1, 2, 3) ou `None` para todas |
| `pu` | `bool` | `True` | Se `True`, retorna em p.u.; senão em Volts |
| `polar` | `bool` | `True` | Se `True`, retorna magnitude; senão (real, imaginário) |
| `mag_only` | `bool` | `False` | Se `True`, retorna apenas a magnitude |
| `average` | `bool` | `False` | Se `True`, retorna a média das fases |
| `zero_voltage_error` | `bool` | `False` | Se `True`, retorna 0.0 em caso de erro |

**Retorno**: `float` (fase única) ou `list[float]` (todas as fases) ou `tuple[float, float]` (polar=False).

#### `get_all_bus_voltages(**kwargs)`

Retorna tensões de todas as barras. Mesmos kwargs de `get_bus_voltage`.

**Retorno**: `dict[str, float|list]` — `{nome_barra: tensão}`.

---

### Elementos (potência, corrente, propriedades)

#### `get_power(name, element, phase=None, total=False, line_bus=1, raw=False)`

Retorna potência P/Q de um elemento.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `name` | `str` | Nome do elemento (ex: `"Load.L1"`) |
| `element` | `str` | Classe (`"Load"`, `"PVSystem"`, etc.) |
| `phase` | `int \| None` | Fase específica ou `None` para total |
| `total` | `bool` | Se `True`, soma todas as fases |
| `line_bus` | `int` | Para linhas: 1=bus de envio, 2=bus de recebimento |
| `raw` | `bool` | Se `True`, retorna valores brutos sem formatação |

**Retorno**: `tuple[float, float]` — `(P, Q)` ou `tuple` para raw.

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

#### `get_current(name, element, polar=True, mag_only=False, line_bus=1, phase=None, total=False, raw=False, winding=1)`

Retorna corrente de um elemento.

Mesmos parâmetros de `get_power()`, com adição de:

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `winding` | `int` | Para transformadores: índice do winding (default: 1) |

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
