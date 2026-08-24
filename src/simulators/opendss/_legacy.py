"""Leituras legadas com retorno polimorfico.

Estes metodos mudam o formato do retorno conforme a combinacao de flags
(``polar``, ``mag_only``, ``total``, ``raw``, ``phase``, ``average``): o mesmo
``get_power`` devolve ``(float, float)``, ``(tuple, tuple)`` ou uma tupla crua.
Foi essa ambiguidade que produziu o erro de mapeamento de fase corrigido em
:func:`~._utils.map_to_phases`.

Nada no simulador os usa. Preferir, para codigo novo:

===========================  ==========================================
legado                       substituto
===========================  ==========================================
``get_power``                ``get_phase_powers`` / ``get_power_total``
``get_current``              ``get_phase_currents``
``get_bus_voltage``          ``get_bus_vmag_pu`` / ``get_bus_vang``
``get_voltage``              ``get_bus_vmag_pu`` na barra do elemento
``get_all_bus_voltages``     ``get_bus_vmag_pu`` por barra
===========================  ==========================================

Mantidos porque notebooks de analise ainda os chamam.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ._types import LINE_CLASSES, OpenDSSException


class LegacyReadsMixin:
    """Leituras superadas, preservadas para compatibilidade."""

    def get_bus_voltage(
        self,
        bus: str,
        phase: int | None = None,
        pu: bool = True,
        polar: bool = True,
        mag_only: bool = True,
        average: bool = False,
        zero_voltage_error: bool = False,
    ) -> float | tuple | list[float]:
        """
        Gets the voltage of a specific bus with flexible formatting options.

        Args:
            bus (str): The bus name.
            phase (int, optional): Specific phase (1, 2, 3). If None, returns all phases.
            pu (bool): If True, returns in per unit. Else, in real Volts/kV.
            polar (bool): If True, returns (Mag, Ang). Else, returns (Real, Imag).
            mag_only (bool): If True (and polar=True), returns only Magnitude.
            average (bool): If True, returns the average of phases (only if mag_only=True).
            zero_voltage_error (bool): If True, raises error if magnitude is ~0.

        Returns:
            Union[float, Tuple, List]: Voltage value(s) in the requested format.
        """
        self.dss.circuit.set_active_bus(bus)

        if polar:
            v = self.dss.bus.vmag_angle_pu if pu else self.dss.bus.vmag_angle
        else:
            v = self.dss.bus.pu_voltages if pu else self.dss.bus.voltages

        if not v or any(np.isnan(x) for x in v):
            self.fail(f"NaN or empty output for bus voltage: {bus}")

        n_phases = self.dss.bus.num_nodes
        nodes = self.dss.bus.nodes
        real_or_mag = tuple(v[0::2])
        imag_or_ang = tuple(v[1::2])

        real_or_mag = tuple(
            [real_or_mag[nodes.index(i + 1)] if (i + 1) in nodes else 0.0 for i in range(3)]
        )

        imag_or_ang = tuple(
            [imag_or_ang[nodes.index(i + 1)] if (i + 1) in nodes else 0.0 for i in range(3)]
        )

        if polar and zero_voltage_error and any([mag <= 1e-10 for mag in real_or_mag]):
            self.fail(f'Bus "{bus}" voltage is out of bounds: {real_or_mag}')

        # if n_phases == 1:
        #     return real_or_mag[0] if (polar and mag_only) else (real_or_mag[0], imag_or_ang[0])
        elif phase is None:
            if polar and mag_only and average:
                return sum(real_or_mag) / len(real_or_mag)
            elif polar and mag_only:
                return real_or_mag
            else:
                return real_or_mag, imag_or_ang
        elif phase - 1 in range(n_phases):
            if polar and mag_only:
                return real_or_mag[phase - 1]
            else:
                return real_or_mag[phase - 1], imag_or_ang[phase - 1]
        else:
            raise OpenDSSException(f"Bad phase for {n_phases}-phase Bus {bus}: {phase}")

    def get_voltage(
        self, name: str, element: str = "Load", line_bus: int = 1, **kwargs
    ) -> float | tuple | Any:
        """
        Gets the voltage at the terminals of a specific element.

        Args:
            name (str): Element name.
            element (str): Element class.
            line_bus (int): For lines/transformers, which bus to monitor (1 or 2).
            **kwargs: Passed to get_bus_voltage.
        """
        self.set_element(name, element)
        buses = self.dss.cktelement.bus_names
        # Selects the correct bus if it's a line element, otherwise picks the first one
        bus = buses[line_bus - 1 if element in LINE_CLASSES else 0]
        if self.dss.cktelement.num_phases == 1:
            kwargs["phase"] = 1
        return self.get_bus_voltage(bus, **kwargs)

    def get_all_bus_voltages(self, **kwargs) -> dict[str, float | tuple]:
        """
        Gets voltages for all buses in the system.

        Args:
            **kwargs: Passed to get_bus_voltage.

        Returns:
            Dict: Keys are bus names (or bus.phase), values are voltages.
        """
        buses = self.get_all_buses()
        data = {}
        for bus in buses:
            v = self.get_bus_voltage(bus, **kwargs)
            if isinstance(v, tuple) and v and not isinstance(v[0], tuple):
                # If tuple of phases is returned, expand to individual keys
                data.update({bus + "." + str(i + 1): v_ph for i, v_ph in enumerate(v)})
            else:
                data[bus] = v
        return data

    def get_power(
        self,
        name: str,
        element: str = "Load",
        phase: int | None = None,
        total: bool = False,
        line_bus: int = 1,
        raw: bool = False,
    ) -> tuple:
        """
        Gets the power (P, Q) of a specific element.

        Args:
            name (str): Element name.
            element (str): Element class.
            phase (int, optional): Specific phase.
            total (bool): If True, sums all phases.
            line_bus (int): Terminal for line elements (1 or 2).
            raw (bool): If True, returns raw DSS output tuple.

        Returns:
            Tuple: (P, Q) or tuple of tuples depending on arguments.
        """
        self.set_element(name, element)
        powers = self.dss.cktelement.powers

        if raw:
            return tuple(powers)

        n_phases = self.dss.cktelement.num_phases
        if element in LINE_CLASSES:
            start_idx = (line_bus - 1) * 2 * n_phases
            end_idx = start_idx + 2 * n_phases
            powers = powers[start_idx:end_idx]
        else:
            powers = powers[: 2 * n_phases]

        p_vals = powers[0::2]
        q_vals = powers[1::2]

        if n_phases == 1:
            return (p_vals[0], q_vals[0]) if p_vals else (0, 0)
        elif n_phases in [2, 3]:
            if phase is None:
                if total:
                    return sum(p_vals), sum(q_vals)
                else:
                    return tuple(p_vals), tuple(q_vals)
            if phase - 1 in range(n_phases):
                return p_vals[phase - 1], q_vals[phase - 1]
            else:
                raise OpenDSSException(f"Unknown phase for {element} {name}: {phase}")
        else:
            raise OpenDSSException(
                f"Cannot parse powers for {element} {name}, num phases={n_phases}"
            )

    def get_current(
        self,
        name: str,
        element: str = "Load",
        polar: bool = True,
        mag_only: bool = True,
        line_bus: int = 1,
        phase: int | None = None,
        total: bool = False,
        raw: bool = False,
        winding: int = 1,
    ) -> float | tuple:
        """
        Gets the current of an element.

        Args:
            name (str): Element name.
            element (str): Class.
            polar (bool): Return in polar format (Mag, Ang).
            mag_only (bool): Return only magnitude (if polar=True).
            line_bus (int): Terminal (1 or 2 for lines).
            phase (int): Specific phase.
            total (bool): Sum magnitudes (if polar=True and mag_only=True).
            raw (bool): Return raw DSS tuple.

        Returns:
            Union[float, Tuple]: Current value or tuple of values.
        """
        self.set_element(name, element)
        if polar:
            currents = self.dss.cktelement.currents_mag_ang
        else:
            currents = self.dss.cktelement.currents
        if raw:
            return tuple(currents)

        n_phases = self.dss.cktelement.num_phases

        if element in LINE_CLASSES:
            start_idx = (line_bus - 1) * 2 * n_phases
            end_idx = start_idx + 2 * n_phases
            currents = currents[start_idx:end_idx]

        elif element.lower() == "transformer":
            start_idx = (winding - 1) * (2 * n_phases + 2)
            end_idx = start_idx + 2 * n_phases
            currents = currents[start_idx:end_idx]
        elif element.lower() == "storage" or element.lower() == "pvsystem":
            currents = currents[:-2]
        else:
            currents = currents[: 2 * n_phases]

        real_or_mag = tuple(currents[0::2])
        imag_or_ang = tuple(currents[1::2])

        if n_phases == 1:
            if not real_or_mag:
                return 0 if mag_only else (0, 0)
            return real_or_mag[0] if mag_only and polar else (real_or_mag[0], imag_or_ang[0])
        elif n_phases in [2, 3]:
            if phase is None:
                if polar and mag_only:
                    return sum(real_or_mag) if total else real_or_mag
                else:
                    return real_or_mag, imag_or_ang
            if phase - 1 in range(n_phases):
                return real_or_mag[phase - 1], imag_or_ang[phase - 1]
            else:
                raise OpenDSSException(f"Unknown phase for {element} {name}: {phase}")
        else:
            raise OpenDSSException(
                f"Cannot parse currents for {element} {name}, num phases={n_phases}"
            )
