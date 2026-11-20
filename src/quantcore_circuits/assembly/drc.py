"""Connectivity DRC: every pin, endpoint and handle connected to something, nothing outside the chip, no crossings.

========================  ========  ====================================================================================
rule                      severity  check
========================  ========  ====================================================================================
``dangling_port``         warning   a component port with no route or snap on it (e.g. an unused claw)
``no_lom``                warning   a component with ports but no LOM model (its ports stay bare nodes in the circuit)
``outside_chip``          error     a component box or route vertex outside the chip box
``overlap``               warning   two component boxes overlap on a chip face both draw on (snapped pairs excepted; a
                                    TSV or bump on another component only where its via or bump lands on that
                                    component's etch)
``crossing``              error     two route centre lines cross on the same chip face (a CPW crossing needs an
                                    airbridge)
``open``/``short``        error     declared vs extracted connectivity (KQC netlist, see :mod:`.netlist`)
``open_conductor``        error     a route and the component port it ends on are not one piece of metal (etch between
                                    them on the centre line, e.g. a pin whose gap runs past the pin), judged on the
                                    face that route end is drawn on
``route_failed``          error     a route could not be built (keep-going build): it is not in the layout, with the
                                    reason
``route_overlap``         error     two routes' *built* centre conductors overlap on the same face (meanders included;
                                    also two routes on one component, away from it)
``route_clearance``       warning   two routes' built gap etch touches (no ground strip between the two CPWs)
``route_self_overlap``    error     a route's built centre conductor runs over itself (nodes looping back across an
                                    earlier straight, meander turns landing on another part of the same route)
``route_over_component``  error     a route's built conductor or gap overlaps the etch of a component that is not one of
                                    its ends (the route runs across it)
``airbridge_short``       error     a route's airbridge pad lands on another route's conductor or gap (shorts it to
                                    ground)
``frame_margin``          warning   a component (not a pad) reaches into the die margin of the PDK frame
``frame_keepout``         warning   a component or route on a frame marker area or the device ID
``pad_edge``              design    PDK pad rule: a bond pad / launcher (or ``TaperedPad`` ring) whose outer etch edge
                                    is not ``frame.pad_edge`` (100 µm) from the nearest die edge (fix: ``place.edge``)
``pdk_rn``                design    PDK margin: a junction's R_n (from the instance's L_J) outside the junction window
``pdk_fq``                design    PDK margin: a qubit's f_q target outside the PDK qubit band (4–8 GHz)
``pdk_claw``              design    PDK margin: a ``metal:TransmonCross`` claw long enough to reach the side arms (fix:
                                    a longer ``cross_length``)
========================  ========  ====================================================================================

The ``pad_edge`` and ``pdk_*`` rows are **design warnings** (severity ``"design"``, 2026-11-03): the design
system builds any values; it flags where a design leaves the PDK margins and never blocks the build. A report with
only design warnings still reads "DRC clean" (with their count) and is ``ok``.

``check(..., netlist=False)`` skips the KQC netlist extraction; that fast variant runs on every build and is written
into the KLayout sidecar so the plugin can mark the issues in place.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from quantcore_circuits import track as _track


@dataclass
class DrcIssue:
    severity: str  # "error" | "warning" | "design" (PDK design warning: flagged, never enforced)
    rule: str
    message: str
    where: list[tuple[float, float]] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)


@dataclass
class DrcReport:
    issues: list[DrcIssue]

    @property
    def errors(self) -> list[DrcIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[DrcIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def design(self) -> list[DrcIssue]:
        """PDK design warnings (pad edge, junction R_n window, f_q band, claw length): flagged, never enforced."""
        return [i for i in self.issues if i.severity == "design"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self) -> list[dict]:
        return [asdict(i) for i in self.issues]

    def __str__(self) -> str:
        lines = [f"{i.severity:7s} {i.rule:13s} {i.message}" for i in self.issues]
        if len(self.design) == len(self.issues):
            head = "DRC clean" + (f" ({len(self.design)} PDK design warning(s))" if self.design else "")
            return "\n".join([head, *lines])
        return "\n".join(lines)


def _segments_cross(p, q, r, s) -> tuple[float, float] | None:
    """Proper intersection point of segments pq and rs (touching at shared endpoints does not count)."""

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1])

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    d1, d2 = sub(q, p), sub(s, r)
    den = cross(d1, d2)
    if abs(den) < 1e-12:
        return None
    t = cross(sub(r, p), d2) / den
    u = cross(sub(r, p), d1) / den
    eps = 1e-6
    if eps < t < 1 - eps and eps < u < 1 - eps:
        return (p[0] + t * d1[0], p[1] + t * d1[1])
    return None


def check(source, netlist: bool = True, keep_going: bool = False) -> DrcReport:
    """DRC of a design or build result. ``keep_going`` builds a design file with the routes that fail left out, and the
    report names them (``route_failed``); the default raises on a route that cannot be built."""
    report = _check(source, netlist, keep_going)
    _track.emit("drc", report=report, design=source.design if hasattr(source, "design") and hasattr(source, "plan") else None)
    return report


def _check(source, netlist: bool = True, keep_going: bool = False) -> DrcReport:
    """DRC of a design (path/dict/Design) or a :class:`~quantcore_circuits.assembly.BuildResult`."""
    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel

    result = source if hasattr(source, "plan") and hasattr(source, "cell") else build(source, keep_going=keep_going)
    design, plan = result.design, result.plan
    issues: list[DrcIssue] = []
    for name, f in plan.failed.items():  # never drop a route silently: a failed one is an error of its own
        where = [(p.x, p.y) for p in f.attempt if p is not None][:1]
        kept = " (its last good route is kept for the LOM)" if f.last_good else ""
        issues.append(DrcIssue("error", "route_failed", f"{f.error}; it is not in the layout{kept}", where, [name]))
    ports = plan.all_ports()

    used = set()
    for route in design.routes.values():
        for end in (route.from_, route.to):
            if isinstance(end, str):
                used.add(end)
    for c in design.couplings.values():  # galvanic joins of overlapping ports
        if c.type == "wire":
            used |= set(c.between)
    snapped = set()
    for name, inst in design.instances.items():
        p = inst.place
        if p.snap and p.to:
            own = p.snap if "." in p.snap else f"{name}.{p.snap}"
            used |= {own, p.to}
            snapped.add(frozenset({name, p.to.split(".", 1)[0]}))
    for ref, port in sorted(ports.items()):
        inst = ref.split(".", 1)[0]
        if inst in design.instances and ref not in used:
            issues.append(
                DrcIssue(
                    "warning",
                    "dangling_port",
                    f"{ref} is not connected (no route or snap)",
                    [(port.pos.x, port.pos.y)],
                    [ref],
                )
            )
    for name, inst in design.instances.items():
        placed = plan.instances.get(name)
        if placed is not None and not placed.local_ports:
            continue  # no ports: nothing to map into the circuit (test pads, ground perforations, markers)
        if not inst.cell.startswith("static:") and lom_model(inst.cell) is None:
            issues.append(DrcIssue("warning", "no_lom", f"{name} ({inst.cell}) has no LOM model", [], [name]))

    x0, y0, x1, y1 = design.chip.box
    from quantcore_circuits.assembly.sidecar import sidecar_dict  # pylint: disable=import-outside-toplevel

    side = sidecar_dict(result, overlays=False)
    boxes = {n: i["bbox"] for n, i in side["instances"].items() if i.get("bbox")}
    for name, b in boxes.items():
        if b[0] < x0 - 1e-6 or b[1] < y0 - 1e-6 or b[2] > x1 + 1e-6 or b[3] > y1 + 1e-6:
            issues.append(
                DrcIssue(
                    "error",
                    "outside_chip",
                    f"{name} extends outside the chip box",
                    [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)],
                    [name],
                )
            )
    issues += _frame_issues(design, boxes, side["routes"], device_id_block(result))
    issues += pdk_margin_issues(design, boxes)
    on_faces = _InstanceFaces(result)
    issues += _conductor_opens(result, on_faces=on_faces)
    issues += _route_overlaps(result)
    names = sorted(boxes)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            A, B = boxes[a], boxes[b]
            if A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3] and frozenset({a, b}) not in snapped:
                hit, face = on_faces.overlap(a, b)
                if not hit:
                    continue  # on different faces, or a TSV / bump on the other's metal
                c = ((max(A[0], B[0]) + min(A[2], B[2])) / 2, (max(A[1], B[1]) + min(A[3], B[3])) / 2)
                msg = f"{a} and {b} overlap" if face is None else (
                    f"{a} and {b} overlap: the via or bump lands on the etch ({face})")
                issues.append(DrcIssue("warning", "overlap", msg, [c], [a, b]))
    polys = {n: [tuple(p) for p in r["polyline"]] for n, r in side["routes"].items()}
    for name, pts in polys.items():
        out = [p for p in pts if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1)]
        if out:
            issues.append(DrcIssue("error", "outside_chip", f"route {name} leaves the chip box", out[:1], [name]))
    rnames = sorted(polys)
    faces = {n: _segment_faces(design, n, side["routes"][n], plan) for n in rnames}
    for i, a in enumerate(rnames):
        for b in rnames[i + 1 :]:
            hit = None
            for k, (p, q) in enumerate(zip(polys[a], polys[a][1:])):
                for m, (r, s) in enumerate(zip(polys[b], polys[b][1:])):
                    if faces[a][k] != faces[b][m]:
                        continue  # one line passes over the other on the other chip face (flip chip)
                    hit = _segments_cross(p, q, r, s)
                    if hit:
                        break
                if hit:
                    break
            if hit:
                issues.append(
                    DrcIssue(
                        "error", "crossing", f"routes {a} and {b} cross (needs an airbridge crossing)", [hit], [a, b]
                    )
                )
    if netlist:
        from quantcore_circuits.assembly.netlist import check_netlist  # pylint: disable=import-outside-toplevel

        for n in check_netlist(result).issues:
            issues.append(DrcIssue("error", n.kind, str(n), n.where, list(n.ports)))
    return DrcReport(issues)


def _edge_component(cell: str) -> bool:
    """Pads and launchers may reach the die edge (their ground cut-out runs to the dicing line)."""
    if cell.startswith("static:"):
        return False
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    try:
        cls = resolve_cell(cell)
    except Exception:  # noqa: BLE001
        return False
    category = getattr(cls, "qcc_category", "")
    return category in ("launcher", "termination") or "Launch" in cls.__name__ or cls.__name__.endswith("Pad")


# Cells outside the ``launcher`` category that are still bond pads for the PDK pad rule. ``TaperedPad``
# (2026-11-18): drawn as a wire-bond / probe ring at the die edge (chip_06's 24 rings), so its etch window follows
# ``frame.pad_edge`` too; one used as a probe pad inside the die gets a ``pad_edge`` design warning (never blocking).
_BOND_PAD_CELLS = ("Launcher", "LauncherDC", "TaperedPad")


def _bond_pad(cell: str) -> bool:
    """Bond pads and launchers (the cells the PDK pad rule puts at the die edge): the ``launcher`` category and
    :data:`_BOND_PAD_CELLS`."""
    if cell.startswith("static:"):
        return False
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    try:
        cls = resolve_cell(cell)
    except Exception:  # noqa: BLE001
        return False
    return getattr(cls, "qcc_category", "") == "launcher" or cls.__name__ in _BOND_PAD_CELLS


_UNITS = {"um": 1.0, "nm": 1e-3, "mm": 1e3}


def _metal_um(value, default: float) -> float:
    """A ``metal:`` length option in µm ("150um", "0.2mm"; a bare number is µm, as the ``metal:`` wrapper reads
    it — see ``layouts/metal/component.py``)."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    for unit, scale in _UNITS.items():
        if text.endswith(unit):
            try:
                return float(text[: -len(unit)]) * scale
            except ValueError:
                return default
    try:
        return float(text)
    except ValueError:
        return default


def _junction_rn_kohm(inst, proc) -> list[float]:
    """Device R_n (kΩ) of each junction element of an instance, from its ``junction.Lj_nH`` (a list: one value per
    junction element). As in :func:`~quantcore_circuits.circuit.bridges.junction_from_fingers` and
    ``size_junction``, the PDK window applies to the device: a SQUID's L_J is its parallel total, so its R_n is the
    parallel R_n of the two junctions (two 90 kΩ junctions = a 45 kΩ SQUID, inside 40–50 kΩ)."""
    from quantcore_circuits.circuit.bridges import rn_from_lj  # pylint: disable=import-outside-toplevel

    j = inst.junction
    if j is None or j.Lj_nH is None:
        return []
    values = j.Lj_nH if isinstance(j.Lj_nH, list) else [j.Lj_nH]
    return [rn_from_lj(float(lj), proc.gap_meV) / 1e3 for lj in values if lj and float(lj) > 0]


def pdk_margin_issues(design, boxes: dict) -> list[DrcIssue]:
    """PDK design warnings (flagged, never enforced): pad edge distance, junction R_n window, f_q band, TransmonCross
    claw vs arm length."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    pdk = get_pdk(design.pdk)
    out = []
    x0, y0, x1, y1 = design.chip.box
    edge = pdk.frame.pad_edge
    for name, inst in design.instances.items():
        b = boxes.get(name)
        if b is None or not _bond_pad(inst.cell):
            continue
        gap = min(b[0] - x0, b[1] - y0, x1 - b[2], y1 - b[3])
        if abs(gap - edge) > 1.0:
            out.append(
                DrcIssue(
                    "design",
                    "pad_edge",
                    f"{name}: outer edge {gap:.0f} µm from the die edge; the Quantcore PDK puts pads {edge:g} µm from "
                    "it — place it with edge='auto'",
                    [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)],
                    [name],
                )
            )
    proc = pdk.junction
    lo, hi = proc.rn_target_kohm
    for name, inst in design.instances.items():
        bad = [rn for rn in _junction_rn_kohm(inst, proc) if not lo <= rn <= hi]
        if bad:
            out.append(
                DrcIssue(
                    "design",
                    "pdk_rn",
                    f"{name}: junction R_n {', '.join(f'{rn:.1f}' for rn in bad)} kΩ is outside the PDK window "
                    f"{lo:g}–{hi:g} kΩ (L_J {inst.junction.Lj_nH} nH)",
                    [],
                    [name],
                )
            )
    f_lo, f_hi = proc.f_q_range_GHz
    for name, target in design.targets.items():
        f = target.get("f_q_GHz")
        if f is not None and not f_lo <= float(f) <= f_hi:
            out.append(
                DrcIssue(
                    "design",
                    "pdk_fq",
                    f"{name}: f_q target {f:g} GHz is outside the PDK band {f_lo:g}–{f_hi:g} GHz",
                    [],
                    [name],
                )
            )
    for name, inst in design.instances.items():
        if inst.cell not in ("metal:TransmonCross", "metal:TransmonCrossFL"):
            continue
        from quantcore_circuits.layouts.metal import flat_options  # pylint: disable=import-outside-toplevel

        p = flat_options(inst.params)
        arm = _metal_um(p.get("cross_length"), 200.0)
        width = _metal_um(p.get("cross_width"), 20.0)
        for pad, opts in (p.get("connection_pads") or {}).items():
            opts = opts or {}
            if str(opts.get("connector_type", "0")) != "0":
                continue  # gap-type connector: no claw arms
            claw = _metal_um(opts.get("claw_length"), 30.0)
            spacing = _metal_um(opts.get("ground_spacing_back") or opts.get("ground_spacing"), 5.0)
            reach = arm + spacing - width / 2  # claw arms longer than this run into the side arms' gap
            if claw >= reach:
                out.append(
                    DrcIssue(
                        "design",
                        "pdk_claw",
                        f"{name}: claw {pad!r} (claw_length {claw:g} µm) reaches the side arms of the cross "
                        f"(cross_length {arm:g} µm); make cross_length ≥ {claw - spacing + width / 2 + 10:.0f} µm",
                        [],
                        [name],
                    )
                )
    return out


def _first_face(params: dict) -> str | None:
    """``face_ids[0]`` (a list, as KQC has it, or one face as a string), else ``face_id``, else None."""
    ids = params.get("face_ids")
    if isinstance(ids, str) and ids:
        return ids
    if isinstance(ids, (list, tuple)) and ids:
        return str(ids[0])
    return str(params["face_id"]) if params.get("face_id") else None


def _route_face(design, name: str, plan=None) -> str:
    """The chip face a route starts on: the first entry of its ``face_ids`` (KQC ``WaveguideComposite`` draws on
    ``face_ids[0]``), else its ``face_id``, else the face it inherits from the chip (the plan's route parameters),
    else ``1t1``."""
    route = design.routes.get(name)
    own = _first_face((route.params or {}) if route is not None else {})
    if own:
        return own
    planned = plan.routes.get(name) if plan is not None else None
    return _first_face((planned.params or {}) if planned is not None else {}) or "1t1"


def _route_end_face(design, name: str, plan=None) -> str:
    """The chip face a route ends on: its start face (:func:`_route_face`), switched by every waypoint whose
    ``params.face_id`` names another face (KQC inserts a ``FlipChipConnectorRf`` there)."""
    face = _route_face(design, name, plan)
    route = design.routes.get(name)
    for node in getattr(route, "nodes", None) or []:
        params = getattr(node, "params", None) or {}
        if params.get("face_id"):
            face = str(params["face_id"])
    return face


def _segment_faces(design, name: str, built: dict, plan=None) -> list[str]:
    """Chip face of each segment of a route's built polyline: the route's start face (:func:`_route_face`: its
    ``face_ids[0]``, else ``face_id``, else the chip's face), switched by every waypoint whose ``params.face_id`` names
    another face, from that waypoint on (KQC ``WaveguideComposite``)."""
    route = design.routes.get(name)
    poly = built.get("polyline") or []
    face = _route_face(design, name, plan)
    faces = [face] * max(len(poly) - 1, 0)
    if route is None:
        return faces
    for node, index in zip(route.nodes, built.get("waypoint_index") or []):
        params = getattr(node, "params", None) or {}
        if "face_id" in params:
            for k in range(index, len(faces)):
                faces[k] = str(params["face_id"])
    return faces


# Layers of a KQC face (``kqcircuits.defaults.default_faces[face]``) that say nothing about where a part has metal or
# etch: avoidance (KQC's ``protect_opposite_face`` draws it on the opposite face) and port texts.
_NEUTRAL_LAYERS = frozenset({"ground_grid_avoidance", "ports"})
# Layers of a part that goes through the substrate (a TSV) or between two chips (an indium bump on its UBM).
_THROUGH_LAYERS = frozenset({"through_silicon_via", "through_silicon_via_avoidance", "indium_bump",
                             "underbump_metallization"})
_FOOTPRINT_LAYERS = ("through_silicon_via", "indium_bump", "underbump_metallization")


class _InstanceFaces:
    """The chip faces each component of a build draws on, read from its built cell: a face counts when the cell has
    shapes on one of that face's layers in ``default_faces`` (avoidance and port texts left out). Components
    without such shapes (a static cell on fab layers) have unknown faces (``None``): they meet every face, as before.

    A *through* part draws only TSV, bump and UBM layers: a TSV (both faces of one chip) or a bump (``1t1`` and
    ``2b1``). It sits under or on another component's metal on purpose; it overlaps that component only where its via
    or bump lands on the component's etch."""

    def __init__(self, result):
        from kqcircuits.defaults import default_faces  # pylint: disable=import-outside-toplevel

        self.layout = result.layout
        self.default_faces = default_faces
        by_info = {  # (layer, datatype) → (face, layer name); a face dict also holds its own name under "id"
            (info.layer, info.datatype): (f, key)
            for f, d in default_faces.items()
            for key, info in d.items()
            if hasattr(info, "datatype")
        }
        self.layer_faces = {}  # layer index → (face, layer name)
        for li in self.layout.layer_indexes():
            info = self.layout.get_info(li)
            if (info.layer, info.datatype) in by_info:
                self.layer_faces[li] = by_info[(info.layer, info.datatype)]
        names = result.design.instances
        self.insts = {i.property("id"): i for i in result.cell.each_inst() if i.property("id") in names}
        self._drawn: dict[int, dict[str, set]] = {}
        self._regions: dict[tuple, object] = {}

    def drawn(self, name: str) -> dict[str, set]:
        """``{face: names of the layers the component draws on there}`` (neutral layers left out)."""
        inst = self.insts.get(name)
        if inst is None:
            return {}
        if inst.cell_index not in self._drawn:
            cell = self.layout.cell(inst.cell_index)
            out: dict[str, set] = {}
            for li, (f, key) in self.layer_faces.items():
                if key not in _NEUTRAL_LAYERS and not cell.bbox_per_layer(li).empty():
                    out.setdefault(f, set()).add(key)
            self._drawn[inst.cell_index] = out
        return self._drawn[inst.cell_index]

    def faces(self, name: str) -> frozenset | None:
        """The faces the component draws on, or None when it draws on none of KQC's face layers."""
        return frozenset(self.drawn(name)) or None

    def through(self, name: str) -> bool:
        drawn = self.drawn(name)
        return bool(drawn) and all(keys <= _THROUGH_LAYERS for keys in drawn.values())

    def region(self, name: str, face: str, keys) -> object:
        """The component's shapes on ``face`` on the layers ``keys`` (chip coordinates, merged)."""
        from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

        cache = (name, face, tuple(keys))
        if cache not in self._regions:
            inst, region = self.insts[name], pya.Region()
            for key in keys:
                info = self.default_faces.get(face, {}).get(key)
                li = self.layout.find_layer(info) if info is not None else None
                if li is not None:
                    region += pya.Region(self.layout.cell(inst.cell_index).begin_shapes_rec(li))
            self._regions[cache] = region.transformed(inst.cplx_trans).merged()
        return self._regions[cache]

    def overlap(self, a: str, b: str) -> tuple[bool, str | None]:
        """Whether two components whose boxes overlap are on top of each other: ``(flag, face)``. They are when they
        draw on a common face (or a face is unknown), except a through part on another component: that one only where
        its via or bump touches the other's etch (``face`` names where)."""
        fa, fb = self.faces(a), self.faces(b)
        common = fa & fb if fa is not None and fb is not None else None
        if common is not None and not common:
            return False, None  # one draws only on faces the other does not use (e.g. the two pads of a TSV)
        ta, tb = (self.through(a), self.through(b)) if common is not None else (False, False)
        if ta == tb:
            return True, None
        part, other = (a, b) if ta else (b, a)
        for f in sorted(common):
            hit = self.region(part, f, _FOOTPRINT_LAYERS) & self.region(other, f, ("base_metal_gap_wo_grid",))
            if not hit.is_empty():
                return True, f
        return False, None


def _route_overlaps(result) -> list[DrcIssue]:
    """Built-geometry check between routes (the ``crossing`` rule sees only sharp node polylines, not meanders).

    Per face, each route's centre conductor (``*_waveguide_path``) and gap etch (``*_base_metal_gap_wo_grid``) as
    built. Pairs that share a port, or where one hangs off the other, legitimately meet and are skipped. Two routes
    that end on one component at different ports (two resonators on one coupler, a bus and a readout on one qubit)
    are checked everywhere except around that component (:func:`_shared_keepout`), where their ports put them side
    by side; two routes from different chip launchers are checked everywhere.
    """
    from kqcircuits.defaults import default_layers  # pylint: disable=import-outside-toplevel
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.design.schema import HangerEnd  # pylint: disable=import-outside-toplevel

    design, layout = result.design, result.layout
    faces = sorted({k.split("_", 1)[0] for k in default_layers if k.endswith("_waveguide_path")})
    layers = {
        f: (
            layout.layer(default_layers[f"{f}_waveguide_path"]),
            layout.layer(default_layers[f"{f}_base_metal_gap_wo_grid"]),
        )
        for f in faces
        if f"{f}_base_metal_gap_wo_grid" in default_layers
    }
    pad_layers = {
        f: layout.layer(default_layers[f"{f}_airbridge_pads"])
        for f in layers
        if f"{f}_airbridge_pads" in default_layers
    }
    built: dict[str, dict[str, tuple]] = {}
    pads: dict[str, dict[str, object]] = {}
    for inst in result.cell.each_inst():
        name = inst.property("id")
        if name not in design.routes:
            continue
        cell = layout.cell(inst.cell_index)
        for f, (path_l, gap_l) in layers.items():
            path = pya.Region(cell.begin_shapes_rec(path_l)).transformed(inst.cplx_trans).merged()
            gap = pya.Region(cell.begin_shapes_rec(gap_l)).transformed(inst.cplx_trans).merged()
            if not path.is_empty() or not gap.is_empty():
                built.setdefault(name, {})[f] = (path, gap)
            if f in pad_layers:
                pad = pya.Region(cell.begin_shapes_rec(pad_layers[f])).transformed(inst.cplx_trans).merged()
                if not pad.is_empty():
                    pads.setdefault(name, {})[f] = pad
    ends, hosts, own = {}, {}, {}
    for name, route in design.routes.items():
        own[name] = {e for e in (route.from_, route.to) if isinstance(e, str)}  # the ports it ends on
        ends[name] = {e.split(".", 1)[0] for e in own[name]}
        hosts[name] = {e.hanger for e in (route.from_, route.to) if isinstance(e, HangerEnd)}
    keepout = _shared_keepout(result, ends)
    out = []
    names = sorted(built)
    for a, by_face in sorted(pads.items()):  # airbridges of route a landing on another route b
        for b in names:
            if b == a or own[a] & own[b]:
                continue
            near = keepout(a, b)
            for f, pad in by_face.items():
                if f not in built[b]:
                    continue
                path_b, gap_b = built[b][f]
                hit = pad & (path_b + gap_b)
                if near is not None:
                    hit -= near
                if not hit.is_empty():
                    c = hit.bbox().center().to_dtype(layout.dbu)
                    out.append(
                        DrcIssue(
                            "error",
                            "airbridge_short",
                            f"an airbridge pad of route {a} lands on route {b} ({f})",
                            [(c.x, c.y)],
                            [a, b],
                        )
                    )
                    break
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if own[a] & own[b] or b in hosts[a] or a in hosts[b]:
                continue
            near = keepout(a, b)
            for f in sorted(set(built[a]) & set(built[b])):
                (pa, ga), (pb, gb) = built[a][f], built[b][f]
                if near is not None:  # side by side at their common component: only what lies beyond it
                    pa, ga, pb, gb = pa - near, ga - near, pb - near, gb - near
                hit = pa & pb
                if not hit.is_empty():
                    c = hit.bbox().center().to_dtype(layout.dbu)
                    out.append(
                        DrcIssue("error", "route_overlap", f"routes {a} and {b} overlap ({f})", [(c.x, c.y)], [a, b])
                    )
                    break
                touch = ga.interacting(gb)
                if not touch.is_empty():
                    c = (
                        (ga & gb).bbox().center().to_dtype(layout.dbu)
                        if not (ga & gb).is_empty()
                        else touch.bbox().center().to_dtype(layout.dbu)
                    )
                    out.append(
                        DrcIssue(
                            "warning",
                            "route_clearance",
                            f"routes {a} and {b} have no ground between their gaps ({f})",
                            [(c.x, c.y)],
                            [a, b],
                        )
                    )
                    break
    out += _route_self_overlaps(result, layers)
    out += _routes_over_components(result, layers, built, ends)
    return out


def _shared_keepout(result, ends: dict):
    """``keepout(a, b)``: for two routes that end on a common component (at different ports), that component's box
    grown by the wider route's half width (``a/2 + b``, its nodes' tapers included), where the two leave their ports
    side by side and may meet; None when they share no component (a chip launcher is no component: two launcher
    routes are compared everywhere)."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    design, layout = result.design, result.layout
    boxes = {i.property("id"): i.bbox() for i in result.cell.each_inst() if i.property("id") in design.instances}

    def half(name: str) -> float:
        planned = result.plan.routes.get(name)
        params = (planned.params or {}) if planned is not None else {}
        a, b = [float(params.get("a", 10.0))], [float(params.get("b", 6.0))]
        for node in getattr(design.routes.get(name), "nodes", None) or []:
            a += [float(node.a)] if getattr(node, "a", None) else []
            b += [float(node.b)] if getattr(node, "b", None) else []
        return max(a) / 2 + max(b)

    def keepout(a: str, b: str):
        shared = sorted((ends.get(a, set()) & ends.get(b, set())) & set(boxes))
        if not shared:
            return None
        grow = int(round(max(half(a), half(b)) / layout.dbu))
        region = pya.Region()
        for n in shared:
            region.insert(boxes[n].enlarged(grow, grow))
        return region

    return keepout


def _route_width_um(result, name: str) -> float:
    """The narrowest centre conductor ``a`` (µm) of a built route: its own ``a`` and any node's taper ``a``."""
    widths = [float(result.plan.routes[name].params.get("a", 10.0))] if name in result.plan.routes else [10.0]
    for node in getattr(result.design.routes[name], "nodes", None) or []:
        if getattr(node, "a", None):
            widths.append(float(node.a))
    return min(widths)


def _route_self_overlaps(result, layers: dict) -> list[DrcIssue]:
    """``route_self_overlap``: a route whose built centre conductor runs over itself: its nodes loop back across an
    earlier straight, or a meander's turns land on another part of the same route. The pieces of a route
    (straights, arcs, meander turns) meet edge to edge; where two of them share area, that area is the route lying on
    itself when it is at least half a conductor width squared (two crossing parts share a full a², a bend tighter than
    a/2 folds its inner edge over by less than (a/2)², which is not flagged). Taper pieces are left out: KQC draws a
    taper's centre-line shape over the straight that follows it."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    design, layout = result.design, result.layout
    dbu2 = layout.dbu * layout.dbu
    out = []
    for inst in result.cell.each_inst():
        name = inst.property("id")
        if name not in design.routes:
            continue
        least = _route_width_um(result, name) ** 2 / 2
        for f, (path_l, _gap_l) in layers.items():
            pieces = pya.Region()
            it = layout.cell(inst.cell_index).begin_shapes_rec(path_l)
            while not it.at_end():
                shape = it.shape()
                if (shape.is_polygon() or shape.is_path() or shape.is_box()) and "taper" not in it.cell().name.lower():
                    pieces.insert(shape.polygon.transformed(it.trans()))
                it.next()
            if pieces.count() < 2:
                continue
            twice = pieces.merged(False, 2)  # covered by two pieces or more (wrap count ≥ 2)
            hits = [poly for poly in twice.each() if poly.area() * dbu2 >= least]
            if hits:
                area = sum(poly.area() for poly in hits) * dbu2
                c = hits[0].transformed(inst.cplx_trans).bbox().center().to_dtype(layout.dbu)
                out.append(DrcIssue("error", "route_self_overlap",
                                    f"route {name} runs over itself ({area:.0f} µm² of its centre conductor lie on "
                                    f"another part of it, {len(hits)} place(s), {f}): move its nodes or meander",
                                    [(c.x, c.y)], [name]))
                break
    return out


def _routes_over_components(result, layers: dict, built: dict, ends: dict) -> list[DrcIssue]:
    """``route_over_component``: a route's conductor or gap overlaps the etch (gaps, pocket) of a component that is not
    one of its ends: the route runs across that component (cuts into its pocket, shorts its island or pads)."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    design, layout = result.design, result.layout
    dbu2 = layout.dbu * layout.dbu
    comps = [(i.property("id"), i) for i in result.cell.each_inst() if i.property("id") in design.instances]
    etch: dict = {}
    out = []
    for name in sorted(built):
        for f, (path, gap) in built[name].items():
            geo = path + gap
            box = geo.bbox()
            hit_any = False
            for cname, inst in comps:
                if cname in ends.get(name, ()) or not inst.bbox().overlaps(box):
                    continue
                key = (cname, f)
                if key not in etch:
                    etch[key] = pya.Region(layout.cell(inst.cell_index).begin_shapes_rec(layers[f][1])).transformed(
                        inst.cplx_trans).merged()
                hit = geo & etch[key]
                if hit.area() * dbu2 > 0.01:
                    c = hit.bbox().center().to_dtype(layout.dbu)
                    out.append(DrcIssue("error", "route_over_component",
                                        f"route {name} runs over {cname} ({design.instances[cname].cell}, {f}), "
                                        "which is not one of its ends", [(c.x, c.y)], [name, cname]))
                    hit_any = True
            if hit_any:
                break
    return out


def _conductor_opens(result, step: float = 1.0, on_faces=None) -> list[DrcIssue]:
    """Galvanic continuity where a route meets a component port (negative mask: metal = not etched).

    The point ``step`` µm inside the component and the point ``step`` µm along the route, both on the port's centre
    line, must lie in the same metal polygon. KQC's netlist extraction joins port *texts*, so it cannot see etch that
    separates two touching ports. Ports without a direction (junction ends), chip launchers and points that are not
    metal inside the component (nothing to judge) are skipped.

    Each end is judged on the face it is drawn on: the route's start face for ``from``, its face after the last
    ``face_id`` waypoint for ``to`` (:func:`_route_face`, :func:`_route_end_face`), with that face's
    ``base_metal_gap_wo_grid`` etch. A route end on a face its component draws nothing on (a backside route ending on
    a front-face pad) is an open as well.
    """
    from kqcircuits.defaults import default_faces  # pylint: disable=import-outside-toplevel
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    design, layout = result.design, result.layout
    dbu = layout.dbu
    gaps: dict[str, object] = {}

    def gap_on(face: str):
        if face not in gaps:  # one face's etch (1t1: 130/1), read only for the faces some route end is on
            info = default_faces.get(face, {}).get("base_metal_gap_wo_grid")
            li = layout.find_layer(info) if info is not None else None
            gaps[face] = pya.Region(result.cell.begin_shapes_rec(li)) if li is not None else pya.Region()
        return gaps[face]

    on_faces = on_faces or _InstanceFaces(result)
    ports = result.plan.all_ports()
    out = []
    for rname, route in design.routes.items():
        if rname in result.plan.failed:
            continue
        for end, face in ((route.from_, _route_face(design, rname, result.plan)),
                          (route.to, _route_end_face(design, rname, result.plan))):
            if not isinstance(end, str) or end.split(".", 1)[0] == "chip":
                continue
            p = ports.get(end)
            if p is None or p.dir is None:
                continue
            drawn = on_faces.faces(end.split(".", 1)[0])
            if drawn is not None and face not in drawn:
                out.append(
                    DrcIssue(
                        "error",
                        "open_conductor",
                        f"route {rname} is galvanically open at {end} (the route end is on {face}, the component "
                        f"draws only on {', '.join(sorted(drawn))})",
                        [(p.pos.x, p.pos.y)],
                        [end, rname],
                    )
                )
                continue
            gap = gap_on(face)
            half = (p.a or 10.0) / 2 + (p.b or 6.0) + 5 * step
            window = pya.DBox(p.pos.x - half, p.pos.y - half, p.pos.x + half, p.pos.y + half).to_itype(dbu)
            metal = (pya.Region(window) - (gap & pya.Region(window))).merged()

            def polygon_at(pt, metal=metal):
                ip = pt.to_itype(dbu)
                return next((i for i, poly in enumerate(metal.each()) if poly.inside(ip)), None)

            inside, along = polygon_at(p.pos - p.dir * step), polygon_at(p.pos + p.dir * step)
            if inside is not None and along != inside:
                out.append(
                    DrcIssue(
                        "error",
                        "open_conductor",
                        f"route {rname} is galvanically open at {end} (etch between the port and the route)",
                        [(p.pos.x, p.pos.y)],
                        [end, rname],
                    )
                )
    return out


def device_id_block(result):
    """Where the chip put its device ID (``qcc_device_id_p1/p2`` refpoints, µm), or None (no frame / older build)."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    refp = getattr(result, "refpoints", None) or {}
    if "qcc_device_id_none" in refp:
        return False  # the chip has no device ID (optional, no room): nothing to keep free
    p1, p2 = refp.get("qcc_device_id_p1"), refp.get("qcc_device_id_p2")
    return pya.DBox(p1, p2) if p1 is not None and p2 is not None else None


def _frame_issues(design, boxes: dict, routes: dict, device_id=None) -> list[DrcIssue]:
    """PDK die frame: components inside the design area, clear of the marker areas and the device-ID block."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.assembly.plan import die_frame  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.chips.frame import design_area, keepouts  # pylint: disable=C0415

    frame = die_frame(design)
    if frame is None:
        return []
    chip = pya.DBox(*design.chip.box)
    area, reserved = design_area(chip, frame), keepouts(chip, frame, device_id)
    out = []
    for name, b in boxes.items():
        box = pya.DBox(*b)
        edge_ok = _edge_component(design.instances[name].cell) if name in design.instances else False
        if not edge_ok and (not area.contains(box.p1) or not area.contains(box.p2)):
            out.append(
                DrcIssue(
                    "warning",
                    "frame_margin",
                    f"{name} reaches into the {frame.margin:g} µm die margin (dicing markers)",
                    [(box.center().x, box.center().y)],
                    [name],
                )
            )
        for key, k in reserved.items():
            if box.overlaps(k):
                out.append(
                    DrcIssue(
                        "warning", "frame_keepout", f"{name} overlaps the {key}", [(k.center().x, k.center().y)], [name]
                    )
                )
    for name, r in routes.items():
        pts = [pya.DPoint(*p) for p in r["polyline"]]
        for key, k in reserved.items():
            hit = next((p for p in pts if k.contains(p)), None)
            if hit is not None:
                out.append(
                    DrcIssue("warning", "frame_keepout", f"route {name} crosses the {key}", [(hit.x, hit.y)], [name])
                )
    return out
