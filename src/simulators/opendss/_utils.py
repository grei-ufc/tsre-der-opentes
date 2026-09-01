"""Reusable helpers for normalizing three-phase data returned by OpenDSS."""

from collections.abc import Sequence


def map_to_phases(nodes: Sequence[int], values: Sequence[float]) -> list[float]:
    """Place per-conductor *values* at the index of the phase they belong to.

    OpenDSS returns element quantities ordered by *conductor*, not by phase. A
    single-phase element connected to ``bus.3`` reports one conductor value that
    belongs to phase 3 — padding it to the right would wrongly report it as
    phase 1. This function uses the element's node numbers (from
    ``cktelement.node_order``) to put each value in its real position.

    Node ``0`` is the neutral/ground conductor and is skipped. Nodes above 3
    (secondary windings, extra conductors) are skipped as well.

    Args:
        nodes: Node number of each conductor on one terminal, e.g. ``[3, 0]``
            for a single-phase element on phase 3 with a neutral.
        values: One value per conductor, in the same order as *nodes*.

    Returns:
        A list of exactly three floats, indexed by phase (``[p1, p2, p3]``).
        Positions with no conductor stay ``0.0``.
    """
    phases = [0.0, 0.0, 0.0]
    for node, value in zip(nodes, values, strict=False):
        if 1 <= node <= 3:
            phases[node - 1] = value
    return phases
