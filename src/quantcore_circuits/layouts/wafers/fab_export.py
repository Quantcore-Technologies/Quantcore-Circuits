"""Fab export: KQC layers → Quantcore fab layers, with polarity, corner rounding and cheese.

M1 (1/0) is the KQC etch region ``base_metal_gap_wo_grid + ground_grid − base_metal_addition`` (what KQC merges into
``base_metal_gap``). Negative polarity (default, as in the legacy fab output) writes the etch; positive writes the
metal (chip box minus etch). With a ``box`` every layer is clipped to it. M3 (3/0) is the second-metal etch:
filled keep-outs per route and component (:func:`keepout_region`, :class:`~quantcore_circuits.pdk.KeepoutRule`) that
cover each 1/0 feature *and* what lies between its gaps, plus ground margin (route 10, component 24, other 9 µm; a
cell's own ``qcc_keepout`` shapes grow by ``own_grow`` = 4 µm). A KQC chip placed as one cell, or a cell over most of
the die, gets its etch grown by the "other" margin, not its bounding box.
JJ, spacer, frame, airbridge (300/301), TSV (700) and flip-chip face ``2b1`` (800–804) layers are
copied from their KQC / qcc source layers (a fab layer's ``faces`` say which KQC faces it reads).

The universal Quantcore (QCT) fab rules of the PDK are applied by :func:`export_fab` (``qcc mask``), never by the
simulation exports:

* **corner rounding** (:class:`~quantcore_circuits.pdk.CornerRounding`, :func:`round_corners`): every polygon of the
  rounded layers gets r = fraction × its shortest dimension (capped);
* **cheese** (:class:`~quantcore_circuits.pdk.CheeseRule`, :func:`cheese_holes`): a band of grid-aligned square
  holes around the components (3/0 grown by ``rows`` pitches, none within ``clearance`` = 4 µm of 3/0), inside the
  design area and clear of the frame's markers and device ID — not over the whole chip. TSVs, indium bumps, UBM and
  airbridges are not on 3/0 (they sit on the ground metal), but the cheese keeps the same distance from them grown by
  the "other" margin (:func:`cheese_avoid_region`).

The PDK band cheese is drawn by the chip build itself (into ``ground_grid``, see
:class:`~quantcore_circuits.pdk.CheeseRule`); a design with its own cheese (KQC's whole-area ``with_grid``, a static
cell's holes) keeps it — the original design wins. :func:`export_fab` adds the band only to a build that has no
cheese at all. The keep-outs of 3/0 are computed from the etch *without* the cheese (the clearance rule and the
band are measured to them), and then every cheese hole written on 1/0 is also written on 3/0 as the same square
(decision 2026-11-17), so 3/0 = keep-outs ∪ cheese holes. ``--no-cheese`` leaves both layers without holes.

Device layers with no PDK fab layer (``SIS_shadow``, EBL helper gaps, the unused qcc layers ``150/0``,
``1002/0``, ``1003/0``) are not written. :func:`dropped_layers` lists the non-empty ones; :func:`export_fab` warns
(:class:`FabLayersDropped`) and reports them, so nothing vanishes silently.

Wafer-level mask sets (many chips, markers, labels) are produced with KQC's ``MaskSet``/``mask_export`` on the
written chip files; that is the next step for ``wafers/``.
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path

from kqcircuits.defaults import default_faces
from kqcircuits.pya_resolver import pya

from quantcore_circuits.pdk import DEFAULT_PDK, QCC_LAYERS, get_pdk


def _region(cell: pya.Cell, info: pya.LayerInfo) -> pya.Region:
    layout = cell.layout()
    return pya.Region(cell.begin_shapes_rec(layout.layer(info)))


# KQC face layers that carry device geometry (the rest are helpers: ports, refpoints, avoidance, waveguide_path, ...)
DEVICE_LAYERS = (
    "base_metal_gap_wo_grid",
    "base_metal_gap",
    "base_metal_gap_for_EBL",
    "base_metal_addition",
    "ground_grid",
    "SIS_junction",
    "SIS_junction_2",
    "SIS_shadow",
    "airbridge_pads",
    "airbridge_flyover",
    "through_silicon_via",
    "indium_bump",
    "underbump_metallization",
)


class FabLayersDropped(UserWarning):
    """Device geometry on layers PDK v2 has no fab layer for was left out of the fab export."""


def _shape_count(cell: pya.Cell, info: pya.LayerInfo) -> int:
    layout = cell.layout()
    index = layout.find_layer(info)
    if index is None:
        return 0
    count = 0
    it = cell.begin_shapes_rec(index)
    while not it.at_end():
        count += 1
        it.next()
    return count


def dropped_layers(cell: pya.Cell, pdk_name: str = DEFAULT_PDK) -> dict[str, int]:
    """Non-empty device layers of a built cell that :func:`fab_regions` does not use: ``{"<face>_<name> (l/d)":
    shape count}``. M1 uses the PDK face's ``base_metal_gap_wo_grid``, ``ground_grid`` and ``base_metal_addition``;
    the other fab layers use their PDK source layer."""
    pdk = get_pdk(pdk_name)
    etch_parts = ("base_metal_gap_wo_grid", "ground_grid", "base_metal_addition")
    used = set()
    for fl in pdk.fab_layers.values():
        for f in fl.faces or (pdk.face,):
            if fl.source == "base_metal_gap":  # M1's symbolic source: built from the three etch layers
                used |= {(f, part) for part in etch_parts}
            elif fl.source in default_faces.get(f, {}):
                used.add((f, fl.source))
    used_qcc = {fl.source for fl in pdk.fab_layers.values() if fl.source in QCC_LAYERS}
    out = {}
    for face, layers in default_faces.items():
        for name in DEVICE_LAYERS:
            if name not in layers or (face, name) in used:
                continue
            n = _shape_count(cell, layers[name])
            if n:
                out[f"{face}_{name} ({layers[name].layer}/{layers[name].datatype})"] = n
    for name, info in QCC_LAYERS.items():
        if name not in used_qcc:
            n = _shape_count(cell, info)
            if n:
                out[f"qcc {name} ({info.layer}/{info.datatype})"] = n
    return out


def etch_region(cell: pya.Cell, face_name: str, grid: bool = True) -> pya.Region:
    """The 1/0 etch of ``face_name`` (dbu): ``base_metal_gap_wo_grid`` (+ the ``ground_grid`` cheese when ``grid``)
    − ``base_metal_addition``."""
    face = default_faces[face_name]
    etch = _region(cell, face["base_metal_gap_wo_grid"])
    if grid:
        etch += _region(cell, face["ground_grid"])
    return etch.merged() - _region(cell, face["base_metal_addition"])


def _etch(cell: pya.Cell, face_name: str) -> pya.Region:
    return etch_region(cell, face_name)


def build_cheese(cell: pya.Cell, pdk_name: str = DEFAULT_PDK) -> int:
    """Cheese holes the chip build already has (``ground_grid`` polygons of the PDK face: the PDK band or the
    original design's own grid)."""
    face = default_faces[get_pdk(pdk_name).face]
    return _region(cell, face["ground_grid"]).count()


def _is_route(child: pya.Cell, cls) -> bool:
    return (cls is not None and cls.__name__ == "WaveguideComposite") or child.name.startswith("Waveguide")


def _is_chip(cls) -> bool:
    """A KQC chip PCell (``kqcircuits.chips.chip.Chip`` or a subclass): a whole chip placed as one cell."""
    from kqcircuits.chips.chip import Chip  # pylint: disable=import-outside-toplevel

    return isinstance(cls, type) and issubclass(cls, Chip)


# KQC face layers the cheese keeps clear of besides 3/0: vias, bump stacks and airbridges sit on the ground metal, so
# they are not 1/0 features and not on 3/0, but no hole may lie under or next to them
CHEESE_CLEAR_LAYERS = (
    "through_silicon_via",
    "indium_bump",
    "underbump_metallization",
    "airbridge_pads",
    "airbridge_flyover",
)


def cheese_avoid_region(cell: pya.Cell, pdk) -> pya.Region:
    """What the cheese of the PDK face stays clear of besides 3/0 (dbu): that face's TSVs, indium bumps, under-bump
    metal, airbridge pads and flyovers (:data:`CHEESE_CLEAR_LAYERS`), filled and grown by ``keepout.other_margin``.
    :func:`cheese_holes` keeps its ``clearance`` from this region as from 3/0, but grows no band around it."""
    face = default_faces[pdk.face]
    out = pya.Region()
    for name in CHEESE_CLEAR_LAYERS:
        if name in face:
            out += _region(cell, face[name])
    if out.is_empty():
        return out
    return out.merged().hulls().sized(round(pdk.keepout.other_margin / cell.layout().dbu))


def ground_region(cell: pya.Cell, pdk, box, rule, etch: pya.Region | None = None) -> pya.Region:
    """The ground plane of the PDK face inside ``box`` (a ``DBox`` in µm; dbu region): the metal (``box`` minus the
    1/0 etch without the cheese, ``base_metal_addition`` counted as metal) split into connected pieces, keeping a
    piece that touches the edge of ``box`` (the die-edge ground) or is at least ``rule.ground_island_mm2`` large
    (ground enclosed by a bus ring or a feedline loop). Smaller isolated pieces (pads, qubit islands, the probe pads
    of a test chip without a ground plane) are left out, so :func:`cheese_holes` puts no hole in them."""
    dbu = cell.layout().dbu
    ibox = box.to_itype(dbu)
    etch = etch if etch is not None else etch_region(cell, pdk.face, grid=False)
    metal = (pya.Region(ibox) - etch).merged()
    edge = pya.Region(ibox) - pya.Region(ibox.enlarged(-1, -1))
    ground = metal.interacting(edge)
    island = float(getattr(rule, "ground_island_mm2", 0.0)) * 1e6 / dbu**2
    ground += metal.not_interacting(edge).with_area(round(island), None, False)
    return ground


def keepout_region(cell: pya.Cell, pdk, etch: pya.Region | None = None) -> pya.Region:
    """3/0 keep-outs of a built chip (dbu, filled; see :class:`~quantcore_circuits.pdk.KeepoutRule`)."""
    rule = pdk.keepout
    layout = cell.layout()
    dbu = layout.dbu
    face = default_faces[pdk.face]
    gap_layer = layout.layer(face["base_metal_gap_wo_grid"])
    path_layer = layout.layer(face["waveguide_path"])  # a route's centre conductor (KQC draws it at width a)
    die = cell.bbox()
    out = pya.Region()

    def visit(parent: pya.Cell, trans: pya.ICplxTrans, depth: int) -> None:
        for inst in parent.each_inst():
            child = layout.cell(inst.cell_index)
            t = trans * inst.cplx_trans
            own = pya.Region(child.begin_shapes_rec(gap_layer)).transformed(t)
            if own.is_empty():
                continue
            decl = child.pcell_declaration()
            cls = type(decl) if decl is not None and not type(decl).__name__.startswith("PCellDeclaration") else None
            hook = getattr(cls, "qcc_keepout", None) if cls is not None else None
            if _is_route(child, cls):
                body = (own + pya.Region(child.begin_shapes_rec(path_layer)).transformed(t)).merged()
                out.insert(body.sized(rule.route_margin / dbu).hulls())
            elif hook is not None:
                grow = round(rule.own_grow / dbu)
                for shape in hook(dict(child.pcell_parameters_by_name())):
                    poly = pya.DPolygon(shape) if isinstance(shape, pya.DBox) else shape
                    # a feature's own keep-out is filled (e.g. a bond pad's legacy ring covers its metal too) and
                    # grown by ``own_grow`` like every other keep-out
                    own_ko = pya.Region(poly.to_itype(dbu).transformed(t)).hulls()
                    out.insert(own_ko.sized(grow) if grow else own_ko)
            elif depth < 2 and (_is_chip(cls) or own.bbox().area() > 0.25 * die.area()) and child.child_cells():
                visit(child, t, depth + 1)  # a whole chip as a cell: its parts are treated like the design's own
            elif _is_chip(cls) or own.bbox().area() > 0.5 * die.area():
                # a whole chip drawn into one cell (a KQC test chip's stripes or squares) or a cell over most of the
                # die: its etch is covered by the etch rule below (other_margin), not by its bounding box
                pass
            else:
                m = round(rule.component_margin / dbu)
                out.insert(own.bbox().enlarged(m, m))

    visit(cell, pya.ICplxTrans(), 0)
    etch = etch if etch is not None else _etch(cell, pdk.face)
    # everything in 1/0 is covered (frame text, shapes in the top cell): grow the etch that is not already well
    # inside a keep-out (deeper than the margin), so a large cell under its own keep-out hook (a KI-TWPA serpentine,
    # 0.8 M vertices) is not sized as a whole; the result is the same
    margin = round(rule.other_margin / dbu)
    out = out.merged()
    rest = etch - out.sized(-margin) if not out.is_empty() else etch
    out += rest.sized(margin)
    return fill_small_holes(out.merged(), rule.fill_holes_um2 / dbu**2)


def fill_small_holes(region: pya.Region, max_area: float) -> pya.Region:
    """``region`` with every hole of area < ``max_area`` (dbu²) filled; larger holes are kept."""
    out = pya.Region()
    for poly in region.each():
        if poly.holes() == 0:
            out.insert(poly)
            continue
        kept = pya.Polygon(list(poly.each_point_hull()), True)
        for k in range(poly.holes()):
            hole = pya.Polygon(list(poly.each_point_hole(k)), True)
            if hole.area() >= max_area:
                kept.insert_hole(list(poly.each_point_hole(k)), True)
        out.insert(kept)
    return out


def shortest_dimension(poly: pya.Polygon, min_edge: float) -> float:
    """A polygon's shortest dimension (dbu): min(2·area/perimeter, its shortest edge ≥ ``min_edge``)."""
    d = 2 * poly.area() / max(poly.perimeter(), 1)
    edges = [e.length() for e in poly.each_edge() if e.length() >= min_edge]
    return min([d, *edges])


def round_corners(region: pya.Region, rule, dbu: float) -> pya.Region:
    """Round each polygon's corners with r = ``rule.fraction`` × its shortest dimension (≤ ``rule.max_radius``)."""
    out = pya.Region()
    for poly in region.merged().each():
        r = min(rule.fraction * shortest_dimension(poly, rule.min_edge / dbu), rule.max_radius / dbu)
        out.insert(poly.round_corners(r, r, rule.points) if r >= rule.min_radius / dbu else poly)
    return out.merged()


def _round_squares(region: pya.Region, rule, dbu: float) -> pya.Region:
    """:func:`round_corners` for a region of many equal boxes (a whole-area cheese grid: millions of squares): the
    boxes of one size are rounded together (same radius, native), size by size; whatever is left (other polygons,
    odd sizes) goes through :func:`round_corners`."""
    left, out = region.merged(), pya.Region()
    for _ in range(8):
        first = next(iter(left.each()), None)
        if first is None or not first.is_box():
            break
        b = first.bbox()
        same = left.with_bbox_width(b.width(), False).with_bbox_height(b.height(), False)
        same = same.with_area(b.width() * b.height(), False)  # equal area in an equal bbox: a box
        r = min(rule.fraction * shortest_dimension(first, rule.min_edge / dbu), rule.max_radius / dbu)
        out += same.rounded_corners(r, r, rule.points) if r >= rule.min_radius / dbu else same
        left -= same
    return (out + round_corners(left, rule, dbu)).merged() if not left.is_empty() else out.merged()


def cheese_holes(
    keepout: pya.Region,
    rule,
    dbu: float,
    allowed: pya.Region | None = None,
    exclude=None,
    avoid=None,
    ground: pya.Region | None = None,
) -> pya.Region:
    """Grid-aligned square holes in a band around ``keepout`` (3/0): squares of ``rule.size`` on a ``rule.pitch``
    grid lying entirely inside ``keepout`` grown by ``rule.rows`` pitches, ≥ ``rule.clearance`` from it (not even
    touching it), inside ``allowed`` (the design area) and clear of ``exclude`` (frame markers, device ID). dbu region.

    ``avoid`` (:func:`cheese_avoid_region`: TSVs, bumps, UBM and airbridges grown by the keep-out margin) is kept
    ``rule.clearance`` clear like ``keepout``, but the band is not grown around it. With ``ground``
    (:func:`ground_region`) the holes lie in the ground plane only, not in floating pads or islands.

    The band is measured like the grid, along x and y (a square Minkowski sum of 3/0). A square of half-width h
    fits where its centre lies in the band eroded by h, so the centres are found by region operations, then read off
    row by row on the grid (fast: no per-square region test).

    ``rule.fill == "chip"``: no band; the squares fill all of ``allowed`` (or the keep-outs' bounding box when
    ``allowed`` is None) at the same clearance from 3/0."""
    whole = getattr(rule, "fill", "band") == "chip"
    if keepout.is_empty() and not (whole and allowed is not None):
        return pya.Region()
    pitch, size = rule.pitch / dbu, rule.size / dbu
    h = size / 2

    def grown(d: float) -> pya.Region:  # 3/0 grown by d along x and y (exact for curved meanders too)
        d = round(d)
        return keepout.minkowski_sum(pya.Box(-d, -d, d, d)) if not keepout.is_empty() else pya.Region()

    if whole:
        area = allowed if allowed is not None else pya.Region(keepout.bbox())
        centres = area.sized(-round(h)) - grown(rule.clearance / dbu + h + 1)
    else:
        centres = grown(rule.rows * pitch - h) - grown(rule.clearance / dbu + h + 1)
    if allowed is not None and not whole:
        centres &= allowed.sized(-round(h))
    if exclude is not None and not exclude.is_empty():
        centres -= exclude.sized(round(h))
    if avoid is not None and not avoid.is_empty():
        d = round(rule.clearance / dbu + h + 1)
        centres -= avoid.minkowski_sum(pya.Box(-d, -d, d, d))
    if ground is not None:
        centres &= ground.sized(-round(h))  # the whole hole in ground metal
    if centres.is_empty():
        return pya.Region()
    bb = centres.bbox()
    half = pitch / 2  # holes centred on the grid (pitch/2 offset), so the grid is chip-aligned
    rows = pya.Region()
    for j in range(math.floor((bb.bottom - half) / pitch), math.ceil((bb.top - half) / pitch) + 1):
        y = round(j * pitch + half)
        rows.insert(pya.Box(bb.left - 1, y - 1, bb.right + 1, y + 1))
    squares = pya.Region()
    for seg in (centres & rows).each():
        b = seg.bbox()
        j = round((b.center().y - half) / pitch)
        y = round(j * pitch + half)
        for i in range(math.ceil((b.left - half) / pitch), math.floor((b.right - half) / pitch) + 1):
            x = round(i * pitch + half)
            squares.insert(pya.Box(round(x - h), round(y - h), round(x + h), round(y + h)))
    return squares.merged()


def fab_regions(
    cell: pya.Cell,
    pdk_name: str = DEFAULT_PDK,
    polarity: dict[str, str] | None = None,
    box: pya.DBox | None = None,
    rounding=None,
    cheese=None,
    cheese_allowed: pya.Region | None = None,
    cheese_exclude: pya.Region | None = None,
    grid: bool = True,
) -> dict[str, pya.Region]:
    """Fab-layer regions (dbu) of a built chip cell, keyed by PDK fab-layer name.

    ``rounding`` / ``cheese``: a :class:`~quantcore_circuits.pdk.CornerRounding` / :class:`~quantcore_circuits.pdk.
    CheeseRule`, ``True`` for the PDK's, or None (raw geometry, the default here; :func:`export_fab` applies them).
    ``grid=False`` leaves the build's own cheese (``ground_grid``) out of 1/0 *and* 3/0. With it, 3/0 also holds the
    cheese squares (the same squares as 1/0, not grown by the keep-out margin); the clearance rule is measured to the
    keep-outs alone (3/0 without the cheese).
    """
    pdk = get_pdk(pdk_name)
    face = default_faces[pdk.face]
    layout = cell.layout()
    dbu = layout.dbu
    rounding = pdk.rounding if rounding is True else rounding
    cheese = pdk.cheese if cheese is True else cheese
    etch = etch_region(cell, pdk.face, grid)
    raw = {}
    for name, fl in pdk.fab_layers.items():
        faces = fl.faces or (pdk.face,)
        if fl.source == "base_metal_gap":
            reg = pya.Region()
            for f in faces:
                reg += etch if f == pdk.face else etch_region(cell, f, grid)
        elif fl.source == "derived":
            reg = keepout_region(cell, pdk, etch_region(cell, pdk.face, grid=False))
        elif fl.source in QCC_LAYERS:
            reg = _region(cell, QCC_LAYERS[fl.source])
        else:
            reg = pya.Region()
            for f in faces:
                if fl.source in default_faces.get(f, {}):
                    reg += _region(cell, default_faces[f][fl.source])
        reg = reg.merged()
        if box is not None:
            reg &= pya.Region(box.to_itype(dbu))  # nothing outside the chip goes on the mask
        if rounding is not None and name in rounding.layers and not reg.is_empty():
            reg = round_corners(reg, rounding, dbu)
        raw[name] = reg
    holes = pya.Region()
    if cheese is not None and "M3" in raw and cheese.layer in raw:
        avoid = cheese_avoid_region(cell, pdk)  # vias, bumps, airbridges: clear of holes, not on 3/0
        ground = ground_region(cell, pdk, box or cell.dbbox(), cheese)  # no holes in floating pads or islands
        holes = cheese_holes(raw["M3"], cheese, dbu, cheese_allowed, cheese_exclude, avoid, ground)  # keep-outs alone
        raw[cheese.layer] = (raw[cheese.layer] + holes).merged()
    if grid and "M3" in raw:
        # the cheese is on 3/0 too, as the same squares as on 1/0 (not grown by the keep-out margin): the build's
        # ground_grid (PDK band or the original design's own grid), rounded as it is on 1/0, and the export band
        built = pya.Region()
        for f in pdk.fab_layers["M1"].faces or (pdk.face,):
            built += _region(cell, default_faces[f]["ground_grid"])
        built = built.merged()
        if box is not None:
            built &= pya.Region(box.to_itype(dbu))
        if rounding is not None and "M1" in rounding.layers and not built.is_empty():
            built = _round_squares(built, rounding, dbu)
        raw["M3"] = (raw["M3"] + built + holes).merged()
    out = {}
    for name, reg in raw.items():
        if (polarity or {}).get(name, "negative") == "positive":
            chip_box = box or cell.dbbox_per_layer(layout.layer(face["base_metal_gap_wo_grid"]))
            reg = pya.Region(chip_box.to_itype(dbu)) - reg
        out[name] = reg
    return out


def frame_cheese_limits(result) -> tuple[pya.Region | None, pya.Region | None]:
    """(allowed, exclude) dbu regions for the cheese of a built design: its design area, and the frame's marker
    areas, dicing corners and device ID (none when the chip has no PDK die frame)."""
    from quantcore_circuits.assembly.drc import device_id_block  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.plan import die_frame  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.chips.frame import design_area, keepouts  # pylint: disable=import-outside-toplevel

    frame = die_frame(result.design)
    if frame is None:
        return None, None
    dbu = result.layout.dbu
    chip = pya.DBox(*result.design.chip.box)
    allowed = pya.Region(design_area(chip, frame).to_itype(dbu))
    rule = result.design.chip.params.get("cheese")
    if isinstance(rule, dict) and rule.get("edge"):  # a design-chosen cheese rule's edge band
        allowed &= pya.Region(chip.enlarged(-float(rule["edge"]), -float(rule["edge"])).to_itype(dbu))
    exclude = pya.Region()
    for b in keepouts(chip, frame, device_id_block(result)).values():
        exclude.insert(b.to_itype(dbu))
    return allowed, exclude


def export_fab(
    result,
    path: str | Path,
    polarity: dict[str, str] | None = None,
    report: dict | None = None,
    cheese=True,
    rounding=True,
) -> Path:
    """Write a fab-ready OAS/GDS with only the PDK fab layers (flat, static).

    The PDK's fab rules apply by default: ``rounding`` (corner rounding) and ``cheese``. ``cheese=True`` keeps the
    cheese the build drew (the PDK band, or the original design's own) and adds the PDK band only when the build has
    none; ``False`` writes no cheese at all (the build's is left out too); a rule object adds that band. Non-empty
    device layers that have no PDK fab layer are left out with a :class:`FabLayersDropped` warning; pass a dict as
    ``report`` to get ``report["dropped"]`` (:func:`dropped_layers`), ``report["written"]`` (fab layer name →
    polygon count), ``report["cheese_holes"]`` (holes on the mask) and ``report["cheese_source"]`` ("build",
    "export" or "none")."""
    pdk = get_pdk(result.design.pdk)
    from quantcore_circuits.assembly.plan import pdk_cheese  # pylint: disable=import-outside-toplevel

    result.require_complete("fab export")  # a mask must never silently lack a route
    in_build = build_cheese(result.cell, result.design.pdk)
    grid = cheese is not False
    if cheese is True and (in_build or not pdk_cheese(result.design)):
        # the build's cheese stands (PDK band or the original design's own, e.g. flux holes drawn on the etch layer:
        # a design marked cheese "original" never gets the band at export either)
        cheese = None
    dropped = dropped_layers(result.cell, result.design.pdk)
    if dropped:
        listed = ", ".join(f"{k}: {n} shape(s)" for k, n in dropped.items())
        warnings.warn(
            f"export_fab({result.design.name}): PDK {pdk.name} has no fab layer for {listed}; not written",
            FabLayersDropped,
            stacklevel=2,
        )
    x0, y0, x1, y1 = result.design.chip.box
    allowed, exclude = frame_cheese_limits(result)
    regions = fab_regions(
        result.cell,
        result.design.pdk,
        polarity,
        pya.DBox(x0, y0, x1, y1),
        rounding=rounding or None,
        cheese=cheese or None,
        cheese_allowed=allowed,
        cheese_exclude=exclude,
        grid=grid,
    )
    out = pya.Layout()
    out.dbu = result.layout.dbu
    top = out.create_cell(result.design.name)
    for name, reg in regions.items():
        fl = pdk.fab_layers[name]
        top.shapes(out.layer(pya.LayerInfo(fl.layer, fl.datatype, name))).insert(reg)
    if report is not None:
        report["dropped"] = dropped
        report["written"] = {name: reg.count() for name, reg in regions.items() if not reg.is_empty()}
        rule = pdk.cheese if cheese is True else (cheese or None)
        added = (
            cheese_holes(
                fab_regions(result.cell, result.design.pdk, None, pya.DBox(x0, y0, x1, y1), grid=False)["M3"],
                rule,
                result.layout.dbu,
                allowed,
                exclude,
                cheese_avoid_region(result.cell, pdk),
                ground_region(result.cell, pdk, pya.DBox(x0, y0, x1, y1), rule),
            ).count()
            if rule is not None
            else 0
        )
        report["cheese_holes"] = added + (in_build if grid else 0)
        own = "original" if grid and not pdk_cheese(result.design) else "none"
        report["cheese_source"] = "export" if added else ("build" if in_build and grid else own)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.write(str(path))
    return path
