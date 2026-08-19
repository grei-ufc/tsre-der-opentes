"""Reusable helpers for normalizing three-phase data returned by OpenDSS."""

from typing import Any


def to_3phase(value: float | tuple | list | None) -> list[float]:
    """Normalize any OpenDSS return (scalar, tuple, list) to a 3-element list.

    Fills missing positions with ``0.0``.

    Args:
        value: Raw value from OpenDSS — may be a scalar, tuple, list,
            or ``None``.

    Returns:
        A list of exactly three floats representing the three phases.
    """
    if value is None:
        return [0.0, 0.0, 0.0]
    if isinstance(value, (list, tuple)):
        result = list(value)
    else:
        result = [value]
    while len(result) < 3:
        result.append(0.0)
    return result


def extract_3phase_pq(
    dss_wrapper: Any,
    name: str,
    element: str,
    attrs: dict[str, Any],
    sign: int = -1,
    line_bus: int = 1,
) -> dict[str, float]:
    """Extract three-phase powers and currents and map them to Mosaik attributes.

    Supported attributes: P1/P2/P3, Q1/Q2/Q3, I1_A/I2_A/I3_A,
    and totals P_act/Q_act (or P_meas/Q_meas) when present in *attrs*.

    Args:
        dss_wrapper: OpenDSS wrapper instance.
        name: Element name.
        element: Element class (``'Storage'``, ``'PVSystem'``, etc.).
        attrs: Dictionary of attributes requested by Mosaik.
        sign: Inversion sign (``-1`` for injection, ``1`` for consumption).
        line_bus: Terminal for line elements (1 or 2).

    Returns:
        Dictionary mapping attribute names to their float values.
    """
    data: dict[str, float] = {}

    # Potências por fase
    p_raw, q_raw = dss_wrapper.get_power(
        name=name,
        element=element,
        total=False,
        line_bus=line_bus,
    )
    p_list = to_3phase(p_raw)
    q_list = to_3phase(q_raw)

    # Correntes por fase
    curr_mag, _ = dss_wrapper.get_current(
        name,
        element=element,
        polar=True,
        mag_only=False,
        line_bus=line_bus,
    )
    i_mags = to_3phase(curr_mag)

    p_map = {"P1": 0, "P2": 1, "P3": 2}
    q_map = {"Q1": 0, "Q2": 1, "Q3": 2}
    i_map = {"I1_A": 0, "I2_A": 1, "I3_A": 2}

    for attr in attrs:
        if attr in p_map:
            data[attr] = sign * p_list[p_map[attr]]
        elif attr in q_map:
            data[attr] = sign * q_list[q_map[attr]]
        elif attr in i_map:
            data[attr] = i_mags[i_map[attr]]
        elif attr in ("P_act", "P_meas"):
            data[attr] = sign * sum(p_list)
        elif attr in ("Q_act", "Q_meas"):
            data[attr] = sign * sum(q_list)

    return data
