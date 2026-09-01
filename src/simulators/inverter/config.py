"""Configuração declarativa das funções de controle do inversor inteligente.

Este módulo é a única fonte de verdade sobre *o que* o inversor controla. Ele
não conhece o OpenDER: traduz a intenção do cenário (curvas, modo, política de
trip) em estruturas validadas, e :mod:`.opender_factory` faz a tradução para os
parâmetros do ``DERCommonFileFormat``.

A separação existe por um motivo concreto: os setters do OpenDER apenas
*avisam* (``logging.warning``) quando um ajuste está fora da faixa da IEEE
1547-2018 — um alimentador com 100 inversores produz avisos que se perdem no
log e um fluxo de potência silenciosamente errado. Aqui, erro estrutural
levanta :class:`ConfigError` na construção do cenário.

Todas as classes são serializáveis por :meth:`to_dict` / :meth:`from_dict`, de
modo que um cenário possa passá-las como parâmetro de ``create()`` tanto para
um simulador local quanto para um container remoto (o mosaik serializa os
parâmetros em JSON no transporte remoto).
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

# Faixas da IEEE 1547-2018 verificadas pelo OpenDER (Cláusulas 5.3.3 e 5.4.2).
QV_OLRT_RANGE = (1.0, 90.0)
PV_OLRT_RANGE = (0.5, 60.0)
QV_V1_MIN = 0.82
QV_V2_RANGE = (0.97, 1.00)
QV_V3_RANGE = (1.00, 1.03)
QV_V4_MAX = 1.18
PV_V1_RANGE = (1.05, 1.09)
PV_V2_MAX = 1.10

# Limiares usados para desativar a proteção de trip.
#
# Esticar a *duração* não funciona: o temporizador de ``ConditionalDelay``
# começa em ``math.inf``, então a primeira avaliação verdadeira já satisfaz
# qualquer duração, por maior que seja. Só afastar o limiar impede a condição
# de ficar verdadeira.
TRIP_DISABLED_OVERVOLTAGE = 99.0
TRIP_DISABLED_UNDERVOLTAGE = 0.0
TRIP_DISABLED_OVERFREQUENCY = 9999.0
TRIP_DISABLED_UNDERFREQUENCY = 0.0

__all__ = [
    "ConfigError",
    "ConstPF",
    "ConstQ",
    "ControlConfig",
    "InverterUnit",
    "PhaseMode",
    "ReactiveMode",
    "VoltVarCurve",
    "VoltWattCurve",
]


class ConfigError(ValueError):
    """Configuração estruturalmente inválida, detectada antes de simular."""


class ReactiveMode(StrEnum):
    """Modo de potência reativa.

    É um enum, e não um conjunto de flags, porque o OpenDER resolve os modos
    por prioridade fixa (``CONST_PF > VOLT_VAR > WATT_VAR > CONST_Q``, veja
    ``q_funcs.calculate_q_desired_pu``): habilitar dois modos desliga um deles
    em silêncio. O enum torna a exclusividade explícita na API.

    Volt-watt **não** aparece aqui: é uma função de potência ativa e portanto
    ortogonal ao modo de reativo — os dois podem operar juntos.
    """

    NONE = "none"
    VOLT_VAR = "volt_var"
    CONST_PF = "const_pf"
    CONST_Q = "const_q"


class PhaseMode(StrEnum):
    """Como uma unidade se conecta à rede."""

    THREE = "THREE"
    SINGLE = "SINGLE"


def _as_floats(values: Sequence[float], name: str, count: int) -> tuple[float, ...]:
    try:
        out = tuple(float(v) for v in values)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name}: todos os pontos devem ser numéricos ({values!r})") from exc
    if len(out) != count:
        raise ConfigError(f"{name}: esperados {count} pontos, recebidos {len(out)} ({out})")
    return out


def _require_increasing(values: tuple[float, ...], name: str) -> None:
    for lo, hi in itertools.pairwise(values):
        if hi <= lo:
            raise ConfigError(
                f"{name}: tensões devem ser estritamente crescentes, recebido {values}"
            )


def _require_non_decreasing(values: tuple[float, ...], name: str) -> None:
    for lo, hi in itertools.pairwise(values):
        if hi < lo:
            raise ConfigError(f"{name}: tensões não podem decrescer, recebido {values}")


def _advise(condition: bool, message: str, strict: bool) -> None:
    """Sinaliza um desvio da IEEE 1547 sem impedir o uso deliberado dele."""
    if condition:
        return
    if strict:
        raise ConfigError(message)
    logger.info("[OpenTES][IEEE1547] %s", message)


@dataclass(frozen=True)
class VoltVarCurve:
    """Curva volt-var de quatro pontos (IEEE 1547-2018, Cláusula 5.3.3).

    Attributes:
        v: Tensões ``(V1, V2, V3, V4)`` em pu da tensão nominal, crescentes.
        q: Potências ``(Q1, Q2, Q3, Q4)`` em pu de ``S_nom``, não crescentes.
            Positivo injeta reativo (eleva a tensão), negativo absorve.
        olrt: Tempo de resposta em malha aberta, em segundos. Veja a nota de
            convergência em :meth:`relaxation_factor`.
        vref: Tensão de referência; desloca a curva inteira por ``vref - 1``.
        vref_auto: Se ``True``, ``vref`` acompanha a média móvel da tensão
            medida (constante de tempo ``vref_time``), limitada a
            ``[vref_min, vref_max]``.
    """

    v: tuple[float, ...] = (0.92, 0.98, 1.02, 1.08)
    q: tuple[float, ...] = (0.44, 0.0, 0.0, -0.44)
    olrt: float = 5.0
    vref: float = 1.0
    vref_auto: bool = False
    vref_time: float = 300.0
    vref_min: float = 0.95
    vref_max: float = 1.05
    strict_ieee1547: bool = False

    def __post_init__(self) -> None:
        v = _as_floats(self.v, "VoltVarCurve.v", 4)
        q = _as_floats(self.q, "VoltVarCurve.q", 4)
        object.__setattr__(self, "v", v)
        object.__setattr__(self, "q", q)

        # V2 e V3 delimitam a banda morta, que pode ter largura zero — é o caso
        # da curva padrão da Categoria A, com V2 = V3 = 1.0 pu. Os segmentos
        # inclinados, esses, precisam de largura para ter inclinação definida.
        _require_non_decreasing(v, "VoltVarCurve.v")
        if v[0] >= v[1]:
            raise ConfigError(f"VoltVarCurve.v: V1 deve ser menor que V2; recebido {v}")
        if v[2] >= v[3]:
            raise ConfigError(f"VoltVarCurve.v: V3 deve ser menor que V4; recebido {v}")

        # Volt-var é um droop: Q tem de cair (ou ficar plana) com V crescente.
        # Uma curva crescente realimenta positivamente a tensão e diverge.
        for lo, hi in itertools.pairwise(q):
            if hi > lo:
                raise ConfigError(
                    f"VoltVarCurve.q deve ser não crescente (droop); recebido {q}. "
                    "Uma curva crescente realimenta a tensão positivamente e diverge."
                )
        if any(abs(x) > 1.0 for x in q):
            raise ConfigError(
                f"VoltVarCurve.q: valores em pu de S_nom devem estar em [-1, 1]; recebido {q}"
            )
        if q[0] < 0:
            raise ConfigError(
                f"VoltVarCurve.q: Q1 (subtensão) não pode absorver reativo; recebido Q1={q[0]}"
            )
        if q[3] > 0:
            raise ConfigError(
                f"VoltVarCurve.q: Q4 (sobretensão) não pode injetar reativo; recebido Q4={q[3]}"
            )
        if self.olrt <= 0:
            raise ConfigError(f"VoltVarCurve.olrt deve ser > 0; recebido {self.olrt}")
        if not (self.vref_min <= self.vref <= self.vref_max):
            raise ConfigError(
                f"VoltVarCurve.vref={self.vref} fora de [{self.vref_min}, {self.vref_max}]"
            )

        s = self.strict_ieee1547
        _advise(v[0] >= QV_V1_MIN, f"QV_CURVE_V1={v[0]} abaixo de {QV_V1_MIN} (Cláusula 5.3.3)", s)
        _advise(
            QV_V2_RANGE[0] <= v[1] <= QV_V2_RANGE[1], f"QV_CURVE_V2={v[1]} fora de {QV_V2_RANGE}", s
        )
        _advise(
            QV_V3_RANGE[0] <= v[2] <= QV_V3_RANGE[1], f"QV_CURVE_V3={v[2]} fora de {QV_V3_RANGE}", s
        )
        _advise(v[3] <= QV_V4_MAX, f"QV_CURVE_V4={v[3]} acima de {QV_V4_MAX}", s)
        _advise(
            QV_OLRT_RANGE[0] <= self.olrt <= QV_OLRT_RANGE[1],
            f"QV_OLRT={self.olrt}s fora de {QV_OLRT_RANGE}s da IEEE 1547; "
            "aceitável como relaxação numérica deliberada (veja relaxation_factor)",
            s,
        )

    # -- Presets ------------------------------------------------------

    @classmethod
    def ieee1547_cat_b(cls, **overrides: Any) -> VoltVarCurve:
        """Curva padrão da Categoria B (Tabela 8 da IEEE 1547-2018)."""
        return cls(v=(0.92, 0.98, 1.02, 1.08), q=(0.44, 0.0, 0.0, -0.44), **overrides)

    @classmethod
    def ieee1547_cat_a(cls, **overrides: Any) -> VoltVarCurve:
        """Curva padrão da Categoria A (Tabela 8 da IEEE 1547-2018)."""
        return cls(v=(0.90, 1.00, 1.00, 1.10), q=(0.25, 0.0, 0.0, -0.25), **overrides)

    # -- Consultas ----------------------------------------------------

    def q_at(self, v_pu: float) -> float:
        """Q em pu de ``S_nom`` para a tensão dada, ignorando OLRT e ``vref``.

        Espelha ``volt_var.calculate_q_qv_desired_var`` e existe para os testes
        e para inspeção no cenário, sem precisar instanciar um DER.
        """
        v, q = self.v, self.q
        if v_pu < v[0]:
            return q[0]
        if v_pu >= v[3]:
            return q[3]
        for i in range(3):
            if v[i] <= v_pu < v[i + 1]:
                span = v[i + 1] - v[i]
                return q[i] - (v_pu - v[i]) / span * (q[i] - q[i + 1])
        return q[3]

    def relaxation_factor(self, step_size: float) -> float:
        """Fração da variação de Q aplicada em um passo, aproximadamente.

        O laço volt-var ↔ fluxo de potência é realimentado com atraso de um
        passo (``time_shifted=True``). O filtro de primeira ordem do OpenDER é
        o que amortece esse laço — o equivalente ao ``delta_q=0.2`` que o
        ``OpenDER_interface`` da EPRI aplica ao iterar dentro do passo.

        Retorna ``1.0`` quando ``olrt < 1.15 * step_size``, caso em que o filtro
        do OpenDER é curto-circuitado (``low_pass_filter``) e a resposta é
        instantânea — sem amortecimento nenhum.
        """
        if step_size <= 0:
            return 1.0
        if self.olrt < 1.15 * step_size:
            return 1.0
        tau = self.olrt / 1.15
        return step_size / (step_size + tau)

    # -- Serialização -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": list(self.v),
            "q": list(self.q),
            "olrt": self.olrt,
            "vref": self.vref,
            "vref_auto": self.vref_auto,
            "vref_time": self.vref_time,
            "vref_min": self.vref_min,
            "vref_max": self.vref_max,
            "strict_ieee1547": self.strict_ieee1547,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoltVarCurve:
        return cls(**data)

    def as_der_params(self) -> dict[str, Any]:
        """Parâmetros do ``DERCommonFileFormat``, em ordem segura de escrita.

        A ordem importa: o setter de ``QV_CURVE_V1`` compara com ``V2`` e o de
        ``V4`` compara com ``V3``. Escrever V2 e V3 antes evita avisos espúrios
        sobre uma curva que é válida.
        """
        v, q = self.v, self.q
        return {
            "QV_MODE_ENABLE": True,
            "QV_CURVE_V2": v[1],
            "QV_CURVE_V3": v[2],
            "QV_CURVE_V1": v[0],
            "QV_CURVE_V4": v[3],
            "QV_CURVE_Q1": q[0],
            "QV_CURVE_Q2": q[1],
            "QV_CURVE_Q3": q[2],
            "QV_CURVE_Q4": q[3],
            "QV_OLRT": self.olrt,
            "QV_VREF": self.vref,
            "QV_VREF_AUTO_MODE": self.vref_auto,
            "QV_VREF_TIME": self.vref_time,
            "QV_VREF_MIN": self.vref_min,
            "QV_VREF_MAX": self.vref_max,
        }


@dataclass(frozen=True)
class VoltWattCurve:
    """Curva volt-watt de dois pontos (IEEE 1547-2018, Cláusula 5.4.2).

    Produz um *limite* de potência ativa, não um setpoint: o OpenDER calcula
    ``p_desired = min(p_disponível, p_entrada_em_serviço, p_limite_vw, 1)``.

    Attributes:
        v: Tensões ``(V1, V2)`` em pu, crescentes.
        p: Limites ``(P1, P2)`` em pu de ``P_nom``, não crescentes.
        olrt: Tempo de resposta em malha aberta, em segundos.
    """

    v: tuple[float, ...] = (1.06, 1.10)
    p: tuple[float, ...] = (1.0, 0.2)
    olrt: float = 10.0
    strict_ieee1547: bool = False

    def __post_init__(self) -> None:
        v = _as_floats(self.v, "VoltWattCurve.v", 2)
        p = _as_floats(self.p, "VoltWattCurve.p", 2)
        object.__setattr__(self, "v", v)
        object.__setattr__(self, "p", p)

        _require_increasing(v, "VoltWattCurve.v")
        if p[1] > p[0]:
            raise ConfigError(
                f"VoltWattCurve.p deve ser não crescente; recebido {p}. "
                "Volt-watt reduz a potência quando a tensão sobe."
            )
        if not all(0.0 <= x <= 1.0 for x in p):
            raise ConfigError(
                f"VoltWattCurve.p: valores em pu de P_nom devem estar em [0, 1]; recebido {p}"
            )
        if self.olrt <= 0:
            raise ConfigError(f"VoltWattCurve.olrt deve ser > 0; recebido {self.olrt}")

        s = self.strict_ieee1547
        _advise(
            PV_V1_RANGE[0] <= v[0] <= PV_V1_RANGE[1], f"PV_CURVE_V1={v[0]} fora de {PV_V1_RANGE}", s
        )
        _advise(v[1] <= PV_V2_MAX, f"PV_CURVE_V2={v[1]} acima de {PV_V2_MAX}", s)
        _advise(
            PV_OLRT_RANGE[0] <= self.olrt <= PV_OLRT_RANGE[1],
            f"PV_OLRT={self.olrt}s fora de {PV_OLRT_RANGE}s da IEEE 1547; "
            "aceitável como relaxação numérica deliberada",
            s,
        )

    @classmethod
    def ieee1547_default(cls, **overrides: Any) -> VoltWattCurve:
        return cls(v=(1.06, 1.10), p=(1.0, 0.2), **overrides)

    def p_limit_at(self, v_pu: float) -> float:
        """Limite de P em pu de ``P_nom``, ignorando OLRT. Espelha ``volt_watt``."""
        v, p = self.v, self.p
        if v_pu <= v[0]:
            return p[0]
        if v_pu >= v[1]:
            return p[1]
        return p[0] - (v_pu - v[0]) / (v[1] - v[0]) * (p[0] - p[1])

    def relaxation_factor(self, step_size: float) -> float:
        """Ver :meth:`VoltVarCurve.relaxation_factor`."""
        if step_size <= 0:
            return 1.0
        if self.olrt < 1.15 * step_size:
            return 1.0
        tau = self.olrt / 1.15
        return step_size / (step_size + tau)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": list(self.v),
            "p": list(self.p),
            "olrt": self.olrt,
            "strict_ieee1547": self.strict_ieee1547,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoltWattCurve:
        return cls(**data)

    def as_der_params(self) -> dict[str, Any]:
        """Parâmetros do ``DERCommonFileFormat``, em ordem segura de escrita.

        ``PV_CURVE_P1`` compara com ``P2`` e ``PV_CURVE_V2`` compara com ``V1``,
        então P2 e V1 vão primeiro.
        """
        v, p = self.v, self.p
        return {
            "PV_MODE_ENABLE": True,
            "PV_CURVE_V1": v[0],
            "PV_CURVE_V2": v[1],
            "PV_CURVE_P2": p[1],
            "PV_CURVE_P1": p[0],
            "PV_OLRT": self.olrt,
        }


@dataclass(frozen=True)
class ConstPF:
    """Fator de potência constante.

    Attributes:
        pf: Fator de potência em ``(0, 1]``.
        excitation: ``'INJ'`` injeta reativo, ``'ABS'`` absorve.
    """

    pf: float = 1.0
    excitation: str = "ABS"

    def __post_init__(self) -> None:
        if not (0.0 < self.pf <= 1.0):
            raise ConfigError(f"ConstPF.pf deve estar em (0, 1]; recebido {self.pf}")
        exc = str(self.excitation).upper()
        if exc not in ("INJ", "ABS"):
            raise ConfigError(
                f"ConstPF.excitation deve ser 'INJ' ou 'ABS'; recebido {self.excitation!r}"
            )
        object.__setattr__(self, "excitation", exc)

    def to_dict(self) -> dict[str, Any]:
        return {"pf": self.pf, "excitation": self.excitation}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstPF:
        return cls(**data)

    def as_der_params(self) -> dict[str, Any]:
        return {
            "CONST_PF_MODE_ENABLE": True,
            "CONST_PF": self.pf,
            "CONST_PF_EXCITATION": self.excitation,
        }


@dataclass(frozen=True)
class ConstQ:
    """Potência reativa constante, em pu de ``S_nom`` (positivo injeta)."""

    q: float = 0.0

    def __post_init__(self) -> None:
        if abs(self.q) > 1.0:
            raise ConfigError(f"ConstQ.q em pu de S_nom deve estar em [-1, 1]; recebido {self.q}")

    def to_dict(self) -> dict[str, Any]:
        return {"q": self.q}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstQ:
        return cls(**data)

    def as_der_params(self) -> dict[str, Any]:
        return {"CONST_Q_MODE_ENABLE": True, "CONST_Q": self.q}


@dataclass(frozen=True)
class InverterUnit:
    """Uma unidade física de inversor — tipicamente um ``PVSystem`` do circuito.

    Attributes:
        name: Nome do elemento no OpenDSS, usado em mensagens de diagnóstico.
        kva: Potência aparente nominal, em kVA.
        kv: Tensão nominal em kV — **linha-linha** se trifásica, **linha-neutro**
            se monofásica. É a base de ``v_pu`` e portanto obrigatória sempre
            que alguma função do OpenDER estiver ativa; sem controle de rede
            ela é irrelevante e pode ficar em ``None``.
        phases: 1 ou 3.
        node: Nó da barra (1, 2 ou 3) quando monofásica; ignorado se trifásica.
        kw: Potência ativa nominal em kW; ``None`` usa ``kva``.
        q_inj_pu, q_abs_pu: Capacidade de injeção/absorção de reativo em pu de
            ``kva``. O default 0.44 é o mínimo exigido pela IEEE 1547 Cat. B.
    """

    name: str
    kva: float
    kv: float | None = None
    phases: int = 3
    node: int | None = None
    kw: float | None = None
    q_inj_pu: float = 0.44
    q_abs_pu: float = 0.44

    def __post_init__(self) -> None:
        if self.kva <= 0:
            raise ConfigError(f"InverterUnit {self.name!r}: kva deve ser > 0; recebido {self.kva}")
        if self.kv is not None and self.kv <= 0:
            raise ConfigError(
                f"InverterUnit {self.name!r}: kv deve ser > 0 ou None; recebido {self.kv}"
            )
        if self.phases not in (1, 3):
            raise ConfigError(
                f"InverterUnit {self.name!r}: phases deve ser 1 ou 3; recebido {self.phases}"
            )
        if self.phases == 1 and self.node not in (1, 2, 3):
            raise ConfigError(
                f"InverterUnit {self.name!r}: unidade monofásica exige node em (1, 2, 3); "
                f"recebido {self.node!r}"
            )
        if self.kw is not None and self.kw <= 0:
            raise ConfigError(
                f"InverterUnit {self.name!r}: kw deve ser > 0 ou None; recebido {self.kw}"
            )
        for label, value in (("q_inj_pu", self.q_inj_pu), ("q_abs_pu", self.q_abs_pu)):
            if not (0.0 < value <= 1.0):
                raise ConfigError(
                    f"InverterUnit {self.name!r}: {label} deve estar em (0, 1]; recebido {value}"
                )

    @property
    def phase_mode(self) -> PhaseMode:
        return PhaseMode.SINGLE if self.phases == 1 else PhaseMode.THREE

    @property
    def kw_rating(self) -> float:
        return self.kva if self.kw is None else self.kw

    @property
    def nodes(self) -> tuple[int, ...]:
        """Nós de fase ocupados por esta unidade."""
        return (self.node,) if self.phases == 1 else (1, 2, 3)  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kva": self.kva,
            "kv": self.kv,
            "phases": self.phases,
            "node": self.node,
            "kw": self.kw,
            "q_inj_pu": self.q_inj_pu,
            "q_abs_pu": self.q_abs_pu,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InverterUnit:
        return cls(**data)


@dataclass(frozen=True)
class ControlConfig:
    """Configuração completa de controle de um inversor inteligente.

    Attributes:
        reactive_mode: Qual função de reativo está ativa. Exclusiva por
            construção — veja :class:`ReactiveMode`.
        volt_var: Curva usada quando ``reactive_mode`` é ``VOLT_VAR``.
        volt_watt: Curva volt-watt. Ortogonal ao modo de reativo: pode estar
            ativa junto com qualquer um deles, ou sozinha.
        const_pf: Ajuste usado quando ``reactive_mode`` é ``CONST_PF``.
        const_q: Ajuste usado quando ``reactive_mode`` é ``CONST_Q``.
        trip_enabled: Proteção de sub/sobretensão e frequência da IEEE 1547.
            Com passo de 5 min, um único instante acima de ``OV1_TRIP_V``
            (1.1 pu por padrão) derruba o DER por ~15 min. Estudos de
            capacidade de hospedagem normalmente querem ``False``; o default
            ``True`` mantém a aderência à norma. Desativar afeta apenas o
            *trip*: os modos de ride-through continuam ativos e ainda podem
            bloquear a saída em tensões extremas (acima de ~1.2 pu), que é o
            comportamento fisicamente correto.
        priority: ``'REACTIVE'`` reduz P para caber no círculo de S,
            ``'ACTIVE'`` reserva a Q mínima da Tabela 7 e dá o resto a P.
        v_meas_unbalance: ``'AVG'`` responde à média das três fases,
            ``'POS'`` à componente de sequência positiva.
        normal_op_cat: ``'CAT_A'`` ou ``'CAT_B'`` (capacidade de reativo).
        abnormal_op_cat: ``'CAT_I'``, ``'CAT_II'`` ou ``'CAT_III'`` (ride-through).
        q_capability_low_p: Capacidade de reativo em baixa potência ativa.
            ``'REDUCED'`` (default do OpenDER) zera a capacidade abaixo de
            0.05 pu de P — ou seja, **o inversor não faz volt-var à noite**.
            ``'SAME'`` mantém a capacidade plena em qualquer P, que é o
            comportamento de inversores que suportam operação noturna.
        frequency_hz: Frequência aplicada às entradas do DER.
        p_min_pu: ``NP_P_MIN_PU``. Mantenha em 0 quando o corte de entrada for
            modelado pelo :class:`~.smart_inverter.SmartInverterModel` (histerese
            ``%cutin``/``%cutout`` do OpenDSS), para não haver dois limiares.
        efficiency: ``NP_EFFICIENCY``. Mantenha em 1.0 quando a curva de
            eficiência for aplicada pelo modelo do inversor, sob pena de o
            rendimento ser contado duas vezes.
    """

    reactive_mode: ReactiveMode = ReactiveMode.NONE
    volt_var: VoltVarCurve | None = None
    volt_watt: VoltWattCurve | None = None
    const_pf: ConstPF | None = None
    const_q: ConstQ | None = None
    trip_enabled: bool = True
    priority: str = "REACTIVE"
    v_meas_unbalance: str = "AVG"
    normal_op_cat: str = "CAT_B"
    abnormal_op_cat: str = "CAT_II"
    q_capability_low_p: str = "REDUCED"
    frequency_hz: float = 60.0
    p_min_pu: float = 0.0
    efficiency: float = 1.0
    extra_der_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        mode = ReactiveMode(self.reactive_mode)
        object.__setattr__(self, "reactive_mode", mode)

        # Coerção: aceitar dicionários vindos de um cenário remoto.
        for attr, cls in (
            ("volt_var", VoltVarCurve),
            ("volt_watt", VoltWattCurve),
            ("const_pf", ConstPF),
            ("const_q", ConstQ),
        ):
            value = getattr(self, attr)
            if isinstance(value, dict):
                object.__setattr__(self, attr, cls.from_dict(value))

        required = {
            ReactiveMode.VOLT_VAR: "volt_var",
            ReactiveMode.CONST_PF: "const_pf",
            ReactiveMode.CONST_Q: "const_q",
        }.get(mode)
        if required is not None and getattr(self, required) is None:
            # Um default silencioso aqui produziria a curva errada sem aviso;
            # exigir o objeto torna a intenção do cenário verificável.
            raise ConfigError(
                f"reactive_mode={mode.value!r} exige o parâmetro {required!r}. "
                f"Ex.: ControlConfig(reactive_mode=ReactiveMode.{mode.name}, "
                f"{required}={required.title().replace('_', '')}(...))"
            )

        priority = str(self.priority).upper()
        if priority not in ("ACTIVE", "REACTIVE"):
            raise ConfigError(
                f"priority deve ser 'ACTIVE' ou 'REACTIVE'; recebido {self.priority!r}"
            )
        object.__setattr__(self, "priority", priority)

        unbalance = str(self.v_meas_unbalance).upper()
        if unbalance not in ("AVG", "POS"):
            raise ConfigError(
                f"v_meas_unbalance deve ser 'AVG' ou 'POS'; recebido {self.v_meas_unbalance!r}"
            )
        object.__setattr__(self, "v_meas_unbalance", unbalance)

        normal = str(self.normal_op_cat).upper()
        if normal not in ("CAT_A", "CAT_B"):
            raise ConfigError(
                f"normal_op_cat deve ser 'CAT_A' ou 'CAT_B'; recebido {self.normal_op_cat!r}"
            )
        object.__setattr__(self, "normal_op_cat", normal)

        abnormal = str(self.abnormal_op_cat).upper()
        if abnormal not in ("CAT_I", "CAT_II", "CAT_III"):
            raise ConfigError(
                f"abnormal_op_cat deve ser 'CAT_I', 'CAT_II' ou 'CAT_III'; recebido {self.abnormal_op_cat!r}"
            )
        object.__setattr__(self, "abnormal_op_cat", abnormal)

        low_p = str(self.q_capability_low_p).upper()
        if low_p not in ("REDUCED", "SAME"):
            raise ConfigError(
                f"q_capability_low_p deve ser 'REDUCED' ou 'SAME'; recebido {self.q_capability_low_p!r}"
            )
        object.__setattr__(self, "q_capability_low_p", low_p)

        if not (0.0 < self.efficiency <= 1.0):
            raise ConfigError(f"efficiency deve estar em (0, 1]; recebido {self.efficiency}")
        if not (0.0 <= self.p_min_pu <= 1.0):
            raise ConfigError(f"p_min_pu deve estar em [0, 1]; recebido {self.p_min_pu}")

    # -- Consultas ----------------------------------------------------

    @property
    def uses_opender(self) -> bool:
        """Se alguma função do OpenDER está ativa."""
        return self.reactive_mode is not ReactiveMode.NONE or self.volt_watt is not None

    def relaxation_factor(self, step_size: float) -> float:
        """Menor fator de relaxação entre as funções ativas.

        ``1.0`` significa resposta instantânea — nenhum amortecimento no laço
        realimentado com o fluxo de potência.
        """
        factors = [
            curve.relaxation_factor(step_size)
            for curve in (self.volt_var, self.volt_watt)
            if curve is not None
        ]
        return min(factors) if factors else 1.0

    # -- Serialização -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "reactive_mode": self.reactive_mode.value,
            "volt_var": self.volt_var.to_dict() if self.volt_var else None,
            "volt_watt": self.volt_watt.to_dict() if self.volt_watt else None,
            "const_pf": self.const_pf.to_dict() if self.const_pf else None,
            "const_q": self.const_q.to_dict() if self.const_q else None,
            "trip_enabled": self.trip_enabled,
            "priority": self.priority,
            "v_meas_unbalance": self.v_meas_unbalance,
            "normal_op_cat": self.normal_op_cat,
            "abnormal_op_cat": self.abnormal_op_cat,
            "q_capability_low_p": self.q_capability_low_p,
            "frequency_hz": self.frequency_hz,
            "p_min_pu": self.p_min_pu,
            "efficiency": self.efficiency,
            "extra_der_params": dict(self.extra_der_params),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ControlConfig:
        return cls(**data)

    @classmethod
    def coerce(cls, value: ControlConfig | dict[str, Any] | None) -> ControlConfig:
        """Aceita a dataclass (cenário local) ou um dicionário (cenário remoto)."""
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls.from_dict(value)
        raise ConfigError(f"ControlConfig inválido: {type(value).__name__}")

    def as_der_params(self) -> dict[str, Any]:
        """Parâmetros de função do ``DERCommonFileFormat``.

        Não inclui os de placa (``NP_*`` dependentes da unidade), que
        :mod:`.opender_factory` acrescenta.
        """
        params: dict[str, Any] = {
            "NP_V_MEAS_UNBALANCE": self.v_meas_unbalance,
            "NP_PRIO_OUTSIDE_MIN_Q_REQ": self.priority,
            "NP_NORMAL_OP_CAT": self.normal_op_cat,
            "NP_ABNORMAL_OP_CAT": self.abnormal_op_cat,
            "NP_P_MIN_PU": self.p_min_pu,
            "NP_EFFICIENCY": self.efficiency,
        }

        active = {
            ReactiveMode.VOLT_VAR: self.volt_var,
            ReactiveMode.CONST_PF: self.const_pf,
            ReactiveMode.CONST_Q: self.const_q,
        }.get(self.reactive_mode)
        if active is not None:
            params.update(active.as_der_params())

        if self.volt_watt is not None:
            params.update(self.volt_watt.as_der_params())

        if not self.trip_enabled:
            params.update(
                {
                    "OV1_TRIP_V": TRIP_DISABLED_OVERVOLTAGE,
                    "OV2_TRIP_V": TRIP_DISABLED_OVERVOLTAGE,
                    "UV1_TRIP_V": TRIP_DISABLED_UNDERVOLTAGE,
                    "UV2_TRIP_V": TRIP_DISABLED_UNDERVOLTAGE,
                    "OF1_TRIP_F": TRIP_DISABLED_OVERFREQUENCY,
                    "OF2_TRIP_F": TRIP_DISABLED_OVERFREQUENCY,
                    "UF1_TRIP_F": TRIP_DISABLED_UNDERFREQUENCY,
                    "UF2_TRIP_F": TRIP_DISABLED_UNDERFREQUENCY,
                }
            )

        params.update(self.extra_der_params)
        return params
