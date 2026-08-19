"""Voltage regulator operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate regulator detection, parameter reading, and measurements.
"""

from __future__ import annotations

from typing import Any


def get_all_regulators_info(dss: Any) -> list[dict[str, Any]]:
    """Detect every RegControl and return its static data.

    Includes topology information (Transformer, Winding, Bus, Phase).

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.

    Returns:
        List of dictionaries, one per detected regulator.
    """
    reg_list: list[dict[str, Any]] = []

    try:
        names = dss.regcontrols.names
    except Exception:
        return reg_list

    for name in names:
        dss.regcontrols.name = name
        dss.regcontrols.max_tap_change = 0
        dss.regcontrols.tap_number = 0

        info: dict[str, Any] = {
            "name": name,
            "vreg": dss.regcontrols.forward_vreg,
            "band": dss.regcontrols.forward_band,
            "pt_ratio": dss.regcontrols.pt_ratio,
            "ct_primary": dss.regcontrols.ct_primary,
            "R": dss.regcontrols.forward_r,
            "X": dss.regcontrols.forward_x,
            "delay": dss.regcontrols.delay,
            "tap_delay": dss.regcontrols.tap_delay,
            "trafo": dss.regcontrols.transformer,
            "winding": dss.regcontrols.winding,
            "tap_ini": 0,
        }

        # Resolve o barramento alvo a partir do transformer
        trafo_name = info["trafo"]
        winding_idx = info["winding"]
        dss.circuit.set_active_element(f"Transformer.{trafo_name}")
        full_bus_name = dss.cktelement.bus_names[winding_idx - 1]

        if "." in full_bus_name:
            parts = full_bus_name.split(".")
            info["target_bus"] = parts[0]
            try:
                info["target_phase"] = int(parts[1])
            except (ValueError, TypeError):
                info["target_phase"] = 1
        else:
            info["target_bus"] = full_bus_name
            info["target_phase"] = 1

        reg_list.append(info)

    return reg_list


def get_regulator_measurements(dss: Any, reg_info: dict[str, Any]) -> dict[str, Any]:
    """Read voltage, current, and tap position of a regulator.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        reg_info: Dictionary returned by :func:`get_all_regulators_info`.

    Returns:
        Dictionary with keys ``'v'`` (complex), ``'i'`` (complex),
        and ``'tap'`` (int).
    """
    res: dict[str, Any] = {"v": 0j, "i": 0j, "tap": 0}

    try:
        dss.regcontrols.name = reg_info["name"]
        res["tap"] = dss.regcontrols.tap_number

        # Tensao no barramento alvo
        dss.circuit.set_active_bus(reg_info["target_bus"])
        phase = reg_info["target_phase"]
        v_r, v_i = _get_bus_voltage_raw(dss, reg_info["target_bus"], phase)
        res["v"] = complex(v_r, v_i)

        # Corrente no transformer
        dss.circuit.set_active_element(f"Transformer.{reg_info['trafo']}")
        n_phases = dss.cktelement.num_phases
        winding = reg_info["winding"]
        start = (winding - 1) * (2 * n_phases + 2)
        currents = dss.cktelement.currents
        phase_currents = currents[start : start + 2 * n_phases]

        i_r = phase_currents[(phase - 1) * 2]
        i_i = phase_currents[(phase - 1) * 2 + 1]
        res["i"] = complex(i_r, i_i)

    except Exception:
        pass

    return res


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _get_bus_voltage_raw(dss: Any, bus: str, phase: int) -> tuple[float, float]:
    """Return the (real, imaginary) voltage for a single bus phase in Volts.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        bus: Bus name to query.
        phase: Phase number (1-based) to extract.

    Returns:
        Tuple of ``(real_voltage, imag_voltage)`` in Volts.
    """
    dss.circuit.set_active_bus(bus)
    v = dss.bus.voltages
    nodes = dss.bus.nodes

    real = v[0::2]
    imag = v[1::2]

    idx = nodes.index(phase) if phase in nodes else 0
    return real[idx], imag[idx]
