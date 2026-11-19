"""Legacy wafer / die layouts (ported from ``pymacros/Cong/75x75_diewafer.lym``, ``components/python/die_creator.py``
and ``wafer_creator.py``). Optional: the Quantcore flow places dies with the PDK die frame
(:mod:`quantcore_circuits.layouts.chips.frame`) and exports masks with :mod:`.fab_export`.

* :class:`WaferMap75`: the 4-inch wafer map of 7.5 mm dies (Cong): die borders (PDK ``chip_boundary``, 100/0), the
  100 mm wafer circle (``wafer_boundary``, 500/0) and the row/column/die labels (``wafer_markers``, 501/0). Legacy
  draws borders and labels on 1/0 and the circle on 2/0; the geometry is the same (Basic ``TEXT``/``CIRCLE`` cells,
  same positions).
* :func:`die_chip_offsets` / :func:`wafer_01_die_positions`: the placement grids of ``die_creator.create_die`` (2×2
  chips per 15 mm die) and ``wafer_creator.py`` (16 dies + resonator chips), in µm.
"""

from __future__ import annotations

import numpy as np
from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.pdk import QCC_LAYERS

ROW_DIES = [4, 6, 8, 10, 10, 10, 10, 10, 8, 6, 4]
COLUMN_DIES = [5, 7, 9, 11, 11, 11, 11, 9, 7, 5]
ROW_LABELS = list("ABCDEFGHIJK")


def wafer_map_75(die=7500.0, border=50.0, rows=None, columns=None):
    """Legacy ``75x75_diewafer`` in µm: (die borders as boxes, labels as (x, y, text, mag)), die lower-left corners
    and their labels."""
    rows = rows or ROW_DIES
    columns = columns or COLUMN_DIES
    d = die * 1000.0  # legacy works in nm
    x0, y0 = -d * 5, -d * 5.5
    wafer_x, wafer_y = np.max(rows), np.max(columns)
    texts, corners = [], []
    for k, n in enumerate(rows):
        dx = -0.5 if 2 < k < 8 else -0.9
        texts.append((x0 + ((wafer_x - n) / 2 + dx) * d, y0 + k * d + 0.3 * d, ROW_LABELS[k], 4000))
        for p in range(int(n)):
            if k == 4:
                texts.append(
                    (x0 + ((wafer_x - n) / 2 + p + 0.5) * d, y0 + ((wafer_y - columns[p]) / 2 - 0.7) * d, p, 4000)
                )
            wx, wy = x0 + (wafer_x - n) * 0.5 * d + p * d, y0 + k * d
            label = ROW_LABELS[k] + str(int(p + (wafer_x - n) / 2))
            texts.append((wx + d - 800e3, wy + d - 500e3, label, 200))
            corners.append((wx, wy, label))
    return corners, texts


def _border_boxes(x, y, w, h, t):
    """Legacy ``draw.boarder`` (its ``x + h`` for the right edge kept: dies are square)."""
    return [pya.Box(x, y, x + t, y + h), pya.Box(x + t, y, x + w - t, y + t), pya.Box(x + h - t, y, x + h, y + h)] + [
        pya.Box(x + h, y + h, x, y + h - t)
    ]


class WaferMap75(Element):
    """4-inch wafer map of 7.5 mm dies with die borders, labels and the wafer circle (legacy Cong 75x75 die wafer)."""

    die_size = Param(pdt.TypeDouble, "Die pitch / size", 7500, unit="μm")
    border = Param(pdt.TypeDouble, "Die border width", 50, unit="μm")
    wafer_radius = Param(pdt.TypeDouble, "Wafer radius", 50000, unit="μm")
    circle_points = Param(pdt.TypeInt, "Points on the wafer circle", 200)
    labels = Param(pdt.TypeBoolean, "Row, column and die labels", True)

    qcc_category = "marker"

    def build(self):
        dbu = self.layout.dbu
        scale = 0.001 / dbu  # legacy coordinates are nm at dbu 0.001
        d, t = self.die_size * 1000.0, self.border * 1000.0
        corners, texts = wafer_map_75(self.die_size, self.border)
        borders = self.cell.shapes(self.layout.layer(QCC_LAYERS["chip_boundary"]))
        for wx, wy, _ in corners:
            for box in _border_boxes(wx, wy, d, d, t):
                borders.insert(box.transformed(pya.ICplxTrans(scale)) if scale != 1 else box)
        if self.labels:
            layer = QCC_LAYERS["wafer_markers"]
            for x, y, text, mag in texts:
                cell = self.layout.create_cell("TEXT", "Basic", {"layer": layer, "text": str(text), "mag": mag})
                self.cell.insert(pya.DCellInstArray(cell.cell_index(), pya.DTrans(pya.DVector(x / 1000, y / 1000))))
        circle = self.layout.create_cell(
            "CIRCLE",
            "Basic",
            {"layer": QCC_LAYERS["wafer_boundary"], "actual_radius": self.wafer_radius, "npoints": self.circle_points},
        )
        self.cell.insert(pya.DCellInstArray(circle.cell_index(), pya.DTrans()))
        for wx, wy, label in corners:
            self.refpoints[f"die_{label}"] = pya.DPoint(wx / 1000 + self.die_size / 2, wy / 1000 + self.die_size / 2)


def die_chip_offsets(chip=7500.0):
    """``die_creator.create_die``: four copies of a chip centred at (±chip/2, ±chip/2) in a 2×chip die (µm)."""
    h = chip / 2
    return [(h, h), (-h, h), (-h, -h), (h, -h)]


def wafer_01_die_positions():
    """``wafer_creator.py``: the 16 die centres (row-major, 15 mm pitch) and the resonator-chip positions (µm)."""
    xs = list(np.arange(-7500 - 15000, 30000, 15000))
    ys = list(np.arange(7500 + 15000, -30000, -15000))
    dies = [(float(x), float(y)) for y in ys for x in xs]
    res = []
    res += [(-30000 - 3750, float(y)) for y in np.arange(30000 - 3750, -34000, -7500)]
    res += [(float(x), -33750) for x in np.arange(-30000 - 3750, 30000, 7500)]
    res += [(float(x), -33750 - 7500) for x in np.arange(-18750, 15000, 7500)]
    res += [(-33750 - 7500, float(y)) for y in np.arange(11250, -24000, -7500)]
    res += [(33750, float(y)) for y in np.arange(11250, -24000, -7500)]
    res += [(float(x), 33750) for x in np.arange(-18750, 15000, 7500)]
    return dies, res
