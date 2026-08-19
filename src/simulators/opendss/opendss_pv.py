"""
Operacoes de PVSystem no OpenDSS.

Funcoes standalone que recebem a instancia ``dss`` (py_dss_interface.DSS)
e encapsulam leitura de parametros, curvas XY, controle PQ e medicao.
"""
from typing import Dict, Tuple

import numpy as np


def get_all_pvsystems_info(dss) -> Dict[str, dict]:
    """Retorna dados estaticos e curvas de todos os PVSystems.

    Le automaticamente as XYCurves (P-TCurve, EffCurve) atreladas
    a cada inversor.

    Args:
        dss: Instancia py_dss_interface.DSS ativa.

    Returns:
        Dict mapeando nome_do_PVSystem -> dict com parametros.
    """
    pv_infos: Dict[str, dict] = {}
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


def set_pvsystem_pq(dss, name: str, p_des: float, q_des: float) -> None:
    """Forca valores de P e Q em um PVSystem, desacoplando das curvas.

    Args:
        dss: Instancia py_dss_interface.DSS ativa.
        name: Nome do PVSystem (sem o prefixo 'PVSystem.').
        p_des: Potencia ativa desejada (kW, sinalizado por injecao).
        q_des: Potencia reativa desejada (kvar).
    """
    dss.circuit.set_active_element(f"PVSystem.{name}")
    p_abs = abs(p_des)

    if p_abs > 0.001:
        cmd = (
            f"Edit PVSystem.{name} pmpp={p_abs} "
            f"irradiance=1.0 kvar={q_des}"
        )
        dss.text(cmd)
    else:
        cmd = f"Edit PVSystem.{name} irradiance=0.0 kvar={q_des}"
        dss.text(cmd)


def get_pvsystem_power(dss, name: str) -> Tuple[float, float]:
    """Le a potencia ativa e reativa de um PVSystem.

    Args:
        dss: Instancia py_dss_interface.DSS ativa.
        name: Nome do PVSystem (sem o prefixo 'PVSystem.').

    Returns:
        Tuple (P_kW, Q_kvar) com sinal invertido (conv. injecao).
    """
    dss.circuit.set_active_element(f"PVSystem.{name}")
    powers = dss.cktelement.powers
    p_meas = -sum(powers[0:6:2])
    q_meas = -sum(powers[1:6:2])
    return p_meas, q_meas


# ------------------------------------------------------------------
# Helpers internos
# ------------------------------------------------------------------

def _read_xy_curve(dss, curve_name: str):
    """Le os arrays X e Y de uma XYCurve do OpenDSS."""
    if not curve_name:
        return [], []
    dss.xycurves.name = curve_name
    x = list(dss.xycurves.x_array)
    y = list(dss.xycurves.y_array)
    return x, y
