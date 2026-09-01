"""Adaptador mosaik do inversor inteligente (IEEE 1547 via OpenDER).

Este é o único adaptador de inversor do projeto. A ``META`` é derivada dos
registros :data:`INPUT_SPECS` e :data:`OUTPUT_GETTERS` logo abaixo — o mesmo
princípio de ``opendss/element_specs.py``: um atributo não pode ser declarado
ao mosaik sem existir o código que o lê ou escreve.

Conexões típicas no cenário::

    world.connect(painel, inversor, ("P_dc", "P_dc"))
    world.connect(
        barra,
        inversor,
        ("V1_pu", "V_meas_1"),
        ("V2_pu", "V_meas_2"),
        ("V3_pu", "V_meas_3"),
        time_shifted=True,
        initial_data={"V1_pu": 1.0, "V2_pu": 1.0, "V3_pu": 1.0},
    )
    world.connect(inversor, pvsystem, ("P_ac_1", "P_des"), ("Q_ac_1", "Q_des"))

``P_ac_k`` / ``Q_ac_k`` são a injeção da **k-ésima unidade**, na ordem em que
``units`` foi passado — não da k-ésima fase. Para grandezas por fase da barra,
use ``P_phase_k`` / ``Q_phase_k``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

import mosaik_api_v3

from .config import ConfigError, ControlConfig, InverterUnit
from .opender_factory import set_time_step
from .smart_inverter import SmartInverterModel

logger = logging.getLogger(__name__)

# Uma barra trifásica comporta no máximo três unidades monofásicas
# distinguíveis; acima disso a injeção não teria como ser roteada de volta.
MAX_UNITS = 3

__all__ = ["META", "InverterSim", "SmartInverterSim", "main"]


# ----------------------------------------------------------------------
# Agregadores de entrada
# ----------------------------------------------------------------------


def _sum_values(attr: str, eid: str, values: Iterable[Any]) -> float:
    """Soma as contribuições de todas as fontes. Padrão para potência."""
    return float(sum(values))


def _single_value(attr: str, eid: str, values: Iterable[Any]) -> float:
    """Espera um valor. Somar tensão ou frequência não faz sentido físico."""
    items = list(values)
    if len(items) > 1:
        logger.warning(
            "[OpenTES][AVISO] %s.%s recebeu %d valores concorrentes (%s); usando o primeiro.",
            eid,
            attr,
            len(items),
            items,
        )
    return float(items[0])


#: Atributo de entrada -> ``(agregador, aplicador)``.
INPUT_SPECS: dict[str, tuple[Callable[..., float], Callable[[SmartInverterModel, float], None]]] = {
    "P_dc": (_sum_values, lambda m, v: setattr(m, "P_dc", v)),
    "Q_des": (_sum_values, lambda m, v: setattr(m, "Q_des", v)),
    "V_meas_1": (_single_value, lambda m, v: m.V_meas.__setitem__(0, v)),
    "V_meas_2": (_single_value, lambda m, v: m.V_meas.__setitem__(1, v)),
    "V_meas_3": (_single_value, lambda m, v: m.V_meas.__setitem__(2, v)),
    # Ângulos em graus (``V1_ang`` etc. da barra). Necessários só quando
    # ``ctrl_config.v_meas_unbalance == 'POS'``.
    "V_ang_1": (_single_value, lambda m, v: m.V_ang.__setitem__(0, v)),
    "V_ang_2": (_single_value, lambda m, v: m.V_ang.__setitem__(1, v)),
    "V_ang_3": (_single_value, lambda m, v: m.V_ang.__setitem__(2, v)),
    "f_meas": (_single_value, lambda m, v: setattr(m, "f_meas", v)),
}


def _unit_getter(index: int, attr: str) -> Callable[[SmartInverterModel], float]:
    """Injeção da k-ésima unidade; 0.0 quando a entidade tem menos unidades."""

    def get(model: SmartInverterModel) -> float:
        values = getattr(model, attr)
        return values[index] if index < len(values) else 0.0

    return get


#: Atributo de saída -> função que o extrai do modelo.
OUTPUT_GETTERS: dict[str, Callable[[SmartInverterModel], Any]] = {
    # Totais da entidade
    "P_ac": lambda m: m.P_ac,
    "Q_ac": lambda m: m.Q_ac,
    # Por unidade, na ordem de `units`
    **{f"P_ac_{k + 1}": _unit_getter(k, "unit_p") for k in range(MAX_UNITS)},
    **{f"Q_ac_{k + 1}": _unit_getter(k, "unit_q") for k in range(MAX_UNITS)},
    # Por fase da barra
    **{f"P_phase_{k + 1}": _unit_getter(k, "phase_p") for k in range(3)},
    **{f"Q_phase_{k + 1}": _unit_getter(k, "phase_q") for k in range(3)},
    # Diagnóstico do controle — sem eles não há como auditar por que Q vale o
    # que vale num resultado de 288 passos.
    "V_meas_pu": lambda m: m.v_meas_pu,
    "der_status": lambda m: m.der_status,
    "q_desired_pu": lambda m: m.q_desired_pu,
    "p_avl_pu": lambda m: m.p_avl_pu,
    "p_pv_limit_pu": lambda m: m.p_pv_limit_pu,
    "is_on": lambda m: m.is_on,
}

MODEL_PARAMS = (
    "units",
    "ctrl_config",
    "eff_curve_x",
    "eff_curve_y",
    "pct_cutin",
    "pct_cutout",
    # Atalho para o caso comum de uma única unidade
    "name",
    "kVA",
    "kW",
    "kv",
    "phases",
    "node",
    # Compatibilidade: os cenários anteriores passavam a prioridade solta.
    "priority",
)

#: Prioridade herdada dos cenários antigos -> ``ControlConfig.priority``.
_LEGACY_PRIORITY = {"ACTIVE": "ACTIVE", "REACTIVE": "REACTIVE"}

META = {
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "Inverter": {
            "public": True,
            "params": list(MODEL_PARAMS),
            "attrs": list(dict.fromkeys([*INPUT_SPECS, *OUTPUT_GETTERS])),
        },
    },
}


def _build_units(model_params: dict[str, Any]) -> list[InverterUnit]:
    """Resolve os parâmetros de criação em uma lista de unidades.

    Aceita ``units=[...]`` explícito ou o atalho de unidade única
    (``kVA``/``kv``/``phases``/``node``), que cobre o caso comum sem obrigar o
    cenário a montar a lista.
    """
    units = model_params.get("units")

    if units is None:
        kva = model_params.get("kVA")
        if kva is None:
            raise ConfigError("Informe 'units' ou o atalho de unidade única com 'kVA'.")
        units = [
            {
                "name": model_params.get("name", "Inverter"),
                "kva": kva,
                "kw": model_params.get("kW"),
                # Obrigatório apenas quando o OpenDER estiver ativo; a fábrica
                # cobra com uma mensagem específica se faltar.
                "kv": model_params.get("kv"),
                "phases": model_params.get("phases", 3),
                "node": model_params.get("node"),
            }
        ]

    resolved = [u if isinstance(u, InverterUnit) else InverterUnit.from_dict(u) for u in units]

    if len(resolved) > MAX_UNITS:
        raise ConfigError(
            f"Uma entidade Inverter comporta no máximo {MAX_UNITS} unidades "
            f"(recebidas {len(resolved)}), porque as saídas por unidade vão até "
            f"P_ac_{MAX_UNITS}. Crie entidades adicionais para as demais."
        )
    return resolved


def _build_ctrl(model_params: dict[str, Any]) -> ControlConfig:
    """Resolve ``ctrl_config``, absorvendo o parâmetro ``priority`` legado."""
    ctrl = ControlConfig.coerce(model_params.get("ctrl_config"))

    legacy = model_params.get("priority")
    if legacy is None:
        return ctrl

    mapped = _LEGACY_PRIORITY.get(str(legacy).upper())
    if mapped is None:
        raise ConfigError(f"priority deve ser 'Active' ou 'Reactive'; recebido {legacy!r}")
    if "ctrl_config" in model_params and ctrl.priority != mapped:
        raise ConfigError(
            f"priority={legacy!r} conflita com ctrl_config.priority={ctrl.priority!r}. "
            "Use apenas ctrl_config; 'priority' existe só para cenários anteriores."
        )
    return ControlConfig(**{**ctrl.to_dict(), "priority": mapped})


class SmartInverterSim(mosaik_api_v3.Simulator):
    """Simulador mosaik de inversores inteligentes."""

    def __init__(self) -> None:
        super().__init__(META)
        self.sid: str | None = None
        self.entities: dict[str, SmartInverterModel] = {}
        self.step_size: float = 1.0

    def init(self, sid, time_resolution=1.0, step_size=900, **sim_params):
        """Inicializa o simulador e fixa o passo global do OpenDER.

        Args:
            sid: Identificador do simulador no mosaik.
            time_resolution: Segundos por unidade de tempo do mosaik.
            step_size: Passo em unidades de tempo do mosaik.

        Returns:
            A ``META`` do simulador.
        """
        self.sid = sid
        self.step_size = step_size

        # `DER.t_s` é atributo de classe do OpenDER e precisa estar em segundos:
        # é ele que dita OLRT, rampa de entrada em serviço e os temporizadores
        # de trip. Sem isso, o default de 100 000 s torna todos eles inertes.
        set_time_step(float(step_size) * float(time_resolution))
        return self.meta

    def create(self, num, model, **model_params):
        if model != "Inverter":
            raise ValueError(f"modelo desconhecido: {model!r}")

        units = _build_units(model_params)
        ctrl = _build_ctrl(model_params)

        entities = []
        for _ in range(num):
            bus_name = model_params.get("bus_name", "")
                units=units,
                ctrl=ctrl,
                eff_curve_x=model_params.get("eff_curve_x"),
                eff_curve_y=model_params.get("eff_curve_y"),
                pct_cutin=model_params.get("pct_cutin", 0.0),
                pct_cutout=model_params.get("pct_cutout", 0.0),
                step_size=self.step_size,
            )
            self.entities[eid] = inverter
            entities.append({"eid": eid, "type": model})
            logger.info("[OpenTES][inversor] %s: %s", eid, inverter.describe())

            if inverter.uses_opender and inverter.relaxation_factor() >= 1.0:
                logger.info(
                    "[OpenTES][inversor] %s: resposta instantanea (OLRT < 1.15x o passo de "
                    "%.0fs). A realimentacao de tensao chega atrasada de um passo; se Q "
                    "oscilar, aumente VoltVarCurve.olrt.",
                    eid,
                    self.step_size,
                )

        return entities

    def step(self, time, inputs, max_advance):
        for eid, attrs in inputs.items():
            inverter = self.entities[eid]
            for attr, sources in attrs.items():
                spec = INPUT_SPECS.get(attr)
                if spec is None or not sources:
                    continue
                aggregate, apply = spec
                apply(inverter, aggregate(attr, eid, sources.values()))

        for inverter in self.entities.values():
            inverter.calculate_step()

        return time + self.step_size

    def get_data(self, outputs):
        data: dict[str, dict[str, Any]] = {}
        for eid, attrs in outputs.items():
            inverter = self.entities[eid]
            values = {}
            for attr in attrs:
                getter = OUTPUT_GETTERS.get(attr)
                if getter is not None:
                    values[attr] = getter(inverter)
            data[eid] = values
        return data


#: Nome histórico usado pelos cenários (``...smart_inverter_simulator:InverterSim``).
InverterSim = SmartInverterSim


def main():
    return mosaik_api_v3.start_simulation(SmartInverterSim())


if __name__ == "__main__":
    main()
