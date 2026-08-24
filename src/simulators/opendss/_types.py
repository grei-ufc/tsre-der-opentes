"""Tipos compartilhados pelas camadas do wrapper OpenDSS."""

from dataclasses import dataclass, field
from typing import Any

# Classes cujos terminais sao escolhidos por `line_bus` na API legada.
LINE_CLASSES = ["Line", "Xfmr", "Capacitor"]


class OpenDSSException(Exception):
    """Custom exception for OpenDSS interface related errors."""

    pass


@dataclass
class ElementSnapshot:
    """Everything read from one circuit element in a single engine visit.

    Holds the terminal layout together with the raw ``powers`` and
    ``currents_mag_ang`` arrays, so every per-phase quantity of the element can
    be derived without going back to the engine.
    """

    full_name: str
    n_cond: int
    n_term: int
    node_order: list[int]
    powers: Any
    currents_mag_ang: Any


@dataclass
class SolutionSnapshot:
    """Results cache scoped to one solution of the circuit.

    Cleared by :meth:`OpenDSS.invalidate_snapshot` on every solve and on every
    circuit edit, so reads never serve values from a superseded solution.

    Bus quantities are kept as the raw flat arrays returned by the engine rather
    than pre-folded per bus: folding every bus costs more than the bulk read
    itself, and a scenario that monitors two buses should not pay for 132.
    Magnitudes and angles come from different engine calls and are fetched
    independently, so asking only for magnitudes never reads the angles.
    """

    bus_vmag_pu: Any = None
    bus_volts: Any = None
    elements: dict[tuple[str, str], ElementSnapshot] = field(default_factory=dict)

    def clear(self) -> None:
        self.bus_vmag_pu = None
        self.bus_volts = None
        self.elements.clear()
