"""The two finger exposures of the QWri trilayer junctions as stand-alone cells (legacy QuantumPcells
``JJ_finger_top.lym`` "JJ_finger Top" and ``JJ_finger_bottom.lym`` "JJ_finger Bottom").

Each is one exposure of a cross junction, not a junction by itself (category ``shape``: no ports, no LOM model);
the junctions built from them are :class:`~.trilayer.TrilayerJunction`, :class:`~.trilayer.TrilayerSquid` and the
cells in :mod:`.legacy_junctions`. They exist for test structures and hand-made junction variants, and use the
legacy parameters and frame (centred on the exposure window; with ``negative`` the cell is the window minus the
finger and its lead, as in the legacy fab output):

* :class:`JJFingerStraight` (legacy "JJ_finger Top", layer 2/0 → KQC ``SIS_junction``): pad, finger and taper;
  ``invert`` flips the result vertically (legacy ``Trans(2, True)``).
* :class:`JJFingerBent` (legacy "JJ_finger Bottom", layer 4/0 → KQC ``SIS_junction_2``): the bent finger with its
  holder; ``invert`` mirrors it before it is moved to ``(x, y)``.

The legacy ``coerce_parameters_impl`` rules (:func:`~.legacy_junctions.coerce_straight` /
:func:`~.legacy_junctions.coerce_bent`) are applied, as KLayout does when the parameters are set.
"""

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.junctions.legacy_junctions import coerce_bent, coerce_straight
from quantcore_circuits.layouts.junctions.trilayer import bent_finger, straight_finger


class _Finger(Element):
    qcc_category = "shape"

    finger_width = Param(pdt.TypeDouble, "Finger width (legacy finger_width)", 0.2, unit="μm")
    negative = Param(pdt.TypeBoolean, "Negative: window minus finger (legacy negative / Fab)", True)
    invert = Param(pdt.TypeBoolean, "Flip (legacy invert)", False)
    x = Param(pdt.TypeDouble, "Finger offset in x (legacy x)", 0.0, unit="μm")

    def _emit(self, region: pya.Region, layer: str):
        self.cell.shapes(self.get_layer(layer)).insert(region)
        if not region.is_empty():
            self.add_protection(pya.Region(region.bbox()).sized(self.margin / self.layout.dbu))


class JJFingerStraight(_Finger):
    """Straight junction finger (legacy "JJ_finger Top"), on ``SIS_junction`` (2/0)."""

    pad_height = Param(pdt.TypeDouble, "Pad height (legacy pad_height)", 3.0, unit="μm")
    pad_width = Param(pdt.TypeDouble, "Pad width (legacy pad_width)", 0.5, unit="μm")
    finger_length = Param(pdt.TypeDouble, "Finger length (legacy finger_length)", 3.0, unit="μm")
    window_width = Param(pdt.TypeDouble, "Window width (legacy width)", 30.0, unit="μm")
    window_height = Param(pdt.TypeDouble, "Window height (legacy height)", 30.0, unit="μm")
    y = Param(pdt.TypeDouble, "Finger offset in y (legacy y)", -10.0, unit="μm")

    def build(self):
        pad_width, pad_height = coerce_straight(self.pad_width, self.pad_height, self.finger_width)
        region = straight_finger(
            self.layout.dbu,
            pad_width,
            pad_height,
            self.finger_width,
            self.finger_length,
            self.window_width,
            self.window_height,
            self.x,
            self.y,
            self.negative,
        )
        if self.invert:
            region.transform(pya.Trans(2, True))
        self._emit(region, "SIS_junction")


class JJFingerBent(_Finger):
    """Bent junction finger with its holder (legacy "JJ_finger Bottom"), on ``SIS_junction_2`` (4/0)."""

    pad_width = Param(pdt.TypeDouble, "Pad width (legacy pad_width)", 0.5, unit="μm")
    conn_height = Param(pdt.TypeDouble, "Connector height (legacy conn_height)", 0.5, unit="μm")
    finger_length = Param(pdt.TypeDouble, "Finger length (legacy finger_length)", 1.5, unit="μm")
    window_width = Param(pdt.TypeDouble, "Window width (legacy width)", 10.0, unit="μm")
    window_height = Param(pdt.TypeDouble, "Window height (legacy height)", 10.0, unit="μm")
    y = Param(pdt.TypeDouble, "Finger offset in y (legacy y)", 0.0, unit="μm")

    def build(self):
        w, h = self.window_width, self.window_height
        pad_width, conn_height, x = coerce_bent(
            self.pad_width, self.conn_height, self.finger_width, self.finger_length, self.x, self.y, w, h
        )
        region = bent_finger(
            self.layout.dbu,
            pad_width,
            2,  # legacy pad_height: read-only 2
            self.finger_width,
            self.finger_length,
            conn_height,
            w,
            h,
            x,
            self.y,
            self.invert,
            self.negative,
        )
        self._emit(region, "SIS_junction_2")
