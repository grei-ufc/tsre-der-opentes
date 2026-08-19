"""PVSystem operations on the OpenDSS circuit.

Standalone functions that receive an active ``py_dss_interface.DSS`` instance
and encapsulate parameter reading, XY-curve lookups, PQ control, and
measurements.
"""

from __future__ import annotations

from typing import Any


def get_all_pvsystems_info(dss: Any) -> dict[str, dict[str, Any]]:
    """Return static data and curves for every PVSystem in the circuit.

    Automatically reads the attached XYCurves (``P-TCurve``, ``EffCurve``)
    for each inverter.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.

    Returns:
        Dictionary mapping PVSystem names to parameter dictionaries.
    """
    pv_infos: dict[str, dict[str, Any]] = {}
    names = dss.pvsystems.names

    if not names or names[0].upper() == "NONE":
        return pv_infos

    for name in names:
        dss.pvsystems.name = name

        pmpp = dss.pvsystems.pmpp
        kva = dss.pvsystems.kva
        irradiance = dss.pvsystems.irradiance
        daily = dss.text(f"? PVSystem.{name}.daily")

        cutin = float(dss.text(f"? PVSystem.{name}.%cutin"))
        cutout = float(dss.text(f"? PVSystem.{name}.%cutout"))

        bus_name = dss.cktelement.bus_names[0]

        pt_curve_name = dss.text(f"? PVSystem.{name}.P-TCurve")
        eff_curve_name = dss.text(f"? PVSystem.{name}.EffCurve")

        pt_x, pt_y = _read_xy_curve(dss, pt_curve_name)
        eff_x, eff_y = _read_xy_curve(dss, eff_curve_name)

        pv_infos[name] = {
            "pmpp": pmpp,
            "kva": kva,
            "irradiance": irradiance,
            "daily": daily,
            "pct_cutin": cutin,
            "pct_cutout": cutout,
            "pt_curve_x": pt_x,
            "pt_curve_y": pt_y,
            "eff_curve_x": eff_x,
            "eff_curve_y": eff_y,
            "bus": bus_name,
        }

    return pv_infos


def set_pvsystem_pq(dss: Any, name: str, p_des: float, q_des: float) -> None:
    """Force active and reactive power values on a PVSystem, bypassing curves.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        name: PVSystem name (without the ``PVSystem.`` prefix).
        p_des: Desired active power (kW, signed for injection).
        q_des: Desired reactive power (kvar).
    """
    dss.circuit.set_active_element(f"PVSystem.{name}")
    p_abs = abs(p_des)

    if p_abs > 0.001:
        cmd = f"Edit PVSystem.{name} pmpp={p_abs} irradiance=1.0 kvar={q_des}"
        dss.text(cmd)
    else:
        cmd = f"Edit PVSystem.{name} irradiance=0.0 kvar={q_des}"
        dss.text(cmd)


def get_pvsystem_power(dss: Any, name: str) -> tuple[float, float]:
    """Read active and reactive power from a PVSystem.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        name: PVSystem name (without the ``PVSystem.`` prefix).

    Returns:
        Tuple ``(P_kW, Q_kvar)`` with inverted sign convention (injection).
    """
    dss.circuit.set_active_element(f"PVSystem.{name}")
    powers = dss.cktelement.powers
    p_meas = -sum(powers[0:6:2])
    q_meas = -sum(powers[1:6:2])
    return p_meas, q_meas


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _read_xy_curve(dss: Any, curve_name: str) -> tuple[list[float], list[float]]:
    """Read the X and Y arrays from an OpenDSS XYCurve.

    Args:
        dss: Active ``py_dss_interface.DSS`` instance.
        curve_name: Name of the XYCurve element.

    Returns:
        Tuple of ``(x_values, y_values)`` as lists of floats.
    """
    if not curve_name:
        return [], []
    dss.xycurves.name = curve_name
    x = list(dss.xycurves.x_array)
    y = list(dss.xycurves.y_array)
    return x, y
