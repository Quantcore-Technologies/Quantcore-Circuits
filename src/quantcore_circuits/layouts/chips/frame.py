"""Quantcore die frame (``components/pdk_geometry_summary.md``): dicing markers, alignment grids, device ID.

The frame lives inside the chip box. Its zero point is the die corner (the centre of the cross that the dicing
markers of neighbouring dies form), so every position below is measured from the nearest die corner and mirrored
for the other three corners.

* **Dicing markers** — an L in each corner, legs ``dicing_leg`` long and ``dicing_width`` wide along the die edges.
* **Design area** — the box inset by ``margin``; components belong inside it.
* **Marker areas** — ``marker_area`` squares in the four corners of the design area, each holding a 3×3 grid of
  alignment squares (``grid_small`` at the corners and centre, ``grid_large`` at the edge midpoints).
* **Device ID** — a ``device_id`` block holding the chip name, centred on one side of the design area: the bottom by
  default; when the chip's own geometry already occupies that spot, the first free centre of top, left, right, else
  the nearest free spot slid along a side (:func:`choose_device_id`; on the left and right the block and its text are
  turned 90°). The chip parameter
  ``device_id_side`` (``"auto"`` default, or a fixed side) overrides the choice.

Marker areas and the device ID are keep-outs for the layout DRC (:func:`keepouts`).
"""

from __future__ import annotations

from kqcircuits.pya_resolver import pya

from quantcore_circuits.pdk import QCC_LAYERS, DieFrame


def design_area(box: pya.DBox, frame: DieFrame) -> pya.DBox:
    m = frame.margin
    return pya.DBox(box.left + m, box.bottom + m, box.right - m, box.top - m)


def _corners(box: pya.DBox):
    """(corner point, x sign, y sign) for the four die corners."""
    return [
        (pya.DPoint(box.left, box.bottom), 1, 1),
        (pya.DPoint(box.right, box.bottom), -1, 1),
        (pya.DPoint(box.left, box.top), 1, -1),
        (pya.DPoint(box.right, box.top), -1, -1),
    ]


def _square(cx: float, cy: float, size: float) -> pya.DBox:
    return pya.DBox(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)


DEVICE_ID_SIDES = ("bottom", "top", "left", "right")  # preference order for device_id_side="auto"


def device_id_box(box: pya.DBox, frame: DieFrame, side: str = "bottom", offset: float = 0.0) -> pya.DBox:
    """The device-ID block on ``side`` of the design area, ``offset`` µm from the side's centre along it (turned 90°
    on the left and right)."""
    area = design_area(box, frame)
    w, h = frame.device_id
    c = area.center()
    if side == "bottom":
        return pya.DBox(c.x + offset - w / 2, area.bottom, c.x + offset + w / 2, area.bottom + h)
    if side == "top":
        return pya.DBox(c.x + offset - w / 2, area.top - h, c.x + offset + w / 2, area.top)
    if side == "left":
        return pya.DBox(area.left, c.y + offset - w / 2, area.left + h, c.y + offset + w / 2)
    if side == "right":
        return pya.DBox(area.right - h, c.y + offset - w / 2, area.right, c.y + offset + w / 2)
    raise ValueError(f"device_id_side must be 'auto' or one of {DEVICE_ID_SIDES}, not {side!r}")


def _slide_offsets(box: pya.DBox, frame: DieFrame, side: str, step: float) -> list[float]:
    """Offsets from the side's centre (0, +step, −step, +2 step, …) that keep the block between the marker areas."""
    area = design_area(box, frame)
    length = area.width() if side in ("bottom", "top") else area.height()
    limit = length / 2 - frame.marker_area - frame.device_id[0] / 2
    out, k = [], 1
    while k * step <= limit + 1e-9:
        out += [k * step, -k * step]
        k += 1
    return out


def _nearest_side(box: pya.DBox, b: pya.DBox) -> str:
    gaps = {
        "bottom": b.bottom - box.bottom,
        "top": box.top - b.top,
        "left": b.left - box.left,
        "right": box.right - b.right,
    }
    return min(gaps, key=gaps.get)


def _beside_pads(box: pya.DBox, frame: DieFrame, anchors: list[pya.DBox], gap: float) -> list[tuple[str, float]]:
    """(side, offset) of blocks ``gap`` µm beside each pad, on the die side the pad sits at (design rule: when no edge
    centre is free, the ID goes left/right of the feedline pads with a 50 µm gap)."""
    area = design_area(box, frame)
    c, w = area.center(), frame.device_id[0]
    out = []
    for pad in anchors:
        side = _nearest_side(box, pad)
        if side in ("bottom", "top"):
            out += [(side, pad.left - gap - w / 2 - c.x), (side, pad.right + gap + w / 2 - c.x)]
        else:
            out += [(side, pad.bottom - gap - w / 2 - c.y), (side, pad.top + gap + w / 2 - c.y)]
    return out


def _within_side(box: pya.DBox, frame: DieFrame, side: str, offset: float) -> bool:
    area = design_area(box, frame)
    length = area.width() if side in ("bottom", "top") else area.height()
    return abs(offset) <= length / 2 - frame.marker_area - frame.device_id[0] / 2 + 1e-9


def choose_device_id(
    box: pya.DBox,
    frame: DieFrame,
    occupied: pya.Region | None,
    dbu: float,
    side: str = "auto",
    clearance: float = 25.0,
    step: float = 50.0,
    anchors: list[pya.DBox] | None = None,
    pad_gap: float = 50.0,
):
    """``(side, block)`` for the device ID, or ``(None, None)`` when there is no room (the ID is optional).

    ``side`` fixed: centred on that side. ``"auto"`` (the user's rule): the first block that keeps ``clearance`` µm
    from ``occupied`` (the chip's geometry, dbu region), trying

    1. the centre of the bottom, top, left and right side;
    2. beside the pads (``anchors``: feedline pads / launchers), ``pad_gap`` µm left or right of each;
    3. slid along the left and right edges, then the bottom and top, in ``step`` µm increments (between the corner
       marker areas).

    If nothing is free the chip gets no device ID (no DRC warning).
    """
    if side != "auto":
        return side, device_id_box(box, frame, side)

    def free(block: pya.DBox) -> bool:
        probe = pya.Region(block.enlarged(clearance, clearance).to_itype(dbu))
        return occupied.interacting(probe).is_empty()

    if occupied is None:
        return "bottom", device_id_box(box, frame, "bottom")
    candidates = [(s, 0.0) for s in DEVICE_ID_SIDES]
    candidates += [
        (s, o) for s, o in _beside_pads(box, frame, anchors or [], pad_gap) if _within_side(box, frame, s, o)
    ]
    candidates += [(s, o) for s in ("left", "right", "bottom", "top") for o in _slide_offsets(box, frame, s, step)]
    for s, o in candidates:
        block = device_id_box(box, frame, s, o)
        if free(block):
            return s, block
    return None, None


def keepouts(box: pya.DBox, frame: DieFrame, device_id: pya.DBox | None = None) -> dict[str, pya.DBox]:
    """Reserved areas: the four marker areas and the device-ID block (inside the design area), and the dicing-marker
    corners (in the margin). ``device_id`` is the block where the chip put it (default: the bottom position;
    ``False``: the chip has no device ID)."""
    area = design_area(box, frame)
    a = frame.marker_area
    out = {
        "marker_area_sw": pya.DBox(area.left, area.bottom, area.left + a, area.bottom + a),
        "marker_area_se": pya.DBox(area.right - a, area.bottom, area.right, area.bottom + a),
        "marker_area_nw": pya.DBox(area.left, area.top - a, area.left + a, area.top),
        "marker_area_ne": pya.DBox(area.right - a, area.top - a, area.right, area.top),
    }
    if device_id is not False:
        out["device_id"] = device_id if device_id is not None else device_id_box(box, frame, "bottom")
    leg = frame.dicing_leg
    for (c, sx, sy), tag in zip(_corners(box), ("sw", "se", "nw", "ne")):
        out[f"dicing_markers_{tag}"] = pya.DBox(c.x, c.y, c.x + sx * leg, c.y + sy * leg)
    return out


def frame_shapes(box: pya.DBox, frame: DieFrame) -> dict[str, list[pya.DBox]]:
    """Frame geometry (µm boxes) keyed by :data:`~quantcore_circuits.pdk.QCC_LAYERS` name."""
    leg, w = frame.dicing_leg, frame.dicing_width
    dicing, align = [], []
    for c, sx, sy in _corners(box):
        dicing.append(pya.DBox(c.x, c.y, c.x + sx * leg, c.y + sy * w))  # leg along the horizontal edge
        dicing.append(pya.DBox(c.x, c.y, c.x + sx * w, c.y + sy * leg))  # leg along the vertical edge
        for i, gx in enumerate(frame.grid_x):
            for j, gy in enumerate(frame.grid_y):
                size = frame.grid_large if (i == 1) != (j == 1) else frame.grid_small
                align.append(_square(c.x + sx * gx, c.y + sy * gy, size))
    return {frame.dicing_layer: dicing, frame.alignment_layer: align, frame.boundary_layer: [box]}


def device_id_text(slot: pya.DBox, text: str, dbu: float) -> pya.Region:
    """``text`` in KLayout's default font, scaled to fit the device-ID block ``slot`` with a 10 % margin (dbu region).

    A block taller than wide (left/right side) gets the text turned 90° (reading bottom to top)."""
    if not text:
        return pya.Region()
    gen = pya.TextGenerator.default_generator()
    raw = gen.text(text, dbu, 1.0)
    bb = raw.bbox()
    if bb.empty() or bb.width() == 0:
        return pya.Region()
    vertical = slot.height() > slot.width()
    long_side, short_side = (slot.height(), slot.width()) if vertical else (slot.width(), slot.height())
    scale = min(0.9 * long_side / (bb.width() * dbu), 0.9 * short_side / (bb.height() * dbu))
    region = gen.text(text, dbu, scale)
    if vertical:
        region = region.transformed(pya.Trans(pya.Trans.R90))
    bb = region.bbox()
    target = slot.center()
    shift = pya.Vector(round(target.x / dbu) - bb.center().x, round(target.y / dbu) - bb.center().y)
    return region.moved(shift)


def draw_frame(
    cell: pya.Cell,
    box: pya.DBox,
    frame: DieFrame,
    text: str = "",
    text_layer=None,
    device_id_side: str = "auto",
    occupied: pya.Region | None = None,
    anchors: list[pya.DBox] | None = None,
) -> pya.DBox | None:
    """Insert the frame into ``cell``; the device-ID ``text`` goes on ``text_layer`` (a layer index).

    ``occupied`` is the chip geometry already drawn and ``anchors`` the pads (for ``device_id_side="auto"``). Returns
    the device-ID block used, or None: no text, or no free place (the ID is optional).
    """
    layout = cell.layout()
    for key, boxes in frame_shapes(box, frame).items():
        shapes = cell.shapes(layout.layer(QCC_LAYERS[key]))
        for b in boxes:
            shapes.insert(b)
    if not text:
        return None
    _, slot = choose_device_id(box, frame, occupied, layout.dbu, device_id_side, anchors=anchors)
    if slot is not None and text_layer is not None:
        cell.shapes(text_layer).insert(device_id_text(slot, text, layout.dbu))
    return slot
