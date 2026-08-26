# Testes

## Visão geral

O projeto usa **pytest**, com 12 arquivos e 326 casos de teste (com parametrização; rodando `uv run --no-sync python -m pytest tests/ -v` neste ambiente: 326 passed, 0 failed, 0 skipped).

Duas categorias, misturadas entre os arquivos:

- **Testes de domínio** — instanciam a classe diretamente (`OpenDSSBattery`, `InverterModel`, `VR_Model`, `SmartInverterModel`, `map_to_phases`), sem fixture, sem mosaik, sem OpenDSS.
- **Testes de integração** — compilam um circuito IEEE real (`data/13Bus/` ou `data/123Bus/`) via `OpenDSS`/`OpenDSSSimulator` e leem/escrevem contra o engine de fato. Usam uma fixture com `pytest.skip(...)` quando o arquivo `.dss` ou o motor compilado não estão disponíveis — não é preciso configurar nada à parte; a suíte inteira roda com o mesmo comando, e essas classes só são puladas se o ambiente não tiver um OpenDSS funcional.

Não há `conftest.py` — cada arquivo declara suas próprias fixtures.

## Executar testes

```bash
# Todos os testes
uv run --no-sync python -m pytest tests/ -v

# Arquivo específico
uv run --no-sync python -m pytest tests/test_battery.py -v

# Classe específica
uv run --no-sync python -m pytest tests/test_inverter.py::TestCutInOut -v

# Verbose com saída detalhada
uv run --no-sync python -m pytest tests/ -v --tb=long
```

## Estrutura dos testes

| Arquivo | Testes¹ | Depende de OpenDSS real | Testa |
|---|---|---|---|
| `test_battery.py` | 14 | Não | `battery.battery_model.OpenDSSBattery` |
| `test_inverter.py` | 13 | Não | `inverter.inverter.InverterModel` (legado) |
| `test_regulator.py` | 10 | Não | `controller.regulator_control.VR_Model` |
| `test_phase_mapping.py` | 13 | Não | `opendss._utils.map_to_phases` |
| `test_smart_inverter.py` | 81 | Não² | `inverter.config`, `inverter.opender_factory`, `inverter.smart_inverter.SmartInverterModel`, `inverter.smart_inverter_simulator.SmartInverterSim` |
| `test_element_specs.py` | 27 | Sim | `opendss.element_specs` (registro declarativo) + `api_opendss.OpenDSSSimulator` |
| `test_error_handling.py` | 18 | Sim | Propagação de erro no wrapper e no adaptador OpenDSS |
| `test_opendss_entities.py` | 23 | Sim | Grafo de entidades mosaik (`rel`, `extra_info`) do adaptador OpenDSS |
| `test_opendss_phase_reads.py` | 9 | Sim | Leitura por fase do wrapper (`opendss_wrapper.py`) |
| `test_opendss_snapshot.py` | 18 | Sim | Cache de leituras do wrapper |
| `test_topology_builder.py` | 18 | Sim | `opendss.topology_builder.build_graph` |
| `test_wrapper_layers.py` | 16 | Sim | Composição em mixins do wrapper (`_engine`/`_reader`/`_writer`/`_legacy`) |

¹ Métodos de teste (não casos parametrizados — vários métodos rodam mais de um caso via `@pytest.mark.parametrize`).
² `TestAdapter`, dentro deste arquivo, testa o adaptador mosaik `SmartInverterSim` e a integração com o `opender.DER` real — não usa OpenDSS, mas não é um teste de domínio puro.

### Testes de domínio

#### `test_battery.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestInitDefaults` | 4 | Nome, potência, estado inicial, eficiência |
| `TestDischarge` | 2 | Transição para descarga, decréscimo de SoC |
| `TestCharge` | 2 | Transição para carga, aumento de SoC |
| `TestIdle` | 1 | Estado idle com potência zero |
| `TestSoCLimits` | 2 | Limites inferior e superior de SoC |
| `TestKVALimit` | 1 | Limite de reativa dentro do círculo kVA |
| `TestEfficiencyCurve` | 2 | Interpolação de eficiência |

#### `test_inverter.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestInitDefaults` | 5 | kVA, prioridade, estado inicial, saídas zero |
| `TestCutInOut` | 3 | Cut-in abaixo/acima, cut-out |
| `TestEfficiency` | 1 | Curva plana → `P_ac = P_dc × η` |
| `TestPriority` | 2 | `Active` clampa Q, `Reactive` clampa P |
| `TestZeroKVA` | 1 | kVA zero → saída zero |
| `TestThreePhaseOutput` | 1 | Soma trifásica = total |

#### `test_regulator.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestInitDefaults` | 4 | Vref, tap inicial, limites |
| `TestHighVoltage` | 1 | OV → tap diminui |
| `TestLowVoltage` | 1 | UV → tap aumenta |
| `TestNormalVoltage` | 1 | Dentro da faixa morta → sem mudança |
| `TestLDC` | 1 | LDC executa sem erro |
| `TestTapLimits` | 2 | Tap clampado em max/min |

#### `test_phase_mapping.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestThreePhase` | 2 | Mapeamento trifásico; condutor neutro é ignorado |
| `TestSinglePhase` | 4 | Fase 2/3 não vaza para a posição 1 — a regressão que motivou o módulo |
| `TestDelta` | 3 | Carga delta (2 condutores) preenche as duas fases certas, sem truncar o total |
| `TestEdgeCases` | 4 | Terminal todo aterrado, nós acima de 3, listas vazias/desalinhadas |

#### `test_smart_inverter.py` — curvas, configuração e modelo

| Classe | Testes | O que valida |
|---|---|---|
| `TestVoltVarCurve` | 14 | Curva de 4 pontos: valores analíticos da IEEE 1547 (não o que o código produz hoje), validação de monotonicidade e faixa, banda morta de largura zero, fator de relaxação, round-trip por dict |
| `TestVoltWattCurve` | 4 | Curva de 2 pontos: valores analíticos, validação, `p_limit_at` |
| `TestControlConfig` | 10 | Cada modo exige sua curva/ajuste, volt-watt é ortogonal ao modo de reativo, serialização `to_dict`/`from_dict` |
| `TestInverterUnit` | 5 | Validação de fase/nó, tensão nominal, `kw` default para `kva` |
| `TestOpenDERFactory` | 9 | Ordem de escrita dos parâmetros do `DERCommonFileFormat` (setters cross-referenciados), capacidade reativa acompanha `NP_VA_MAX` mesmo escalando o inversor |
| `TestVoltVarEndToEnd` | 6 | Curva reproduzida ponta a ponta pelo modelo, saturação na capacidade reativa, prioridade `REACTIVE` reduz P |
| `TestVoltWattEndToEnd` | 3 | Limite de P aplicado, funciona junto com volt-var |
| `TestConstantModes` | 2 | Fator de potência constante, Q constante |
| `TestSinglePhaseUnits` | 6 | Cada unidade responde só à própria fase; tensão ausente levanta erro em vez de assumir 1.0 |
| `TestPassthrough` | 5 | Caminho sem OpenDER: segue `Q_des`, histerese de cut-in/cut-out, curva de eficiência |
| `TestTrip` | 5 | Trip por sobre/subtensão quando habilitado; desabilitar move os limiares, não só estica o tempo |

#### `test_smart_inverter.py` — adaptador mosaik

| Classe | Testes | O que valida |
|---|---|---|
| `TestAdapter` | 12 | `META` bate exatamente com `INPUT_SPECS`/`OUTPUT_GETTERS`; `init` propaga o passo para `DER.t_s`; atalho de unidade única vs. `units` explícito; `step`/`get_data` ponta a ponta |

### Testes de integração (circuito OpenDSS real)

Todos usam uma fixture de módulo que compila `data/13Bus/IEEE13Nodeckt.dss`, `run_ieee13_cosim_pv_5min.dss` ou `data/123Bus/run_ieee123_cosim_5min.dss`, com `pytest.skip` se o arquivo ou o motor não estiverem disponíveis.

#### `test_wrapper_layers.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestLayerBoundaries` | 4 | Cada mixin (`_engine`/`_reader`/`_writer`/`_legacy`) não está vazio nem duplica um método de outro; o `_writer` só tem mutadores, o `_reader` nenhum |
| `TestPublicApiIsPreserved` | 2 | Todo método usado por cenários/notebooks continua acessível na fachada `OpenDSS` |
| `TestPowerTotal` | 3 | Total de potência bate com a soma das fases; terminais opostos de uma linha têm sinais opostos |
| `TestCompileIsRobust` | 4 | Construir o wrapper não muda o diretório de trabalho do processo; caminho relativo resolve contra o diretório do chamador; arquivo ausente levanta erro em vez de compilar um circuito vazio |
| `TestReadersDoNotMutate` | 3 | Uma leitura (`get_circuit_info`) nunca chama `run_dss`; escrita limpa o cache |

#### `test_opendss_snapshot.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestBulkVoltagesMatchPerBusReads` | 3 | Leitura em lote bate exatamente com a leitura por barra que ela substitui |
| `TestCachingIsTransparent` | 3 | Todo valor servido pelo cache é idêntico ao lido "a frio" |
| `TestLazyReads` | 4 | Magnitude e ângulo são leituras independentes; só busca o que foi pedido |
| `TestCacheIsPopulatedAndReused` | 2 | Segunda leitura é servida do cache, sem nova chamada ao engine |
| `TestInvalidation` | 6 | `run_dss`, `run_command`, `set_tap` e `set_pvsystem_pq` limpam o cache; uma mudança real é observável na próxima leitura |

#### `test_opendss_phase_reads.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestSinglePhaseLoads` | 2 | Carga monofásica reporta na própria fase, não na fase 1 |
| `TestDeltaLoads` | 2 | Carga delta (2 condutores) preenche as duas fases; total não é truncado |
| `TestThreePhaseLoads` | 1 | As três fases aparecem |
| `TestLineTerminals` | 2 | Os dois terminais de uma linha são legíveis; terminal fora da faixa levanta erro |
| `TestTransformerWindings` | 1 | Regulador monofásico reporta só na própria fase |
| `TestMosaikAttributeExtraction` | 1 | O leitor do registro (`read_phases`) usa o nó real do elemento, não a posição |

#### `test_opendss_entities.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestParseBus` | 3 | Parsing de `"671.1.2.3"` em barra + nós; nós implícitos resolvidos a partir das fases |
| `TestRelIsWellFormed` | 6 | Nenhuma referência (`rel`) solta; toda referência aponta para um `Bus-`; linha conecta duas barras |
| `TestExtraInfo` | 6 | Todo filho tem `extra_info`; é serializável em JSON (necessário para o modo Docker); PV monofásico reporta o nó real |
| `TestCreateGuards` | 2 | `Grid` não pode ser criado duas vezes; outros modelos são rejeitados em `create()` |
| `TestExtraInfoMatchesTheEngine` | 2 | Barra/nós/segundo terminal em `extra_info` batem com o que o `cktelement` do engine reporta |
| `TestBackwardCompatibility` | 4 | `get_detected_pvsystems`/`_regulators`/`_storages` e os mapas por eid, usados por cenários existentes, continuam funcionando |

#### `test_element_specs.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestAggregators` | 4 | `sum_values` soma; `single_value` avisa e não descarta silenciosamente um valor concorrente |
| `TestPhaseAttrMap` | 2 | Sinal se aplica à potência, não à corrente; escala se aplica aos totais |
| `TestGeneratedMeta` | 5 | `META` gerada tem todo modelo, sem atributo duplicado; todo modelo com input declara um writer |
| `TestMetaMatchesImplementation` | 4 | Toda saída declarada é de fato produzida por `get_data`; atributo desconhecido é ignorado, não quebra |
| `TestInputRouting` | 6 | Setpoint de PV chega ao circuito; múltiplos controladores no mesmo elemento são somados; PV monofásico cai na fase certa |
| `TestStorage` | 5 | SoC lido e aplicado corretamente, com clamp em `[0, 1]`; Storage monofásico reporta na própria fase |
| `TestExtraInfoIsolation` | 1 | `extra_info` de um filho é uma cópia, não uma referência viva ao estado do simulador |

#### `test_error_handling.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestValueComparison` | 3 | Comparação numérica e textual (case-insensitive) usada para confirmar uma escrita |
| `TestSetProperty` | 3 | Formas numéricas equivalentes (int/float/str) são aceitas; propriedade inexistente é rejeitada **antes** de chegar ao engine |
| `TestRegulatorMeasurements` | 6 | Toda fase de regulador reporta corrente e tensão (não zero por indexação errada); fase/winding inválidos levantam erro |
| `TestControlWritesAreNotSwallowed` | 3 | Uma escrita de controle que falha interrompe o passo e nomeia a entidade no erro |
| `TestSetupDone` | 1 | `setup_done()` resolve o circuito de fato |
| `TestPvCurveBypassIsOptional` | 2 | O bypass das curvas nativas de PV do OpenDSS é ligado por padrão e pode ser desligado |

#### `test_topology_builder.py`

| Classe | Testes | O que valida |
|---|---|---|
| `TestSourceBus` | 4 | A barra de referência vem da fonte de tensão, não do nome `"sourcebus"` |
| `TestParallelElements` | 4 | Elementos paralelos na mesma dupla de barras (ex.: `reg1`/`reg2`/`reg3`) não se sobrescrevem |
| `TestNodeClassification` | 5 | Classificação de barra por papel real no circuito (regulador, PV, carga), não por convenção de nome |
| `TestNodeMetadata` | 2 | Barras carregam coordenadas e tensão base; arestas carregam contagem de fases |
| `TestDisabledElements` | 3 | Linha desabilitada não vira aresta; chave aberta permanece, mas marcada |

## Escrever novos testes

**Teste de domínio** — instancie o modelo diretamente, sem fixture:

```python
import sys
sys.path.insert(0, "src")

from simulators.battery.battery_model import OpenDSSBattery

class TestMinhaFuncionalidade:
    def setup_method(self):
        self.battery = OpenDSSBattery(
            name="test", kw_rated=100, kwh_rated=400, kwh_stored=200
        )

    def test_exemplo(self):
        result = self.battery.calculate_step(50, 0, 300)
        assert result["state"] == 1  # descarga
```

**Teste de integração** — use uma fixture de módulo que compila um circuito real, com `pytest.skip` se ele não existir:

```python
import datetime as dt
import pathlib
import pytest
import sys
sys.path.insert(0, "src")

from simulators.opendss.opendss_wrapper import OpenDSS

MASTER = (pathlib.Path(__file__).parent.parent / "data" / "13Bus" / "IEEE13Nodeckt.dss").resolve()

@pytest.fixture(scope="module")
def dss_13bus():
    if not MASTER.exists():
        pytest.skip(f"IEEE13 fixture not found at {MASTER}")
    wrapper = OpenDSS(redirects=str(MASTER), time_step=dt.timedelta(seconds=300), start_time=dt.datetime(2025, 1, 1))
    if wrapper.dss.circuit.num_buses == 0:
        pytest.skip("IEEE13 failed to compile (check the OpenDSS DataPath)")
    wrapper.run_dss()
    return wrapper

class TestMinhaFuncionalidade:
    def test_exemplo(self, dss_13bus):
        assert dss_13bus.get_bus_vmag_pu("675")
```

Em ambos os casos, importe o modelo de domínio ou o wrapper diretamente — nunca `py_dss_interface` (veja [Convenções de Código](code-conventions.md)) — e use classes `Test*` com métodos `test_*`.

## Cobertura

A suíte cobre hoje as três camadas do projeto (mesma divisão de [Arquitetura](../explanation/architecture.md)): modelos de domínio, o adaptador mosaik do inversor (`SmartInverterSim`) e o adaptador + wrapper do OpenDSS, este último contra circuitos reais.

Não há teste dedicado para:

- Os demais adaptadores mosaik: `battery_sim.py`, `pv_panel_simulator.py`, `controller_sim.py`, `regulator_control.py`, `collector.py`, `csv_sim_pandas.py`
- Os cenários (`scenarios/*.py`) executados ponta a ponta — nenhum teste roda um cenário completo e verifica o CSV de saída
