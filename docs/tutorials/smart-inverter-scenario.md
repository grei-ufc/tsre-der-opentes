# Cenário Inversor Inteligente

Este tutorial explica como usar o inversor smart com controle IEEE 1547 (Volt-Var) no cenário 123-bus.

## Objetivo

Executar um cenário com inversor inteligente que ajusta a injeção de reativa com base na tensão da barra (controle Volt-Var).

## Pré-requisitos

- Familiaridade com o [Pipeline PV Local](pv-pipeline-local.md)
- Ambiente instalado

## Diferença entre inversor padrão e smart

| Característica | Padrão | Smart |
|---|---|---|
| Controle | P/Q fixo | Volt-Var / Volt-Watt / Const PF |
| Entradas | P_dc | P_dc + V_meas (tensão da barra) |
| Saídas | P_ac, Q_ac | P_ac, Q_ac (total e por fase) |
| OpenDER | Não | Sim |
| Feedback | Não | Sim (time_shifted) |
| Adaptador | `smart_inverter_simulator.py` (o mesmo, sem `ctrl_config`) | `smart_inverter_simulator.py` |

## Configuração do controle

A configuração é declarativa e validada na construção do cenário — uma curva
malformada levanta `ConfigError` em vez de produzir um fluxo de potência
silenciosamente errado.

```python
from simulators.inverter.config import (
    ControlConfig, InverterUnit, ReactiveMode, VoltVarCurve,
)

STEP_SIZE = 60 * 5

CONTROLE = ControlConfig(
    reactive_mode=ReactiveMode.VOLT_VAR,
    volt_var=VoltVarCurve.ieee1547_cat_b(olrt=2 * STEP_SIZE),
    trip_enabled=False,
)

inv_obj = inv_sim.Inverter.create(
    1,
    units=[u.to_dict() for u in units],
    ctrl_config=CONTROLE.to_dict(),
    eff_curve_x=[0, 0.2, 0.4, 1.0],
    eff_curve_y=[0.86, 0.90, 0.93, 0.97],
    pct_cutin=info["pct_cutin"],
    pct_cutout=info["pct_cutout"],
)[0]
```

Os modos de reativo são **mutuamente exclusivos** — o `ReactiveMode` torna isso
explícito, porque no OpenDER habilitar dois desliga um deles em silêncio.
Volt-watt é função de potência ativa e é ortogonal: entra como `volt_watt=` e
pode operar junto com qualquer modo.

Detalhes de todos os parâmetros em
[Inversor Inteligente — Referência](../reference/inverter-model.md); o passo a
passo de ligação está em
[Configurar um Inversor Inteligente](../how-to-guides/configure-smart-inverter.md).

## Agrupamento topológico

O cenário `opendss_scenario_123bus_smart_pv.py` agrupa por barra: vários
`PVSystem` na mesma barra viram uma entidade `Inverter`, mas **cada um mantém
seu próprio objeto OpenDER**, medindo a tensão da sua fase.

```
Bus.1.2.3:
  ├── PVSystem.1  (fase 1) → InverterUnit(phases=1, node=1) → DER_PV monofásico
  ├── PVSystem.2  (fase 2) → InverterUnit(phases=1, node=2) → DER_PV monofásico
  └── PVSystem.3  (fase 3) → InverterUnit(phases=1, node=3) → DER_PV monofásico
```

A injeção volta para cada `PVSystem` por `P_ac_k` / `Q_ac_k`, onde `k` é a
posição da unidade na lista `units` — não o número da fase.

## Conexões de feedback

O inversor smart recebe tensão medida do OpenDSS via `time_shifted=True`:

```python
world.connect(
    bus_entity, inverter_entity,
    ("V1_pu", "V_meas_1"),
    time_shifted=True,
    initial_data={"V_meas_1": 1.0}
)
```

Isso usa a tensão do **passo anterior**, quebrando o ciclo causal (o inversor afeta a tensão via potência injetada, que por sua vez afeta o inversor).

## Executar

```bash
# Local (123-bus)
uv run --no-sync python scenarios/opendss_scenario_123bus_smart_pv.py

# Docker (13-bus)
docker compose up -d
uv run --no-sync python scenarios/scenario_13bus_smart_pv_docker.py
```

## Configuração do smart inverter no Docker

O smart inverter roda na porta **5680** (não 5677 como o padrão):

```python
SIM_CONFIG = {
    "InverterSim": {"connect": "localhost:5680"},  # smart inverter
}
```

No `docker-compose.yml`, o serviço `smart-inverter` usa:

```yaml
smart-inverter:
  command: python -m simulators.inverter.smart_inverter_simulator --remote 0.0.0.0:5680
```
