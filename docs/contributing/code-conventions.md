# Convenções de Código

## Convenções gerais

- **Linguagem**: português brasileiro em comentários e documentação
- **Inglês**: nomes de variáveis, funções, classes e módulos
- **Indentação**: 4 espaços
- **Comprimento de linha**: 100 caracteres (tratado pelo formatter)
- **Aspas**: duplas (`"`)

## Organização de imports

Imports são ordenados por `isort` (via Ruff):

```python
# 1. Bibliotecas padrão
import os
import sys
from pathlib import Path

# 2. Bibliotecas externas
import mosaik_api_v3
import numpy as np
import pandas as pd

# 3. Módulos do projeto
from simulators.opendss.opendss_wrapper import OpenDSS
from simulators.opendss._utils import sum_phases
```

## Adaptadores mosaik

### META dict

Todo adaptador deve ter:

```python
META = {
    "api_version": "3.0",
    "type": "time-based",  # ou "event-based" ou "hybrid"
    "models": {
        "NomeDoModelo": {
            "public": True,
            "params": [...],
            "attrs": [...],
        }
    }
}
```

### Nomenclatura de atributos

| Direção | Convenção | Exemplo |
|---|---|---|
| Entrada (input) | Nome descritivo | `P_dc`, `v_meas`, `tap` |
| Saída (output) | Nome descritivo | `P_ac`, `Q_ac`, `P_out` |
| Bidirecional | Mesmo nome | `tap` (read/write) |

### Bloco main

Todo adaptador que pode ser executado remotamente deve ter:

```python
if __name__ == "__main__":
    mosaik_api_v3.start_sim(MinhaClasse.meta["models"])
```

## Modelos de domínio

### Nomenclatura

| Tipo | Exemplo | Descrição |
|---|---|---|
| Classe | `InverterModel` | Modelo de domínio (física/controle) |
| Classe | `InverterSim` | Adaptador mosaik |
| Função | `calculate_step()` | Método principal de cálculo |
| Função | `get_state_str()` | Método auxiliar |

### Separation of concerns

- Modelos de domínio (`inverter.py`, `battery_model.py`) não importam mosaik
- Adaptadores (`inverter_simulator.py`, `battery_sim.py`) importam mosaik e o modelo

## OpenDSS

- Nunca chame `py_dss_interface` diretamente
- Use sempre `opendss_wrapper.py` como interface — a fachada
- No adaptador e no registry, não acesse `dss_wrapper.dss`: se falta uma
  operação, crie um método na fachada (ou uma função num módulo atrás dela,
  como `opendss_pv.py`, delegada pelo `_reader`/`_writer`).
  `tests/test_wrapper_layers.py::TestFacadeIsNotBypassed` reprova a violação
- Comandos ao motor passam por `run_command`, que detecta o erro pelo código
  do OpenDSS; não leia `errorinterface.error_desc`, que derruba o processo no
  `py-dss-interface` 2.3.0
- Classe vazia no `py-dss-interface` devolve `['None']`, e não uma lista vazia:
  confira `.count` ou compare com `"NONE"`
- A convenção de sinais é invertida na fronteira (`sign=-1` no registry)

## Cenários

- Cenários são scripts standalone, não módulos importáveis
- Cada cenário define seu próprio `SIM_CONFIG`
- Use `uv run --no-sync python scenarios/<arquivo>.py` para executar

## Testes

- Framework: pytest
- Classes com `Test*`, métodos com `test_*`
- Sem `conftest.py` — cada arquivo declara suas próprias fixtures
- Dois padrões, conforme o alvo (veja [Testes](testing.md)):
  - **Domínio**: instancia o modelo diretamente, sem fixture, sem OpenDSS
  - **Integração**: fixture de módulo compila um circuito IEEE real e usa `pytest.skip(...)` se o arquivo `.dss` ou o motor não estiverem disponíveis
- `monkeypatch` (da própria biblioteca pytest) é usado nos testes de integração para simular falhas do engine — não há biblioteca de mocking externa
- **Um motor por processo.** Todas as instâncias de `py_dss_interface.DSS()`
  compartilham o mesmo motor: um teste que compila outro circuito substitui o da
  fixture de módulo. Ponha esses testes **no fim do arquivo**, como fazem os de
  `test_element_specs.py`; antes, os testes seguintes leriam o circuito errado
  sem falhar
- Teste de regressão de um defeito: confira que ele **falha** com o
  comportamento antigo (por exemplo, com `monkeypatch` reproduzindo o código
  anterior), e não só que passa com o novo

## Erros

- Use `except Exception:` em vez de `except:` (bare except)
- Levante exceções específicas quando possível
- `OpenDSSException` para erros do wrapper
- Três níveis de reação, conforme a natureza do problema:
    - **Erro de uso** (elemento ou propriedade inexistente, multiplicador fora
      da faixa): levanta sempre, com `raise`
    - **Erro do motor** (comando recusado, fluxo que não convergiu): passa por
      `self.fail()`, que levanta ou só imprime conforme `fail_on_error`
    - **Situação suspeita que não invalida o estudo**: aviso
      `[OpenTES][AVISO]` impresso, que diz a consequência e não só o erro
- Prefira falhar alto a seguir em silêncio: numa co-simulação, uma falha
  silenciosa produz um dia inteiro de dados errados sem nada no resultado que a
  denuncie
