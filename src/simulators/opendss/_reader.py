"""Leituras do circuito OpenDSS.

Todas as consultas servem a ultima solucao e passam pelo cache de
:class:`~._types.SolutionSnapshot`, entao repetir uma leitura no mesmo passo
nao custa nova ida ao motor. Resolva o fluxo antes de ler.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import py_dss_interface

from . import opendss_pv, opendss_regulator, opendss_storage
from ._types import ElementSnapshot, OpenDSSException
from ._utils import map_to_phases


class ReaderMixin:
    """Consultas de barras, elementos, propriedades e totais do circuito."""

    def get_all_buses(self) -> list[str]:
        """Returns a list of all bus names in the circuit."""
        return self.dss.circuit.buses_names

    def get_all_elements(self, element: str = "Load") -> pd.DataFrame:
        """
        Returns a DataFrame containing all properties for all elements of a specific class.

        Args:
            element (str): The element class (e.g., 'Load', 'Line').

        Returns:
            pd.DataFrame: DataFrame indexed by the full element name.
        """
        try:
            self.dss.circuit.set_active_class(element)
        except py_dss_interface.errors.DSSException:
            # A classe nao existe no OpenDSS: nao ha elementos a listar.
            return pd.DataFrame()

        # CORREÇÃO DEFINITIVA: Checa se existem elementos antes de acessar os nomes
        if self.dss.active_class.count == 0:
            return pd.DataFrame()

        # Agora é seguro pedir os nomes
        names = self.dss.active_class.names

        # Dupla checagem de segurança
        if not names or names[0] is None or names[0].lower() == "none":
            return pd.DataFrame()

        all_data = {}
        for name in names:
            full_name = f"{element}.{name}"
            self.dss.circuit.set_active_element(full_name)

            element_data = {}
            prop_names = self.dss.dsselement.property_names
            for i, prop_name in enumerate(prop_names, 1):
                element_data[prop_name] = self.dss.dssproperties.value_read(str(i))

            all_data[full_name] = element_data

        df = pd.DataFrame.from_dict(all_data, orient="index")
        return df

    def _element_snapshot(self, name: str, element: str) -> ElementSnapshot:
        """Terminal layout plus powers and currents of one element, read once per solve.

        Activating an element and pulling its arrays costs one engine round-trip
        each. Within a single step every attribute of an element is derived from
        the same three arrays, so they are fetched together and reused until the
        next solve or circuit edit.

        Args:
            name: Element name.
            element: Element class.

        Returns:
            The cached :class:`ElementSnapshot` for this element.
        """
        key = (element.lower(), name.lower())
        snapshot = self._snapshot.elements.get(key)

        if snapshot is None:
            self.set_element(name, element)
            snapshot = ElementSnapshot(
                full_name=self.dss.cktelement.name,
                n_cond=self.dss.cktelement.num_conductors,
                n_term=self.dss.cktelement.num_terminals,
                node_order=list(self.dss.cktelement.node_order),
                powers=self.dss.cktelement.powers,
                currents_mag_ang=self.dss.cktelement.currents_mag_ang,
            )
            self._snapshot.elements[key] = snapshot

        return snapshot

    @property
    def node_index(self) -> dict[str, list[tuple[int, int]]]:
        """Position of each bus phase inside the engine's flat nodal arrays.

        The node layout is a property of the compiled circuit, not of a
        solution, so it is built once and reused across steps.

        Returns:
            Mapping of lowercase bus name to a list of
            ``(phase_index, array_position)`` pairs, where ``phase_index`` is
            0-based and ``array_position`` indexes ``circuit.nodes_names``.
        """
        if self._node_index is None:
            self._node_index = self._build_node_index()
        return self._node_index

    def _build_node_index(self) -> dict[str, list[tuple[int, int]]]:
        """Parse ``circuit.nodes_names`` once into a per-bus position lookup."""
        index: dict[str, list[tuple[int, int]]] = {}

        for position, node_name in enumerate(self.dss.circuit.nodes_names):
            bus, _, node_str = node_name.rpartition(".")
            try:
                node = int(node_str)
            except ValueError:
                continue
            if not 1 <= node <= 3:
                continue
            index.setdefault(bus.lower(), []).append((node - 1, position))

        return index

    def _bus_positions(self, bus: str) -> list[tuple[int, int]]:
        """Positions for *bus*, or an empty list after reporting an unknown bus."""
        bus_key = bus.lower().split(".")[0]
        positions = self.node_index.get(bus_key)

        if positions is None:
            self.fail(f'Bus "{bus}" not found in circuit voltages')
            return []

        return positions

    def get_bus_vmag_pu(self, bus: str) -> list[float]:
        """Per-unit voltage magnitude per phase of one bus.

        Served from a single bulk read of the whole circuit
        (``circuit.buses_vmag_pu``), cached until the next solve or edit. Only
        the requested bus is unpacked, so monitoring a couple of buses does not
        cost the whole circuit.

        Args:
            bus: Bus name, with or without a node suffix (``'675'`` or ``'675.1'``).

        Returns:
            ``[|V1|, |V2|, |V3|]`` in per unit; phases the bus lacks stay ``0.0``.

        Raises:
            OpenDSSException: If the bus is not in the circuit and
                ``fail_on_error`` is set.
        """
        if self._snapshot.bus_vmag_pu is None:
            self._snapshot.bus_vmag_pu = self.dss.circuit.buses_vmag_pu
        mags = self._snapshot.bus_vmag_pu

        phases = [0.0, 0.0, 0.0]
        for phase_idx, position in self._bus_positions(bus):
            phases[phase_idx] = mags[position]
        return phases

    def get_bus_vang(self, bus: str) -> list[float]:
        """Voltage angle per phase of one bus, in degrees.

        Angles come from ``circuit.buses_volts``, read and cached separately
        from the magnitudes so that a scenario asking only for magnitudes never
        pays for this call.

        Args:
            bus: Bus name, with or without a node suffix.

        Returns:
            ``[ang1, ang2, ang3]`` in degrees; phases the bus lacks stay ``0.0``.

        Raises:
            OpenDSSException: If the bus is not in the circuit and
                ``fail_on_error`` is set.
        """
        if self._snapshot.bus_volts is None:
            self._snapshot.bus_volts = self.dss.circuit.buses_volts
        volts = self._snapshot.bus_volts

        phases = [0.0, 0.0, 0.0]
        for phase_idx, position in self._bus_positions(bus):
            phases[phase_idx] = math.degrees(
                math.atan2(volts[2 * position + 1], volts[2 * position])
            )
        return phases

    def get_bus_voltage_pu(self, bus: str) -> tuple[list[float], list[float]]:
        """Per-unit magnitude and angle per phase of one bus.

        Convenience over :meth:`get_bus_vmag_pu` and :meth:`get_bus_vang`; reads
        both arrays. Prefer the individual methods when only one is needed.

        Args:
            bus: Bus name, with or without a node suffix.

        Returns:
            Tuple ``([|V1|, |V2|, |V3|], [ang1, ang2, ang3])`` in per unit and
            degrees.
        """
        return self.get_bus_vmag_pu(bus), self.get_bus_vang(bus)

    @staticmethod
    def _terminal_nodes_and_slice(
        snapshot: ElementSnapshot, terminal: int
    ) -> tuple[list[int], slice]:
        """Node numbers and the value slice for one terminal of *snapshot*.

        OpenDSS lays out ``powers``/``currents`` as ``num_terminals`` blocks of
        ``num_conductors`` complex pairs. ``node_order`` follows the same layout
        with one node number per conductor, so both are sliced identically.

        Using ``num_conductors`` (rather than ``num_phases``) is what makes this
        work uniformly for wye elements with a neutral, delta elements, lines,
        and transformer windings.

        Args:
            snapshot: Element snapshot to slice.
            terminal: 1-based terminal (or winding) number.

        Returns:
            Tuple of the terminal's node numbers and the ``slice`` selecting its
            values inside a flat ``[re, im, re, im, ...]`` OpenDSS array.

        Raises:
            OpenDSSException: If *terminal* is out of range for the element.
        """
        if not 1 <= terminal <= snapshot.n_term:
            raise OpenDSSException(
                f'Terminal {terminal} is out of range for "{snapshot.full_name}" '
                f"({snapshot.n_term} terminal(s))"
            )

        start = (terminal - 1) * snapshot.n_cond
        nodes = snapshot.node_order[start : start + snapshot.n_cond]
        return nodes, slice(2 * start, 2 * (start + snapshot.n_cond))

    def get_phase_powers(
        self, name: str, element: str = "Load", terminal: int = 1
    ) -> tuple[list[float], list[float]]:
        """Active and reactive power per phase, positioned by the element's nodes.

        Unlike :meth:`get_power`, the return shape does not depend on the number
        of phases: it is always three values indexed by phase, with ``0.0`` where
        the element has no conductor.

        Args:
            name: Element name.
            element: Element class (``'Load'``, ``'PVSystem'``, ``'Line'``, ...).
            terminal: Terminal to read (1 for shunt elements; 1 or 2 for lines;
                winding number for transformers).

        Returns:
            Tuple ``([P1, P2, P3], [Q1, Q2, Q3])`` in kW and kvar, using the
            native OpenDSS sign convention (load positive).
        """
        snapshot = self._element_snapshot(name, element)
        nodes, values = self._terminal_nodes_and_slice(snapshot, terminal)
        powers = snapshot.powers[values]
        return map_to_phases(nodes, powers[0::2]), map_to_phases(nodes, powers[1::2])

    def get_phase_currents(
        self, name: str, element: str = "Load", terminal: int = 1
    ) -> tuple[list[float], list[float]]:
        """Current magnitude and angle per phase, positioned by the element's nodes.

        Args:
            name: Element name.
            element: Element class (``'Load'``, ``'PVSystem'``, ``'Line'``, ...).
            terminal: Terminal to read (1 for shunt elements; 1 or 2 for lines;
                winding number for transformers).

        Returns:
            Tuple ``([|I1|, |I2|, |I3|], [ang1, ang2, ang3])`` in amperes and
            degrees.
        """
        snapshot = self._element_snapshot(name, element)
        nodes, values = self._terminal_nodes_and_slice(snapshot, terminal)
        currents = snapshot.currents_mag_ang[values]
        return map_to_phases(nodes, currents[0::2]), map_to_phases(nodes, currents[1::2])

    def get_power_total(
        self, name: str, element: str = "Load", terminal: int = 1
    ) -> tuple[float, float]:
        """Active and reactive power of an element, summed over its phases.

        The scalar counterpart of :meth:`get_phase_powers`. Separating the two
        is what removes the need for a ``total`` flag that changes the return
        shape.

        Args:
            name: Element name.
            element: Element class.
            terminal: Terminal to read.

        Returns:
            Tuple ``(P, Q)`` in kW and kvar, native OpenDSS sign convention.
        """
        active, reactive = self.get_phase_powers(name, element=element, terminal=terminal)
        return sum(active), sum(reactive)

    def get_all_complex(self, name: str, element: str = "Load") -> dict[str, tuple]:
        """Returns a dictionary with all complex quantities (V, I, S) for the element."""
        self.set_element(name, element)
        return {
            "Voltages": self.dss.cktelement.voltages,
            "VoltagesMagAng": self.dss.cktelement.voltages_mag_ang,
            "Currents": self.dss.cktelement.currents,
            "CurrentsMagAng": self.dss.cktelement.currents_mag_ang,
            "Powers": self.dss.cktelement.powers,
        }

    def get_all_properties(self, name: str, element: str = "Load") -> list[str]:
        """Returns a list of property names available for the element."""
        self.set_element(name, element)
        return self.dss.dsselement.property_names

    def get_property(self, name: str, property_name: str, element: str = "Load") -> float | str:
        """Reads the value of a specific property of an element."""
        all_properties = self.get_all_properties(name, element)
        if property_name.lower() not in [p.lower() for p in all_properties]:
            raise OpenDSSException(
                f'Could not find {property_name} property for {element} "{name}"'
            )

        idx = [p.lower() for p in all_properties].index(property_name.lower()) + 1
        value = self.dss.dssproperties.value_read(str(idx))

        try:
            return float(value)
        except (ValueError, TypeError):
            return value

    def get_is_open(self, name: str, element: str = "Load", term: int = 1) -> bool:
        """Checks if the element terminal is open."""
        self.set_element(name, element)
        return bool(self.dss.cktelement.is_terminal_open(term))

    def get_tap(self, name: str) -> int:
        """Gets the current tap of a RegControl."""
        # self.set_element(name, 'RegControl')
        self.dss.regcontrols.name = name
        return self.dss.regcontrols.tap_number

    def get_pt_ratio(self, name: str) -> float:
        """Gets the PT Ratio of a CapControl."""
        self.set_element(name, "CapControl")
        return self.dss.capcontrols.pt_ratio

    def get_circuit_power(self) -> tuple[float, float]:
        """
        Gets the total active and reactive power of the circuit.

        Note: This inverts the standard OpenDSS sign convention (where generation is positive)
        so that grid consumption is positive and injection into the grid is negative
        (or vice versa, depending on reference, but signs are flipped from native output).

        Returns:
            Tuple[float, float]: (P_kW, Q_kvar).
        """
        p_kw, q_kvar = self.dss.circuit.total_power
        p_kw, q_kvar = -p_kw, -q_kvar

        if np.isnan(p_kw) or np.isnan(q_kvar):
            self.fail(f"NaN output for circuit power: ({p_kw}, {q_kvar})")
        return p_kw, q_kvar

    def get_losses(self) -> tuple[float, float]:
        """
        Gets the total circuit losses.

        Returns:
            Tuple[float, float]: (P_kW, Q_kvar).
        """
        p_w, q_var = self.dss.circuit.losses
        return p_w / 1000.0, q_var / 1000.0

    def get_total_power(self, element: str = "Load") -> tuple[float, float]:
        """
        Calculates the aggregated power for a specific class of elements.

        Args:
            element (str): The class name (e.g., 'Load', 'PVSystem', 'Storage').

        Returns:
            Tuple[float, float]: Total (P_kW, Q_kvar).
        """
        p_total, q_total = 0.0, 0.0

        try:
            self.dss.circuit.set_active_class(element)
        except py_dss_interface.errors.DSSException:
            return 0.0, 0.0

        if self.dss.active_class.count == 0:
            return 0.0, 0.0

        idx = self.dss.active_class.first()
        while idx > 0:
            powers = self.dss.cktelement.powers
            p_total += sum(powers[0::2])
            q_total += sum(powers[1::2])
            idx = self.dss.active_class.next()

        # For Storage, we invert the sign to match injection/consumption conventions
        if element == "Storage":
            return -p_total, -q_total

        return p_total, q_total

    def get_circuit_info(self) -> dict[str, float]:
        """Summary of the system state for the current solution.

        Reads only; solve first via :meth:`~._engine.EngineMixin.run_dss`.
        (It used to re-solve on its own, which made a getter silently advance
        the simulation.)

        Returns:
            Dict[str, float]: Dictionary containing Total P/Q (MW/MVAR) and Losses.
        """
        p_total_kw, q_total_kvar = self.get_circuit_power()
        p_loss_kw, q_loss_kvar = self.get_losses()
        total_by_class = {
            class_name: self.get_total_power(class_name)
            for class_name, included in self.includes_elements.items()
            if included
        }

        out = {
            "Total P (MW)": p_total_kw / 1000,
            "Total Loss P (MW)": p_loss_kw / 1000,
        }
        for class_name, (p, _q) in total_by_class.items():
            display_name = "PV" if class_name == "PVSystem" else class_name
            out[f"Total {display_name} P (MW)"] = p / 1000

        out.update(
            {
                "Total Q (MVAR)": q_total_kvar / 1000,
                "Total Loss Q (MVAR)": q_loss_kvar / 1000,
            }
        )
        for class_name, (_p, q) in total_by_class.items():
            display_name = "PV" if class_name == "PVSystem" else class_name
            out[f"Total {display_name} Q (MVAR)"] = q / 1000
        return out

    def get_all_regulators_info(self):
        """Detecta todos os RegControls e retorna seus dados estaticos."""
        return opendss_regulator.get_all_regulators_info(self.dss)

    def get_regulator_measurements(self, reg_info):
        """Le tensao, corrente e tap de um regulador."""
        return opendss_regulator.get_regulator_measurements(self.dss, reg_info)

    def get_pvsystem_power(self, name: str):
        """Le P e Q medidos nos terminais de um PVSystem."""
        return opendss_pv.get_pvsystem_power(self.dss, name)

    def get_all_pvsystems_info(self):
        """Retorna dados estaticos e curvas de todos os PVSystems."""
        return opendss_pv.get_all_pvsystems_info(self.dss)

    def get_all_storages_info(self):
        """Retorna dados estaticos de todos os elementos Storage."""
        return opendss_storage.get_all_storages_info(self.dss)

    def get_storage_soc(self, name: str) -> float:
        """State of charge of a Storage element, in per unit.

        Args:
            name: Storage name (without the ``Storage.`` prefix).

        Returns:
            State of charge between 0.0 and 1.0.
        """
        self.dss.storages.name = name
        return self.dss.storages.pu_soc
