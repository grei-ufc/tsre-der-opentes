"""Declarative registry mapping mosaik models to OpenDSS elements.

This table is the single source of truth for what each model exposes. The
mosaik ``META``, the input routing in ``step()`` and the output reads in
``get_data()`` are all derived from it, so a declared attribute cannot drift
away from the code that implements it.

Adding a model means adding one :class:`ModelSpec` here — not editing META,
``step`` and ``get_data`` in three places and hoping they agree.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

# Fontes de leitura de um elemento, resolvidas sob demanda por `read_phases`.
SOURCE_P = "p"
SOURCE_Q = "q"
SOURCE_P_SUM = "p_sum"
SOURCE_Q_SUM = "q_sum"
SOURCE_I_MAG = "i_mag"
SOURCE_I_ANG = "i_ang"

_POWER_SOURCES = (SOURCE_P, SOURCE_Q, SOURCE_P_SUM, SOURCE_Q_SUM)


# ----------------------------------------------------------------------
# Agregadores de entrada
# ----------------------------------------------------------------------


def sum_values(attr: str, eid: str, values: Iterable[Any]) -> Any:
    """Soma as contribuições de todos os simuladores conectados.

    Padrão para setpoints de potência, onde vários controladores podem
    legitimamente contribuir para o mesmo elemento.
    """
    return sum(values)


def single_value(attr: str, eid: str, values: Iterable[Any]) -> Any:
    """Espera exatamente um valor; avisa e usa o primeiro se houver mais.

    Para grandezas em que somar não faz sentido físico (posição de tap, SoC
    alvo). Antes esses casos pegavam ``list(values)[0]`` silenciosamente, o que
    descartava comandos concorrentes sem deixar rastro.
    """
    values = list(values)
    if len(values) > 1:
        print(
            f"[OpenTES][AVISO] {eid}.{attr} recebeu {len(values)} valores "
            f"concorrentes ({values}); usando o primeiro."
        )
    return values[0]


# ----------------------------------------------------------------------
# Especificações
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class InputSpec:
    """Como um atributo de entrada do mosaik é reduzido a um único valor."""

    aggregator: Callable[[str, str, Iterable[Any]], Any] = sum_values


@dataclass(frozen=True)
class ModelSpec:
    """Contrato de um modelo mosaik atendido por este simulador.

    Attributes:
        dss_class: Classe OpenDSS correspondente (``None`` para ``Bus``, que
            não é um elemento de circuito).
        reader: ``(sim, name, attrs, spec) -> dict`` com os valores de saída.
        writer: ``(sim, name, values) -> None`` aplicando as entradas já
            agregadas; ``None`` para modelos somente de leitura.
        inputs: Atributos de entrada aceitos e como agregá-los.
        attr_map: Atributo de saída -> ``(fonte, índice, fator)``.
        extra_outputs: Saídas que o *reader* produz fora do ``attr_map``.
        terminal: Terminal lido (1 para elementos shunt, 1 ou 2 para linhas).
        public: Se o cenário pode instanciar o modelo diretamente.
        params: Parâmetros aceitos na criação.
    """

    dss_class: str | None
    reader: Callable[..., dict[str, Any]]
    writer: Callable[..., None] | None = None
    inputs: dict[str, InputSpec] = field(default_factory=dict)
    attr_map: dict[str, tuple[str, int, float]] = field(default_factory=dict)
    extra_outputs: tuple[str, ...] = ()
    terminal: int = 1
    public: bool = False
    params: tuple[str, ...] = ()

    @property
    def outputs(self) -> tuple[str, ...]:
        return tuple(self.attr_map) + self.extra_outputs

    @property
    def attrs(self) -> list[str]:
        """Todos os atributos do modelo, na ordem entradas -> saídas.

        Um atributo pode ser lido e escrito (``tap``), então a lista é
        deduplicada preservando a ordem.
        """
        return list(dict.fromkeys([*self.inputs, *self.outputs]))


def phase_attr_map(
    p: tuple[str, ...] = (),
    q: tuple[str, ...] = (),
    i_mag: tuple[str, ...] = (),
    i_ang: tuple[str, ...] = (),
    p_total: tuple[str, ...] = (),
    q_total: tuple[str, ...] = (),
    sign: int = 1,
    scale: float = 1.0,
) -> dict[str, tuple[str, int, float]]:
    """Monta o mapa atributo -> (fonte, índice, fator) de um elemento trifásico.

    Args:
        p, q: Nomes dos atributos de potência ativa/reativa por fase.
        i_mag, i_ang: Nomes dos atributos de módulo/ângulo de corrente por fase.
        p_total, q_total: Nomes dos atributos de total somado nas fases.
        sign: ``-1`` inverte a convenção do OpenDSS para injeção positiva.
        scale: Fator de unidade aplicado aos totais (ex.: ``1/1000`` para MW).

    Returns:
        Mapa pronto para ``ModelSpec.attr_map``.
    """
    mapping: dict[str, tuple[str, int, float]] = {}

    for source, names in ((SOURCE_P, p), (SOURCE_Q, q)):
        for index, attr in enumerate(names):
            mapping[attr] = (source, index, float(sign))

    # Correntes são magnitudes: a convenção de sinal não se aplica.
    for source, names in ((SOURCE_I_MAG, i_mag), (SOURCE_I_ANG, i_ang)):
        for index, attr in enumerate(names):
            mapping[attr] = (source, index, 1.0)

    for source, names in ((SOURCE_P_SUM, p_total), (SOURCE_Q_SUM, q_total)):
        for attr in names:
            mapping[attr] = (source, 0, sign * scale)

    return mapping


# ----------------------------------------------------------------------
# Leitores
# ----------------------------------------------------------------------


def read_phases(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê grandezas por fase de um elemento, buscando só as fontes necessárias.

    Potências e correntes vêm de chamadas distintas ao motor, então cada uma é
    buscada apenas se algum atributo pedido depender dela — e no máximo uma vez.
    """
    cache: dict[str, list[float]] = {}

    def source(kind: str) -> list[float]:
        if kind not in cache:
            if kind in _POWER_SOURCES:
                values_p, values_q = sim.dss_wrapper.get_phase_powers(
                    name, element=spec.dss_class, terminal=spec.terminal
                )
                cache[SOURCE_P] = values_p
                cache[SOURCE_Q] = values_q
                cache[SOURCE_P_SUM] = [sum(values_p)]
                cache[SOURCE_Q_SUM] = [sum(values_q)]
            else:
                mags, angs = sim.dss_wrapper.get_phase_currents(
                    name, element=spec.dss_class, terminal=spec.terminal
                )
                cache[SOURCE_I_MAG] = mags
                cache[SOURCE_I_ANG] = angs
        return cache[kind]

    result: dict[str, Any] = {}
    for attr in attrs:
        mapping = spec.attr_map.get(attr)
        if mapping is None:
            continue
        kind, index, factor = mapping
        result[attr] = source(kind)[index] * factor
    return result


def read_bus(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê tensões de barra; módulo e ângulo vêm de leituras em bloco distintas."""
    cache: dict[str, list[float]] = {}
    result: dict[str, Any] = {}

    for attr in attrs:
        mapping = spec.attr_map.get(attr)
        if mapping is None:
            continue
        kind, index, factor = mapping
        if kind not in cache:
            cache[kind] = (
                sim.dss_wrapper.get_bus_vmag_pu(name)
                if kind == "vmag"
                else sim.dss_wrapper.get_bus_vang(name)
            )
        result[attr] = cache[kind][index] * factor
    return result


def read_regulator(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê tensão, corrente e tap de um regulador."""
    wanted = {a for a in attrs if a in ("v_meas", "i_meas", "tap")}
    if not wanted:
        return {}

    info = sim.regulator_map.get(f"RegControl-{name}")
    if info is None:
        return {}

    measurements = sim.dss_wrapper.get_regulator_measurements(info)
    keys = {"v_meas": "v", "i_meas": "i", "tap": "tap"}
    return {attr: measurements[keys[attr]] for attr in wanted}


def read_storage(sim, name: str, attrs: Iterable[str], spec: ModelSpec) -> dict[str, Any]:
    """Lê grandezas por fase mais o estado de carga da bateria."""
    result = read_phases(sim, name, attrs, spec)
    if "SoC" in attrs:
        result["SoC"] = sim.dss_wrapper.get_storage_soc(name)
    return result


# ----------------------------------------------------------------------
# Escritores
# ----------------------------------------------------------------------


def write_tap(sim, name: str, values: dict[str, Any]) -> None:
    if "tap" in values:
        sim.dss_wrapper.set_tap(name=name, tap=int(values["tap"]))


def write_storage(sim, name: str, values: dict[str, Any]) -> None:
    """Aplica setpoints de potência e, se enviado, força o estado de carga.

    ``SoC_set`` existe para o padrão em que um modelo de bateria externo é dono
    da física e o elemento do OpenDSS apenas espelha o estado dele.
    """
    if "P_set" in values or "Q_set" in values:
        sim.dss_wrapper.set_power(
            name,
            p=values.get("P_set"),
            q=values.get("Q_set"),
            element="Storage",
        )

    if "SoC_set" in values:
        sim.dss_wrapper.set_storage_soc(name, values["SoC_set"])


def write_pvsystem(sim, name: str, values: dict[str, Any]) -> None:
    sim.dss_wrapper.set_pvsystem_pq(
        name,
        values.get("P_des", 0.0),
        values.get("Q_des", 0.0),
    )


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------

MODEL_SPECS: dict[str, ModelSpec] = {
    "Bus": ModelSpec(
        dss_class=None,
        reader=read_bus,
        attr_map={
            "V1_pu": ("vmag", 0, 1.0),
            "V2_pu": ("vmag", 1, 1.0),
            "V3_pu": ("vmag", 2, 1.0),
            "V1_ang": ("vang", 0, 1.0),
            "V2_ang": ("vang", 1, 1.0),
            "V3_ang": ("vang", 2, 1.0),
        },
    ),
    "Load": ModelSpec(
        dss_class="Load",
        reader=read_phases,
        # Convenção do OpenDSS: carga consome com sinal positivo.
        attr_map=phase_attr_map(
            p_total=("P_out_mw",),
            q_total=("Q_out_mvar",),
            scale=1 / 1000.0,
        ),
    ),
    "Line": ModelSpec(
        dss_class="Line",
        reader=read_phases,
        attr_map=phase_attr_map(
            p=("P1_w", "P2_w", "P3_w"),
            q=("Q1_var", "Q2_var", "Q3_var"),
            i_mag=("I1_A", "I2_A", "I3_A"),
            i_ang=("I1_ang", "I2_ang", "I3_ang"),
        ),
    ),
    "RegControl": ModelSpec(
        dss_class="RegControl",
        reader=read_regulator,
        writer=write_tap,
        inputs={"tap": InputSpec(aggregator=single_value)},
        extra_outputs=("tap", "v_meas", "i_meas"),
    ),
    "Storage": ModelSpec(
        dss_class="Storage",
        reader=read_storage,
        writer=write_storage,
        public=True,
        inputs={
            "P_set": InputSpec(),
            "Q_set": InputSpec(),
            "SoC_set": InputSpec(aggregator=single_value),
        },
        # sign=-1: injeção na rede é positiva para o cenário.
        attr_map=phase_attr_map(
            p=("P1", "P2", "P3"),
            q=("Q1", "Q2", "Q3"),
            i_mag=("I1_A", "I2_A", "I3_A"),
            p_total=("P_act",),
            q_total=("Q_act",),
            sign=-1,
        ),
        extra_outputs=("SoC",),
    ),
    "PVSystem": ModelSpec(
        dss_class="PVSystem",
        reader=read_phases,
        writer=write_pvsystem,
        public=True,
        inputs={"P_des": InputSpec(), "Q_des": InputSpec()},
        attr_map=phase_attr_map(
            p=("P1", "P2", "P3"),
            q=("Q1", "Q2", "Q3"),
            i_mag=("I1_A", "I2_A", "I3_A"),
            p_total=("P_meas",),
            q_total=("Q_meas",),
            sign=-1,
        ),
    ),
}


def build_meta() -> dict[str, Any]:
    """Gera a META do mosaik a partir do registry.

    Derivar em vez de escrever à mão é o que impede a META de declarar
    atributos que o simulador não produz.
    """
    models: dict[str, Any] = {
        "Grid": {
            "public": True,
            "params": ["topofile", "step_size", "output_graph_path"],
            "attrs": [],
        }
    }
    for model, spec in MODEL_SPECS.items():
        models[model] = {
            "public": spec.public,
            "params": list(spec.params),
            "attrs": spec.attrs,
        }

    return {
        "api_version": "3.0",
        "type": "time-based",
        "models": models,
        "extra_methods": [
            "get_dss_wrapper",
            "get_extra_info",
            "get_detected_regulators",
            "get_detected_pvsystems",
            "get_detected_storages",
        ],
    }
