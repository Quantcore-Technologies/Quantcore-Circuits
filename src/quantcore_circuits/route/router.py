"""Route specs → KQC ``WaveguideComposite`` node lists.

Routing policy (deliberately simple and predictable, everything else is KQC):

* A route leaves a port straight along the port's outward direction for one turn radius (the KQC ``port_*_corner``
  convention) and enters the destination port the same way.
* Between the two stubs it follows the user ``nodes``; without nodes it auto-routes Manhattan style
  (one elbow if possible, otherwise a Z through the midpoint), never doubling back on itself.
* A route between ports that face an angle (a StarQubit pin at 72° steps, a ConcentricTransmon coupler at 60°) may
  run one oblique straight instead of a Manhattan stair: straight from stub to stub when the two ports face each
  other along one line (within a few degrees), else with one bend where the two ports' axes meet (see
  :func:`_oblique`). Only where the bends fit; routes between axis-aligned ports are Manhattan as before.
* ``type="meander"`` keeps the path and inserts a KQC ``Meander`` on one straight segment so that the *total*
  route length equals ``length``. The correction uses KQC's ``Node(length_increment=...)`` and is verified by
  building the waveguide (two-step correction like ``WaveguideComposite.produce_fixed_length_waveguide``). A path
  that is already about the right length gets no meander, or its free corners' radius trimmed, never a flattened
  zigzag (:func:`fix_length`).
* ``airbridges="auto"`` puts ``n_bridges=-1`` on every straight segment (KQC spaces them by ``ab_to_ab_spacing``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from kqcircuits.elements.airbridge_connection import AirbridgeConnection
from kqcircuits.pya_resolver import pya
from kqcircuits.util.node import Node

from quantcore_circuits.design.schema import FreeEnd, Route
from quantcore_circuits.layouts.ports import Port, direction_vector

_EPS = 1e-6


class RoutingError(ValueError):
    pass


@dataclass
class RouteEnd:
    """Resolved route end: position, direction pointing from the end into the route, termination.

    For a port this is the port's outward direction (``corner - port``). A free end uses the same convention, so it
    behaves like a virtual port.
    """

    pos: pya.DPoint
    dir: pya.DVector | None
    a: float | None = None
    b: float | None = None
    term: float | None = None  # None for ports (no termination), else KQC term1/term2
    # fixed points the route passes through right before ``pos`` (in travel order), e.g. a hanger coupler
    approach: list = field(default_factory=list)

    @classmethod
    def from_port(cls, port: Port) -> RouteEnd:
        return cls(port.pos, port.dir, port.a, port.b)

    @classmethod
    def from_free(cls, end: FreeEnd) -> RouteEnd:
        d = None if end.dir is None else direction_vector(end.dir)
        return cls(pya.DPoint(*end.at), d, term=end.term)


@dataclass
class RoutePlan:
    name: str
    nodes: list[Node]
    params: dict = field(default_factory=dict)  # WaveguideComposite params (a, b, r, term1, term2, ...)
    target_length: float | None = None
    length: float | None = None  # as built (filled in by the builder)
    fixed_segments: set = field(default_factory=set)  # segment indices that must not host a meander
    # ends at a placed cell's port, [{"inst", "node": 0 | -1}]: DesignChip closes a hairline to the cell's etch there
    # (route.waveguide.joined_nodes)
    joins: list = field(default_factory=list)

    def node_strings(self) -> list[str]:
        """The KQC nodes the route cell is built from (:func:`kqc_nodes`: a taper that ends at its waypoint starts
        ``taper_length`` before it); :meth:`polyline` keeps the waypoints where the design puts them."""
        return [str(n) for n in kqc_nodes(self.nodes)]

    def polyline(self) -> list[pya.DPoint]:
        return [n.position for n in self.nodes]


def _is_axis(v: pya.DVector) -> bool:
    return abs(v.x) < _EPS or abs(v.y) < _EPS


def _dedupe(points: list[pya.DPoint]) -> list[pya.DPoint]:
    """Drop repeated points. Collinear points are kept on purpose: port stubs stay separate segments, so a meander
    never starts right at a port and segment indices stay predictable."""
    out = []
    for p in points:
        if not out or (p - out[-1]).length() > _EPS:
            out.append(p)
    return out


def _on_axis(origin: pya.DPoint, direction: pya.DVector, p: pya.DPoint) -> bool:
    """True if ``p`` lies on the ray from ``origin`` along ``direction``."""
    v = p - origin
    return v.length() > _EPS and abs(v.x * direction.y - v.y * direction.x) < _EPS and v.sprod(direction) > 0


def _reverses(points: list[pya.DPoint]) -> bool:
    """True if the polyline doubles back (≈180° turn) anywhere."""
    for i in range(1, len(points) - 1):
        v1, v2 = points[i] - points[i - 1], points[i + 1] - points[i]
        if v1.length() < _EPS or v2.length() < _EPS:
            continue
        if v1.sprod(v2) < -0.999 * v1.length() * v2.length():
            return True
    return False


def merge_collinear(points: list[pya.DPoint], angle_tol: float = 1e-6) -> list[pya.DPoint]:
    """Drop interior points where the polyline goes straight on (no bend there): a straight leg split into pieces
    must not be checked piece by piece."""
    out = list(points[:1])
    for i in range(1, len(points) - 1):
        v1, v2 = points[i] - out[-1], points[i + 1] - points[i]
        if v1.length() < _EPS or v2.length() < _EPS:
            continue
        if abs(v1.vprod(v2)) <= angle_tol * v1.length() * v2.length() and v1.sprod(v2) > 0:
            continue
        out.append(points[i])
    out += points[-1:] if len(points) > 1 else []
    return out


def _key(p: pya.DPoint) -> tuple[float, float]:
    return (round(p.x, 6), round(p.y, 6))


def corner_violations(
    points: list[pya.DPoint], r: float, tol: float = 1e-3, radii: dict | None = None
) -> list[tuple[int, float, float]]:
    """Segments too short for their bends: (segment index, length, required).

    A bend of angle θ with radius ``r`` uses ``r·tan(θ/2)`` of each adjacent straight segment (KQC
    ``WaveguideCoplanar`` corner model). ``radii`` maps corner positions (``(x, y)`` rounded to 1e-6 µm) to their own
    radius (``Waypoint.r``); every other corner uses ``r``. Call it on :func:`merge_collinear` points (the router
    does): indices refer to the list passed in.
    """
    radii = radii or {}

    def cut(i):  # length used by the bend at interior point i
        if i <= 0 or i >= len(points) - 1:
            return 0.0
        v1, v2 = points[i] - points[i - 1], points[i + 1] - points[i]
        if v1.length() < _EPS or v2.length() < _EPS:
            return 0.0
        cos = max(-1.0, min(1.0, v1.sprod(v2) / (v1.length() * v2.length())))
        theta = math.acos(cos)
        rad = radii.get(_key(points[i]), r)
        return rad * math.tan(theta / 2) if theta < math.pi - 1e-9 else float("inf")

    out = []
    for i in range(len(points) - 1):
        need = cut(i) + cut(i + 1)
        length = (points[i + 1] - points[i]).length()
        if length + tol < need:
            out.append((i + 1, length, need))
    return out


def _manhattan(
    p0: pya.DPoint,
    d0: pya.DVector | None,
    p1: pya.DPoint,
    d1: pya.DVector | None,
    r: float = 0.0,
    prefix: list | None = None,
    suffix: list | None = None,
    radii: dict | None = None,
) -> list[pya.DPoint]:
    """Intermediate points between stub ends p0 and p1.

    ``d0`` is the travel direction arriving at p0, ``d1`` the travel direction leaving p1 (towards the route end).
    Candidates that double back are rejected; among the rest the first whose bends fit (radius ``r``, checked on the
    full path ``prefix + [p0, ..., p1] + suffix``) wins.
    """
    v = p1 - p0
    if v.length() < _EPS or abs(v.x) < _EPS or abs(v.y) < _EPS:
        candidates = [[]]
    else:
        mid = p0 + v * 0.5
        candidates = [
            [pya.DPoint(p1.x, p0.y)],
            [pya.DPoint(p0.x, p1.y)],
            [pya.DPoint(mid.x, p0.y), pya.DPoint(mid.x, p1.y)],
            [pya.DPoint(p0.x, mid.y), pya.DPoint(p1.x, mid.y)],
        ]
        # prefer continuing straight out of the start port
        if d0 is not None and abs(d0.y) > abs(d0.x):
            candidates[0], candidates[1] = candidates[1], candidates[0]
            candidates[2], candidates[3] = candidates[3], candidates[2]
    pre = [] if d0 is None else [p0 - d0]  # point before p0, to test the turn at p0
    post = [] if d1 is None else [p1 + d1]  # point after p1, to test the turn at p1
    ok = [m for m in candidates if not _reverses(_dedupe(pre + [p0] + m + [p1] + post))]

    def fits(mids, merge=True):
        path = _dedupe(prefix + [p0] + mids + [p1] + (suffix or []))
        return prefix is None or not corner_violations(merge_collinear(path) if merge else path, r, radii=radii)

    for mids in ok:
        if fits(mids):
            return mids
    if prefix is not None and r > 0:
        # none of the one- and two-corner paths fits its bends (e.g. a port facing sideways under a hanger coupler
        # that starts less than 2r beside it): detour paths with three corners, the shortest that fits. Only reached
        # where the paths above all fail, so routes that built before keep their geometry.
        best = None
        for mids in _detours(p0, p1, r):
            path = _dedupe(pre + [p0] + mids + [p1] + post)
            # KQC checks each node pair: a corner closer than r to the stub's (collinear) end node does not fit either
            if _reverses(path) or not fits(mids) or not fits(mids, merge=False):
                continue
            length = sum((q - p).length() for p, q in zip(path[:-1], path[1:]))
            if best is None or length < best[0] - 1e-9:
                best = (length, mids)
        if best is not None:
            return best[1]
    return ok[0] if ok else candidates[0]


_ALIGN_TOL = math.radians(5.0)  # an oblique stub-to-stub straight may turn this much at each stub end


def _turn(d_from: pya.DVector, d_to: pya.DVector) -> float:
    """Angle (rad) between two travel directions."""
    c = d_from.sprod(d_to) / (d_from.length() * d_to.length())
    return math.acos(max(-1.0, min(1.0, c)))


def _oblique(
    p0: pya.DPoint,
    d0: pya.DVector | None,
    p1: pya.DPoint,
    d1: pya.DVector | None,
    r: float,
    prefix: list,
    suffix: list,
    radii: dict | None,
) -> list[pya.DPoint] | None:
    """Oblique alternative to the Manhattan stair between stub ends p0 and p1 (``d0`` the travel direction arriving at
    p0, ``d1`` leaving p1), or None. Only for ports that face an angle (some direction is off-axis); the candidates,
    first that fits its bends and does not double back wins:

    1. one straight p0 → p1 (no corner), when it leaves p0 and reaches p1 within ``_ALIGN_TOL`` of both directions:
       two ports facing each other along one line (exactly, or a few µm off);
    2. one corner where the line through p0 along ``d0`` meets the line through p1 along ``d1`` (ahead of p0, behind
       p1), turning by at most 90°: an angled port whose ray meets the other end's axis.
    """
    if (d0 is None or _is_axis(d0)) and (d1 is None or _is_axis(d1)):
        return None
    v = p1 - p0
    if v.length() < _EPS:
        return None
    cands = []
    ends = [d for d in (d0, d1) if d is not None]
    if ends and all(_turn(d, v) <= _ALIGN_TOL for d in ends):
        cands.append([])
    if d0 is not None and d1 is not None:
        den = d0.vprod(d1)
        if abs(den) > 1e-3 and _turn(d0, d1) <= math.pi / 2 + 1e-6:  # not (nearly) parallel, no hairpin
            t = v.vprod(d1) / den
            u = d0.vprod(v) / den
            if t > _EPS and u > _EPS:
                cands.append([p0 + d0 * t])
    pre = [] if d0 is None else [p0 - d0]
    post = [] if d1 is None else [p1 + d1]
    for mids in cands:
        full = _dedupe(prefix + [p0] + mids + [p1] + suffix)
        if _reverses(_dedupe(pre + [p0] + mids + [p1] + post)):
            continue
        if not corner_violations(merge_collinear(full), r, radii=radii) and not corner_violations(full, r, radii=radii):
            return mids
    return None


def _detours(p0: pya.DPoint, p1: pya.DPoint, r: float) -> list[list[pya.DPoint]]:
    """Three-corner Manhattan paths p0 → p1 (x, y, x or y, x, y legs) through coordinates beside both ends: their
    own, the middle, and 2r / 3r beyond either end on both sides."""
    offsets = (0.0, -2 * r, 2 * r, -3 * r, 3 * r)
    xs = sorted({round(c + o, 6) for c in (p0.x, p1.x) for o in offsets} | {round((p0.x + p1.x) / 2, 6)})
    ys = sorted({round(c + o, 6) for c in (p0.y, p1.y) for o in offsets} | {round((p0.y + p1.y) / 2, 6)})
    out = []
    for x in xs:
        for y in ys:
            out.append([pya.DPoint(x, p0.y), pya.DPoint(x, y), pya.DPoint(p1.x, y)])  # horizontal first
            out.append([pya.DPoint(p0.x, y), pya.DPoint(x, y), pya.DPoint(x, p1.y)])  # vertical first
    return out


def _unit(v: pya.DVector) -> pya.DVector | None:
    return v / v.length() if v.length() > _EPS else None


def _enter_straight(pts_start, middle, pts_end, d_start, e_in, r, radii) -> list | None:
    """``middle`` (the user's nodes) with Manhattan corners added between the start stub and the first node and / or
    between the last node and the end stub (a port's, or a hanger coupler's approach), so both stubs are entered
    along their axis; the first variant whose bends fit, or None."""
    variants = []
    if len(pts_end) > 1:  # the end has a stub / approach: corners from the last node into it
        p0, p1 = middle[-1], pts_end[0]
        d0 = _unit(middle[-1] - middle[-2]) if len(middle) > 1 else _unit(middle[-1] - pts_start[-1])
        tail = _manhattan(p0, d0, p1, e_in, r, pts_start + middle[:-1], pts_end[1:], radii)
        variants.append(middle + tail)
    if len(pts_start) > 1:  # the start has a stub: corners from it into the first node
        p0, p1 = pts_start[-1], middle[0]
        d1 = _unit(middle[1] - middle[0]) if len(middle) > 1 else _unit(pts_end[0] - middle[0])
        head = _manhattan(p0, d_start, p1, d1, r, pts_start[:-1], middle[1:] + pts_end, radii)
        variants.append(head + middle)
        if len(variants) == 2:
            variants.append(head + variants[0])
    for v in variants:
        pts = merge_collinear(_dedupe(pts_start + v + pts_end))
        if not corner_violations(pts, r, radii=radii) and not corner_violations(
                _dedupe(pts_start + v + pts_end), r, radii=radii):
            return v
    return None


def plan_route(
    name: str,
    route: Route,
    start: RouteEnd,
    end: RouteEnd,
    defaults: dict,
) -> RoutePlan:
    """Build the node list for one route. ``defaults`` supplies ``a``, ``b``, ``r`` when neither route nor port does."""
    a = route.a if route.a is not None else (start.a if start.a is not None else end.a)
    b = route.b if route.b is not None else (start.b if start.b is not None else end.b)
    a = defaults["a"] if a is None else a
    b = defaults["b"] if b is None else b
    r = route.r if route.r is not None else defaults["r"]

    # stub points: leave/enter ports straight for one turn radius
    pts_start = [start.pos]
    s0 = start.pos
    if start.dir is not None:
        s0 = start.pos + start.dir * r
        pts_start.append(s0)
    if end.approach:
        pts_end = list(end.approach) + [end.pos]
        e0 = pts_end[0]
        v = pts_end[1] - pts_end[0]
        e_in = v / v.length()
    else:
        pts_end = [end.pos]
        e0, e_in = end.pos, None
        if end.dir is not None:
            e0 = end.pos + end.dir * r
            pts_end.insert(0, e0)
            e_in = -end.dir

    waypoints = route.waypoints()
    oblique = False  # auto-routed with an oblique straight (an angled port)
    # per-corner radii (Waypoint.r): bend-fit checks use each corner's own radius
    radii = {(round(w.at[0], 6), round(w.at[1], 6)): float(w.r) for w in waypoints if w.r is not None}
    if waypoints:
        middle = [pya.DPoint(*w.at) for w in waypoints]
        # a waypoint straight in front of a port, closer than the stub, already is that port's stub; further away
        # the stub stays a separate (fixed) segment, so the rest of that straight can still host a meander
        if start.dir is not None and _on_axis(start.pos, start.dir, middle[0]):
            if (middle[0] - start.pos).length() <= r + _EPS:
                pts_start = [start.pos]
        if not end.approach and end.dir is not None and _on_axis(end.pos, end.dir, middle[-1]):
            if (middle[-1] - end.pos).length() <= r + _EPS:
                pts_end = [end.pos]
    else:
        middle = _oblique(s0, start.dir, e0, e_in, r, pts_start[:-1], pts_end[1:], radii)
        oblique = middle is not None
        if middle is None:
            middle = _manhattan(s0, start.dir, e0, e_in, r, pts_start[:-1], pts_end[1:], radii)

    raw = pts_start + middle + pts_end
    points = _dedupe(raw)
    if len(points) < 2:
        raise RoutingError(f"route {name}: start and end coincide")
    merged = merge_collinear(points)
    bad = corner_violations(merged, r, radii=radii)
    ends = {_key(q) for q in pts_start + pts_end}
    if bad and waypoints and any(_key(merged[i - 1]) in ends or _key(merged[i]) in ends for i, _, _ in bad):
        # the user's first / last node is off the axis of a port stub or a hanger coupler's approach (whose short
        # straight has room for one bend only): add the corners that enter it straight. Only where the nodes as
        # given do not fit, so routes that built before keep their geometry.
        fixed_up = _enter_straight(pts_start, middle, pts_end, start.dir, e_in, r, radii)
        if fixed_up is not None:
            middle = fixed_up
            raw = pts_start + middle + pts_end
            points = _dedupe(raw)
            merged = merge_collinear(points)
            bad = corner_violations(merged, r, radii=radii)
    if bad:
        i, length, need = bad[0]
        own = [f"{radii[_key(q)]:g}" for q in (merged[i - 1], merged[i]) if _key(q) in radii]
        at_r = f"r={r:g} µm" + (f" (corner r {', '.join(own)} µm)" if own else "")
        raise RoutingError(
            f"route {name}: segment {i} ({merged[i - 1].x:.1f},{merged[i - 1].y:.1f})→({merged[i].x:.1f},"
            f"{merged[i].y:.1f}) is {length:.1f} µm but its bends need {need:.1f} µm at {at_r}; "
            "move the ports, add 'nodes' or reduce 'r'"
        )
    if not waypoints and not oblique:
        # a port facing at an angle (ConcentricTransmon couplers, StarQubit pins) leaves along its own direction for
        # its stub; the Manhattan path starts at the stub's end, the bend there takes r·tan(θ/2) (checked above)
        stubs = {(_key(start.pos), _key(s0))}
        if not end.approach and end.dir is not None:
            stubs.add((_key(e0), _key(end.pos)))
        for p, q in zip(points[:-1], points[1:]):
            if not _is_axis(q - p) and (_key(p), _key(q)) not in stubs:
                raise RoutingError(f"route {name}: could not auto-route Manhattan path; add 'nodes'")

    # attach waypoint extras to the matching node positions
    extras = {}
    for w in waypoints:
        key = (round(w.at[0], 6), round(w.at[1], 6))
        node_params = dict(w.params)
        if w.a is not None:
            node_params["a"] = w.a
        if w.b is not None:
            node_params["b"] = w.b
        if w.r is not None and abs(float(w.r) - r) > _EPS:  # this corner only (route.waveguide.CORNER_R)
            node_params["corner_r"] = float(w.r)
        extras[key] = (w.airbridge, node_params)

    nodes = []
    for i, p in enumerate(points):
        airbridge, node_params = extras.get((round(p.x, 6), round(p.y, 6)), (False, {}))
        if route.airbridges == "auto" and i > 0:
            node_params.setdefault("n_bridges", -1)
        elif isinstance(route.airbridges, int) and not isinstance(route.airbridges, bool) and i > 0:
            node_params.setdefault("n_bridges", route.airbridges)
        element = AirbridgeConnection if airbridge else None
        nodes.append(Node(p, element, **node_params))

    params = {"a": a, "b": b, "r": r, **route.params}
    if start.term is not None:
        params["term1"] = start.term
    if end.term is not None:
        params["term2"] = end.term
    # segments (by index of their end node) that must stay straight: port stubs and hanger couplers
    fixed = set()
    if start.dir is not None and len(points) > 2:
        fixed.add(1)
    n_end_fixed = len(end.approach) if end.approach else (1 if end.dir is not None else 0)
    fixed.update(range(len(points) - n_end_fixed, len(points)))
    plan = RoutePlan(name, nodes, params, route.length if route.type == "meander" else None)
    plan.fixed_segments = fixed
    return plan


def _kqc_taper_length() -> float:
    from kqcircuits.elements.waveguide_composite import WaveguideComposite  # pylint: disable=import-outside-toplevel

    return float(WaveguideComposite.get_schema()["taper_length"].default)


def _bend_cut(nodes: list[Node], i: int, r: float) -> float:
    """Length of the straight used by the bend at node ``i`` (0 at the route's ends and on collinear nodes)."""
    if i <= 0 or i >= len(nodes) - 1:
        return 0.0
    v1, v2 = nodes[i].position - nodes[i - 1].position, nodes[i + 1].position - nodes[i].position
    if v1.length() < _EPS or v2.length() < _EPS:
        return 0.0
    turn = math.atan2(v1.x * v2.y - v1.y * v2.x, v1.x * v2.x + v1.y * v2.y)
    return float(nodes[i].params.get("corner_r", r)) * math.tan(abs(turn) / 2)


TAPER_END = "taper_end"  # node parameter (Quantcore only, never passed to KQC): the taper of this node ends here, µm


def kqc_nodes(nodes: list[Node]) -> list[Node]:
    """The nodes KQC builds the route from: a node marked :data:`TAPER_END` (by :func:`fit_tapers`) is moved back
    along its incoming straight by its taper's length, so KQC's taper, which starts at the node, ends at the
    waypoint. Other nodes are returned as they are."""
    if not any(TAPER_END in (n.params or {}) for n in nodes):
        return list(nodes)
    out = []
    for i, n in enumerate(nodes):
        shift = (n.params or {}).get(TAPER_END)
        if shift is None or i == 0:
            out.append(n)
            continue
        v = n.position - nodes[i - 1].position
        params = {k: x for k, x in n.params.items() if k != TAPER_END}
        out.append(Node(n.position - v * (float(shift) / v.length()), n.element, n.inst_name, n.align, n.angle,
                        n.length_before, n.length_increment, n.meander_direction, **params))
    return out


def fit_tapers(plan: RoutePlan, measure) -> RoutePlan:
    """Tapers that end where the route can take them.

    A waypoint with its own ``a``/``b`` becomes a KQC ``WaveguideCoplanarTaper`` that *starts* at the node and runs
    ``taper_length`` forward. Where the straight after the node is shorter than that (a widening taper 51 µm before
    the route's end, say), KQC draws the taper past the next node and then runs the line back to it: the etch reaches
    beyond the route's end and the built length counts the overshoot twice (forward in the taper, back in the
    line). Such a node is marked :data:`TAPER_END`: the route cell is built with it ``taper_length`` further back
    along its incoming straight (:func:`kqc_nodes`), so the taper *ends* at the waypoint and the line after it keeps
    the new width up to the next node. The plan's nodes, polyline and waypoint indices stay where the design puts
    them (the plugin's route handles do not move).

    ``measure(plan) -> float`` builds the route and returns its length: a mark is kept only where it removes the
    whole double count (the length drops by twice the overshoot), i.e. where the straight before the node has room
    for the taper after whatever element ends there. Other routes, and routes whose tapers fit, are returned as
    they are."""
    nodes = list(plan.nodes)
    if len(nodes) < 3:
        return plan
    a, b = plan.params.get("a"), plan.params.get("b")
    r = float(plan.params.get("r", 100))
    default = float(plan.params.get("taper_length", _kqc_taper_length()))
    out, base = plan, None
    for i, n in enumerate(plan.nodes):
        p = n.params or {}
        new_a, new_b = p.get("a", a), p.get("b", b)
        taper = n.element is None and "face_id" not in p and (new_a != a or new_b != b)
        if "a" in p or "b" in p:  # KQC carries a node's width on to the rest of the route
            a, b = new_a, new_b
        if not taper or not 0 < i < len(nodes) - 1 or n.angle is not None:
            continue
        length = float(p.get("taper_length", default))
        after = (nodes[i + 1].position - n.position).length()
        v = n.position - nodes[i - 1].position
        if after + _EPS >= length or v.length() - _bend_cut(nodes, i - 1, r) <= length + _EPS:
            continue  # the taper fits after its node, or there is no room before it either
        marked = list(out.nodes)
        marked[i] = Node(n.position, n.element, n.inst_name, n.align, n.angle, n.length_before, n.length_increment,
                         n.meander_direction, **{**p, TAPER_END: length})
        trial = RoutePlan(out.name, marked, dict(out.params), out.target_length, None, set(out.fixed_segments))
        base = measure(out) if base is None else base
        got = measure(trial)
        if abs(base - got - 2 * (length - after)) < 1e-3:
            out, base = trial, got
    return out


def meander_segment_index(nodes: list[Node], preferred: int | None = None, fixed: set | None = None) -> int:
    """Index of the node *ending* the segment that hosts the meander (KQC puts length_* on that node)."""
    if preferred is not None:
        if not 1 <= preferred < len(nodes):
            raise RoutingError(f"meander_segment {preferred} out of range 1..{len(nodes) - 1}")
        return preferred
    candidates = [i for i in range(1, len(nodes)) if i not in (fixed or set())] or list(range(1, len(nodes)))
    return max(candidates, key=lambda i: (nodes[i].position - nodes[i - 1].position).length())


def meander_span(plan: RoutePlan, segment: int) -> float:
    """Length (µm) of the straight KQC lays a meander on for the segment ending at node ``segment``: the node-to-node
    distance less the bend cut at each end (KQC ``Meander`` start / end points)."""
    nodes = plan.nodes
    r = float(plan.params.get("r", 100))
    pts = [n.position for n in nodes]

    def cut(i):  # bend cut at interior node i (0 at the route's ends and on collinear nodes)
        if i <= 0 or i >= len(pts) - 1:
            return 0.0
        v1, v2 = pts[i] - pts[i - 1], pts[i + 1] - pts[i]
        if v1.length() < _EPS or v2.length() < _EPS:
            return 0.0
        turn = math.atan2(v1.x * v2.y - v1.y * v2.x, v1.x * v2.x + v1.y * v2.y)
        ri = float(nodes[i].params.get("corner_r", r))
        return ri * math.tan(abs(turn) / 2)

    taper = float(nodes[segment].params.get(TAPER_END, 0.0))  # a taper ending at the node takes the straight's end
    return (pts[segment] - pts[segment - 1]).length() - cut(segment - 1) - cut(segment) - taper


def max_meanders(span: float, r: float) -> int:
    """Most meander turns that stay on a straight of length ``span``: KQC puts the first bend ``r`` after the straight's
    start and each turn takes 2·r along it, so ``int(span / 2r - 1)`` (the count KQC itself picks when automatic).
    A larger count runs the first and last bends past the straight's ends (over whatever lies beyond the node)."""
    return int(span / (2 * r) - 1 + 1e-9)


def with_length_increment(
    plan: RoutePlan, increment: float, segment: int, meanders: int = -1, direction: int | None = None
) -> RoutePlan:
    """``plan`` with a meander of ``increment`` extra length on ``segment``; ``direction`` (1 / −1) picks the side of
    the meander's first turn (KQC ``Node.meander_direction``). A requested number of turns that does not fit on the
    straight is reduced to what fits (the meander gets wider instead, the length is the same)."""
    if meanders > 0:
        span, r = meander_span(plan, segment), float(plan.params.get("r", 100))
        fit = max_meanders(span, r)
        if 1 <= fit < meanders:
            import warnings  # pylint: disable=import-outside-toplevel

            # say so: the meander's shape changes (fewer, taller turns) where the design asked for more
            warnings.warn(f"route {plan.name}: {meanders} meander turns need {2 * r * (meanders + 1):.0f} µm of "
                          f"straight at r = {r:g} µm, segment {segment} has {span:.0f} µm: {fit} turns used (same "
                          "length, wider meander); lower 'meanders', use a longer straight or reduce 'r'",
                          UserWarning, stacklevel=2)
            meanders = fit
    nodes = []
    for i, n in enumerate(plan.nodes):
        if i == segment:
            params = dict(n.params)
            if meanders > 0:
                params["meanders"] = meanders
            turn = n.meander_direction if direction is None else direction
            n = Node(n.position, n.element, n.inst_name, n.align, n.angle, None, increment, turn, **params)
        nodes.append(n)
    return RoutePlan(plan.name, nodes, dict(plan.params), plan.target_length, None, set(plan.fixed_segments))


def _kqc_bend_increment(w: float, r: float) -> float:
    """Extra length of one bend of a KQC ``Meander`` of half-width ``w`` (``Meander.build``'s
    ``bend_length_increment``): below ``w = r`` the bend is less than 90°."""
    if w >= r:
        return r * (math.pi / 2 - 2) + w
    h = w / r
    x = (1 - h) / (1 - h / 2)
    return r * (2 * math.atan(1 - x) + (x + h * (h - 1)) / math.sqrt(x**2 + h**2) - 1)


def meander_width(increment: float, r: float, meanders: int) -> float:
    """Total width (µm) of the KQC ``Meander`` that adds ``increment`` with ``meanders`` turns of radius ``r`` (the
    same formulas as ``Meander.build``). At ``4·r`` and above every bend is 90°; below, KQC flattens the bends, and a
    width under ``r`` is a near-straight zigzag along the whole straight."""
    def added(w):
        return 4 * _kqc_bend_increment(w / 4, r) + 2 * (meanders - 1) * _kqc_bend_increment(w / 2, r)

    full = added(4 * r)
    if increment >= full:
        return 4 * r + (increment - full) / meanders
    lo, hi = 0.0, 4 * r
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if added(mid) < increment else (lo, mid)
    return lo


def meander_turns(increment: float, span: float, r: float, meanders: int = -1) -> int:
    """The turn count for a length-fixing meander of ``increment`` on a straight of ``span``: ``meanders`` as given
    (``-1``: as many as fit, KQC's choice) unless that meander would be narrower than ``r`` — KQC then draws its
    flattened bends along the whole straight, a slanted zigzag. Then the most turns that keep it ``r`` wide (at least
    one: a single bump in the middle of the straight)."""
    fit = max_meanders(span, r)
    m = min(meanders, fit) if meanders > 0 else fit
    if m < 1 or meander_width(increment, r, m) >= r:
        return meanders
    return next((k for k in range(m - 1, 0, -1) if meander_width(increment, r, k) >= r), 1)


TRIM_FRACTION = 0.05  # most a corner's bend radius may shrink to absorb a small length leftover (5 % of r)


def _free_corners(plan: RoutePlan) -> list[tuple[int, float]]:
    """``(node index, dL/dr)`` of the corners whose radius may be trimmed: plain interior nodes with the route radius
    (no own ``corner_r``, no element) between two segments that are not fixed (port stubs and hanger couplers keep
    their bends). ``dL/dr = θ - 2·tan(θ/2)`` (< 0) for a turn of θ: a smaller radius makes the route longer."""
    nodes = plan.nodes
    out = []
    for i in range(1, len(nodes) - 1):
        n = nodes[i]
        if n.element is not None or "corner_r" in n.params or i in plan.fixed_segments or i + 1 in plan.fixed_segments:
            continue
        v1, v2 = n.position - nodes[i - 1].position, nodes[i + 1].position - n.position
        if v1.length() < _EPS or v2.length() < _EPS:
            continue
        theta = abs(_turn(v1, v2))
        if 1e-6 < theta < math.pi - 1e-3:
            out.append((i, theta - 2 * math.tan(theta / 2)))
    return out


def trim_corners(plan: RoutePlan, increment: float, measure, tol: float = 0.01) -> RoutePlan | None:
    """``plan`` lengthened by ``increment`` without a meander: the free corners (:func:`_free_corners`) get a slightly
    smaller bend radius (node ``corner_r``, one value for all of them), so the path, its nodes and its fixed parts stay
    as drawn. None where the route has no free corner, a node sets its own ``r`` (KQC then changes the radius for the
    rest of the route), or the radius would shrink by more than :data:`TRIM_FRACTION`."""
    r = float(plan.params.get("r", 100))
    corners = _free_corners(plan)
    gain = -sum(g for _, g in corners)  # length gained per µm of radius taken off
    if gain < 1e-9 or any("r" in n.params for n in plan.nodes):
        return None
    target = plan.target_length

    def trial(dr):
        at = {i for i, _ in corners}
        nodes = [
            Node(n.position, n.element, n.inst_name, n.align, n.angle, n.length_before, n.length_increment,
                 n.meander_direction, **{**n.params, "corner_r": r - dr}) if i in at else n
            for i, n in enumerate(plan.nodes)
        ]
        return RoutePlan(plan.name, nodes, dict(plan.params), target, None, set(plan.fixed_segments))

    # the analytic step, then corrections: KQC's arcs are polygons on the 1 nm grid, so the built length moves in
    # steps of a few nm; accepted within tol or 10 ppm of the length (the meander path accepts 0.1 %)
    accept = max(tol, 1e-5 * target)
    dr, best = increment / gain, None
    for _ in range(4):
        if not 0 < dr <= TRIM_FRACTION * r:
            break
        out = trial(dr)
        got = measure(out)
        if best is None or abs(got - target) < abs(best[1] - target):
            best = (out, got)
        if abs(got - target) <= tol:
            break
        dr += (target - got) / gain
    if best is None or abs(best[1] - target) > accept:
        return None
    best[0].length = best[1]
    return best[0]


def fix_length(
    plan: RoutePlan,
    measure,
    segment: int | None = None,
    meanders: int = -1,
    tol: float = 0.01,
    direction: int | None = None,
) -> RoutePlan:
    """Make the built length equal ``plan.target_length``.

    ``measure(plan) -> float`` must build the waveguide and return its length (µm). By the leftover ``target -
    length of the path as drawn`` (2026-11-18: no slanted zigzags on a route that is already about the right
    length):

    * within ``tol``: the path as drawn, no meander;
    * small enough: the free corners' bend radius trimmed by up to :data:`TRIM_FRACTION` (:func:`trim_corners`);
    * else a KQC ``Meander`` on the longest free straight (or ``segment``), with as many turns as fit unless they
      would flatten into a zigzag (:func:`meander_turns`: then fewer, wider turns).
    """
    target = plan.target_length
    base = measure(plan)
    if target < base - tol:
        raise RoutingError(
            f"route {plan.name}: target length {target:.1f} µm is shorter than the shortest path {base:.1f} µm"
        )
    if abs(target - base) <= tol:
        return RoutePlan(plan.name, list(plan.nodes), dict(plan.params), target, base, set(plan.fixed_segments))
    if segment is None:
        trimmed = trim_corners(plan, target - base, measure, tol)
        if trimmed is not None:
            return trimmed
    seg = meander_segment_index(plan.nodes, segment, plan.fixed_segments)

    def on(seg):
        r = float(plan.params.get("r", 100))
        turns = meander_turns(target - base, meander_span(plan, seg), r, meanders)
        if meanders > 0 and turns != meanders:
            import warnings  # pylint: disable=import-outside-toplevel

            warnings.warn(f"route {plan.name}: {meanders} meander turns for +{target - base:.2f} µm would flatten into "
                          f"a zigzag narrower than r = {r:g} µm; {turns} used (same length)", UserWarning, stacklevel=3)
        trial = with_length_increment(plan, target - base, seg, turns, direction)
        got = measure(trial)
        if abs(got - target) > tol:  # one correction step absorbs meander end-bend effects
            trial = with_length_increment(plan, target - base + (target - got), seg, turns, direction)
            got = measure(trial)
        if abs(got - target) > max(tol, 1e-3 * target):
            raise RoutingError(
                f"route {plan.name}: could only reach {got:.2f} µm of {target:.2f} µm (segment too short?)")
        trial.length = got
        return trial

    try:
        return on(seg)
    except Exception as first:  # noqa: BLE001  the meander does not fit on that straight (KQC: "too close")
        if segment is not None:
            raise RoutingError(
                f"route {plan.name}: the meander does not fit on segment {segment} ({first}); choose a longer "
                "straight (route dialog: Meander on segment, or Ctrl+Shift+M) or make this one longer") from first
        # the longest free straight could not take it (a node edit made the route tight): the other free straights,
        # longest first. Only reached where the build failed before.
        others = sorted((i for i in range(1, len(plan.nodes)) if i != seg and i not in plan.fixed_segments),
                        key=lambda i: -(plan.nodes[i].position - plan.nodes[i - 1].position).length())
        for i in others:
            try:
                return on(i)
            except Exception:  # noqa: BLE001
                continue
        turns = f", or let the number of meander turns be automatic (now {meanders})" if meanders > 0 else ""
        raise RoutingError(
            f"route {plan.name}: the meander fits on no straight of this route ({first}); make a straight longer "
            f"(Route handles: move or insert a node) or shorten the length{turns}") from first
