"""Wafer assembly: pack square dies on a round wafer, name them, and place real chip layouts on them.

Wafer level layers (PDK): the wafer outline is on **500/0** (``wafer_boundary``) and everything else drawn at wafer
level (die labels, die outlines, alignment / orientation marks) is on **501/0** (``wafer_markers``). Chips keep their
own layers; each is a sub-cell of the wafer cell.

Units: the user-facing parameters and tables are in **mm** (a wafer is "100 mm", a die "7.5 mm"); the layout is
written in µm like every other Quantcore layout. The wafer centre is the origin, x to the right, y up.

>>> w = Wafer(diameter_mm=100, die_mm=7.5)             # dense packing, notch on the bottom edge
>>> w.die_count, w.dies[0].name                        # doctest: +SKIP
>>> w.write("build/wafer/wafer_100.oas", chips="examples/designs/legacy/chip_06_test_cyro_tlq.json")  # doctest: +SKIP

Naming: rows are letters from the top (``A``, ``B`` ... ``Z``, ``AA`` ...), columns are numbers from the left
(``1``, ``2`` ...), a die is ``<row><column>`` (``C4``). On a uniform wafer columns are counted from the leftmost
occupied column of the whole wafer, so a short top row starts at a higher number, as on a wafer map; on a mixed wafer
(``bands``) the rows do not share a grid and each row is counted from its leftmost die.

Packing:

* ``packing="dense"``: every die that fits completely inside the usable disc (wafer radius minus the edge exclusion,
  and clear of the notch / flat).
* ``packing="centred"``: only dies completely inside a circle of ``radius_mm`` around the packing centre
  (``offset_mm`` away from the wafer centre), and still inside the usable disc. The grid is laid out around that centre.
* ``bands=[(die_mm, n_rows), ...]`` (mixed die sizes): rows of one size stacked top to bottom, the stack centred on the
  packing centre; each row is filled with as many dies as fit.
"""

from __future__ import annotations

import csv
import math
import string
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from kqcircuits.pya_resolver import pya

from quantcore_circuits.pdk import QCC_LAYERS

DBU = 0.001  # µm per database unit, same as every other Quantcore layout
WAFER_LAYER = (500, 0)  # PDK ``wafer_boundary``
MARKER_LAYER = (501, 0)  # PDK ``wafer_markers``

#: wafer presets: diameter (mm) → (flat length mm for the "flat" orientation, name). Notch: SEMI-style V, 1 mm deep.
PRESETS = {100.0: (32.5, "4 in"), 150.0: (57.5, "6 in")}
NOTCH_DEPTH_MM = 1.0
_SIDES = {"bottom": 0.0, "right": 90.0, "top": 180.0, "left": 270.0}


def row_letters(index: int) -> str:
    """0 → ``A``, 25 → ``Z``, 26 → ``AA`` (spreadsheet style)."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = string.ascii_uppercase[rem] + out
    return out


@dataclass
class Die:
    """One die position: ``name`` = row letter + column number, centre (x, y) in mm, side ``size_mm``."""

    name: str
    row: str
    col: int
    size_mm: float
    x_mm: float
    y_mm: float
    band: int = 0
    chip: str | None = None  # chip id (name of the placed layout) or None for an empty die

    @property
    def box_um(self) -> tuple[float, float, float, float]:
        h = self.size_mm * 500.0
        return (self.x_mm * 1000 - h, self.y_mm * 1000 - h, self.x_mm * 1000 + h, self.y_mm * 1000 + h)


@dataclass
class Wafer:
    """A wafer layout plan: the die positions and names, and :meth:`write` / :meth:`build` to draw it.

    ``diameter_mm`` 100 (4 in) or 150 (6 in) are the presets; any diameter works. ``orientation`` is ``"notch"``
    (default), ``"flat"`` or ``"none"`` at ``orientation_side`` (``bottom`` default). ``edge_mm`` is the edge exclusion
    (no die closer than this to the rim, the notch or the flat); ``street_mm`` the dicing street between dies.
    ``align``: where the die grid sits relative to the packing centre: ``"centre"`` (a die centred there), ``"corner"``
    (a street crossing there), ``"row"`` / ``"column"`` (one of each) or ``"auto"`` (the one that fits most dies).
    """

    diameter_mm: float = 100.0
    die_mm: float = 7.5
    packing: str = "dense"
    radius_mm: float | None = None
    offset_mm: tuple[float, float] = (0.0, 0.0)
    street_mm: float = 0.1
    edge_mm: float = 3.0
    orientation: str = "notch"
    orientation_side: str = "bottom"
    align: str = "auto"
    bands: list[tuple[float, int]] | None = None
    die_outline: bool = True
    labels: bool = True
    label_mm: float | None = None  # label character height, default die / 12.5
    name: str = ""
    dies: list[Die] = field(init=False, default_factory=list)

    def __post_init__(self):
        if self.packing not in ("dense", "centred"):
            raise ValueError(f"packing must be 'dense' or 'centred', not {self.packing!r}")
        if self.packing == "centred" and not self.radius_mm:
            raise ValueError("packing='centred' needs radius_mm")
        if self.orientation not in ("notch", "flat", "none"):
            raise ValueError("orientation must be 'notch', 'flat' or 'none'")
        if self.orientation_side not in _SIDES:
            raise ValueError(f"orientation_side must be one of {sorted(_SIDES)}")
        if self.align not in ("auto", "centre", "corner", "row", "column"):
            raise ValueError("align must be auto, centre, corner, row or column")
        self.offset_mm = (float(self.offset_mm[0]), float(self.offset_mm[1]))
        self.name = self.name or PRESETS.get(float(self.diameter_mm), (0, f"{self.diameter_mm:g} mm"))[1]
        self._usable = self._usable_region()
        self.dies = self._pack()

    # ---- geometry ------------------------------------------------------------------------------------------------
    @property
    def radius_wafer_mm(self) -> float:
        return self.diameter_mm / 2

    def outline_polygon_um(self, points: int = 2000) -> pya.DPolygon:
        """The wafer outline (a circle with the notch or flat cut in), in µm."""
        r = self.diameter_mm * 500.0
        pts: list[tuple[float, float]] = []
        if self.orientation == "notch":
            d = NOTCH_DEPTH_MM * 1000.0
            rim = math.sqrt(r * r - d * d)
            # arc from the right rim round the top to the left rim (counter-clockwise)
            a_start = math.atan2(-rim, d)
            a_end = math.atan2(-rim, -d) + 2 * math.pi
            n = max(8, int(points * (a_end - a_start) / (2 * math.pi)))
            pts = [
                (r * math.cos(a_start + (a_end - a_start) * i / n), r * math.sin(a_start + (a_end - a_start) * i / n))
                for i in range(n + 1)
            ]
            pts += [(0.0, -r + d)]
        elif self.orientation == "flat":
            flat = PRESETS.get(float(self.diameter_mm), (self.diameter_mm * 0.325, ""))[0] * 1000.0
            half = flat / 2
            y = math.sqrt(r * r - half * half)
            a_start = math.atan2(-y, half)
            a_end = math.atan2(-y, -half) + 2 * math.pi
            n = max(8, int(points * (a_end - a_start) / (2 * math.pi)))
            pts = [
                (r * math.cos(a_start + (a_end - a_start) * i / n), r * math.sin(a_start + (a_end - a_start) * i / n))
                for i in range(n + 1)
            ]
        else:
            pts = [
                (r * math.cos(2 * math.pi * i / points), r * math.sin(2 * math.pi * i / points)) for i in range(points)
            ]
        rot = math.radians(_SIDES[self.orientation_side]) if self.orientation != "none" else 0.0
        c, s = math.cos(rot), math.sin(rot)
        return pya.DPolygon([pya.DPoint(x * c - y * s, x * s + y * c) for x, y in pts])

    def _usable_region(self) -> pya.Region:
        poly = self.outline_polygon_um().to_itype(DBU)
        return pya.Region(poly).sized(-int(round(self.edge_mm * 1000 / DBU)), 2)

    def _fits(self, x_mm: float, y_mm: float, size_mm: float) -> bool:
        h = size_mm * 500.0
        box = pya.DBox(x_mm * 1000 - h, y_mm * 1000 - h, x_mm * 1000 + h, y_mm * 1000 + h)
        if self.packing == "centred":  # the die must lie completely inside the packing circle
            ox, oy = self.offset_mm
            reach = max(
                math.hypot(cx / 1000 - ox, cy / 1000 - oy)
                for cx in (box.left, box.right)
                for cy in (box.bottom, box.top)
            )
            if reach > self.radius_mm + 1e-9:
                return False
        far = max(math.hypot(cx, cy) for cx in (box.left, box.right) for cy in (box.bottom, box.top))
        if far > self.radius_wafer_mm * 1000 - self.edge_mm * 1000 + 1e-6:  # outside the usable disc: quick reject
            return False
        return (pya.Region(box.to_itype(DBU)) - self._usable).is_empty()

    # ---- packing -------------------------------------------------------------------------------------------------
    def _centre(self) -> tuple[float, float]:
        return self.offset_mm

    def _aligns(self) -> list[str]:
        return ["centre", "corner", "row", "column"] if self.align == "auto" else [self.align]

    def _grid(self, align: str) -> list[tuple[int, int, float, float]]:
        p = self.die_mm + self.street_mm
        cx, cy = self._centre()
        sx = 0.5 if align in ("corner", "column") else 0.0  # half-pitch shifts (see ``align``)
        sy = 0.5 if align in ("corner", "row") else 0.0
        reach = (self.radius_mm if self.packing == "centred" else self.radius_wafer_mm) + max(abs(cx), abs(cy))
        n = int(reach / p) + 2
        out = []
        for j in range(-n, n + 1):
            for i in range(-n, n + 1):
                x, y = cx + (i + sx) * p, cy + (j + sy) * p
                if self._fits(x, y, self.die_mm):
                    out.append((i, j, x, y))
        return out

    def _pack(self) -> list[Die]:
        if self.bands:
            return self._pack_bands()
        best = max((self._grid(a) for a in self._aligns()), key=len)  # first (centre) wins ties
        return self._named([(0, self.die_mm, x, y) for _, _, x, y in best])

    def _pack_bands(self) -> list[Die]:
        cx, cy = self._centre()
        total = sum(n * (s + self.street_mm) for s, n in self.bands) - self.street_mm
        y_top = cy + total / 2
        found: list[tuple[int, float, float, float]] = []
        for b, (size, nrows) in enumerate(self.bands):
            for _ in range(int(nrows)):
                yc = y_top - size / 2
                y_top -= size + self.street_mm
                p = size + self.street_mm
                best: list[float] = []
                for shift in (0.0, 0.5):
                    n = int(self.radius_wafer_mm / p) + 2
                    xs = [cx + (i + shift) * p for i in range(-n, n + 1)]
                    xs = [x for x in xs if self._fits(x, yc, size)]
                    if len(xs) > len(best):
                        best = xs
                found += [(b, size, x, yc) for x in best]
        return self._named(found)

    def _named(self, found: list[tuple[int, float, float, float]]) -> list[Die]:
        """Name the dies: rows A… from the top over the occupied rows, columns 1… from the left per band."""
        if not found:
            return []
        rows = sorted({round(y, 6) for _, _, _, y in found}, reverse=True)
        letter = {y: row_letters(k) for k, y in enumerate(rows)}
        first_x: dict[int, float] = {}
        for b, _, x, _ in found:
            first_x[b] = min(first_x.get(b, x), x)
        out = []
        per_row: dict[float, int] = {}
        for b, size, x, y in sorted(found, key=lambda t: (-round(t[3], 6), t[2])):
            p = size + self.street_mm
            if self.bands:  # rows of a mixed wafer do not share a grid: count from the left of each row
                col = per_row[round(y, 6)] = per_row.get(round(y, 6), 0) + 1
            else:
                col = int(round((x - first_x[b]) / p)) + 1
            row = letter[round(y, 6)]
            out.append(Die(f"{row}{col}", row, col, size, round(x, 6), round(y, 6), b))
        return out

    # ---- results -------------------------------------------------------------------------------------------------
    @property
    def die_count(self) -> int:
        return len(self.dies)

    def counts_by_size(self) -> dict[float, int]:
        out: dict[float, int] = {}
        for d in self.dies:
            out[d.size_mm] = out.get(d.size_mm, 0) + 1
        return out

    def die(self, name: str) -> Die:
        for d in self.dies:
            if d.name == name:
                return d
        raise KeyError(name)

    def table(self) -> list[dict]:
        """One row per die: name, row, column, size, centre (mm) and the chip placed on it."""
        return [
            {
                "die": d.name,
                "row": d.row,
                "col": d.col,
                "size_mm": d.size_mm,
                "x_mm": d.x_mm,
                "y_mm": d.y_mm,
                "chip": d.chip or "",
            }
            for d in self.dies
        ]

    def table_markdown(self, limit: int | None = None) -> str:
        rows = self.table()[:limit]
        out = ["| die | size mm | x mm | y mm | chip |", "|---|---|---|---|---|"]
        out += [f"| {r['die']} | {r['size_mm']:g} | {r['x_mm']:.3f} | {r['y_mm']:.3f} | {r['chip']} |" for r in rows]
        return "\n".join(out)

    def assign(self, chips) -> None:
        """Set the chip id of every die from ``chips`` (see :meth:`build`) without loading any layout."""
        for d in self.dies:
            src = _pick(chips, d)
            d.chip = None if src is None else _chip_id(src)

    # ---- drawing -------------------------------------------------------------------------------------------------
    def build(self, chips=None, layout: pya.Layout | None = None) -> tuple[pya.Layout, pya.Cell]:
        """Draw the wafer: outline 500/0, labels / outlines / marks 501/0, the chips as sub-cells. Returns
        ``(layout, top cell)``.

        ``chips`` places layouts on the dies: ``None`` (empty dies), one source for every die, ``{"B3": src}`` by die
        name, ``{7.5: src}`` by die size in mm (``"*"`` is the default) or a function ``die -> source | None``. A source
        is a ``.json`` design (built headless), an ``.oas`` / ``.gds`` file, or a ``BuildResult``. A chip is centred
        on its die; it must fit inside the die (its ``100/0`` chip boundary, or its bounding box)."""
        layout = layout or pya.Layout()
        layout.dbu = DBU
        top = layout.create_cell(f"wafer_{self.name.replace(' ', '')}")
        l_wafer = layout.layer(QCC_LAYERS["wafer_boundary"])
        l_mark = layout.layer(QCC_LAYERS["wafer_markers"])
        top.shapes(l_wafer).insert(self._ring())
        mk = pya.Region()
        for d in self.dies:
            if self.die_outline:
                mk += self._frame(d)
            if self.labels:
                mk += self._label(d)
        mk += self._marks()
        top.shapes(l_mark).insert(mk.merged())
        cache: dict[str, tuple[pya.Cell, pya.DBox]] = {}
        for d in self.dies:
            src = _pick(chips, d)
            d.chip = None if src is None else _chip_id(src)
            if src is None:
                continue
            key = str(src) if isinstance(src, (str, Path)) else f"obj{id(src)}"
            if key not in cache:
                cache[key] = _load_chip(src, layout, f"chip_{_chip_id(src)}")
            cell, box = cache[key]
            if box.width() > d.size_mm * 1000 + 1e-6 or box.height() > d.size_mm * 1000 + 1e-6:
                raise ValueError(
                    f"die {d.name}: chip {_chip_id(src)} is {box.width():g} x {box.height():g} µm, larger than the "
                    f"{d.size_mm:g} mm die"
                )
            dx, dy = d.x_mm * 1000 - box.center().x, d.y_mm * 1000 - box.center().y
            top.insert(pya.DCellInstArray(cell.cell_index(), pya.DTrans(dx, dy)))
        return layout, top

    def write(self, path: str | Path, chips=None, table: bool = True) -> Path:
        """Build and write the wafer OAS / GDS; with ``table=True`` also ``<path>.csv`` (the die table)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        layout, top = self.build(chips)
        layout.write(str(path))
        if table:
            self.write_table(path.with_suffix(".csv"))
        return path

    def write_table(self, path: str | Path) -> Path:
        path = Path(path)
        rows = self.table()
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["die"])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def plot_map(self, path: str | Path | None = None, ax=None, size_in: float = 7.0):
        """Die map (matplotlib): the outline with the notch, every die with its name. Saves to ``path`` when given."""
        import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
        from matplotlib.patches import Polygon, Rectangle  # pylint: disable=import-outside-toplevel

        fig = None
        if ax is None:
            fig, ax = plt.subplots(figsize=(size_in, size_in))
        pts = [(p.x / 1000, p.y / 1000) for p in self.outline_polygon_um().each_point_hull()]
        ax.add_patch(Polygon(pts, closed=True, fill=False, ec="#444444", lw=1.5))
        for d in self.dies:
            x0, y0, x1, y1 = (v / 1000 for v in d.box_um)
            ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc="#dbe7f5", ec="#2b5c8a", lw=0.8))
            fs = max(4.0, 1.1 * d.size_mm * size_in / self.diameter_mm * 2.2)
            ax.text(d.x_mm, d.y_mm, d.name, ha="center", va="center", fontsize=fs, color="#1b2f45")
        r = self.diameter_mm / 2 * 1.02
        ax.set_xlim(-r, r)
        ax.set_ylim(-r, r)
        ax.set_aspect("equal")
        ax.set_xlabel("x (mm)")
        ax.set_ylabel("y (mm)")
        ax.set_title(f"{self.name} wafer, {self.die_count} dies")
        if fig is not None and path is not None:
            fig.savefig(path, dpi=140, bbox_inches="tight")
            plt.close(fig)
        return ax

    # ---- pieces --------------------------------------------------------------------------------------------------
    def _ring(self) -> pya.Region:
        """The wafer outline on 500/0: a 200 µm ring just inside the rim (hollow, so the dies stay visible)."""
        outer = pya.Region(self.outline_polygon_um().to_itype(DBU))
        return (outer - outer.sized(-int(200 / DBU), 2)).merged()

    def _frame(self, d: Die) -> pya.Region:
        x0, y0, x1, y1 = (int(round(v / DBU)) for v in d.box_um)
        w = int(round(30 / DBU))
        return pya.Region(pya.Box(x0, y0, x1, y1)) - pya.Region(pya.Box(x0 + w, y0 + w, x1 - w, y1 - w))

    def _label(self, d: Die) -> pya.Region:
        h = (self.label_mm if self.label_mm else d.size_mm / 12.5) * 1000.0
        gen = pya.TextGenerator.default_generator()
        reg = gen.text(d.name, DBU, h)
        bb = reg.bbox()
        x0, y1 = d.box_um[0], d.box_um[3]
        pad = 0.25 * h
        return reg.moved(int(round((x0 + pad) / DBU)) - bb.left, int(round((y1 - pad) / DBU)) - bb.top)

    def _marks(self) -> pya.Region:
        """Alignment / orientation crosses on the four axis points in the edge-exclusion band (skipping the notch)."""
        reg = pya.Region()
        r = self.diameter_mm * 500.0
        arm = min(self.edge_mm * 1000 * 0.3, 1000.0)
        w = int(round(40 / DBU))
        a = int(round(arm / DBU))
        for side in _SIDES:
            if self.orientation != "none" and side == self.orientation_side:
                continue
            c, s = (0, -1) if side == "bottom" else (1, 0) if side == "right" else (0, 1) if side == "top" else (-1, 0)
            dist = r - self.edge_mm * 500.0
            px, py = int(round(c * dist / DBU)), int(round(s * dist / DBU))
            reg.insert(pya.Box(px - a, py - w // 2, px + a, py + w // 2))
            reg.insert(pya.Box(px - w // 2, py - a, px + w // 2, py + a))
        return reg.merged()


# ---- chips ---------------------------------------------------------------------------------------------------------
def _pick(chips, die: Die):
    """The chip source for ``die`` from the ``chips`` argument of :meth:`Wafer.build`."""
    if chips is None:
        return None
    if callable(chips) and not hasattr(chips, "layout"):
        return chips(die)
    if isinstance(chips, dict):
        for key in (die.name, die.size_mm, float(die.size_mm), "*"):
            if key in chips:
                return chips[key]
        return None
    return chips


def _chip_id(src) -> str:
    if isinstance(src, (str, Path)):
        return Path(src).stem
    design = getattr(src, "design", None)
    return getattr(design, "name", None) or str(getattr(src, "name", "chip"))


def _load_chip(src, layout: pya.Layout, name: str) -> tuple[pya.Cell, pya.DBox]:
    """Bring a chip into ``layout`` as a static cell. Returns ``(cell, box)`` where box is the chip extent in µm
    (the 100/0 chip boundary when the chip has one, else everything it draws)."""
    scratch = pya.Layout()
    if isinstance(src, (str, Path)) and Path(src).suffix.lower() in (".oas", ".gds", ".oasis"):
        scratch.read(str(src))
        top = scratch.top_cells()[0]
    else:
        from quantcore_circuits.assembly import build, write_layout  # pylint: disable=import-outside-toplevel

        result = src if hasattr(src, "top") and hasattr(src, "layout") else build(src)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chip.oas"
            write_layout(result, path, sidecar=False)
            scratch.read(str(path))
        top = scratch.top_cells()[0]
    li = scratch.find_layer(QCC_LAYERS["chip_boundary"])
    box = top.dbbox_per_layer(li) if li is not None else pya.DBox()
    if box.empty():
        box = top.dbbox()
    cell = layout.create_cell(name)
    cell.copy_tree(top)
    return cell, box
