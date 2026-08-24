"""Modelo de inversor inteligente: potência DC e tensão de barra → P/Q injetados.

O modelo não conhece o mosaik. Ele agrega uma ou mais
:class:`~.config.InverterUnit` — tipicamente os ``PVSystem`` de uma mesma barra
— e, para cada uma, mantém um objeto OpenDER independente, que é como o padrão
IEEE 1547 modela um inversor: cada unidade mede a própria tensão terminal e
responde por conta própria.

Divisão de responsabilidades com o OpenDER:

===========================  ==========================================
Corte de entrada/saída       aqui (histerese ``%cutin``/``%cutout``)
Curva de eficiência DC→AC    aqui (``NP_EFFICIENCY`` fica em 1.0)
Volt-var / volt-watt / PF    OpenDER
Círculo de S e curva Q(P)    OpenDER (``CapabilityPriority``)
Trip e ride-through          OpenDER
===========================  ==========================================

Cada grandeza tem um dono só. O contrário — o antigo modelo reaplicava o
círculo de kVA depois do OpenDER — faz duas políticas de prioridade
divergentes disputarem o mesmo limite.
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from .config import ControlConfig, InverterUnit, PhaseMode, ReactiveMode
from .opender_factory import build_der, voltage_for

logger = logging.getLogger(__name__)

# Passos consecutivos com Q alternando de sinal antes de suspeitar de ciclo
# limite na malha realimentada com o fluxo de potência.
_OSCILLATION_WINDOW = 6

__all__ = ["SmartInverterModel"]


class SmartInverterModel:
    """Inversor fotovoltaico com as funções de suporte à rede da IEEE 1547.

    Args:
        units: Unidades físicas agregadas nesta entidade. Cada uma recebe seu
            próprio objeto OpenDER. Uma lista de uma unidade trifásica é o caso
            comum; três unidades monofásicas representam uma instalação
            distribuída entre as fases de uma barra.
        ctrl: Funções de controle. Se nenhuma estiver ativa, o inversor opera
            com ``Q_des`` recebido de fora e limitação local pelo círculo de S.
        eff_curve_x: Eixo x da curva de eficiência, em pu da potência nominal.
        eff_curve_y: Eficiência correspondente, em ``(0, 1]``.
        pct_cutin: Potência DC mínima, em % do kVA total, para ligar o inversor.
        pct_cutout: Potência DC, em % do kVA total, abaixo da qual ele desliga.
        step_size: Passo de simulação em segundos. Usado apenas para relatar o
            fator de relaxação da malha; ``DER.t_s`` é definido pelo adaptador.

    Attributes:
        P_ac: Potência ativa injetada total, em kW.
        Q_ac: Potência reativa injetada total, em kvar (positivo injeta).
        unit_p, unit_q: Injeção por unidade, na ordem de ``units``.
        phase_p, phase_q: Injeção por fase da barra (índices 0, 1, 2).
        der_status: Estado operativo mais restritivo entre as unidades.
    """

    def __init__(
        self,
        units: Sequence[InverterUnit],
        ctrl: ControlConfig | dict[str, Any] | None = None,
        eff_curve_x: Sequence[float] | None = None,
        eff_curve_y: Sequence[float] | None = None,
        pct_cutin: float = 0.0,
        pct_cutout: float = 0.0,
        step_size: float | None = None,
    ) -> None:
        if not units:
            raise ValueError("SmartInverterModel exige ao menos uma InverterUnit")

        self.units: list[InverterUnit] = [
            u if isinstance(u, InverterUnit) else InverterUnit.from_dict(u) for u in units
        ]
        self.ctrl = ControlConfig.coerce(ctrl)

        self.eff_curve_x = list(eff_curve_x) if eff_curve_x else [0.0, 1.0]
        self.eff_curve_y = list(eff_curve_y) if eff_curve_y else [1.0, 1.0]
        self.pct_cutin = float(pct_cutin)
        self.pct_cutout = float(pct_cutout)
        self.step_size = step_size

        self.kva_total = sum(u.kva for u in self.units)
        self.kw_total = sum(u.kw_rating for u in self.units)

        self._validate_nodes()

        # Entradas
        self.P_dc = 0.0
        self.Q_des = 0.0
        self.V_meas: list[float | None] = [1.0, 1.0, 1.0]
        # Ângulos de fase em graus, como o OpenDSS reporta. Só importam quando
        # `v_meas_unbalance='POS'`, que decompõe a tensão em componentes
        # simétricas; em 'AVG' os defaults equilibrados bastam.
        self.V_ang: list[float] = [0.0, -120.0, 120.0]
        self.f_meas = self.ctrl.frequency_hz

        # Saídas
        self.is_on = False
        self.P_ac = 0.0
        self.Q_ac = 0.0
        self.unit_p = [0.0] * len(self.units)
        self.unit_q = [0.0] * len(self.units)
        self.phase_p = [0.0, 0.0, 0.0]
        self.phase_q = [0.0, 0.0, 0.0]

        # Diagnóstico
        self.der_status = "Not Started"
        self.v_meas_pu = 0.0
        self.q_desired_pu = 0.0
        self.p_avl_pu = 0.0
        self.p_pv_limit_pu = 1.0

        self._ders: list[Any] = []
        if self.ctrl.uses_opender:
            self._ders = [build_der(unit, self.ctrl) for unit in self.units]

        self._q_history: list[float] = []
        self._oscillation_reported = False

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _validate_nodes(self) -> None:
        """Rejeita agregações ambíguas de unidades monofásicas.

        Duas unidades monofásicas no mesmo nó da mesma barra são
        eletricamente indistinguíveis depois de somadas, então o cenário não
        conseguiria rotear a injeção de volta para o ``PVSystem`` certo.
        """
        seen: dict[int, str] = {}
        for unit in self.units:
            if unit.phase_mode is not PhaseMode.SINGLE:
                continue
            node = unit.node
            if node in seen:
                raise ValueError(
                    f"Unidades {seen[node]!r} e {unit.name!r} estão ambas no nó {node}. "
                    "Agregue-as em uma única InverterUnit ou crie entidades separadas: "
                    "somadas, a injeção não pode ser roteada de volta para cada PVSystem."
                )
            seen[node] = unit.name

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    @property
    def uses_opender(self) -> bool:
        return bool(self._ders)

    def relaxation_factor(self) -> float:
        """Fração da variação de Q aplicada por passo. Ver :class:`~.config.VoltVarCurve`."""
        if self.step_size is None:
            return 1.0
        return self.ctrl.relaxation_factor(self.step_size)

    def describe(self) -> str:
        """Resumo de uma linha, para o log de partida do cenário."""
        names = ", ".join(u.name for u in self.units)
        mode = self.ctrl.reactive_mode.value
        vw = "+volt_watt" if self.ctrl.volt_watt else ""
        return (
            f"{len(self.units)} unidade(s) [{names}] | {self.kva_total:.1f} kVA | "
            f"modo={mode}{vw} | trip={'on' if self.ctrl.trip_enabled else 'off'}"
        )

    # ------------------------------------------------------------------
    # Passo de simulação
    # ------------------------------------------------------------------

    def calculate_step(self) -> None:
        """Executa um passo: aplica corte, eficiência, controle e distribuição."""
        if not self._pass_cut_in_out():
            self._reset_outputs()
            return

        p_ac_available = self._apply_efficiency()

        if self.uses_opender:
            self._run_opender(p_ac_available)
        else:
            self._run_passthrough(p_ac_available)

        self._detect_oscillation()

    def _pass_cut_in_out(self) -> bool:
        """Histerese de entrada/saída, em % do kVA (convenção do OpenDSS)."""
        if self.kva_total <= 0:
            self.is_on = False
            return False

        p_dc_pct = (self.P_dc / self.kva_total) * 100.0
        if self.is_on:
            if p_dc_pct <= self.pct_cutout:
                self.is_on = False
        elif p_dc_pct >= self.pct_cutin:
            self.is_on = True
        return self.is_on

    def _apply_efficiency(self) -> float:
        """Converte a potência DC em potência AC disponível, em kW."""
        p_pu = self.P_dc / self.kw_total if self.kw_total > 0 else 0.0
        eff = float(np.interp(p_pu, self.eff_curve_x, self.eff_curve_y))
        return float(self.P_dc * eff)

    def _run_opender(self, p_ac_available: float) -> None:
        """Roda um objeto OpenDER por unidade e agrega os resultados."""
        p_unit = [0.0] * len(self.units)
        q_unit = [0.0] * len(self.units)
        phase_p = [0.0, 0.0, 0.0]
        phase_q = [0.0, 0.0, 0.0]

        statuses: list[str] = []
        v_meas: list[float] = []
        q_desired: list[float] = []
        p_avl: list[float] = []
        p_limit: list[float] = []

        for i, (unit, der) in enumerate(zip(self.units, self._ders, strict=True)):
            # A potência disponível é rateada pela potência nominal da unidade,
            # que é como um arranjo fotovoltaico compartilhado se divide entre
            # os inversores que o atendem.
            share = unit.kw_rating / self.kw_total if self.kw_total > 0 else 0.0

            der.update_der_input(
                p_dc_kw=p_ac_available * share,
                v_pu=voltage_for(unit, self.V_meas),
                theta=self._theta_for(unit),
                f=self.f_meas,
            )
            p_w, q_var = der.run()

            p_kw = float(p_w) / 1000.0
            q_kvar = float(q_var) / 1000.0
            p_unit[i] = p_kw
            q_unit[i] = q_kvar

            nodes = unit.nodes
            for node in nodes:
                phase_p[node - 1] += p_kw / len(nodes)
                phase_q[node - 1] += q_kvar / len(nodes)

            statuses.append(der.der_status)
            v_meas.append(der.der_input.v_meas_pu)
            q_desired.append(der.reactivepowerfunc.q_desired_pu or 0.0)
            p_avl.append(der.der_input.p_avl_pu or 0.0)
            p_limit.append(der.activepowerfunc.p_pv_limit_pu or 1.0)

        self.unit_p = p_unit
        self.unit_q = q_unit
        self.phase_p = phase_p
        self.phase_q = phase_q
        self.P_ac = float(sum(p_unit))
        self.Q_ac = float(sum(q_unit))

        self.der_status = self._worst_status(statuses)
        self.v_meas_pu = float(sum(v_meas) / len(v_meas))
        self.q_desired_pu = float(sum(q_desired) / len(q_desired))
        self.p_avl_pu = float(sum(p_avl) / len(p_avl))
        self.p_pv_limit_pu = float(min(p_limit))

    def _theta_for(self, unit: InverterUnit) -> float | list[float]:
        """Ângulos de tensão em radianos, como o OpenDER espera.

        As leituras de barra do OpenDSS vêm em graus; passá-las sem converter
        embaralharia a decomposição em componentes simétricas do modo ``POS``.
        """
        if unit.phase_mode is PhaseMode.SINGLE:
            return math.radians(self.V_ang[unit.node - 1])  # type: ignore[index]
        return [math.radians(a) for a in self.V_ang]

    def _run_passthrough(self, p_ac_available: float) -> None:
        """Sem funções do OpenDER: usa ``Q_des`` e limita pelo círculo de S."""
        p_ac, q_ac = self._apply_capability(p_ac_available, self.Q_des)

        self.P_ac = p_ac
        self.Q_ac = q_ac
        self.der_status = "Continuous Operation"

        connected = [v for v in self.V_meas if v is not None]
        self.v_meas_pu = sum(connected) / len(connected) if connected else 0.0
        self.p_avl_pu = p_ac_available / self.kw_total if self.kw_total > 0 else 0.0
        self.q_desired_pu = q_ac / self.kva_total if self.kva_total > 0 else 0.0
        self.p_pv_limit_pu = 1.0

        self._distribute_pro_rata(p_ac, q_ac)

    def _apply_capability(self, p_ac: float, q_ac: float) -> tuple[float, float]:
        """Limita P e Q ao círculo de S conforme :attr:`ControlConfig.priority`.

        Só é usado no caminho sem OpenDER; quando o OpenDER está ativo, o
        limite já foi aplicado por ``CapabilityPriority`` com a mesma política.
        """
        s_max = self.kva_total
        if self.ctrl.priority == "ACTIVE":
            p_ac = min(p_ac, s_max)
            q_max = math.sqrt(max(0.0, s_max**2 - p_ac**2))
            q_ac = math.copysign(min(abs(q_ac), q_max), q_ac)
        else:
            q_ac = math.copysign(min(abs(q_ac), s_max), q_ac)
            p_max = math.sqrt(max(0.0, s_max**2 - q_ac**2))
            p_ac = min(p_ac, p_max)
        return p_ac, q_ac

    def _distribute_pro_rata(self, p_ac: float, q_ac: float) -> None:
        """Distribui P/Q totais pelas unidades e pelas fases que elas ocupam."""
        p_unit = [0.0] * len(self.units)
        q_unit = [0.0] * len(self.units)
        phase_p = [0.0, 0.0, 0.0]
        phase_q = [0.0, 0.0, 0.0]

        for i, unit in enumerate(self.units):
            share = unit.kva / self.kva_total if self.kva_total > 0 else 0.0
            p_unit[i] = p_ac * share
            q_unit[i] = q_ac * share
            nodes = unit.nodes
            for node in nodes:
                phase_p[node - 1] += p_unit[i] / len(nodes)
                phase_q[node - 1] += q_unit[i] / len(nodes)

        self.unit_p = p_unit
        self.unit_q = q_unit
        self.phase_p = phase_p
        self.phase_q = phase_q

    def _reset_outputs(self) -> None:
        """Inversor desligado: nenhuma injeção, diagnóstico preservado."""
        self.P_ac = 0.0
        self.Q_ac = 0.0
        self.unit_p = [0.0] * len(self.units)
        self.unit_q = [0.0] * len(self.units)
        self.phase_p = [0.0, 0.0, 0.0]
        self.phase_q = [0.0, 0.0, 0.0]
        self.der_status = "Off (cut-out)"
        self.q_desired_pu = 0.0
        self.p_avl_pu = 0.0

    @staticmethod
    def _worst_status(statuses: list[str]) -> str:
        """Estado mais restritivo entre as unidades, para uma coluna única no CSV."""
        order = [
            "Trip",
            "Cease to Energize",
            "Momentary Cessation",
            "Permissive Operation",
            "Mandatory Operation",
            "Not Defined",
            "Entering Service",
            "Continuous Operation",
        ]
        ranked = [s for s in order if s in statuses]
        return ranked[0] if ranked else (statuses[0] if statuses else "Unknown")

    # ------------------------------------------------------------------
    # Diagnóstico da malha realimentada
    # ------------------------------------------------------------------

    def _detect_oscillation(self) -> None:
        """Avisa uma vez se Q entra em ciclo limite.

        A realimentação de tensão do OpenDSS chega atrasada de um passo
        (``time_shifted=True``). Se o ganho da curva volt-var superar a
        sensibilidade dV/dQ da barra, Q alterna de sinal a cada passo em vez de
        convergir. O remédio é aumentar o OLRT da curva, que é o filtro de
        primeira ordem que amortece o laço.
        """
        if self._oscillation_reported or self.ctrl.reactive_mode is not ReactiveMode.VOLT_VAR:
            return

        self._q_history.append(self.Q_ac)
        if len(self._q_history) > _OSCILLATION_WINDOW:
            self._q_history.pop(0)
        if len(self._q_history) < _OSCILLATION_WINDOW:
            return

        deltas = [b - a for a, b in itertools.pairwise(self._q_history)]
        significant = max(abs(d) for d in deltas)
        if significant < 0.01 * self.kva_total:
            return
        if not all(a * b < 0 for a, b in itertools.pairwise(deltas)):
            return

        self._oscillation_reported = True
        names = ", ".join(u.name for u in self.units)
        suggested = 4.0 * (self.step_size or 0.0)
        logger.warning(
            "[OpenTES][volt-var] %s: Q alternando de sinal ha %d passos "
            "(amplitude %.1f kvar) — provavel ciclo limite da malha realimentada. "
            "Aumente VoltVarCurve.olrt (atual %.1fs; fator de relaxacao %.2f). "
            "Sugestao: olrt=%.0fs.",
            names,
            _OSCILLATION_WINDOW,
            significant,
            self.ctrl.volt_var.olrt if self.ctrl.volt_var else 0.0,
            self.relaxation_factor(),
            suggested,
        )
