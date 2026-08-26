# Conceitos de Co-Simulação

## O que é co-simulação

Co-simulação é uma abordagem de modelagem em que múltiplos simuladores executam simultaneamente e trocam dados entre si em passos de tempo discretos. Cada simulador é responsável por uma parte do sistema — por exemplo, um simulador de rede elétrica, um de geração fotovoltaica e um de controle de inversor.

No contexto de sistemas de distribuição, a co-simulação permite:

- Simular cada componente com o modelo mais adequado
- Testar estratégias de controle distribuídas
- Validar interações entre diferentes equipamentos
- Isolar efeitos de cada componente no sistema total

## Mosaik

[mosaik](https://mosaik.readthedocs.io/) é o framework de co-simulação utilizado neste projeto. Ele fornece:

- **World**: orquestrador que coordena a execução de todos os simuladores
- **Simulators**: processos individuais que implementam a API do mosaik
- **Conexões**: canais de dados entre entidades de diferentes simuladores
- **Step**: sincronização temporal entre simuladores

### API v3

O projeto utiliza a versão 3.0 da API do mosaik (`mosaik_api_v3`). Cada adaptador implementa:

```python
class MeuSimulador(mosaik_api_v3.Simulator):
    def init(self, sid, time_resolution, **kwargs):
        # Configuração inicial
        pass

    def create(self, num, model, **kwargs):
        # Criar entidades
        pass

    def step(self, time, inputs, max_advance):
        # Executar um passo de simulação
        return time + step_size

    def get_data(self, outputs):
        # Retornar dados das entidades
        return data
```

### META dict

Todo adaptador mosaik deve declarar um `META` dict:

```python
META = {
    "api_version": "3.0",
    "type": "time-based",  # ou "event-based" ou "hybrid"
    "models": {
        "ModelName": {
            "public": True,       # acessível para conexões externas
            "params": [...],      # parâmetros de criação
            "attrs": [...],       # atributos de entrada/saída
        }
    }
}
```

## Tipos de simulador mosaik

| Tipo | Comportamento | Exemplo no projeto |
|---|---|---|
| `time-based` | Executa `step()` a cada passo de tempo fixo | OpenDSS, Inverter, PV Panel |
| `event-based` | Recebe eventos, não avança tempo próprio | Collector |
| `hybrid` | Combina ambos; avança tempo com base em dados externos | CSV Reader |

## Conexões no mosaik

### Conexão padrão (mesmo tempo)

```python
world.connect(pv_panel, inverter, ("P_dc", "P_dc"))
```

Os dados são trocados no mesmo passo de tempo. Funciona quando não há ciclos causais.

### Conexão com time_shifted

```python
world.connect(bus, inverter, ("V1_pu", "V_meas_1"), time_shifted=True, initial_data={"V_meas_1": 1.0})
```

Usa o valor do **passo anterior**, quebrando ciclos causais. Essencial para feedback de tensão no controle inteligente.

### Conexão many-to-one

```python
mosaik.util.connect_many_to_one(world, lines, monitor, "loading_percent")
```

Conecta múltiplas entidades a uma única entidade de destino.

### Conexão weak

```python
world.connect(controller, generator, ("p_mw", "p_mw"), weak=True)
```

Permite que a conexão não bloqueie se o destino não consumir o valor.

## Resolução de tempo

O `step_size` define o intervalo entre passos de simulação. Nos cenários deste projeto:

| Cenário | Step Size | Passos | Tempo total |
|---|---|---|---|
| 13-bus (base) | 600s (10 min) | 144 | 24h |
| 123-bus / 34-bus | 300s (5 min) | 288 | 24h |
| LV-rural (legado) | 60s | 3600 | 1h |

A simulação avança em **snapshot**: a cada passo, o OpenDSS resolve o fluxo de potência para o instante correspondente.

## OpenDSS

[OpenDSS](https://www.epri.com/pages/sa/opendss) é um motor de simulação de sistemas de distribuição elétrica desenvolvido pelo EPRI. Ele:

- Resolve fluxo de potência em regime permanente (snapshot)
- Suporta elementos trifásicos e monofásicos
- Oferece controle nativo de PVSystem, Storage, RegControl
- É acessado via `py-dss-interface` (wrapper Python)

Neste projeto, o OpenDSS é a **fonte de verdade** para o estado da rede elétrica. Os demais simuladores enviam comandos (potência, tap) e recebem medições (tensão, corrente).

## OpenDER

[OpenDER](https://github.com/epri-dev/OpenDER) é uma biblioteca que implementa as curvas de controle do padrão **IEEE 1547** para inversores inteligentes:

- **Volt-Var**: injeta/absorve reativa com base na tensão
- **Volt-Watt**: limita potência ativa com base na tensão
- **Constant PF**: mantém fator de potência fixo

O OpenDER é utilizado pelo `SmartInverterModel` quando o cenário passa um
`ctrl_config`. A configuração é declarativa e validada — ver
[Inversor Inteligente — Referência](../reference/inverter-model.md):

```python
ControlConfig(
    reactive_mode=ReactiveMode.VOLT_VAR,
    volt_var=VoltVarCurve.ieee1547_cat_b(olrt=2 * STEP_SIZE),
)
```

Os modos de reativo são mutuamente exclusivos; volt-watt é função de potência
ativa e opera em paralelo a qualquer um deles.
