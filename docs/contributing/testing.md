# Testes

## Visão geral

O projeto usa **pytest** para testes unitários. Os testes cobrem os modelos de domínio puros (bateria, inversor, regulador) sem dependência do OpenDSS.

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

```
tests/
├── __init__.py
├── test_battery.py      # Testes de OpenDSSBattery
├── test_inverter.py     # Testes de InverterModel
└── test_regulator.py    # Testes de VR_Model
```

### test_battery.py

| Classe | Testes | O que valida |
|---|---|---|
| `TestInitDefaults` | 4 | Nome, potência, estado inicial, eficiência |
| `TestDischarge` | 2 | Transição para descarga, decréscimo de SoC |
| `TestCharge` | 2 | Transição para carga, aumento de SoC |
| `TestIdle` | 1 | Estado idle com potência zero |
| `TestSoCLimits` | 2 | Limites inferior e superior de SoC |
| `TestKVALimit` | 2 | Limite de reativa dentro do círculo kVA |
| `TestEfficiencyCurve` | 2 | Interpolação de eficiência |

### test_inverter.py

| Classe | Testes | O que valida |
|---|---|---|
| `TestInitDefaults` | 5 | kVA, prioridade, estado inicial, saídas zero |
| `TestCutInOut` | 3 | Cut-in abaixo/above, cut-out |
| `TestEfficiency` | 1 | Curva plana → P_ac = P_dc × η |
| `TestPriority` | 2 | Active clampa Q, Reactive clampa P |
| `TestZeroKVA` | 1 | kVA zero → saída zero |
| `TestThreePhaseOutput` | 1 | Soma trifásica = total |

### test_regulator.py

| Classe | Testes | O que valida |
|---|---|---|
| `TestInitDefaults` | 4 | Vref, tap inicial, limites |
| `TestHighVoltage` | 1 | OV → tap diminui |
| `TestLowVoltage` | 1 | UV → tap aumenta |
| `TestNormalVoltage` | 1 | Dentro da faixa morta → sem mudança |
| `TestLDC` | 1 | LDC executa sem erro |
| `TestTapLimits` | 2 | Tap clamped em max/min |

## Escrever novos testes

1. Crie um arquivo `tests/test_<modulo>.py`
2. Importe o modelo de domínio (não o adaptador mosaik)
3. Crie classes `Test*` com métodos `test_*`
4. Use asserts diretos

Exemplo:

```python
import sys
sys.path.insert(0, "src")

from simulators.battery.battery_model import OpenDSSBattery

class TestMinhaFuncionalidade:
    def setup_method(self):
        self.battery = OpenDSSBattery(
            name="test",
            kw_rated=100,
            kwh_rated=400,
            kwh_stored=200
        )

    def test_exemplo(self):
        result = self.battery.calculate_step(50, 0, 300)
        assert result["state"] == 1  # descarga
```

## Cobertura

Atualmente os testes cobrem apenas modelos de domínio. Não há testes para:

- Adaptadores mosaik
- Wrapper OpenDSS
- Cenários
- CSV Reader / Collector

Testes de integração com OpenDSS requerem o motor compilado e não são executados automaticamente.
