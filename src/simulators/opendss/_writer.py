"""Escritas no circuito OpenDSS.

Toda escrita invalida o cache da solucao, direta ou indiretamente via
``run_command``, para que nenhuma leitura sirva valores de uma solucao
superada.
"""

from __future__ import annotations

from typing import Any

from . import opendss_pv

# Tolerância relativa ao conferir um valor numérico relido do motor.
_VALUE_TOLERANCE = 1e-6


def _values_match(read_back: Any, written: Any) -> bool:
    """Compara o valor relido com o escrito, sem falsos negativos de formatação.

    O motor devolve as propriedades como texto, e ``get_property`` converte para
    float quando dá. Comparar as duas representações como string reprovava
    escritas corretas — escrever ``kW=1100`` e reler ``1100.0`` dá
    ``"1100" != "1100.0"``. Números são comparados numericamente; o resto,
    como texto sem diferenciar maiúsculas.
    """
    try:
        return abs(float(read_back) - float(written)) <= _VALUE_TOLERANCE * max(
            1.0, abs(float(written))
        )
    except (TypeError, ValueError):
        return str(read_back).strip().lower() == str(written).strip().lower()


class WriterMixin:
    """Ajuste de potencias, propriedades, taps e estado de elementos."""

    def set_power(
        self,
        name: str,
        p: float | None = None,
        q: float | None = None,
        element: str = "Load",
        size: float | None = None,
    ) -> None:
        """
        Sets the active and reactive power of an element.

        For 'Storage': Automatically calculates state (Charging/Discharging) and
        Power Factor based on the sign of 'p'.

        Args:
            name (str): Element name.
            p (float): Active Power (kW).
            q (float): Reactive Power (kvar).
            element (str): Class ('Load', 'PV', 'Storage').
            size (float): Rated power (only for Storage).
        """
        element_class = "PVSystem" if element == "PV" else element
        if element_class != "Storage":
            cmd = f"edit {element_class}.{name}"
            if p is not None:
                cmd += f" kW={p}"
            if q is not None:
                cmd += f" kvar={q}"
            self.run_command(cmd)
        else:
            # Specific logic for Storage
            if p is None:
                return
            if q is None:
                q = 0.0

            if p > 0:
                state_str = "Discharging"
            elif p < 0:
                state_str = "Charging"
            else:
                state_str = "Idling"

            if state_str == "Idling":
                cmd = f"Edit Storage.{name} State={state_str}"
            else:
                cmd = f"Edit Storage.{name} State={state_str} kW={p} kvar={q}"

            self.run_command(cmd)

    def set_property(
        self, name: str, property_name: str, value: Any, element: str = "Load"
    ) -> None:
        """Set an element property and confirm the engine accepted it.

        Args:
            name: Element name.
            property_name: DSS property to write.
            value: Value to write.
            element: Element class.

        Raises:
            OpenDSSException: If the property does not exist for that element,
                or if reading it back does not match what was written.
        """
        # Validar antes de escrever: mandar uma propriedade inexistente ao
        # motor faz o OpenDSS abrir uma caixa de dialogo no Windows, que trava
        # execucoes nao interativas.
        valid = self.get_all_properties(name, element)
        if property_name.lower() not in [p.lower() for p in valid]:
            self.fail(
                f'{element}.{name} has no property "{property_name}". '
                f"Valid options: {', '.join(sorted(valid))}"
            )
            return

        self.run_command(f"edit {element}.{name} {property_name}={value}")

        new_value = self.get_property(name, property_name, element)
        if not _values_match(new_value, value):
            self.fail(
                f"Failed to set {element}.{name}.{property_name}: "
                f"wrote {value!r}, engine reports {new_value!r}"
            )

    def remove_loadshape(self, name: str, element: str = "Load") -> None:
        """Removes the associated loadshape, setting the mode to constant."""
        self.set_property(name, "yearly", "constant", element)

    def set_is_open(
        self, name: str, open: bool = True, element: str = "Load", term: int = 1
    ) -> None:
        """Opens or closes the terminal of an element."""
        action = "Open" if open else "Close"
        full_name = f"{element}.{name}"
        self.run_command(f"{action} {full_name} term={term}")

    def set_tap(self, name: str, tap: int, max_tap: int = 16) -> None:
        """Sets the tap of a RegControl, clamping it to the max value."""
        # self.set_element(name, 'RegControl')
        self.invalidate_snapshot()
        self.dss.regcontrols.name = name
        tap = int(min(max(tap, -max_tap), max_tap))
        self.dss.regcontrols.tap_number = tap

    def set_pt_ratio(self, name: str, pt_ratio: float) -> None:
        """Sets the Potential Transformer (PT) Ratio of a CapControl."""
        self.invalidate_snapshot()
        self.set_element(name, "CapControl")
        self.dss.capcontrols.pt_ratio = pt_ratio

    def set_pvsystem_pq(self, name: str, p_des: float, q_des: float):
        """Forca valores de P e Q em um PVSystem."""
        self.invalidate_snapshot()
        opendss_pv.set_pvsystem_pq(self.dss, name, p_des, q_des)

    def set_storage_soc(self, name: str, soc_pu: float) -> None:
        """Force the state of charge of a Storage element.

        Args:
            name: Storage name (without the ``Storage.`` prefix).
            soc_pu: Target state of charge in per unit; clamped to ``[0, 1]``.
        """
        soc_pu = min(max(float(soc_pu), 0.0), 1.0)
        self.run_command(f"Edit Storage.{name} %stored={soc_pu * 100.0}")
