"""Unified inverter model for mosaik co-simulation.

Combines:
- Cut-in / cut-out logic and efficiency (inverter_simulator.py)
- Active/Reactive priority with kVA limits
- Optional OpenDER integration (smart_inverter_simulator_2.py)
- AVG / INDEP phase mode support (smart_inverter_simulator.py)
"""

import math
import statistics

import numpy as np


class InverterModel:
    """Physical and control model of a photovoltaic inverter.

    Receives DC power (P_dc) and grid voltage (V_meas), applies inverter
    efficiency, kVA limits, and optionally runs IEEE 1547 control loops
    via OpenDER.

    Attributes:
        kVA: Rated apparent power of the inverter (kVA).
        priority: ``'Active'`` or ``'Reactive'``.
        eff_curve_x: X-axis of the efficiency curve (pu).
        eff_curve_y: Y-axis of the efficiency curve (0..1).
        pct_cutin: Minimum DC power (%) to turn the inverter on.
        pct_cutout: Minimum DC power (%) to turn the inverter off.
        ctrl_config: Remote control configuration (OpenDER).
            Keys: ``'volt_var'``, ``'volt_watt'``, ``'Const_PF'``, ``'PF'``.
        phase_mode: ``'AVG'`` or ``'INDEP'``.
    """

    def __init__(
        self,
        kVA: float,
        priority: str = "Active",
        eff_curve_x: list[float] | None = None,
        eff_curve_y: list[float] | None = None,
        pct_cutin: float = 20.0,
        pct_cutout: float = 20.0,
        ctrl_config: dict | None = None,
        phase_mode: str = "AVG",
    ) -> None:
        self.kVA = kVA
        self.priority = priority
        self.eff_curve_x = eff_curve_x if eff_curve_x is not None else [0.0, 1.0]
        self.eff_curve_y = eff_curve_y if eff_curve_y is not None else [1.0, 1.0]
        self.pct_cutin = pct_cutin
        self.pct_cutout = pct_cutout
        self.ctrl_config = ctrl_config or {}
        self.phase_mode = phase_mode.upper()

        self.is_on = False
        self.P_dc = 0.0
        self.Q_des = 0.0
        self.V_meas: list[float] = [1.0, 1.0, 1.0]

        self.P_ac = 0.0
        self.Q_ac = 0.0
        self.P_ac_out: list[float] = [0.0, 0.0, 0.0]
        self.Q_ac_out: list[float] = [0.0, 0.0, 0.0]

        self._der_objects: list = []
        self._setup_opender()

    # ------------------------------------------------------------------
    # OpenDER setup
    # ------------------------------------------------------------------

    def _setup_opender(self) -> None:
        """Configure DER_PV objects if ctrl_config requires them."""
        has_vv = bool(self.ctrl_config.get("volt_var"))
        has_vw = bool(self.ctrl_config.get("volt_watt"))
        has_const_pf = bool(self.ctrl_config.get("Const_PF"))

        if not (has_vv or has_vw or has_const_pf):
            return

        from opender import DER_PV

        if self.phase_mode == "INDEP":
            kva_per_phase = self.kVA / 3.0
            self._der_objects = [self._create_der(DER_PV, kva_per_phase) for _ in range(3)]
        else:
            self._der_objects = [self._create_der(DER_PV, self.kVA)]

    def _create_der(self, der_cls: type, kva_rating: float) -> object:
        """Create and configure a DER_PV instance.

        Args:
            der_cls: The DER_PV class to instantiate.
            kva_rating: kVA rating for this DER object.

        Returns:
            A configured DER_PV instance.
        """
        der = der_cls()
        der.der_file.NP_VA_MAX = kva_rating * 1000.0
        der.der_file.NP_P_MAX = kva_rating * 1000.0

        vv = self.ctrl_config.get("volt_var")
        vw = self.ctrl_config.get("volt_watt")

        if vv:
            der.der_file.QV_MODE_ENABLE = True
            if isinstance(vv, dict):
                for key, attr in [
                    ("vref", "QV_VREF"),
                    ("v1", "QV_CURVE_V1"),
                    ("q1", "QV_CURVE_Q1"),
                    ("v2", "QV_CURVE_V2"),
                    ("q2", "QV_CURVE_Q2"),
                    ("v3", "QV_CURVE_V3"),
                    ("q3", "QV_CURVE_Q3"),
                    ("v4", "QV_CURVE_V4"),
                    ("q4", "QV_CURVE_Q4"),
                ]:
                    if key in vv:
                        setattr(der.der_file, attr, vv[key])

        if vw:
            der.der_file.PV_MODE_ENABLE = True
            if isinstance(vw, dict):
                for key, attr in [
                    ("v1", "PV_CURVE_V1"),
                    ("p1", "PV_CURVE_P1"),
                    ("v2", "PV_CURVE_V2"),
                    ("p2", "PV_CURVE_P2"),
                ]:
                    if key in vw:
                        setattr(der.der_file, attr, vw[key])

        pf = self.ctrl_config.get("PF")
        if pf is not None:
            der.der_file.CONST_PF_MODE_ENABLE = True
            # PF value applied if the library supports it

        return der

    # ------------------------------------------------------------------
    # Step calculation
    # ------------------------------------------------------------------

    def calculate_step(self) -> None:
        """Execute one simulation step of the inverter.

        Applies cut-in/cut-out logic, efficiency curve, optional OpenDER
        control, and kVA-priority clamping to produce the AC outputs.
        """
        p_ac = 0.0
        q_ac = 0.0

        if self.kVA <= 0:
            self._set_outputs(0.0, 0.0)
            return

        # --- Cut-in / Cut-out ---
        p_dc_pct = (self.P_dc / self.kVA) * 100.0

        if not self.is_on:
            if p_dc_pct >= self.pct_cutin:
                self.is_on = True
        else:
            if p_dc_pct <= self.pct_cutout:
                self.is_on = False

        if not self.is_on:
            self._set_outputs(0.0, 0.0)
            return

        # --- Inverter efficiency ---
        p_pu = self.P_dc / self.kVA
        eff = float(np.interp(p_pu, self.eff_curve_x, self.eff_curve_y))
        p_ac_uncapped = self.P_dc * eff

        # --- OpenDER (if configured) ---
        if self._der_objects:
            p_ac, q_ac = self._run_opender(p_ac_uncapped)
        else:
            # No OpenDER: use Q_des directly
            p_ac = p_ac_uncapped
            q_ac = self.Q_des

        # --- Priority filter (kVA circle) ---
        p_ac, q_ac = self._apply_priority(p_ac, q_ac)

        self._set_outputs(p_ac, q_ac)

    def _run_opender(self, p_ac_uncapped: float) -> tuple[float, float]:
        """Run the OpenDER and return (P_ac, Q_ac).

        Args:
            p_ac_uncapped: Uncapped AC active power (kW) before OpenDER.

        Returns:
            A tuple ``(P_ac, Q_ac)`` in kW/kVAR after OpenDER processing.
        """
        if self.phase_mode == "INDEP":
            p_per_phase = p_ac_uncapped / 3.0
            p_outs = [0.0, 0.0, 0.0]
            q_outs = [0.0, 0.0, 0.0]

            for i, der in enumerate(self._der_objects):
                v_pu = self.V_meas[i] if self.V_meas[i] > 0.1 else 1.0
                p_pu = (
                    (p_per_phase * 1000.0) / der.der_file.NP_P_MAX
                    if der.der_file.NP_P_MAX > 0
                    else 0.0
                )
                der.update_der_input(v_pu=v_pu, f=60.0, p_dc_pu=p_pu)
                p_w, q_var = der.run()
                p_outs[i] = p_w / 1000.0
                q_outs[i] = q_var / 1000.0

            self.P_ac_out = p_outs
            self.Q_ac_out = q_outs
            return sum(p_outs), sum(q_outs)

        # AVG mode
        valid_v = [v for v in self.V_meas if v > 0.1]
        v_avg = statistics.mean(valid_v) if valid_v else 1.0

        der = self._der_objects[0]
        p_pu = (
            (p_ac_uncapped * 1000.0) / der.der_file.NP_P_MAX if der.der_file.NP_P_MAX > 0 else 0.0
        )
        der.update_der_input(v_pu=v_avg, f=60.0, p_dc_pu=p_pu)
        p_w, q_var = der.run()

        p_total = p_w / 1000.0
        q_total = q_var / 1000.0
        self.P_ac_out = [p_total / 3.0] * 3
        self.Q_ac_out = [q_total / 3.0] * 3
        return p_total, q_total

    def _apply_priority(self, p_ac: float, q_ac: float) -> tuple[float, float]:
        """Apply Active/Reactive priority filter within the kVA circle.

        Args:
            p_ac: Active power (kW).
            q_ac: Reactive power (kVAR).

        Returns:
            A tuple ``(P_ac, Q_ac)`` clamped according to the priority rule.
        """
        if self.priority == "Active":
            p_ac = min(p_ac, self.kVA)
            q_max = math.sqrt(max(0, self.kVA**2 - p_ac**2))
            q_ac = math.copysign(min(abs(q_ac), q_max), q_ac) if q_ac != 0 else 0.0
        elif self.priority == "Reactive":
            q_ac = math.copysign(min(abs(q_ac), self.kVA), q_ac) if q_ac != 0 else 0.0
            p_max = math.sqrt(max(0, self.kVA**2 - q_ac**2))
            p_ac = min(p_ac, p_max)
        return p_ac, q_ac

    def _set_outputs(self, p_ac: float, q_ac: float) -> None:
        """Set inverter AC output values.

        Args:
            p_ac: Total active power output (kW).
            q_ac: Total reactive power output (kVAR).
        """
        self.P_ac = p_ac
        self.Q_ac = q_ac
        if not self._der_objects or self.phase_mode != "INDEP":
            self.P_ac_out = [p_ac / 3.0] * 3
            self.Q_ac_out = [q_ac / 3.0] * 3
