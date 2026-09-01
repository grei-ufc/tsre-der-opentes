"""Battery model faithful to the OpenDSS Storage element (Storage.pas).

Signal convention (Generator / OpenDSS):
- kW > 0: discharging (injecting into the grid)
- kW < 0: charging (absorbing from the grid)
"""

import math


class OpenDSSBattery:
    """Python implementation of the OpenDSS Storage model.

    Simulates charge / discharge behaviour, inverter efficiency curves,
    idle losses and state-of-charge tracking for a single battery unit.

    Attributes:
        name: Identifier for this battery instance.
        kw_rated: Rated active power (kW).
        kwh_rated: Rated energy capacity (kWh).
        kwh_reserve: Minimum energy before discharge stops (kWh).
        kwh_stored: Current stored energy (kWh).
        state: Current operating state (one of ``STATE_IDLING``,
            ``STATE_DISCHARGING``, ``STATE_CHARGING``).
        eff_charge: Charging efficiency (0..1).
        eff_discharge: Discharging efficiency (0..1).
        idling_kw: Idle parasitic draw (kW).
        kva_rated: Rated apparent power of the inverter (kVA).
        max_charge_kw: Maximum charging power (kW).
        max_discharge_kw: Maximum discharging power (kW).
        p_out_kw: Last computed active power output (kW).
        q_out_kvar: Last computed reactive power output (kVAR).
    """

    STATE_IDLING: int = 0
    STATE_DISCHARGING: int = 1
    STATE_CHARGING: int = -1

    def __init__(
        self,
        name: str,
        kw_rated: float,
        kwh_rated: float,
        kwh_stored: float,
        pct_reserve: float = 20.0,
        pct_eff_charge: float = 90.0,
        pct_eff_discharge: float = 90.0,
        pct_idling_kw: float = 2.0,
        kva_rated: float | None = None,
        max_charge_kw: float | None = None,
        max_discharge_kw: float | None = None,
        eff_curve_x: list[float] | None = None,
        eff_curve_y: list[float] | None = None,
    ) -> None:
        self.name = name

        # Inverter efficiency curve (safe against memory leaks)
        self.eff_curve_x = eff_curve_x if eff_curve_x is not None else [0.1, 0.2, 0.4, 1.0]
        self.eff_curve_y = eff_curve_y if eff_curve_y is not None else [0.86, 0.9, 0.93, 0.97]

        # Rated parameters
        self.kw_rated = float(kw_rated)
        self.kwh_rated = float(kwh_rated)
        self.kwh_reserve = (
            float(pct_reserve / 100.0) * self.kwh_rated
        )  # Minimum level before discharge stops

        # Initial state
        self.kwh_stored = float(kwh_stored)
        self.state = self.STATE_IDLING

        # Efficiencies and losses
        self.eff_charge = float(pct_eff_charge / 100)
        self.eff_discharge = float(pct_eff_discharge / 100)
        self.pct_idling_kw = float(pct_idling_kw)
        self.idling_kw = (self.pct_idling_kw / 100.0) * self.kw_rated

        # Inverter efficiency curve
        self.eff_curve_x = eff_curve_x if eff_curve_x is not None else [0.1, 0.2, 0.4, 1.0]
        self.eff_curve_y = eff_curve_y if eff_curve_y is not None else [0.86, 0.9, 0.93, 0.97]

        # Inverter limits
        self.kva_rated = float(kva_rated) if kva_rated is not None else self.kw_rated * 1.0  # Default PF=1

        # Explicit charge / discharge limits (if different from rated)
        self.max_charge_kw = max_charge_kw if max_charge_kw is not None else self.kw_rated
        self.max_discharge_kw = max_discharge_kw if max_discharge_kw is not None else self.kw_rated

        # Discrete-time state variables
        self.kwh_stored = float(kwh_stored)
        self.pending_delta_energy = 0.0
        self.state = self.STATE_IDLING

        # Initial outputs
        eta_inv_idle = self.get_inverter_efficiency(self.idling_kw)
        self.p_out_kw = -(self.idling_kw / eta_inv_idle) if eta_inv_idle > 0 else -self.idling_kw
        self.q_out_kvar = 0.0

    def calculate_step(
        self,
        p_request: float | None,
        q_request: float | None,
        dt_seconds: float,
    ) -> dict[str, float | str]:
        """Execute dispatch logic and update state for one time step.

        Args:
            p_request: Requested active power (+ discharge, - charge) in kW.
            q_request: Requested reactive power in kVAR.
            dt_seconds: Time step duration in seconds.

        Returns:
            Dictionary with keys ``'p_kw'``, ``'q_kvar'``, ``'soc_pct'``
            and ``'state'`` reflecting the updated inverter state.
        """
        dt_hours = dt_seconds / 3600.0

        # ------------------------------------------------------------------
        # 1. Inverter limitation (apparent power circle)
        # ------------------------------------------------------------------

        p_limited = float(p_request) if p_request is not None else 0.0
        q_limited = float(q_request) if q_request is not None else 0.0

        self.kwh_stored += self.pending_delta_energy

        # Clamp P within rated charge/discharge limits
        if p_limited > self.max_discharge_kw:
            p_limited = self.max_discharge_kw
        elif p_limited < -self.max_charge_kw:
            p_limited = -self.max_charge_kw

        # Check kVA violation
        s_sq = p_limited**2 + q_limited**2
        if s_sq > self.kva_rated**2:
            # If kVA exceeded, reduce Q first (P priority)
            available_q = math.sqrt(max(0, self.kva_rated**2 - p_limited**2))
            if q_limited > 0:
                q_limited = available_q
            else:
                q_limited = -available_q

            # If even with Q=0 P is too high (rare if kw_rated <= kva_rated), clamp P
            if abs(p_limited) > self.kva_rated:
                p_limited = math.copysign(self.kva_rated, p_limited)

        # ------------------------------------------------------------------
        # 2. Default behaviour (fallback)
        # ------------------------------------------------------------------
        calc_delta_energy = 0.0
        next_state = self.STATE_IDLING

        eta_inv_idle = self.get_inverter_efficiency(self.idling_kw)

        # Save for weighted average
        p_idle_ac = -(self.idling_kw / eta_inv_idle) if eta_inv_idle > 0 else -self.idling_kw
        p_output = p_idle_ac

        # ------------------------------------------------------------------
        # 3. State determination and chemical energy calculation (DC side)
        #    OpenDSS instantaneous snapshot emulation
        # ------------------------------------------------------------------
        if p_limited > 1e-6:
            # --- DISCHARGE ATTEMPT (inject into grid) ---
            eta_inv = self.get_inverter_efficiency(p_limited)
            if eta_inv > 0:
                p_dc_req = p_limited / eta_inv
                p_chem = p_dc_req / self.eff_discharge

                total_drain_rate = p_chem + self.idling_kw

                energy_required = total_drain_rate * dt_hours
                available_energy = max(0.0, self.kwh_stored - self.kwh_reserve)

                if available_energy > 0:
                    # Lock read power to rated value (instantaneous snapshot)
                    next_state = self.STATE_DISCHARGING
                    p_output = p_limited

                    if energy_required > available_energy:
                        # Battery empties mid-step: limit only the energy
                        calc_delta_energy = -available_energy
                    else:
                        calc_delta_energy = -energy_required

        elif p_limited < -1e-6:
            # --- CHARGE ATTEMPT (absorb from grid) ---
            p_grid_mag = abs(p_limited)
            eta_inv = self.get_inverter_efficiency(p_grid_mag)

            p_dc_input = p_grid_mag * eta_inv
            p_chem = p_dc_input * self.eff_charge

            total_charge_rate = p_chem - self.idling_kw

            if total_charge_rate > 0:
                energy_space = max(0.0, self.kwh_rated - self.kwh_stored)
                energy_to_store = total_charge_rate * dt_hours

                if energy_space > 0:
                    # Lock read power to rated value (instantaneous snapshot)
                    next_state = self.STATE_CHARGING
                    p_output = p_limited

                    if energy_to_store > energy_space:
                        # Battery fills mid-step: limit only the space
                        calc_delta_energy = energy_space
                    else:
                        calc_delta_energy = energy_to_store

        # ------------------------------------------------------------------
        # 4. Final state update
        # ------------------------------------------------------------------

        # Safety clamp (numerical errors)
        if self.kwh_stored < 0:
            self.kwh_stored = 0.0
        if self.kwh_stored > self.kwh_rated:
            self.kwh_stored = self.kwh_rated

        self.pending_delta_energy = calc_delta_energy
        self.state = next_state
        self.p_out_kw = p_output
        self.q_out_kvar = q_limited

        return {
            "p_kw": self.p_out_kw,
            "q_kvar": self.q_out_kvar,
            "soc_pct": (self.kwh_stored / self.kwh_rated) * 100,
            "state": self.get_state_str(),
        }

    def get_state_str(self) -> str:
        """Return a human-readable string for the current operating state.

        Returns:
            One of ``'Charging'``, ``'Discharging'``, or ``'Idling'``.
        """
        if self.state == self.STATE_CHARGING:
            return "Charging"
        if self.state == self.STATE_DISCHARGING:
            return "Discharging"
        return "Idling"

    def get_inverter_efficiency(self, p_kw: float) -> float:
        """Interpolate or linearly extrapolate inverter efficiency from the XY curve.

        Args:
            p_kw: Active power magnitude (kW).

        Returns:
            Inverter efficiency value between 0.1 and 1.0.
        """
        p_pu = abs(p_kw) / self.kw_rated if self.kw_rated > 0 else 0.0

        if p_pu <= 0.0:
            return 0.0

        # Clamp to upper curve limit (e.g. 1.0 pu)
        if p_pu >= self.eff_curve_x[-1]:
            return self.eff_curve_y[-1]

        # Linear interpolation / extrapolation (downward)
        for i in range(len(self.eff_curve_x) - 1):
            if p_pu <= self.eff_curve_x[i + 1]:
                x0, x1 = self.eff_curve_x[i], self.eff_curve_x[i + 1]
                y0, y1 = self.eff_curve_y[i], self.eff_curve_y[i + 1]
                eta = y0 + (p_pu - x0) * (y1 - y0) / (x1 - x0)
                return max(0.1, eta)  # Mathematical safety limit to avoid division by zero

        return 0.0
