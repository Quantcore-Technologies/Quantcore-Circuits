"""Design sim-group → KQC ``Simulation``.

For a ``sim_groups`` entry the builder:

1. derives a simulation design: junctions of the selected qubits become KQC ``"Sim"`` junctions; for capacitance
   analyses, selected routes attached to selected instances are *cut* (removed) and replaced by a short
   waveguide-to-port stub at that port, so the coupler becomes its own net (the resonator itself is modelled as a
   transmission line in LOM); no ground grid, no chip frame;
2. builds it and cuts out the box spanned by the selected instances/routes plus ``margin_um``;
3. adds ports: junction ``InternalPort`` (eigenmode / driven: L at the design flux and C_J as the LOM takes them,
   :func:`lumped_junction`; capacitance: a placeholder L, the gap stays open), waveguide-to-port stubs, and one
   port per route crossing the box edge — an ``EdgePort`` for capacitance analyses; for eigenmode, where KQC forbids
   edge ports, a 50 Ω lumped ``InternalPort`` next to the edge (KQC's ``use_internal_ports="at_edge"`` geometry), so
   the crossing line is terminated and the eigenmode Q gives κ / Purcell. Where a straight line crosses the box edge
   at an angle, that port sits on the line's own axis just inside the box, its cut square to the line
   (:func:`line_port`; driven: the same lumped port instead of a wave port);
4. passes the PDK stack (substrate, permittivity, box heights).

The group name ``"chip"`` (unless the design defines its own) means the whole chip: every instance and route is kept
uncut, the box is the chip box, and each cell exposing ``lumped_signal``/``lumped_ground`` refpoints (bond pads) gets a
50 Ω lumped port. In other groups, the selected pads get that port, and so do the pads that terminate the
selection (snapped to a selected instance, or at an end of a selected route): a selected feedline is never floating.

The returned :class:`SimSetup` records the port number → design name mapping used later to label C-matrices.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field

from kqcircuits.defaults import default_faces
from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.port import EdgePort, InternalPort
from kqcircuits.simulations.simulation import Simulation

from quantcore_circuits.assembly import build
from quantcore_circuits.design import Design, load_design, split_port_ref
from quantcore_circuits.design.schema import SimGroup
from quantcore_circuits.layouts.registry import resolve_cell
from quantcore_circuits.lom.fragment import (
    effective_junction,
    instance_junction,
    junction_values,
    missing_junction_message,
)
from quantcore_circuits.pdk import get_pdk

CAPACITANCE_ANALYSES = {"q3d_cmatrix", "elmer_cap", "palace_cap"}
EIGENMODE_ANALYSES = {"hfss_eigenmode", "eigenmode_epr", "palace_eig"}
DRIVEN_ANALYSES = {"hfss_driven"}  # S-parameters (e.g. a hanger's S21 → κ, to calibrate the LOM coupling k)
ALL_ANALYSES = CAPACITANCE_ANALYSES | EIGENMODE_ANALYSES | DRIVEN_ANALYSES
CHIP_GROUP = "chip"


def analysis_kind(analysis: str) -> str:
    """ "capacitance", "eigenmode", "driven" or a plugin's kind (see :mod:`quantcore_circuits.plugins`)."""
    if analysis in CAPACITANCE_ANALYSES:
        return "capacitance"
    if analysis in EIGENMODE_ANALYSES:
        return "eigenmode"
    if analysis in DRIVEN_ANALYSES:
        return "driven"
    from quantcore_circuits.plugins import analysis_plugins  # pylint: disable=import-outside-toplevel

    plugins = analysis_plugins()
    if analysis in plugins:
        return plugins[analysis].kind
    raise ValueError(f"unknown analysis {analysis!r}; choose from {sorted(ALL_ANALYSES | set(plugins))}")


@dataclass
class SimPortInfo:
    number: int
    kind: str  # "junction" | "waveguide" | "edge" | "edge_lumped" (eigenmode 50 Ω; driven: an angled line) | "lumped"
    name: str  # design-level label, e.g. "Q1.junction", "Q1.claw_n", "FL"
    excitation: str | None = None  # net label used for C-matrix rows (island, coupler, feedline)


@dataclass
class SimSetup:
    design: Design
    group: str
    analysis: str
    simulation: Simulation
    ports: list[SimPortInfo] = field(default_factory=list)
    box: pya.DBox | None = None
    waveguide_length: float = 100.0  # µm of CPW stub added at cut coupler ports
    nets: dict[int, str] = field(default_factory=dict)  # KQC excitation number → net label (C-matrix rows)
    geometry: dict = field(default_factory=dict)  # what the export dropped: ground grid, airbridges (→ job.json)
    notes: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)  # routes present (not cut) in the simulated geometry (→ job.json)

    def port_labels(self) -> dict[int, str]:
        return {p.number: p.excitation or p.name for p in self.ports}


def is_junction_cell(cell_ref: str) -> bool:
    """A junction cell — KQC ``Junction`` subclasses (Manhattan, NoSquid, Sim, SuperInductor, …), the Quantcore
    trilayer cells, Metal junctions (``metal:SNAIL``, …: category ``junction``). They belong in a qubit's gap (or a
    code-built layout's): placed on their own they are not a qubit, so the export gives them no qubit treatment (see
    :func:`build_simulation`: a junction port only where the cell bridges two different conductors)."""
    if cell_ref.startswith("static:"):
        return False
    try:
        cls = resolve_cell(cell_ref)
    except Exception:  # noqa: BLE001  (an unknown cell is reported by the build, not here)
        return False
    from kqcircuits.junctions.junction import Junction  # pylint: disable=import-outside-toplevel

    return getattr(cls, "qcc_category", "") == "junction" or (isinstance(cls, type) and issubclass(cls, Junction))


def _is_qubit(cell_ref: str) -> bool:
    if cell_ref.startswith("static:") or is_junction_cell(cell_ref):
        return False
    cls = resolve_cell(cell_ref)
    # KQC/Quantcore qubits have a junction_type; wrapped cells (metal:<Class>) declare their category instead
    return "junction_type" in cls.get_schema() or getattr(cls, "qcc_category", "") in ("qubit", "coupler")


def _has_param(cell_ref: str, param: str) -> bool:
    if cell_ref.startswith("static:"):
        return False
    try:
        return param in resolve_cell(cell_ref).get_schema()
    except Exception:  # noqa: BLE001  (an unknown cell is reported by the build, not here)
        return False


def strip_layers(result, airbridges: bool = False, bumps: bool = True) -> dict:
    """Remove geometry a simulation must not contain from a built layout, in place.

    * the ground grid (cheese) — always: FEM exports are never cheesed;
    * airbridges (``*airbridge_pads`` / ``*airbridge_flyover``, which KQC's ``Simulation`` would insert as PEC pads
      and bridges) — unless ``airbridges=True``;
    * indium bumps (``*indium_bump``) when ``bumps=False`` (a one-face simulation): with no opposite face KQC extends a
      bump as PEC from the face to the top of the simulation box, a pillar that shorts its island to the outer
      boundary (HFSS) or adds its capacitance (Q3D).

    Returns ``{"ground_grid_shapes", "airbridge_shapes", "airbridges"}`` (shape counts removed), plus
    ``"indium_bump_shapes"`` when bumps were removed.
    """
    layout = result.layout
    out = {"ground_grid_shapes": 0, "airbridge_shapes": 0, "airbridges": "kept" if airbridges else "dropped"}
    for li in layout.layer_indexes():
        name = layout.get_info(li).name or ""
        key = "ground_grid_shapes" if name.endswith("ground_grid") else None
        if key is None and not airbridges and "airbridge" in name:
            key = "airbridge_shapes"
        if key is None and not bumps and name.endswith("indium_bump"):
            key = "indium_bump_shapes"
        if key is None:
            continue
        n = sum(cell.shapes(li).size() for cell in layout.each_cell())
        if n:
            layout.clear_layer(li)
            out[key] = out.get(key, 0) + n
    return out


CONTACT_PATCH_UM = 0.5  # metal square joining two pieces that touch at one point (see vertex_contact_patches)


def _faces(faces) -> list[str]:
    out = []
    for f in faces or []:
        out += _faces(f) if isinstance(f, (list, tuple)) else [str(f)]
    return out


def vertex_contact_patches(result, box: pya.DBox, faces, size: float = CONTACT_PATCH_UM) -> dict[str, list[pya.DBox]]:
    """``{face: [patch boxes]}`` joining metal pieces that touch at a single point inside ``box``.

    KQC decides nets with ``Region.interacting``, which counts a point contact (a polygon vertex on another piece's
    boundary) as connected; Q3D's ``AutoIdentifyNets`` does not, splits the KQC net and stops with "Object … in Net
    'Net1' and object … in Net '…' are touching". Typical source: junction metal (a Sim pad, a fab junction window)
    drawn exactly up to a curved island edge, e.g. a neighbour Flipmon's trilayer window on its disc. A ``size`` µm
    square of ``base_metal_addition`` centred on the contact makes the join an overlap, so AEDT agrees with KQC's nets
    (it only adds metal where KQC already counted the pieces as one conductor). A patch that would also touch a third
    piece is left out."""
    layout = result.layout
    dbu = layout.dbu
    ibox = pya.Region(box.to_itype(dbu))
    out: dict[str, list[pya.DBox]] = {}
    for face in _faces(faces):
        layers = default_faces.get(face) or {}
        if "base_metal_gap_wo_grid" not in layers:
            continue

        def region(name, layers=layers):
            idx = layout.find_layer(layers[name]) if name in layers else None
            return pya.Region(result.top.begin_shapes_rec(idx)) if idx is not None else pya.Region()

        metal = ibox - (region("base_metal_gap_wo_grid") - region("base_metal_addition"))
        pieces = metal.merged(True, 0)  # min coherence: pieces touching at a point stay separate
        if pieces.count() < 2:
            continue
        regions = [pya.Region(p) for p in pieces.each()]
        boxes = [r.bbox() for r in regions]
        half = size / 2 / dbu
        for i, a in enumerate(regions):
            for j in range(i + 1, len(regions)):
                if not boxes[i].touches(boxes[j]) or a.interacting(regions[j]).is_empty():
                    continue
                touch = a.sized(1) & regions[j].sized(1)
                for spot in touch.each():
                    c = spot.bbox().center()
                    patch = pya.Region(pya.Box(c.x - half, c.y - half, c.x + half, c.y + half))
                    third = any(
                        k not in (i, j) and not r.interacting(patch).is_empty() for k, r in enumerate(regions)
                    )
                    if not third:
                        out.setdefault(face, []).append(patch.bbox().to_dtype(dbu))
    return out


# ---- the simulated metal of one face, as KQC derives it (junction ports, island nets, line cuts) --------------------
KQC_EDGE_TOL_UM = 0.007  # a point this close (per axis) to a metal edge is found by KQC (find_edge…: 0.01 µm, Euclid)
JJ_AXIS_REACH_UM = 120.0  # how far past each junction pin the junction axis is searched for the island edges
GDS_MAX_POINTS = 4000  # sim polygons stay below the 4095-point GDS XY record (0x8000 bytes) with this
FACE_METAL_MARGIN_UM = 400.0  # FaceMetal reads the layout this far around the box (straighten_box moves edges)
SIM_SMOOTH_UM = 0.05  # largest deviation from the drawn bends when a sim polygon must lose points (C8)


class FaceMetal:
    """The metal of ``face`` inside ``box`` as KQC's ``Simulation`` builds it: box − (gap − addition), plus ``etch``
    boxes (on the gap layer) and ``metal`` boxes (addition), optionally with the etch ``smooth``-ed (µm, the sim-only
    bend simplification). ``pieces`` are its conductors; ``boxed[k]``: piece k touches the box edge (ground)."""

    def __init__(self, result, box: pya.DBox, face: str, etch=(), metal=(), smooth: float = 0.0):
        layout = result.layout
        self.dbu = dbu = layout.dbu
        layers = default_faces.get(face) or {}

        def region(name):
            idx = layout.find_layer(layers[name]) if name in layers else None
            if idx is None:
                return pya.Region()
            return pya.Region(result.top.begin_shapes_rec_overlapping(idx, window.to_itype(dbu))) & window_region

        window = box.enlarged(FACE_METAL_MARGIN_UM, FACE_METAL_MARGIN_UM)  # room for the C6 box search
        window_region = pya.Region(window.to_itype(dbu))
        gap, add = region("base_metal_gap_wo_grid"), region("base_metal_addition")
        for b in etch:
            gap.insert(b.to_itype(dbu))
        for b in metal:
            add.insert(b.to_itype(dbu))
        lith = gap - add
        if smooth > 0:
            lith = lith.smoothed(max(1, round(smooth / dbu)), True)
        self._init(box, lith, dbu)

    @classmethod
    def from_etch(cls, etch: pya.Region, box: pya.DBox, dbu: float = 0.001) -> FaceMetal:
        """A FaceMetal of a plain etch region (dbu units): synthetic geometry for tests."""
        fm = cls.__new__(cls)
        fm.dbu = dbu
        fm._init(box, etch, dbu)
        return fm

    def _init(self, box: pya.DBox, lith: pya.Region, dbu: float) -> None:
        self.lith = lith  # the etch (gap − addition) around the box, uncut by it
        self.box = box
        self.box_region = pya.Region(box.to_itype(dbu))
        self.metal = (self.box_region - lith).merged()
        self.pieces = [pya.Region(p) for p in self.metal.each()]
        self._bboxes = [p.bbox() for p in self.pieces]
        border = self.box_region.edges()
        self.boxed = [not p.interacting(border).is_empty() for p in self.pieces]
        self.edges = self.metal.edges()

    def _probe(self, p: pya.DPoint, half: float) -> pya.Region:
        ip = p.to_itype(self.dbu)
        h = max(1, round(half / self.dbu))
        return pya.Region(pya.Box(ip.x - h, ip.y - h, ip.x + h, ip.y + h))

    def piece_at(self, p: pya.DPoint) -> int | None:
        """The conductor at ``p`` (None in etch); a point on an edge belongs to the piece it touches."""
        probe = self._probe(p, self.dbu)
        bb = probe.bbox()
        hits = [k for k, r in enumerate(self.pieces)
                if self._bboxes[k].touches(bb) and not r.interacting(probe).is_empty()]
        if len(hits) <= 1:
            return hits[0] if hits else None
        return max(hits, key=lambda k: (self.pieces[k] & probe).area())

    def on_edge(self, p: pya.DPoint, tol: float = KQC_EDGE_TOL_UM) -> bool:
        """``p`` lies on a metal edge (where KQC's ``find_edge_from_point_in_polygons`` finds one)."""
        return not self.edges.interacting(self._probe(p, tol)).is_empty()

    def max_points(self) -> int:
        """Most points of one metal or gap polygon as a GDS writer stores it (holes keyholed into the hull)."""
        gap = (self.box_region - self.metal).merged()
        return max([p.num_points() + 2 * p.holes() for r in (self.metal, gap) for p in r.each()] or [0])


def junction_gap(fm: FaceMetal, a: pya.DPoint, b: pya.DPoint, reach: float = JJ_AXIS_REACH_UM):
    """``(signal point, ground point)`` on the facing edges of the two conductors a junction drawn from ``a`` (island
    side) to ``b`` bridges, found along its axis — wherever its pins sit: on the edges, inside the metal (a junction
    overlapping into the islands) or short of them (a pin in a cut-out, StarQubit's line ending between its two leads).
    Among the gaps between two *different* conductors on the axis (not two box-edge grounds) the one overlapping the
    pins' span, nearest its middle, wins. None if there is none (both ends on one conductor, a zero-length junction)."""
    d = a.distance(b)
    if d < 2 * fm.dbu:
        return None
    u = (a - b) * (1.0 / d)
    p0, p1 = b - u * reach, a + u * reach
    inside = pya.Edges(pya.Edge(p0.to_itype(fm.dbu), p1.to_itype(fm.dbu))) & fm.metal

    def t(p):  # µm along the axis from b towards a
        return (p.to_dtype(fm.dbu) - b).sprod(u)

    spans = sorted(tuple(sorted((t(e.p1), t(e.p2)))) for e in inside.each())
    merged: list[list[float]] = []
    for s0, s1 in spans:
        if merged and s0 <= merged[-1][1] + 2 * fm.dbu:
            merged[-1][1] = max(merged[-1][1], s1)
        else:
            merged.append([s0, s1])
    tags = [fm.piece_at(b + u * ((s0 + s1) / 2)) for s0, s1 in merged]
    best = None
    for k in range(len(merged) - 1):
        ci, cj = tags[k], tags[k + 1]
        if ci is None or cj is None or ci == cj or (fm.boxed[ci] and fm.boxed[cj]):
            continue
        g0, g1 = merged[k][1], merged[k + 1][0]
        key = (max(0.0, g0 - d, -g1), abs((g0 + g1) / 2 - d / 2))
        if best is None or key < best[0]:
            best = (key, g0, g1)
    if best is None:
        return None
    return b + u * best[2], b + u * best[1]


JJ_SHEET_CLEARANCE_UM = 1.0  # metal-free margin along the long sides of a builder-drawn junction sheet


def junction_sheet(fm: FaceMetal, sig: pya.DPoint, gnd: pya.DPoint, width: float = 10.0, min_width: float = 0.5,
                   clearance: float = JJ_SHEET_CLEARANCE_UM):
    """``(polygon points, width)``: the junction's lumped sheet between ``gnd`` and ``sig`` (points on the two metal
    edges): a strip on the axis, ``width`` wide or narrower until no metal lies within ``clearance`` of it away from its
    ends (metal along its long sides would short the lumped element), cut to the gap (its ends follow the metal edges,
    so nothing of the sheet lies on metal and both ends touch a conductor). None if not even ``min_width`` fits."""
    v = sig - gnd
    length = v.length()
    if length < 2 * fm.dbu:
        return None
    u = v * (1.0 / length)
    n = pya.DVector(-u.y, u.x)
    mid = (gnd + v * 0.5).to_itype(fm.dbu)
    w = min(width, max(length, min_width))
    while w >= min_width - 1e-9:
        end = min(w, length / 3)  # metal may reach into the strip near oblique end edges
        hw = w / 2 + min(clearance, w / 2)
        core = pya.DPolygon([gnd + u * end + n * hw, sig - u * end + n * hw, sig - u * end - n * hw,
                             gnd + u * end - n * hw])
        ext = w + 1.0
        strip = pya.DPolygon([gnd - u * ext + n * (w / 2), sig + u * ext + n * (w / 2), sig + u * ext - n * (w / 2),
                              gnd - u * ext - n * (w / 2)])
        if (pya.Region(core.to_itype(fm.dbu)) & fm.metal).area() * fm.dbu**2 < 1e-4:
            parts = [p for p in (pya.Region(strip.to_itype(fm.dbu)) - fm.metal).each() if p.inside(mid)]
            if parts:
                poly = parts[0].to_dtype(fm.dbu)
                ts = [(pt - gnd).sprod(u) for pt in poly.each_point_hull()]
                if min(ts) > -ext + 0.5 and max(ts) < length + ext - 0.5:  # bounded by metal at both ends
                    return [pya.DPoint(pt.x, pt.y) for pt in poly.each_point_hull()], w
        w /= 2
    return None


def _has_junction_type(cell_ref: str) -> bool:
    """KQC/Quantcore qubits take ``junction_type`` (→ ``"Sim"`` for simulation); wrapped cells do not."""
    return not cell_ref.startswith("static:") and "junction_type" in resolve_cell(cell_ref).get_schema()


def junction_nets(name: str, inst, pdk) -> tuple[str, str | None]:
    """FEM net labels on the two sides of a qubit's junction: (``squid_a`` side, ``squid_b`` side or None = ground).

    Taken from the component's LOM model (island labels such as ``Q1.island``, or ``Q1.island1``/``Q1.island2`` for a
    floating transmon, whose junction connects two islands); ``<name>.island`` when there is no model.
    """
    from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel

    default = (f"{name}.island", None)
    fn = lom_model(inst.cell)
    if fn is None:
        return default
    try:
        frag = fn(name, inst, pdk)
    except Exception:  # noqa: BLE001  (a model that cannot evaluate must not block the export)
        return default
    jj = next((e for e in frag.elements if e.type in ("JJ", "SQUID")), None)
    if jj is None:
        return default

    def label(node):
        return (frag.nodes.get(node) or {}).get("island") or f"{name}.{node}"

    if "gnd" in jj.nodes:
        return label(next(n for n in jj.nodes if n != "gnd")), None
    a = frag.port_nodes.get("squid_a", jj.nodes[0])
    b = frag.port_nodes.get("squid_b", jj.nodes[1])
    return label(a), (label(b) if b != "gnd" else None)


def lumped_junction(name: str, inst, pdk, notes: list | None = None) -> tuple[float, float]:
    """(L nH, C_J fF) of a qubit's junction as a lumped RLC sheet (eigenmode, driven): the values its LOM takes
    (:func:`~quantcore_circuits.lom.fragment.instance_junction`: the design's junction, else the drawn trilayer junction
    on the PDK rule), L at the design flux. ``notes`` gets the source; raises when there is no L, saying where to set
    it."""
    # a cell whose model draws no junction element (SquidTermination: its SQUID is line length) still has a junction
    # port here: the design / drawn values
    ej = instance_junction(name, inst, pdk) or effective_junction(inst)
    try:
        lj = ej.lj_eff_nH if ej is not None else None
    except ValueError:  # Φ = ½ with d = 0
        lj = None
    if lj is None:
        raise ValueError(missing_junction_message(name, inst, ej))
    if notes is not None:
        notes.append(f"{name}: {ej.describe()}")
    return lj, ej.cj_fF


def net_names(
    sim: Simulation,
    probes: list[tuple[str, pya.DPoint]],
    near: list[tuple[str, pya.DPoint]] | None = None,
    reach: float = 100.0,
) -> dict[int, str]:
    """Label KQC's signal excitations by probing points: the first probe inside an excitation's metal names it.

    KQC numbers signals by conductor (``Simulation.split_metal_layers_by_excitation``): ports sharing a conductor
    share one excitation, and floating conductors follow in arbitrary order, so port k is not always net k.
    ``near`` probes that land in ground name the nearest unnamed conductor within ``reach`` µm (bounding-box
    distance), e.g. a floating claw whose port tail is joined to a grounded resonator.
    """
    from kqcircuits.simulations.simulation import get_simulation_layer_by_name  # pylint: disable=C0415

    regions: dict[int, pya.Region] = {}
    for name, layer in sim.layers.items():
        exc = layer.get("excitation")
        if exc:  # produce_layers moved the regions into the simulation cell
            shapes = sim.cell.shapes(sim.layout.layer(get_simulation_layer_by_name(name)))
            regions.setdefault(exc, pya.Region()).insert(pya.Region(shapes))
    names: dict[int, str] = {}
    for label, point in probes:
        ip = point.to_itype(sim.layout.dbu)
        for exc, region in sorted(regions.items()):
            if exc not in names and not region.interacting(pya.Edge(ip, ip)).is_empty():
                names[exc] = label
                break
    # proximity fallback: a component-port probe that lands in ground (e.g. a claw tail joined to a shorted resonator)
    # names the nearest still-unnamed conductor within ``reach`` µm (the floating claw body next to it)
    for label, point in near or []:
        ip = point.to_itype(sim.layout.dbu)
        if any(not r.interacting(pya.Edge(ip, ip)).is_empty() for r in regions.values()):
            continue  # inside a conductor: handled (or deliberately skipped) above
        best = None
        for exc, region in regions.items():
            if exc in names or label in names.values():
                continue
            bb = region.bbox().to_dtype(sim.layout.dbu)
            dx = max(bb.left - point.x, 0.0, point.x - bb.right)
            dy = max(bb.bottom - point.y, 0.0, point.y - bb.top)
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= reach and (best is None or dist < best[0]):
                best = (dist, exc)
        if best is not None:
            names[best[1]] = label
    # one label per conductor: two probes with the same label on different conductors means the geometry split what
    # the design treats as one (e.g. a line etched through an island). Keep both, visibly, instead of merging them.
    seen: dict[str, int] = {}
    for exc in sorted(names):
        label = names[exc]
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            names[exc] = f"{label}#{seen[label]}"
    return names


def _port_probes(sim: Simulation, labels: dict[int, str], far_sides: dict[int, str]) -> list[tuple[str, pya.DPoint]]:
    """Probe points as KQC uses them: signal side of each port (and the far island of floating junction ports)."""
    out = []
    for port in sorted(sim.ports, key=lambda p: p.number):
        if port.number not in labels:
            continue
        if hasattr(port, "ground_location"):
            v = port.signal_location - port.ground_location
            v = sim.minimum_point_spacing * v / v.abs()
            out.append((labels[port.number], port.signal_location + v))
            if port.number in far_sides:
                out.append((far_sides[port.number], port.ground_location - v))
        else:
            out.append((labels[port.number], port.signal_location))
    return out


def group_spec(design: Design, group: str) -> SimGroup:
    """The sim group ``group`` of ``design``; ``"chip"`` defaults to the whole chip with nothing cut."""
    if group in design.sim_groups:
        return design.sim_groups[group]
    if group == CHIP_GROUP:
        return SimGroup(
            select=[*design.instances, *design.routes],
            margin_um=0.0,
            analyses=sorted(ALL_ANALYSES),
            ports={r: "keep" for r in design.routes},
        )
    raise ValueError(f"no sim group {group!r}; available: {sorted(design.sim_groups) + [CHIP_GROUP]}")


def simulation_design(design: Design, group: str, analysis: str) -> tuple[Design, list[tuple[str, str]]]:
    """Copy of ``design`` prepared for simulating ``group``; also returns the cut (instance, port) pairs."""
    kind = analysis_kind(analysis)
    g = group_spec(design, group)
    data = design.to_json_dict()
    data["chip"]["params"] = {
        **data["chip"]["params"],
        "with_grid": False,
        "cheese": "original",  # no PDK band either: FEM exports are never cheesed
        "frames_enabled": [],
        "die_frame": False,
    }
    selected = set(g.select)
    for name, inst in data["instances"].items():
        if _has_param(inst["cell"], "with_grid"):
            inst["params"]["with_grid"] = False  # never cheese a simulation (whole-cell KQC chips have their own grid)
        if name in selected and _has_junction_type(inst["cell"]) and inst["params"].get("junction_type") != "No Squid":
            inst["params"]["junction_type"] = "Sim"  # wrapped qubits (metal:<Class>) keep their junction line
            if inst["params"].get("junction_window"):
                # the fab junction window is metal bridging island and ground; the simulated junction is the port
                inst["params"]["junction_window"] = []
    cuts = []
    # ports={"<route>": "cut"} (subset simulation): the route goes for every analysis. Capacitance: an end on a selected
    # *qubit* gets the waveguide-to-port stub, so the coupling pad is its own net (``<Q>.<port>``). Eigenmode / driven:
    # the pad is left open (it still loads the qubit through its capacitance; no bus mode, no loss) — a stub port at a
    # pocket pad has no port polygon (KQC finds no ground edge inside the pocket), so AEDT would skip it anyway. An end
    # on any other component (a bus tee) is left open.
    for rname, how in g.ports.items():
        if how != "cut" or rname not in data["routes"]:
            continue
        for end in (design.routes[rname].from_, design.routes[rname].to):
            if isinstance(end, str):
                inst, port = split_port_ref(end)
                from quantcore_circuits.sim_tools.subset import has_junction  # pylint: disable=C0415

                if kind == "capacitance" and inst in selected and has_junction(design, inst):
                    cuts.append((inst, port))
        del data["routes"][rname]
    if kind == "capacitance":
        from quantcore_circuits.design.schema import HangerEnd  # pylint: disable=import-outside-toplevel

        # feedlines that other routes hang from stay (removing one would leave its hangers without a line)
        hosts = {r.to.hanger for r in design.routes.values() if isinstance(r.to, HangerEnd)}
        hosts |= {r.from_.hanger for r in design.routes.values() if isinstance(r.from_, HangerEnd)}
        for rname in list(data["routes"]):
            if rname not in selected or g.ports.get(rname) in ("keep", "cut") or rname in hosts:
                continue
            route = design.routes[rname]
            for end in (route.from_, route.to):
                if isinstance(end, str):
                    inst, port = split_port_ref(end)
                    if inst in selected:
                        cuts.append((inst, port))
            del data["routes"][rname]
    # couplings are LOM-only (no geometry); drop those that name a route the cut removed, so the design validates
    data["couplings"] = {
        k: c
        for k, c in (data.get("couplings") or {}).items()
        if all(e in data["routes"] or e.split(".", 1)[0] in data["instances"] for e in c["between"])
    }
    data["sim_groups"] = {}  # the derived design is only built, never simulated by group again
    return Design.model_validate(data), cuts


def grounded_routes(design: Design) -> set[str]:
    """Routes whose centre conductor is galvanically grounded (they must not become C-matrix nets).

    A route is grounded if an end is a short: a free end with ``term == 0``, a hanger with ``end == "short"``, or a
    port that the cell class lists in ``qcc_shorted_ports`` (e.g. the Xmon flux-line tip).
    """
    from quantcore_circuits.design.schema import FreeEnd, HangerEnd  # pylint: disable=import-outside-toplevel

    out = set()
    for name, route in design.routes.items():
        for end in (route.from_, route.to):
            if isinstance(end, FreeEnd) and end.term == 0:
                out.add(name)
            elif isinstance(end, HangerEnd) and end.end == "short":
                out.add(name)
            elif isinstance(end, str):
                inst, port = split_port_ref(end)
                cell = design.instances[inst].cell if inst in design.instances else "static:"
                if not cell.startswith("static:") and port in getattr(resolve_cell(cell), "qcc_shorted_ports", ()):
                    out.add(name)
    return out


def _selection_box(result, names: list[str], margin: float) -> pya.DBox:
    box = pya.DBox()
    layout = result.layout
    gap_layer = layout.layer(pya.LayerInfo(130, 1))  # 1t1_base_metal_gap_wo_grid
    for inst in result.cell.each_inst():
        if inst.property("id") in names:
            cell = layout.cell(inst.cell_index)
            b = cell.dbbox_per_layer(gap_layer)
            if b.empty():
                b = cell.dbbox()
            box += b.transformed(inst.dcplx_trans)
    if box.empty():
        raise ValueError(f"nothing selected for simulation: {names}")
    box = box.enlarged(margin, margin)
    return pya.DBox(round(box.left), round(box.bottom), round(box.right), round(box.top))


def _route_paths(result) -> dict[str, pya.Region]:
    """Route name → its centre conductor (``1t1_waveguide_path``) in chip coordinates."""
    layout = result.layout
    path_layer = layout.layer(pya.LayerInfo(135, 1))  # 1t1_waveguide_path (centre conductor)
    out: dict[str, pya.Region] = {}
    for inst in result.cell.each_inst():
        name = inst.property("id")
        cell = layout.cell(inst.cell_index)
        if name and cell.name.startswith("Waveguide Composite"):
            region = pya.Region(cell.begin_shapes_rec(path_layer)).transformed(inst.cplx_trans)
            out.setdefault(name, pya.Region()).insert(region)
    return out


def _edge_crossings(result, box: pya.DBox, exclude: set[str], every: bool = False,
                    paths: dict[str, pya.Region] | None = None) -> list[tuple[str, pya.DPoint]]:
    """Points on the box edge where route centre conductors cross it: one per route (a capacitance net needs one
    port), or with ``every`` each crossing (eigenmode: every line end leaving the box is terminated)."""
    dbu = result.layout.dbu
    band = 2 * dbu
    out = []
    edges = [
        pya.DBox(box.left - band, box.bottom, box.left + band, box.top),
        pya.DBox(box.right - band, box.bottom, box.right + band, box.top),
        pya.DBox(box.left, box.bottom - band, box.right, box.bottom + band),
        pya.DBox(box.left, box.top - band, box.right, box.top + band),
    ]
    for name, region in (paths if paths is not None else _route_paths(result)).items():
        if name in exclude:
            continue
        found = []
        for i, edge in enumerate(edges):
            hit = (region & pya.Region(edge.to_itype(dbu))).merged()
            for poly in hit.each():  # one point per place the conductor crosses this edge
                c = poly.bbox().center().to_dtype(dbu)
                found.append(
                    [
                        pya.DPoint(box.left, c.y),
                        pya.DPoint(box.right, c.y),
                        pya.DPoint(c.x, box.bottom),
                        pya.DPoint(c.x, box.top),
                    ][i]
                )
        out += [(name, p) for p in (found if every else found[:1])]
    return out


EDGE_SHIFT_STEP_UM = 2.0


def edge_port_ok(lith: pya.Region, box: pya.DBox, pos: pya.DPoint, a: float, b: float, dbu: float) -> bool:
    """Whether KQC builds the polygon of the 50 Ω edge port at crossing ``pos`` (see :func:`build_simulation`: signal
    1 µm inside the box edge, ground ``a`` further in, the line etched between them ``a + b`` wide): after that etch
    both points must lie on a metal edge. On a bend, a taper or a diagonal they do not and AEDT skips the port (C6;
    a straight diagonal gets its port on its own axis instead, :func:`line_port`). ``lith``: the face's etch
    (gap − addition), uncut by the box."""
    out = _outward(box, pos)
    t = pya.DVector(-out.y, out.x) * ((a + b) / 2)
    signal = pos - out * 1.0
    ground = signal - out * a
    h = a + b + 5.0
    win = pya.DBox(pos.x - h, pos.y - h, pos.x + h, pos.y + h) & box
    etch = pya.Region(pya.DPolygon([signal - t, signal + t, ground + t, ground - t]).to_itype(dbu))
    edges = (pya.Region(win.to_itype(dbu)) - lith - etch).edges()
    tol = max(1, round(KQC_EDGE_TOL_UM / dbu))

    def on_edge(p):
        ip = p.to_itype(dbu)
        return not edges.interacting(pya.Region(pya.Box(ip.x - tol, ip.y - tol, ip.x + tol, ip.y + tol))).is_empty()

    return on_edge(signal) and on_edge(ground)


def crossing_square(path: pya.Region, box: pya.DBox, pos: pya.DPoint, a: float, b: float, dbu: float) -> bool:
    """The route's centre conductor (``path``) crosses the box edge at ``pos`` roughly at 90°: inside a band as deep as
    the 50 Ω edge port (``1 + a + b``) it is one piece, ``a`` to ``a + b/2`` wide along the edge, reaching across the
    band. Rules out an edge that runs along the line (a bend tangent to the edge) or a diagonal crossing, where KQC may
    still find edges but the port and the cut are skewed (a straight one gets a :func:`line_port`)."""
    out = _outward(box, pos)
    t = pya.DVector(abs(out.y), abs(out.x))
    depth = 1.0 + a + b
    half = a / 2 + b + 2.0
    band = pya.Region(pya.DBox(pos - out * depth - t * half, pos + t * half).to_itype(dbu))
    piece = (path & band).merged()
    if piece.count() != 1:
        return False
    bb = next(piece.each()).bbox().to_dtype(dbu)
    width = abs(bb.width() * t.x + bb.height() * t.y)
    along = abs(bb.width() * out.x + bb.height() * out.y)
    return a - 0.01 <= width <= a + b / 2 and along >= depth - 0.01


# ---- C6b: a straight line the box edge crosses at an angle: the 50 Ω port on the line's own axis ---------------------
LINE_PORT_MAX_ANGLE_DEG = 80.0  # a line closer than 90° − this to the box edge gets no port on its axis
LINE_PORT_STRAIGHT_SIN = 2e-3  # centre-line segments this close to parallel (~0.1°) count as one straight
LINE_PORT_WALK_UM = 500.0  # how far a straight is followed inwards from the box edge
EDGE_GAP_EXTENSION_UM = 1.0  # KQC's at-edge port: its signal point (here: the cut's nearest corner) this far inside


@dataclass(frozen=True)
class LinePort:
    """The 50 Ω port of a straight line the box edge crosses at an angle, on the line's own axis (:func:`line_port`).
    The cut runs from ``signal`` along ``direction`` (``a − 2·over_etching`` long, ``a + b`` wide, square to the line);
    the stub from ``signal`` out to the box edge stays metal, as the at-edge port's 1 µm stub."""

    edge: pya.DPoint  # where the centre line crosses the box edge
    signal: pya.DPoint  # the cut's outer side, on the axis
    direction: pya.DVector  # unit vector along the line, into the box
    angle: float  # deg between the line and the box edge's normal


def _route_spines(result) -> dict[str, list[list[pya.DPoint]]]:
    """Route name → its centre lines in chip coordinates (µm): KQC's zero-width ``waveguide_path`` paths, one point
    list per straight / curved element (the conductor polygons on the same layer are :func:`_route_paths`)."""
    layout = result.layout
    path_layer = layout.layer(pya.LayerInfo(135, 1))  # 1t1_waveguide_path
    out: dict[str, list[list[pya.DPoint]]] = {}
    for inst in result.cell.each_inst():
        name = inst.property("id")
        cell = layout.cell(inst.cell_index)
        if not (name and cell.name.startswith("Waveguide Composite")):
            continue
        it = cell.begin_shapes_rec(path_layer)
        while not it.at_end():
            shape = it.shape()
            if shape.is_path():
                t = inst.dcplx_trans * it.dtrans()
                pts = [t * p for p in shape.dpath.each_point()]
                if len(pts) > 1:
                    out.setdefault(name, []).append(pts)
            it.next()
    return out


def _spine_crossing(spines: list[list[pya.DPoint]], box: pya.DBox, pos: pya.DPoint, reach: float):
    """Where a centre line crosses the box edge at ``pos`` (the crossing nearest to it within ``reach`` µm): ``(point
    on the edge, unit vector along the line into the box, µm the line runs straight from there inwards)``, or None."""
    out = _outward(box, pos)
    segs = [(p, q) for pts in spines for p, q in zip(pts, pts[1:]) if p.distance(q) > 1e-6]
    best = None
    for p, q in segs:
        dp, dq = (p - pos).sprod(out), (q - pos).sprod(out)  # µm outside the box edge (< 0: inside)
        if dp * dq > 0 or min(dp, dq) >= 0:
            continue
        x = p + (q - p) * (dp / (dp - dq))
        if x.distance(pos) <= reach and (best is None or x.distance(pos) < best[0]):
            best = (x.distance(pos), x, p if dp < 0 else q)
    if best is None:
        return None
    _, x, tip = best
    u = (tip - x) * (1.0 / tip.distance(x))
    straight = tip.distance(x)
    while straight < LINE_PORT_WALK_UM:  # a straight split into elements (nodes, airbridges): collinear segments
        nxt = None
        for p, q in segs:
            for s, e in ((p, q), (q, p)):
                w = e - s
                if s.distance(tip) < 0.002 and w.sprod(u) > 0 and abs(w.vprod(u)) < LINE_PORT_STRAIGHT_SIN * w.length():
                    nxt = e
        if nxt is None:
            break
        straight += tip.distance(nxt)
        tip = nxt
    return x, u, straight


def line_port(spines: list[list[pya.DPoint]], box: pya.DBox, pos: pya.DPoint, a: float, b: float) -> LinePort | None:
    """The 50 Ω port of the line crossing the box edge at ``pos``, on the line's own axis (C6b). KQC's at-edge port
    cuts along the box normal: where the line crosses at an angle its points miss the metal edges, the port has no
    polygon and AEDT skips it. Here the cut is square to the line, ``a + b`` wide, with its corner nearest the box
    edge 1 µm inside it (the at-edge port's signal point); the line must run straight from the edge to ``b`` past the
    cut. At 90° this is the at-edge geometry. ``spines``: the route's centre lines (:func:`_route_spines`). None on a
    bend or a taper (:func:`straighten_box` moves the edge) and for a line within 90° − ``LINE_PORT_MAX_ANGLE_DEG`` of
    the edge."""
    found = _spine_crossing(spines, box, pos, a + b) if spines else None
    if found is None:
        return None
    x, u, straight = found
    cos = -u.sprod(_outward(box, pos))
    if cos < math.cos(math.radians(LINE_PORT_MAX_ANGLE_DEG)):
        return None
    sin = math.sqrt(max(0.0, 1.0 - cos * cos))
    s = (EDGE_GAP_EXTENSION_UM + (a + b) / 2 * sin) / cos  # along the line, edge → the cut's outer side
    if straight < s + a + b:
        return None
    return LinePort(x, x + u * s, u, math.degrees(math.acos(min(1.0, cos))))


def line_port_ok(lith: pya.Region, box: pya.DBox, edge: pya.DPoint, signal: pya.DPoint, ground: pya.DPoint,
                 etch_width: float, dbu: float) -> bool:
    """Whether KQC builds the polygon of the 50 Ω port cut from ``signal`` to ``ground``, ``etch_width`` wide (both
    points on a metal edge after the cut, as :func:`edge_port_ok` checks), and the cut parts the line: the stub
    beyond the signal side is not the line beyond the ground side, and it reaches the box edge (``edge``: where the
    line crosses it) like the at-edge port's stub. ``lith``: the face's etch (gap − addition), uncut by the box."""
    d = ground - signal
    if d.length() == 0:
        return False
    v = d * (1.0 / d.length())
    t = pya.DVector(-v.y, v.x) * (etch_width / 2)
    cut = pya.Region(pya.DPolygon([signal - t, signal + t, ground + t, ground - t]).to_itype(dbu))
    win = (pya.DBox(edge, signal) + pya.DBox(ground, ground)).enlarged(etch_width + 5.0, etch_width + 5.0) & box
    metal = pya.Region(win.to_itype(dbu)) - lith - cut
    edges = metal.edges()
    tol = max(1, round(KQC_EDGE_TOL_UM / dbu))

    def probe(p, h=tol):
        ip = p.to_itype(dbu)
        return pya.Region(pya.Box(ip.x - h, ip.y - h, ip.x + h, ip.y + h))

    if edges.interacting(probe(signal)).is_empty() or edges.interacting(probe(ground)).is_empty():
        return False
    stub, line = metal.interacting(probe(signal - v * 0.05, 1)), metal.interacting(probe(ground + v * 0.05, 1))
    if stub.is_empty() or line.is_empty() or not (stub & line).is_empty():
        return False
    return not stub.interacting(pya.Region(box.to_itype(dbu)).edges()).is_empty()


def crossing_port(path: pya.Region, spines: list[list[pya.DPoint]], lith: pya.Region, box: pya.DBox, pos: pya.DPoint,
                  a: float, b: float, dbu: float, over_etching: float = 0.0):
    """How the 50 Ω port of the line crossing the box edge at ``pos`` is built (C6): ``"edge"`` — a square crossing
    where KQC's at-edge port works (:func:`edge_port_ok`, :func:`crossing_square`; the port as it always was); a
    :class:`LinePort` — a straight line crossing at an angle, the port on its own axis (:func:`line_port`,
    :func:`line_port_ok`); None — neither (a bend, a taper: :func:`straighten_box` moves the edge; if the edge stays,
    the port has no polygon). ``path``: the route's centre conductor, ``spines``: its centre lines."""
    if edge_port_ok(lith, box, pos, a, b, dbu) and crossing_square(path, box, pos, a, b, dbu):
        return "edge"
    lp = line_port(spines, box, pos, a, b)
    if lp is not None and line_port_ok(lith, box, lp.edge, lp.signal, lp.signal + lp.direction * (a - 2 * over_etching),
                                       a + b, dbu):
        return lp
    return None


def _crossing_ports(result, box, exclude, route_ab, paths, default_ab, lith, spines,
                    over_etching=0.0) -> list[tuple[str, pya.DPoint, object]]:
    """``[(route, crossing, crossing_port(...))]`` for every line end leaving ``box``."""
    dbu = result.layout.dbu
    out = []
    for r, p in _edge_crossings(result, box, exclude, every=True, paths=paths):
        a, b = route_ab.get(r, default_ab)
        out.append((r, p, crossing_port(paths[r], spines.get(r, []), lith, box, p, a, b, dbu, over_etching)))
    return out


def _bad_crossings(result, box, exclude, route_ab, paths, default_ab, lith, spines,
                   over_etching=0.0) -> list[tuple[str, pya.DPoint]]:
    return [(r, p) for r, p, how in _crossing_ports(result, box, exclude, route_ab, paths, default_ab, lith, spines,
                                                     over_etching) if how is None]


def straighten_box(result, box: pya.DBox, exclude: set[str], route_ab: dict, default_ab: tuple,
                   inner: pya.DBox, limit: pya.DBox, max_out: float, max_in: float,
                   lith: pya.Region, over_etching: float = 0.0) -> tuple[pya.DBox, list[str]]:
    """Move box edges so every line that leaves the box is cut on a straight section (C6): the eigenmode / driven
    50 Ω edge port needs that — at 90° KQC's at-edge port, at an angle a port on the line's own axis
    (:func:`crossing_port`); on a bend or a taper KQC finds no edges and AEDT skips the port. An edge
    with a bad crossing moves out (up to ``max_out`` µm from where it was, inside ``limit``) or in (up to ``max_in``,
    never into ``inner``) by the smallest step that leaves no bad crossing on it and no more elsewhere; a line whose
    crossing then moves to the next edge (a bend at a corner of the box) is handled on that edge in the next round.
    The original box is kept when nothing improves. Returns (box, notes)."""
    paths = _route_paths(result)
    paths = {k: v for k, v in paths.items() if k not in exclude}
    spines = {k: v for k, v in _route_spines(result).items() if k not in exclude}

    def bad_of(b):
        return _bad_crossings(result, b, exclude, route_ab, paths, default_ab, lith, spines, over_etching)

    bad0 = bad_of(box)
    if not bad0:
        return box, []
    sides = ("left", "right", "bottom", "top")
    sign = {"left": -1, "right": 1, "bottom": -1, "top": 1}
    orig = {"left": box.left, "right": box.right, "bottom": box.bottom, "top": box.top}

    def side_of(b, p):
        v = _outward(b, p)
        return sides[[(-1, 0), (1, 0), (0, -1), (0, 1)].index((int(v.x), int(v.y)))]

    def moved(b, side, off):  # off > 0: outwards, measured from the original edge
        c = {"left": b.left, "right": b.right, "bottom": b.bottom, "top": b.top}
        c[side] = orig[side] + sign[side] * off
        return pya.DBox(c["left"], c["bottom"], c["right"], c["top"])

    def fits(b):
        return limit.contains(b.p1) and limit.contains(b.p2) and b.contains(inner.p1) and b.contains(inner.p2)

    # 2 µm steps near the edge, 10 µm beyond 60 µm (a bend spans up to 2r)
    steps = [k * EDGE_SHIFT_STEP_UM for k in range(1, int(60.0 / EDGE_SHIFT_STEP_UM) + 1)]
    steps += [60.0 + 10.0 * k for k in range(1, int(max(max_out, max_in, 60.0) - 60.0) // 10 + 1)]

    def search(cur, bad, strict):
        for _round in range(3):
            progressed = False
            for side in sides:
                if not [c for c in bad if side_of(cur, c[1]) == side]:
                    continue
                done = False
                for step in steps:
                    for off in (step, -step):
                        if (off > 0 and off > max_out) or (off < 0 and -off > max_in):
                            continue
                        cand = moved(cur, side, off)
                        if not fits(cand):
                            continue
                        cbad = bad_of(cand)
                        fewer = len(cbad) < len(bad) if strict else len(cbad) <= len(bad)
                        if fewer and not [c for c in cbad if side_of(cand, c[1]) == side]:
                            cur, bad, done = cand, cbad, True
                            break
                    if done:
                        progressed = True
                        break
            if not bad or not progressed:
                break
        return cur, bad

    # strict first (each move removes a bad crossing); then let a crossing move on to the next edge (a bend at a
    # corner of the box) from wherever that left off
    cur, bad = search(box, bad0, True)
    if bad:
        cur2, bad2 = search(cur, bad, False)
        if len(bad2) < len(bad):
            cur, bad = cur2, bad2
    notes = []
    if len(bad) >= len(bad0):
        return box, []
    final = {"left": cur.left, "right": cur.right, "bottom": cur.bottom, "top": cur.top}
    moves = [f"{s} {'out' if (final[s] - orig[s]) * sign[s] > 0 else 'in'} by {abs(final[s] - orig[s]):g} µm"
             for s in sides if abs(final[s] - orig[s]) > 1e-9]
    fixed = sorted({r for r, _ in bad0})
    angled = sorted({r for r, _, how in _crossing_ports(result, cur, exclude, route_ab, paths, default_ab, lith,
                                                         spines, over_etching)
                     if isinstance(how, LinePort) and r in fixed})
    where = ("on a straight section at 90° (the 50 Ω edge port needs one)" if not angled else
             f"on a straight section (the 50 Ω edge port needs one; {', '.join(angled)} at an angle, the port on the "
             "line's own axis)")
    notes.append(f"box edge(s) moved ({', '.join(moves)}) so {', '.join(fixed)} leave the box {where}"
                 + (f"; still on a bend: {', '.join(sorted({r for r, _ in bad}))}" if bad else ""))
    return cur, notes


def _terminating_pads(design: Design, selected: set[str], refp: dict) -> list[str]:
    """Pads (cells with ``lumped_signal``/``lumped_ground`` refpoints) that terminate the selection: attached by a
    snap to a selected instance, or at an end of a selected route. They join the group with their 50 Ω port, so a
    selected feedline is never left floating."""
    near = set()
    for name, route in design.routes.items():
        if name in selected:
            near |= {split_port_ref(e)[0] for e in (route.from_, route.to) if isinstance(e, str)}
    for name, inst in design.instances.items():
        p = inst.place
        if p.snap and p.to:
            other = split_port_ref(p.to)[0]
            if name in selected:
                near.add(other)
            elif other in selected:
                near.add(name)
    return sorted(
        n
        for n in near - selected
        if n in design.instances and f"{n}_lumped_signal" in refp and f"{n}_lumped_ground" in refp
    )


def _connected_ports(sim_design: Design, cuts) -> set[str]:
    """``"<inst>.<port>"`` keys with something attached in the simulated design: a route end, a snap, a cut stub."""
    out = {f"{i}.{p}" for i, p in cuts}
    for route in sim_design.routes.values():
        out |= {e for e in (route.from_, route.to) if isinstance(e, str)}
    for name, inst in sim_design.instances.items():
        pl = inst.place
        if pl.snap and pl.to:
            out |= {f"{name}.{pl.snap}", pl.to}
    return out


def lead_open_ends(fm: FaceMetal, ports: dict, islands: dict[str, set[int]], connected: set[str],
                   default_ab: tuple) -> list[tuple[str, pya.DPolygon]]:
    """``[(port key, etch polygon)]``: an open end (``b`` long, ``a + 2b`` wide) beyond each unconnected port of a
    simulated qubit whose own junction island (``islands``: qubit → its island pieces) runs through the port into the
    ground plane (the island piece reaches the box edge) — a galvanic lead left unrouted (TwoPadTransmon's ``left``
    lead ends on the pocket edge). Unetched, it joins the island to the ground plane; the fab cell is unchanged, the
    etch goes into the simulation only (C4)."""
    out = []
    for key, p in sorted(ports.items()):
        inst = key.split(".", 1)[0]
        if inst not in islands or key in connected or p.dir is None or p.dir.length() == 0:
            continue
        d = p.dir * (1.0 / p.dir.length())
        inside, outside = fm.piece_at(p.pos - d * 0.3), fm.piece_at(p.pos + d * 0.3)
        if inside is None or inside not in islands[inst] or outside != inside or not fm.boxed[inside]:
            continue
        out.append((key, _open_end(p, default_ab)))
    return out


def _open_end(p, default_ab: tuple) -> pya.DPolygon | None:
    """Etch of an open CPW end beyond port ``p``: ``b`` long (outwards), ``a + 2b`` wide."""
    if p.dir is None or p.dir.length() == 0:
        return None
    d = p.dir * (1.0 / p.dir.length())
    a, b = p.a or default_ab[0], p.b or default_ab[1]
    t = pya.DVector(-d.y, d.x) * (a / 2 + b)
    return pya.DPolygon([p.pos - t, p.pos + t, p.pos + d * b + t, p.pos + d * b - t])


def galvanic_routes(fm: FaceMetal, islands: set[int], crossings) -> tuple[set[str], set[int]]:
    """Routes whose box crossing lies on a junction island (a galvanic lead line leaving the box: the island would be
    joined to the box edge = ground) and the islands still on the box edge without such a route (C4)."""
    routes, via = set(), set()
    for route, pos in crossings:
        k = fm.piece_at(pos - _outward(fm.box, pos) * 0.3)
        if k is not None and k in islands:
            routes.add(route)
            via.add(k)
    return routes, {k for k in islands if fm.boxed[k] and k not in via}


def _outward(box: pya.DBox, p: pya.DPoint) -> pya.DVector:
    """Outward unit normal of the box edge that ``p`` lies on."""
    d = {
        (-1, 0): abs(p.x - box.left),
        (1, 0): abs(p.x - box.right),
        (0, -1): abs(p.y - box.bottom),
        (0, 1): abs(p.y - box.top),
    }
    return pya.DVector(*min(d, key=d.get))


def build_simulation(
    source,
    group: str,
    analysis: str,
    waveguide_length: float = 100.0,
    airbridges: bool | None = None,
    **sim_params,
) -> SimSetup:
    """Create the KQC ``Simulation`` for ``group``/``analysis`` (see module docstring).

    The simulated geometry never has the ground grid (cheese). Airbridges are dropped for speed unless
    ``airbridges=True`` (or the group's ``settings["airbridges"]``); a note flags crossing bridges whose line is then
    open at the crossing."""
    design = load_design(source)
    g = group_spec(design, group)
    keep_ab = bool(g.settings.get("airbridges", False)) if airbridges is None else bool(airbridges)
    whole_chip = group == CHIP_GROUP and group not in design.sim_groups
    pdk = get_pdk(design.pdk)
    sim_design, cuts = simulation_design(design, group, analysis)
    result = build(sim_design)
    faces = list(sim_params.get("face_stack") or pdk.simulation_params().get("face_stack") or [])
    geometry = strip_layers(result, airbridges=keep_ab, bumps=len(faces) > 1)
    notes = []
    if geometry["ground_grid_shapes"]:
        notes.append(f"ground grid removed from the simulation ({geometry['ground_grid_shapes']} shapes)")
    if geometry.get("indium_bump_shapes"):
        notes.append(
            f"indium bumps dropped ({geometry['indium_bump_shapes']} shapes): the simulation has one face "
            f"({', '.join(map(str, faces)) or '?'}), so a bump would be a PEC pillar to the top of the box; the "
            "flip-chip top face (2b1) is not simulated"
        )
    crossing = sorted(
        name
        for name, r in sim_design.routes.items()
        if (name in g.select or whole_chip) and any(getattr(w, "airbridge", False) for w in (r.nodes or []))
    )
    if not keep_ab and crossing:
        notes.append(
            f"crossing airbridges dropped on {', '.join(crossing)}: those lines are open at the crossing in the "
            "simulation; use airbridges=True (sim group settings) to keep them"
        )
    refp = result.refpoints
    select = list(g.select) + ([] if whole_chip else _terminating_pads(design, set(g.select), refp))
    box = pya.DBox(*design.chip.box) if whole_chip else _selection_box(result, select, g.margin_um)
    ports_ports = result.plan.all_ports()
    face = (_faces(faces) or [pdk.face])[0]
    default_ab = (pdk.cpw_a, pdk.cpw_b)
    route_ab = {
        name: (rp.params.get("a", pdk.cpw_a), rp.params.get("b", pdk.cpw_b)) for name, rp in result.plan.routes.items()
    }
    grounded = grounded_routes(sim_design)
    over_etching = float(sim_params.get("over_etching") or 0.0)  # KQC Simulation param (the PDK leaves it 0)
    eigen = analysis_kind(analysis) == "eigenmode"
    # eigenmode terminates every line end in 50 Ω; a driven run needs a wave port on every line end (S21)
    every = analysis_kind(analysis) in ("eigenmode", "driven")
    if every:  # ports={"<route>": "edge"}: a grounded line the box cuts (a qubit's λ/4 readout) is terminated too
        grounded -= {r for r, how in g.ports.items() if how == "edge"}

    # the analysis metal (FaceMetal) stands in an open end for each cut route's waveguide stub, which KQC adds later and
    # which keeps the coupler pad / lead off the ground plane
    stub_ends = [_open_end(ports_ports[f"{i}.{p}"], default_ab) for i, p in cuts if f"{i}.{p}" in ports_ports]
    stub_ends = [e for e in stub_ends if e is not None]
    # C8: a metal / gap polygon of more than GDS_MAX_POINTS points (long meanders and spirals keyholed into one ground
    # polygon) gets its bends simplified by at most SIM_SMOOTH_UM, in the simulation only (DesignSimulation below)
    fm = FaceMetal(result, box, face, etch=stub_ends)
    smooth = SIM_SMOOTH_UM if fm.max_points() > GDS_MAX_POINTS else 0.0
    if smooth:
        fm = FaceMetal(result, box, face, etch=stub_ends, smooth=smooth)

    infos: list[SimPortInfo] = []
    junctions = []
    junction_probes: list[tuple[str, pya.DPoint]] = []
    island_points: dict[str, list] = {}  # qubit → a point on each of its junction islands (C4)
    for name in g.select:
        inst = design.instances.get(name)
        if inst is None:
            continue
        junction_cell = is_junction_cell(inst.cell)
        if not junction_cell and not _is_qubit(inst.cell):
            continue
        # Quantcore cells expose the junction ends directly; KQC qubits through their "Sim" junction sub-cell
        a = refp.get(f"{name}_port_squid_a") or refp.get(f"{name}_squid_port_squid_a")
        b = refp.get(f"{name}_port_squid_b") or refp.get(f"{name}_squid_port_squid_b")
        if a is None or b is None:
            continue
        sheet = None
        if a.distance(b) < 2 * fm.dbu:
            notes.append(f"{name}: zero-length junction (squid_a = squid_b at ({a.x:.2f}, {a.y:.2f})): no junction "
                         "port")
            continue
        kqc_edges = fm.on_edge(a) and fm.on_edge(b)
        if junction_cell or not kqc_edges:
            # C3: a junction cell is simulated as a junction only where it bridges two conductors (a code-built layout);
            # C5: pins off the metal edges (Metal qubits) — the port spans the gap between the edges on the junction
            # axis
            found = junction_gap(fm, a, b)
            if found is None and junction_cell:
                notes.append(f"{name}: junction cell {inst.cell} does not bridge two conductors here (placed on its "
                             "own, both ends on one metal): no junction port, it is simulated as drawn metal — "
                             "simulate the qubit that contains it")
                continue
            if found is None:
                outside = "" if box.contains(a) and box.contains(b) else (
                    " — a junction pin lies outside the simulation box: increase margin_um")
                notes.append(f"{name}: KQC finds no metal edge at the junction pins and the junction axis crosses no "
                             "gap between two conductors: the junction port stays at the drawn pins (check the "
                             f"geometry){outside}")
            elif not (kqc_edges and found[0].distance(a) < 0.01 and found[1].distance(b) < 0.01):
                sig, gnd = found
                sheet = junction_sheet(fm, sig, gnd, JJ_PORT_WIDTH_UM)
                notes.append(
                    f"{name}: junction port spans the gap on the junction axis from ({gnd.x:.2f}, {gnd.y:.2f}) to "
                    f"({sig.x:.2f}, {sig.y:.2f}) µm ({sig.distance(gnd):.2f} µm; the drawn pins ({a.x:.2f}, "
                    f"{a.y:.2f}) / ({b.x:.2f}, {b.y:.2f}) are not on the metal edges)"
                    + (f", sheet {sheet[1]:g} µm wide" if sheet else ", no clean sheet fits: KQC's edge polygon")
                )
                a, b = sig, gnd
        if analysis_kind(analysis) in ("eigenmode", "driven"):
            # the lumped RLC sheet (and the EPR Lj) take the junction as the LOM does: L at the design flux, C_J
            lj, cj = lumped_junction(name, inst, pdk, notes)
        else:  # capacitance: the gap stays open, L is a placeholder (the design value, else 10 nH)
            lj, cj = junction_values(inst)
        net_a, net_b = junction_nets(name, inst, pdk)
        junctions.append((name, a, b, (lj or 10.0) * 1e-9, cj * 1e-15, net_a, net_b, sheet))
        # naming only (the port geometry stays as KQC wants it): the island metal next to each junction end
        junction_probes.append((net_a, _onto_metal(result, a, b)))
        island_points.setdefault(name, []).append(_island_point(fm, a, b))
        if net_b:
            junction_probes.append((net_b, _onto_metal(result, b, a)))
            island_points[name].append(_island_point(fm, b, a))

    def islands_by(m: FaceMetal) -> dict[str, set[int]]:
        return {q: {k for k in (m.piece_at(p) for p in pts if p is not None) if k is not None}
                for q, pts in island_points.items()}

    def islands_of(m: FaceMetal) -> set[int]:
        return set().union(*islands_by(m).values()) if island_points else set()

    # C4: an unrouted galvanic lead of a simulated qubit runs into the ground plane → an open end in the simulation
    open_ends = lead_open_ends(fm, ports_ports, islands_by(fm), _connected_ports(sim_design, cuts), default_ab)
    etch_extra = [poly for _, poly in open_ends]
    if open_ends:
        fm = FaceMetal(result, box, face, etch=stub_ends + etch_extra, smooth=smooth)
        geometry["lead_open_ends"] = [key for key, _ in open_ends]
        notes.append(f"open end etched beyond the unrouted lead(s) {', '.join(k for k, _ in open_ends)} (simulation "
                     "only): the lead met the ground plane at the pocket edge and joined its junction island to ground")

    def galvanic(m: FaceMetal, b: pya.DBox):
        if whole_chip:
            return set(), set()
        forced_, stuck_ = galvanic_routes(m, islands_of(m), _edge_crossings(result, b, set(), every=True))
        return forced_ & grounded, stuck_

    # C4: a grounded line (λ/4, hanger short) galvanic to an island and cut by the box joins the island to the box edge
    forced, stuck = galvanic(fm, box)
    if every and not whole_chip:  # C6: lines leave the box on a straight section (50 Ω edge port)
        inner = box.enlarged(-g.margin_um, -g.margin_um)
        r_max = max([float(rp.params.get("r", 100.0)) for rp in result.plan.routes.values()] or [100.0])
        new_box, box_notes = straighten_box(result, box, grounded - forced, route_ab, default_ab, inner,
                                            pya.DBox(*design.chip.box),
                                            min(max(g.margin_um, 2 * r_max + 30.0), FACE_METAL_MARGIN_UM - 50.0),
                                            g.margin_um / 2, fm.lith, over_etching)
        if new_box != box:
            box = new_box
            notes += box_notes
            fm = FaceMetal(result, box, face, etch=stub_ends + etch_extra, smooth=smooth)
            forced, stuck = galvanic(fm, box)
    if forced:
        grounded -= forced
        notes.append(f"{', '.join(sorted(forced))}: galvanic to a junction island and cut by the box, so terminated at "
                     "the box edge (50 Ω / edge port) instead of joining the island to the box edge (ground)")
    if stuck:
        notes.append(f"{len(stuck)} junction island(s) still reach the box edge (joined to the ground plane or a line "
                     "the export cannot terminate)")
    contact_patches = vertex_contact_patches(result, box, faces)
    if contact_patches:
        n_patches = sum(len(v) for v in contact_patches.values())
        geometry["vertex_contacts_joined"] = n_patches
        where = ", ".join(f"({b.center().x:.1f}, {b.center().y:.1f})" for v in contact_patches.values() for b in v)
        notes.append(
            f"{n_patches} metal piece(s) touching at a single point joined with a {CONTACT_PATCH_UM:g} µm patch at "
            f"{where} µm: KQC counts a point contact as connected, Q3D does not (\"objects … are touching\")"
        )

    stubs = []
    for inst, port in cuts:
        p = ports_ports[f"{inst}.{port}"]
        stubs.append((f"{inst}.{port}", p))
    crossings = [] if whole_chip else _edge_crossings(result, box, grounded, every=every)
    # C6b: a straight line the box edge crosses at an angle gets its 50 Ω port on its own axis (crossing index →
    # LinePort); a square crossing keeps KQC's at-edge port (eigenmode) / the wave port (driven), unchanged
    line_ports: dict[int, LinePort] = {}
    if every and crossings:
        paths, spines = _route_paths(result), _route_spines(result)
        for i, (route, pos) in enumerate(crossings):
            a, b = route_ab.get(route, default_ab)
            how = crossing_port(paths.get(route, pya.Region()), spines.get(route, []), fm.lith, box, pos, a, b,
                                fm.dbu, over_etching)
            if isinstance(how, LinePort):
                line_ports[i] = how
    if line_ports:
        listed = ", ".join(f"{crossings[i][0]} {lp.angle:.0f}°" for i, lp in sorted(line_ports.items()))
        notes.append(
            f"{len(line_ports)} 50 Ω port(s) on the line's own axis ({listed} from the box edge's normal): the box "
            "edge crosses these lines at an angle, so each port cuts its line square, just inside the box (the short "
            "piece out to the box edge stays metal, as at a square crossing)"
            + ("" if eigen else "; driven: a lumped 50 Ω port instead of a wave port (a wave port needs the line "
               "normal to the box face)")
        )
    lumped = []  # pads (cells with lumped_signal/lumped_ground refpoints): the whole chip's, or the selected ones
    for name in design.instances if whole_chip else [n for n in select if n in design.instances]:
        sig, gnd = refp.get(f"{name}_lumped_signal"), refp.get(f"{name}_lumped_ground")
        if sig is not None and gnd is not None and box.contains(sig) and box.contains(gnd):
            lumped.append((name, sig, gnd))

    chip_index = result.cell.cell_index()
    far_sides: dict[int, str] = {}
    sheets: dict[int, tuple] = {}  # junction port number → (sheet polygon points, width) where the builder drew it
    line_port_numbers: set[int] = set()  # C6b ports (on a line's own axis)

    class DesignSimulation(Simulation):
        def build(self):
            self.cell.insert(pya.DCellInstArray(chip_index, pya.DTrans()))
            for f, patches in contact_patches.items():
                shapes = self.cell.shapes(self.layout.layer(default_faces[f]["base_metal_addition"]))
                for patch in patches:
                    shapes.insert(patch)
            if etch_extra:  # C4 open ends (simulation only)
                shapes = self.cell.shapes(self.layout.layer(default_faces[face]["base_metal_gap_wo_grid"]))
                for poly in etch_extra:
                    shapes.insert(poly)
            n = 0
            for name, a, b, lj, cj, net_a, net_b, sheet in junctions:
                n += 1
                self.ports.append(  # floating transmon: the far island must not be forced to ground
                    InternalPort(
                        n, *self.etched_line(a, b), inductance=lj, capacitance=cj, junction=True, floating=bool(net_b)
                    )
                )
                infos.append(SimPortInfo(n, "junction", f"{name}.junction", net_a))
                if sheet:
                    sheets[n] = sheet
                if net_b:
                    far_sides[n] = net_b
            for label, p in stubs:
                n += 1
                self.produce_waveguide_to_port(
                    p.pos,
                    p.pos + p.dir * 10,
                    n,
                    use_internal_ports=True,
                    waveguide_length=waveguide_length,
                    a=p.a,
                    b=p.b,
                )
                infos.append(SimPortInfo(n, "waveguide", label, label))
            for i, (route, pos) in enumerate(crossings):
                n += 1
                lp = line_ports.get(i)
                if lp is not None:  # C6b: a straight line at an angle: the port on its own axis, cut square to it
                    a, b = route_ab.get(route, (pdk.cpw_a, pdk.cpw_b))
                    outer, inner_ = lp.signal, lp.signal + lp.direction * (a - 2 * self.over_etching)
                    # eigenmode: the at-edge order (signal on the stub out to the box edge, ground on the line);
                    # driven: a terminal lumped port, signal on the line, the stub (box wall = ground) its reference
                    sig, gnd = (outer, inner_) if eigen else (inner_, outer)
                    self.ports.append(InternalPort(n, sig, gnd, etch_width=a + b, resistance=50.0,
                                                   floating=eigen and route in forced))
                    infos.append(SimPortInfo(n, "edge_lumped", route, route))
                    line_port_numbers.add(n)
                elif eigen:  # lumped 50 Ω port 1 µm inside the edge, across the centre conductor (KQC "at_edge")
                    a, b = route_ab.get(route, (pdk.cpw_a, pdk.cpw_b))
                    out = _outward(self.box, pos)
                    signal = pos - 1.0 * out
                    ground = signal - (a - 2 * self.over_etching) * out
                    # a line galvanic to a junction island (C4): floating, or KQC makes the island part of ground
                    self.ports.append(InternalPort(n, signal, ground, etch_width=a + b, resistance=50.0,
                                                   floating=route in forced))
                    infos.append(SimPortInfo(n, "edge_lumped", route, route))
                else:
                    self.ports.append(EdgePort(n, pos))
                    infos.append(SimPortInfo(n, "edge", route, route))
            for name, sig, gnd in lumped:
                n += 1
                self.ports.append(InternalPort(n, *self.etched_line(sig, gnd), resistance=50.0))
                infos.append(SimPortInfo(n, "lumped", f"{name}.pad", f"{name}.pad"))

        def simplified_region(self, region, expansion=0.0):
            out = super().simplified_region(region, expansion)
            return out.smoothed(max(1, round(smooth / self.layout.dbu)), True) if smooth else out  # C8, sim only

        def get_port_data(self):
            out = []
            for p in super().get_port_data():
                if p.get("junction") and p["number"] in sheets:
                    p = sheet_junction_port(p, *sheets[p["number"]])
                elif p.get("junction"):
                    p = narrow_junction_port(p)
                elif p["number"] in line_port_numbers:
                    p = edge_midpoint_locations(p)
                out.append(p)
            return out

    DesignSimulation.__name__ = f"DesignSimulation_{group}"
    params = {
        **pdk.simulation_params(),
        "name": f"{design.name}_{group}_{analysis}",
        "box": box,
        "use_internal_ports": True,
        "use_ports": True,
        **sim_params,
    }
    sim = DesignSimulation(result.layout, **params)
    if smooth:
        geometry["bends_simplified_um"] = smooth
        notes.append(f"bends simplified by at most {smooth:g} µm in the simulation (a polygon had more than "
                     f"{GDS_MAX_POINTS} points, the GDS XY record limit); the fab layout is unchanged")
    labels = {p.number: p.excitation or p.name for p in infos}
    # KQC qubits mark their islands (probe_island, probe_island_1/_2): those name the island nets first
    islands = [
        (f"{name}.{key[len(name) + 7 :].replace('_', '')}", pos)
        for name in g.select
        for key, pos in sorted(refp.items())
        if key.startswith(f"{name}_probe_island")
    ]
    lom_probes = _lom_port_probes(design, select, ports_ports)
    probes = islands + _port_probes(sim, labels, far_sides) + junction_probes + _cell_probes(design, select, result)
    probes += lom_probes + _route_probes(result, select, sim_design)
    nets = net_names(sim, probes, near=lom_probes)
    named = label_unnamed(sim, nets, result, select, design)
    if named:
        nets.update(named)
        notes.append(f"{len(named)} conductor(s) no port or LOM node touches, named after their component: "
                     f"{', '.join(sorted(named.values()))} (cut where dropped airbridges crossed, floating parts of a "
                     "cell, or ground enclosed by it; airbridges=True keeps the bridges)")
    # an internal port without a port polygon is skipped by KQC's AEDT import (KQC only logs it): a missing junction
    # L_J or 50 Ω termination. Eigenmode / driven only (Q3D uses nets, not ports). Typical causes: the box edge cuts a
    # line in a bend or a taper that the box straightening could not avoid (edge_lumped; a straight line at any angle
    # gets a port on its own axis, C6b), or a junction line that is not axis-aligned.
    if every:
        port_data = {d["number"]: d for d in sim.get_port_data()}
        for p in infos:
            d = port_data.get(p.number, {})
            if d.get("type") == "InternalPort" and "polygon" not in d:
                why = (
                    "the box edge cuts the line in a bend or a taper (a straight line gets a port at any angle); "
                    "change margin_um so the edge crosses a straight section"
                    if p.kind == "edge_lumped"
                    else "KQC found no metal edge at its signal/ground points (e.g. a diagonal junction line)"
                )
                notes.append(f"port {p.number} ({p.name}, {p.kind}): no port polygon, so AEDT skips it — {why}")
                warnings.warn(f"{design.name} {group}/{analysis}: {notes[-1]}", stacklevel=2)
    return SimSetup(design, group, analysis, sim, infos, box, waveguide_length, nets, geometry, notes,
                    sorted(sim_design.routes))


def edge_midpoint_locations(p: dict) -> dict:
    """A port polygon KQC built on slanted edges (C6b): its corners are the found edges' end points on the database
    grid, so the drawn signal / ground points (off the grid) can lie a fraction of a nm off the polygon's slanted
    sides, and AEDT then refuses the port's current line ("Both endpoints of the directed line must lie on the
    boundary face"). The exported locations become the midpoints of KQC's own signal and ground edges, which lie on
    the polygon; KQC's nets were assigned from the drawn points already. Without a polygon nothing changes."""
    if "polygon" not in p or "signal_edge" not in p or "ground_edge" not in p:
        return p
    out = dict(p)
    for loc, edge in (("signal_location", "signal_edge"), ("ground_location", "ground_edge")):
        (x1, y1, z1), (x2, y2, _) = p[edge]
        out[loc] = [(x1 + x2) / 2, (y1 + y2) / 2, z1]
    return out


JJ_PORT_WIDTH_UM = 10.0  # junction lumped-RLC sheet width where KQC's own edges are too long (see below)
JJ_PORT_MAX_EDGE_UM = 20.0


def narrow_junction_port(p: dict, width: float = JJ_PORT_WIDTH_UM, max_edge: float = JJ_PORT_MAX_EDGE_UM) -> dict:
    """The junction port sheet as a ``width``-wide rectangle on the junction line (signal → ground location).

    KQC spans the port polygon between the *whole* metal edges nearest the signal and ground points. With a junction
    drawn on lead stubs (KQC qubits, Xmon + Quantcore Junction) those are short (≈ 8 µm) and kept. Where the junction
    bridges a plain gap they are the island's and the ground's whole edges: chip 12's TransmonCrossFL (signal 50 µm,
    ground 90–1145 µm: a skewed trapezoid sheet, no qubit eigenmode), IBM pocket pads (750 µm both), and a diagonal
    StarQubit line has no edge at all (no polygon, AEDT skips the port). Those get the rectangle instead; the ends sit
    on the metal boundary (``etched_line``), the current line is unchanged."""
    def length(e):
        return math.dist(e[0][:2], e[1][:2])

    edges = [p.get("signal_edge"), p.get("ground_edge")]
    if "polygon" in p and all(e is not None and length(e) <= max_edge for e in edges):
        return p
    s, g = p["signal_location"], p["ground_location"]
    dx, dy = g[0] - s[0], g[1] - s[1]
    d = math.hypot(dx, dy)
    if d == 0:
        return p
    known = [length(e) for e in edges if e is not None]
    w = min([width] + known) / 2
    tx, ty = -dy / d * w, dx / d * w
    z = s[2] if len(s) > 2 else 0.0
    out = dict(p)
    out["signal_edge"] = ((s[0] - tx, s[1] - ty, z), (s[0] + tx, s[1] + ty, z))
    out["ground_edge"] = ((g[0] + tx, g[1] + ty, z), (g[0] - tx, g[1] - ty, z))
    out["polygon"] = [list(out["signal_edge"][0]), list(out["signal_edge"][1]), list(out["ground_edge"][0]),
                      list(out["ground_edge"][1])]
    return out


def sheet_junction_port(p: dict, polygon, width: float) -> dict:
    """Port data with the builder's junction sheet (:func:`junction_sheet`): ``polygon`` replaces KQC's; the signal /
    ground edges are ``width`` long across the junction axis at the port's signal / ground points."""
    s, g = p["signal_location"], p["ground_location"]
    z = s[2] if len(s) > 2 else 0.0
    dx, dy = g[0] - s[0], g[1] - s[1]
    d = math.hypot(dx, dy) or 1.0
    tx, ty = -dy / d * width / 2, dx / d * width / 2
    out = dict(p)
    out["polygon"] = [[q.x, q.y, z] for q in polygon]
    out["signal_edge"] = ((s[0] - tx, s[1] - ty, z), (s[0] + tx, s[1] + ty, z))
    out["ground_edge"] = ((g[0] + tx, g[1] + ty, z), (g[0] - tx, g[1] - ty, z))
    return out


def _gds_points(poly) -> int:
    return poly.num_points() + 2 * poly.holes()  # a GDS writer keyholes each hole into the hull


def split_large_gds_polygons(path, limit: int = GDS_MAX_POINTS, overlap_um: float = 0.01) -> int:
    """Rewrite each polygon of the simulation GDS ``path`` with more than ``limit`` points (a GDS XY record holds at
    most 4095) as pieces of the same conductor that overlap by ``overlap_um`` along the cuts, inside the original
    outline (a layer's pieces that KLayout's writer split at 8000 points, edge to edge, are rejoined first). For HFSS
    jobs only: every metal sheet is PEC there, so the pieces act as one conductor; Q3D's ``AutoIdentifyNets`` keeps
    overlapping objects as separate nets (AEDT 2024 R1 render). Used where simplifying bends is not enough (many holes,
    e.g. flux-trap rows); done on the written file, after KQC built the port polygons from the whole outlines. Layers
    without such a polygon are not touched; returns the number of polygons rewritten (0: file unchanged)."""
    layout = pya.Layout()
    layout.read(str(path))
    ov = max(1, round(overlap_um / layout.dbu))
    count = 0
    for cell in layout.each_cell():
        for li in layout.layer_indexes():
            shapes = cell.shapes(li)
            if not any((s.is_polygon() or s.is_simple_polygon()) and _gds_points(s.polygon) > limit
                       for s in shapes.each()):
                continue
            merged = pya.Region(shapes).merged()  # also rejoins pieces a writer split at 8000 points
            shapes.clear()
            for poly in merged.each():
                if _gds_points(poly) <= limit:
                    shapes.insert(poly)
                    continue
                whole = pya.Region(poly)
                todo, pieces = [poly], []
                while todo:
                    q = todo.pop()
                    if _gds_points(q) <= limit - 100:
                        pieces.append(q)
                    else:
                        todo += list(q.split())
                for piece in pieces:
                    for part in (pya.Region(piece).sized(ov) & whole).each():
                        shapes.insert(part)
                count += 1
    if count:
        opts = pya.SaveLayoutOptions()
        opts.set_format_from_filename(str(path))
        opts.write_context_info = False
        layout.write(str(path), opts)
    return count


def _island_point(fm: FaceMetal, p: pya.DPoint, other: pya.DPoint) -> pya.DPoint | None:
    """A point on the island metal at junction end ``p`` (just past it, away from ``other``), or None."""
    d = p.distance(other)
    for step in (0.3, 1.0, 0.0):
        q = p + (p - other) * (step / d) if d else p
        if fm.piece_at(q) is not None:
            return q
    return None


def _cell_probes(design: Design, select: list[str], result) -> list[tuple[str, pya.DPoint]]:
    """Probes a cell declares for its LOM nodes (``qcc_probes(params) -> {node: (x, y)}``, cell frame, µm): islands
    no port touches (JtwpaChain's chain islands ``n1``…), labelled with the node's FEM island."""
    from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel

    trans = {inst.property("id"): inst.dcplx_trans for inst in result.cell.each_inst() if inst.property("id")}
    pdk = get_pdk(design.pdk)
    out = []
    for name in select:
        inst = design.instances.get(name)
        if inst is None or inst.cell.startswith("static:") or name not in trans:
            continue
        fn = getattr(resolve_cell(inst.cell), "qcc_probes", None)
        if fn is None:
            continue
        try:
            points = fn(dict(inst.params or {}))
            model = lom_model(inst.cell)
            frag = model(name, inst, pdk) if model else None
        except Exception:  # noqa: BLE001  (naming must not block the export)
            continue
        for node, (x, y) in points.items():
            label = ((frag.nodes.get(node) or {}).get("island") if frag else None) or f"{name}.{node}"
            out.append((label, trans[name] * pya.DPoint(x, y)))
    return out


def _excitation_regions(sim) -> dict[int, pya.Region]:
    from kqcircuits.simulations.simulation import get_simulation_layer_by_name  # pylint: disable=C0415

    regions: dict[int, pya.Region] = {}
    for name, layer in sim.layers.items():
        exc = layer.get("excitation")
        if exc:
            shapes = sim.cell.shapes(sim.layout.layer(get_simulation_layer_by_name(name)))
            regions.setdefault(exc, pya.Region()).insert(pya.Region(shapes))
    return regions


def label_unnamed(sim, nets: dict[int, str], result, select: list[str], design: Design) -> dict[int, str]:
    """Labels for signal conductors no probe named (C7): a piece of a selected cell's own line (its waveguide path;
    a spiral cut where a dropped airbridge crossed) → the cell's LOM island when it has exactly one (``X.res#2``), a
    piece of a route's line → the route; any other conductor inside a selected cell → ``<cell>.floating[k]``
    (floating parts such as a coupler's cross, ground enclosed by the cell); else ``floating<k>``."""
    from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel

    regions = _excitation_regions(sim)
    todo = [e for e in sorted(regions) if e not in nets]
    if not todo:
        return {}
    layout = result.layout
    dbu = layout.dbu
    path_layer = layout.layer(pya.LayerInfo(135, 1))  # 1t1_waveguide_path
    pdk = get_pdk(design.pdk)
    cells = {}  # selected instance → (bbox, own line path, line label)
    for inst in result.cell.each_inst():
        name = inst.property("id")
        if name not in select or name not in design.instances:
            continue
        cell = layout.cell(inst.cell_index)
        path = pya.Region(cell.begin_shapes_rec(path_layer)).transformed(inst.cplx_trans)
        di = design.instances[name]
        model = lom_model(di.cell) if not di.cell.startswith("static:") else None
        try:
            frag = model(name, di, pdk) if model else None
        except Exception:  # noqa: BLE001
            frag = None
        isl = [v.get("island") for v in (frag.nodes.values() if frag else []) if v and v.get("island")]
        # a piece of the cell's own line is that line's island only if the cell has one (a resonator: X.res)
        cells[name] = (inst.dbbox(), path if len(isl) == 1 else pya.Region(), isl[0] if len(isl) == 1 else "")
    routes = _route_paths(result)
    raw: dict[int, str] = {}
    for e in todo:
        r = regions[e]
        label = next((line for _, (_, path, line) in cells.items() if not path.is_empty() and
                      not r.interacting(path).is_empty()), None)
        label = label or next((rn for rn, path in routes.items() if not r.interacting(path).is_empty()), None)
        if label is None:
            c = r.bbox().to_dtype(dbu).center()
            inside = [(bb.area(), n) for n, (bb, _, _) in cells.items() if bb.contains(c)]
            label = f"{min(inside)[1]}.floating" if inside else "floating"
        raw[e] = label
    out: dict[int, str] = {}
    used = list(nets.values())
    for e, label in raw.items():
        same = [x for x in raw.values() if x == label]
        if label.endswith("floating"):
            k = sum(1 for x in out.values() if x.startswith(label)) + 1
            out[e] = label if len(same) == 1 and label not in used else f"{label}{k}"
        else:
            k = sum(1 for x in used + list(out.values()) if x == label or x.startswith(label + "#")) + 1
            out[e] = label if k == 1 else f"{label}#{k}"
    return out


def _onto_metal(result, p: pya.DPoint, other: pya.DPoint, reach: float = 60.0, step: float = 0.5) -> pya.DPoint:
    """A point on the metal at a junction end, for *naming* the island net: ``p`` itself if it touches metal, else the
    first metal point moving away from ``other`` along the junction line (within ``reach`` µm). Some Metal qubits
    (StarQubit) end their junction line inside an etched slot, so the port probe lands in etch and the island stays
    unnamed. The port geometry itself is not changed (KQC places junction ports inside the gap by design)."""
    layout = result.layout
    gap = pya.Region(result.cell.begin_shapes_rec(layout.layer(pya.LayerInfo(130, 1))))  # 1t1_base_metal_gap_wo_grid

    def metal(pt):  # touches metal: on metal, or on the metal/etch boundary (where KQC's own ports sit)
        box = pya.Region(pya.DBox(pt.x - 0.05, pt.y - 0.05, pt.x + 0.05, pt.y + 0.05).to_itype(layout.dbu))
        return not (box - gap).is_empty()

    if metal(p):
        return p
    d = p - other
    if d.length() == 0:
        return p
    d = d / d.length()
    k = step
    while k <= reach:
        q = p + d * k
        if metal(q):
            return q
        k += step
    return p


def _route_probes(result, select: list[str], sim_design: Design) -> list[tuple[str, pya.DPoint]]:
    """A probe on each selected route that stays in the simulation (not cut): the middle of its longest straight
    segment (on the centre conductor even where corners are rounded), labelled with the route name."""
    out = []
    for name in select:
        rp = result.plan.routes.get(name)
        if rp is None or name not in sim_design.routes:
            continue
        pts = rp.polyline()
        if len(pts) < 2:
            continue
        a, b = max(zip(pts, pts[1:]), key=lambda ab: (ab[1] - ab[0]).length())
        out.append((name, a + (b - a) * 0.5))
    return out


def _lom_port_probes(design: Design, select: list[str], ports: dict) -> list[tuple[str, pya.DPoint]]:
    """Fallback probes: each selected component's ports, labelled with the FEM island of the LOM node they map to.

    Names conductors no simulation port touches (e.g. a resonator component next to a feedline: ``R2.res``). A probe
    sits 0.5 µm inside the component, behind the port. Ports mapped to ground or a control are skipped.
    """
    from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel

    pdk = get_pdk(design.pdk)
    out = []
    for name in select:
        inst = design.instances.get(name)
        fn = lom_model(inst.cell) if inst is not None and not inst.cell.startswith("static:") else None
        if fn is None:
            continue
        try:
            frag = fn(name, inst, pdk)
        except Exception:  # noqa: BLE001  (a model that cannot evaluate must not block the export)
            continue
        for port, local in sorted(frag.port_nodes.items()):
            p = ports.get(f"{name}.{port}")
            if p is None or local == "gnd" or local.startswith("control:"):
                continue
            label = (frag.nodes.get(local) or {}).get("island") or f"{name}.{local}"
            out.append((label, p.pos - p.dir * 0.5 if p.dir is not None else p.pos))
    return out
