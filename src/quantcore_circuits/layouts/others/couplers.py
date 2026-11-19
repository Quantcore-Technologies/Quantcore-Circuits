"""Two-pad gap coupler ported from the QWri ``coupler.lym`` (``Coupler``) PCell.

The legacy coupler is the same drawing as the legacy ``Transmon``: two pads facing each other across ``gap`` with a
10 µm lead on each outer side, positive metal only. Here it is :class:`~quantcore_circuits.layouts.qubits.
legacy_transmon.TwoPadTransmon` without the junction refpoints: a series gap capacitor between ports ``left`` and
``right`` (metal on ``base_metal_addition``, own pocket on ``base_metal_gap_wo_grid`` when ``pocket_margin`` > 0).
"""

from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.qubits.legacy_transmon import TwoPadTransmon


class PadCoupler(TwoPadTransmon):
    """Series gap capacitor of two facing pads (legacy ``Coupler``); ports ``left`` / ``right``."""

    qcc_category = "coupler"
    qcc_junction = False

    junction_type = Param(pdt.TypeString, "No junction on a coupler", "No Squid", hidden=True)
    junction_params = Param(pdt.TypeString, "Unused on a coupler", "{}", hidden=True)
