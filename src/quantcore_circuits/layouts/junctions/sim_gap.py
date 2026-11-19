"""KQC ``"Sim"`` junction across a plain etched gap (the simulation stand-in of a drawn junction).

Simulation builds set ``junction_type = "Sim"``: KQC's :class:`~kqcircuits.junctions.sim.Sim` draws two 8 µm wide
metal pads, the lower one ``junction_lower_pad_length`` up from its origin and the upper one
``junction_upper_pad_length`` down from ``junction_total_length``; the junction port is the gap between them
(``port_squid_b`` = top of the lower pad, ``port_squid_a`` = bottom of the upper pad).

A qubit whose junction bridges a gap between two metal edges (Flipmon disc ↔ ring, TransmonTaperedInsets taper tips)
used to place it with ``junction_total_length = gap`` and KQC's default 12 + 13 µm pads. Two failures followed:

* a gap below 25 µm (both cells' defaults: 20 µm) makes the pads overlap — the islands are one conductor, the port
  points lie inside metal (KQC: ``Unable to create polygon for port``) and the C-matrix loses an island;
* the pads end exactly on the island edges: on a curved edge (the Flipmon disc) the pad touches the island at a single
  polygon vertex. KQC counts that as connected (``Region.interacting``), Q3D does not: ``AutoIdentifyNets`` splits
  the net and Q3D stops with ``Object '…signal_1_2' in Net 'Net1' and object '…signal_1_3' … are touching``.

:func:`sim_junction_in_gap` gives the pads :data:`SIM_PAD_OVERLAP_UM` of overlap into the metal on both sides
(merged with the island, so a straight edge looks the same as before) and keeps KQC's 12 / 13 µm in the gap while
that leaves at least KQC's own 8 µm port; a narrower gap gets a ``min(8, gap / 2)`` µm port in the middle. Only the
``"Sim"`` junction changes: fab junctions (and so every chip build) are untouched.
"""

from __future__ import annotations

SIM_PAD_OVERLAP_UM = 2.0  # how far the Sim pads reach into the metal on each side of the gap
SIM_PORT_UM = 8.0  # KQC's default Sim port length (33 − 13 − 12 µm)
KQC_LOWER_PAD_UM, KQC_UPPER_PAD_UM = 12.0, 13.0  # KQC Sim defaults


def sim_junction_in_gap(gap: float, overlap: float = SIM_PAD_OVERLAP_UM) -> tuple[float, dict]:
    """``(shift, params)`` of a KQC ``Sim`` junction across a ``gap`` µm wide etched gap.

    ``params`` go to ``produce_squid``; place the junction ``shift`` µm back into the metal on the origin side, i.e.
    ``trans * pya.DCplxTrans(1, 0, False, 0, -shift)`` where ``trans`` puts the origin on that gap edge with +y across
    the gap. ``include_background_gap`` is off: the cell has already etched the gap (KQC's 18 µm background box would
    notch both islands where the pads now enter them)."""
    gap = float(gap)
    if gap - KQC_LOWER_PAD_UM - KQC_UPPER_PAD_UM >= SIM_PORT_UM:
        lower, upper = KQC_LOWER_PAD_UM, KQC_UPPER_PAD_UM
    else:
        port = min(SIM_PORT_UM, gap / 2)
        lower = upper = (gap - port) / 2
    return overlap, {
        "junction_total_length": gap + 2 * overlap,
        "junction_lower_pad_length": lower + overlap,
        "junction_upper_pad_length": upper + overlap,
        "include_background_gap": False,
    }
