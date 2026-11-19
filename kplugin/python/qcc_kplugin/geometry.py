"""Plain-Python geometry for the GUI tools (points are ``(x, y)`` tuples in µm; no pya, so it is unit-tested).

Mirrors what ``quantcore_circuits.route`` does when it builds a route, closely enough for a live preview:
port stub → user waypoints → port stub, with Manhattan corners when there are no waypoints (or one oblique straight
between ports that face an angle: :func:`oblique_mids`). The real geometry (KQC ``WaveguideComposite``, bends of
radius ``r``, meanders) always comes from the rebuild.
"""

from __future__ import annotations

import math

Point = tuple[float, float]
EPS = 1e-6


def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def mul(a: Point, s: float) -> Point:
    return (a[0] * s, a[1] * s)


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def norm(a: Point) -> float:
    return math.hypot(a[0], a[1])


def dist(a: Point, b: Point) -> float:
    return norm(sub(a, b))


def dist_point_segment(p: Point, a: Point, b: Point) -> float:
    ab = sub(b, a)
    L2 = dot(ab, ab)
    if L2 < EPS:
        return dist(p, a)
    t = max(0.0, min(1.0, dot(sub(p, a), ab) / L2))
    return dist(p, add(a, mul(ab, t)))


def dist_point_polyline(p: Point, pts: list[Point]) -> tuple[float, int]:
    """Distance to a polyline and the 1-based index of the closest segment (segment k joins points k-1 and k)."""
    best, seg = math.inf, 0
    for k in range(1, len(pts)):
        d = dist_point_segment(p, pts[k - 1], pts[k])
        if d < best:
            best, seg = d, k
    return best, seg


def nearest(points: dict[str, Point], p: Point, radius: float) -> str | None:
    best, name = radius, None
    for n, q in points.items():
        d = dist(p, q)
        if d <= best:
            best, name = d, n
    return name


def snap_grid(p: Point, grid: float) -> Point:
    if grid <= 0:
        return p
    return (round(p[0] / grid) * grid, round(p[1] / grid) * grid)


def _manhattan(a: Point, da: Point, b: Point) -> list[Point]:
    """Corner from ``a`` (leaving along ``da``) to ``b``; turns at ``a`` instead if going on would reverse."""
    if abs(a[0] - b[0]) < EPS or abs(a[1] - b[1]) < EPS:
        return []
    horizontal = abs(da[0]) > abs(da[1])
    corner = (b[0], a[1]) if horizontal else (a[0], b[1])
    if dot(sub(corner, a), da) < -EPS:
        corner = (a[0], b[1]) if horizontal else (b[0], a[1])
    return [corner]


ALIGN_TOL = math.radians(5.0)  # the router's limit for an oblique stub-to-stub straight (route.router._ALIGN_TOL)


def unit(v: Point) -> Point | None:
    n = norm(v)
    return None if n < EPS else (v[0] / n, v[1] / n)


def is_axis(d: Point | None) -> bool:
    """True for a horizontal / vertical direction (a port that faces along an axis)."""
    return d is not None and (abs(d[0]) < EPS or abs(d[1]) < EPS)


def _turn(a: Point, b: Point) -> float:
    c = dot(a, b) / (norm(a) * norm(b))
    return math.acos(max(-1.0, min(1.0, c)))


def oblique_mids(p0: Point, d0: Point | None, p1: Point, d1: Point | None, r: float = 0.0) -> list[Point] | None:
    """Corners of the oblique route the router draws between stub ends ``p0`` (arriving along ``d0``) and ``p1``
    (leaving along ``d1``) when a port faces an angle, else None (Manhattan, as the router). ``[]`` = one straight (the
    ports face each other along a line, within 5°); ``[X]`` = one corner where the two ports' axes meet. Candidates
    whose bends do not fit the radius ``r`` are left out, as in the router."""
    if (d0 is None or is_axis(d0)) and (d1 is None or is_axis(d1)):
        return None
    v = sub(p1, p0)
    if norm(v) < EPS:
        return None
    cands: list[list[Point]] = []
    ends = [d for d in (d0, d1) if d is not None]
    if ends and all(_turn(d, v) <= ALIGN_TOL for d in ends):
        cands.append([])
    if d0 is not None and d1 is not None:
        den = d0[0] * d1[1] - d0[1] * d1[0]
        if abs(den) > 1e-3 and _turn(d0, d1) <= math.pi / 2 + 1e-6:  # not (nearly) parallel, no hairpin
            t = (v[0] * d1[1] - v[1] * d1[0]) / den
            u = (d0[0] * v[1] - d0[1] * v[0]) / den
            if t > EPS and u > EPS:
                cands.append([add(p0, mul(d0, t))])
    for mids in cands:
        path = [p0, *mids, p1]
        if d0 is not None:
            path.insert(0, sub(p0, d0))
        if d1 is not None:
            path.append(add(p1, d1))
        if r <= 0 or not tight_segments(path, [r] * len(path)):
            return mids
    return None


def route_preview(
    start: Point, start_dir: Point | None, waypoints: list[Point], end: Point, end_dir: Point | None, stub: float
) -> list[Point]:
    """Sharp polyline of a route from a port (``start``, outward ``start_dir``) through ``waypoints`` to ``end``.

    ``end_dir`` is the outward direction of the end port (``None`` while the end is still the mouse position or a
    free end); ``start_dir`` is None for a route starting at a free end (no stub).
    """
    pts = [start] if start_dir is None else [start, add(start, mul(start_dir, stub))]
    tail = [add(end, mul(end_dir, stub)), end] if end_dir is not None else [end]
    if waypoints:
        pts += list(waypoints)
    else:
        mids = oblique_mids(pts[-1], start_dir, tail[0], None if end_dir is None else mul(end_dir, -1.0), stub)
        pts += _manhattan(pts[-1], start_dir or (1.0, 0.0), tail[0]) if mids is None else mids
    pts += tail
    out: list[Point] = []
    for p in pts:
        if not out or dist(p, out[-1]) > EPS:
            out.append(p)
    return out


def compatible(pa: dict, pb: dict, tol: float = 1e-3) -> bool:
    """Ports that can be snapped together: same CPW (a, b) and facing each other."""
    if not pa.get("dir") or not pb.get("dir"):
        return False
    if abs((pa.get("a") or 0) - (pb.get("a") or 0)) > tol or abs((pa.get("b") or 0) - (pb.get("b") or 0)) > tol:
        return False
    return dot(tuple(pa["dir"]), tuple(pb["dir"])) < -0.999


def snap_candidate(
    moving: dict[str, dict], others: dict[str, dict], delta: Point, radius: float
) -> tuple[str, str, Point] | None:
    """Best (moving_port, target_port, corrected_delta) when ``moving`` ports are translated by ``delta``.

    ``moving``/``others`` map port names to sidecar ports ``{"pos", "dir", "a", "b"}``. Only translation is
    considered while dragging; the rebuild solves the rotation for ``place.snap`` exactly.
    """
    best = None
    for mn, mp in moving.items():
        pos = add(tuple(mp["pos"]), delta)
        for on, op in others.items():
            d = dist(pos, tuple(op["pos"]))
            if d <= radius and compatible(mp, op) and (best is None or d < best[0]):
                best = (d, mn, on, add(delta, sub(tuple(op["pos"]), pos)))
    return None if best is None else best[1:]


FACE_TOL_DEG = 2.5  # ports already facing within this are snapped without a rotation (the old rule)


def _rot_pt(p: Point, deg: float, about: Point = (0.0, 0.0)) -> Point:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    x, y = p[0] - about[0], p[1] - about[1]
    return (about[0] + x * c - y * s, about[1] + x * s + y * c)


def _norm180(deg: float) -> float:
    deg = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if deg == -180.0 else deg


def same_line(pa: dict, pb: dict, tol: float = 1e-3) -> bool:
    """Ports of the same CPW cross-section (a, b), whichever way they face."""
    return abs((pa.get("a") or 0) - (pb.get("a") or 0)) <= tol and abs((pa.get("b") or 0) - (pb.get("b") or 0)) <= tol


def snap_candidate_rot(
    moving: dict[str, dict],
    others: dict[str, dict],
    delta: Point,
    radius: float,
    origin: Point = (0.0, 0.0),
    turn: float = 0.0,
    rotate: bool = True,
) -> tuple[str, str, Point, float] | None:
    """Best ``(moving_port, target_port, corrected_delta, extra_turn)`` while dragging, rotation included.

    ``moving``/``others`` are sidecar ports ``{"pos", "dir", "a", "b"}``. The held instance is turned by ``turn``
    degrees about ``origin`` (the 90° steps of [ and ]) and translated by ``delta``. With ``rotate`` a port snaps to
    any target port of the same CPW, however it faces: the instance is turned by ``extra_turn`` (degrees, -180..180)
    more, so the port faces the target exactly (StarQubit pins 72° apart, ConcentricTransmon couplers at 60°), and the
    port then has to be within ``radius`` of the target *after* that turn. The smallest turn wins ties (a symmetric
    qubit has four ports that all land on the same spot). Without ``rotate`` only ports that already face the target
    (within 2.5°) snap, with ``extra_turn`` 0: translation only. ``corrected_delta`` is the translation that puts the
    port on the target.
    """
    best = None
    for mn, mp in moving.items():
        if not mp.get("dir"):
            continue
        d_now = _rot_pt(tuple(mp["dir"]), turn)
        for on, op in others.items():
            if not op.get("dir") or not same_line(mp, op):
                continue
            want = (-op["dir"][0], -op["dir"][1])
            extra = _norm180(math.degrees(math.atan2(want[1], want[0]) - math.atan2(d_now[1], d_now[0])))
            if abs(extra) < 1e-6:
                extra = 0.0
            if not rotate:
                if abs(extra) > FACE_TOL_DEG:
                    continue
                extra = 0.0
            pos = add(_rot_pt(tuple(mp["pos"]), turn + extra, origin), delta)
            d = dist(pos, tuple(op["pos"]))
            key = d + 0.01 * abs(extra)
            if d <= radius and (best is None or key < best[0]):
                best = (key, mn, on, add(delta, sub(tuple(op["pos"]), pos)), extra)
    return None if best is None else best[1:]


def waypoint_insert_index(waypoint_pidx: list[int], segment: int) -> int:
    """Index in ``route.nodes`` for a new waypoint on polyline ``segment`` (1-based)."""
    return sum(1 for i in waypoint_pidx if i < segment)


def handle_points(route: dict) -> tuple[list[tuple[int, Point]], list[tuple[int, Point]]]:
    """(waypoint handles [(node_index, pos)], insert handles [(segment, midpoint)]) for a sidecar route."""
    pts = [tuple(p) for p in route["polyline"]]
    fixed = set(route.get("fixed_segments", []))
    wps = [(i, tuple(p)) for i, p in enumerate(route.get("waypoints", []))]
    inserts = [
        (k, mul(add(pts[k - 1], pts[k]), 0.5))
        for k in range(1, len(pts))
        if k not in fixed and dist(pts[k - 1], pts[k]) > EPS
    ]
    return wps, inserts


def route_near(routes: dict, p: Point, radius: float, exclude=()) -> tuple[str, int] | None:
    """The sidecar route whose polyline passes within ``radius`` µm of ``p``: ``(name, segment)`` or None."""
    best, hit = radius, None
    for name, route in routes.items():
        pts = [tuple(q) for q in route.get("polyline") or []]
        if name in exclude or len(pts) < 2:
            continue
        d, seg = dist_point_polyline(p, pts)
        if d <= best:
            best, hit = d, (name, seg)
    return hit


def hanger_side(polyline: list[Point], segment: int, toward: Point) -> str:
    """``"left"`` / ``"right"`` of the route's travel direction on ``segment`` (1-based), the side ``toward`` is on
    (a hanger coupler sits on the side its resonator comes from)."""
    a, b = tuple(polyline[segment - 1]), tuple(polyline[segment])
    d, v = sub(b, a), sub(toward, a)
    return "left" if d[0] * v[1] - d[1] * v[0] > 0 else "right"


# ---- grid, Shift (45° / orthogonal) constraints---------------------------------------------------------------------
def parse_grid(text) -> float | None:
    """A KLayout editor-grid config value (``"0.5"``, ``"1,1"``, ``""``) → grid step in µm, or None."""
    if text is None:
        return None
    for part in str(text).replace(";", ",").split(","):
        try:
            v = float(part.strip())
        except ValueError:
            continue
        if v > 0:
            return v
    return None


def ortho(anchor: Point, p: Point) -> Point:
    """``p`` moved so the segment from ``anchor`` is horizontal or vertical, whichever is nearer (Shift)."""
    if abs(p[0] - anchor[0]) >= abs(p[1] - anchor[1]):
        return (p[0], anchor[1])
    return (anchor[0], p[1])


def ortho_between(p: Point, neighbours) -> Point:
    """``p`` (a node being moved or inserted) aligned with its neighbours (Shift): each neighbour segment is made
    horizontal or vertical, the nearer choice first; a second neighbour can only fix the other coordinate, so two
    generic neighbours give the square corner nearest ``p`` and two neighbours on one line keep ``p`` on it."""
    rules = []
    for n in neighbours:
        if n is None:
            continue
        if abs(p[0] - n[0]) <= abs(p[1] - n[1]):
            rules.append((abs(p[0] - n[0]), 0, n[0]))  # vertical segment: x of the neighbour
        else:
            rules.append((abs(p[1] - n[1]), 1, n[1]))  # horizontal segment: y of the neighbour
    out, fixed = list(p), set()
    for _cost, axis, value in sorted(rules):
        if axis not in fixed:
            out[axis] = value
            fixed.add(axis)
    return (out[0], out[1])


_DIRS8 = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]


def snap45(anchor: Point, p: Point, grid: float = 0.0) -> Point:
    """``p`` moved onto the nearest of the 8 directions from ``anchor`` (0°, 45°, 90°, …; Shift while drawing).
    Horizontal / vertical keep the anchor's exact coordinate; a diagonal keeps |dx| = |dy| on the grid."""
    v = sub(p, anchor)
    if norm(v) < EPS:
        return p
    ux, uy = _DIRS8[round(math.atan2(v[1], v[0]) / (math.pi / 4)) % 8]
    if ux and uy:
        s = (abs(v[0]) + abs(v[1])) / 2
        if grid > 0:
            s = round(s / grid) * grid
        return (anchor[0] + ux * s, anchor[1] + uy * s)
    q = snap_grid(p, grid)
    return (q[0], anchor[1]) if ux else (anchor[0], q[1])


def elbow(anchor: Point, anchor_dir: Point | None, p: Point) -> list[Point]:
    """The square corner between ``anchor`` and ``p`` (``[]`` when they are aligned): the segment leaves ``anchor``
    along ``anchor_dir`` (the previous segment / the port), or along the longer axis when there is none. This is the
    corner the Connect preview shows, and a click commits it as a node, so the built route matches the preview."""
    d = sub(p, anchor)
    if anchor_dir is None or norm(anchor_dir) < EPS:
        anchor_dir = (1.0, 0.0) if abs(d[0]) >= abs(d[1]) else (0.0, 1.0)
    return _manhattan(anchor, anchor_dir, p)


def snap_rays(p: Point, q: Point, rays, tol: float, grid: float = 0.0) -> Point:
    """``q`` (the point an axis / 45° snap chose for ``p``), or ``p`` put on the nearest of ``rays`` ((origin,
    direction) lines, e.g. an angled port's own axis) when that ray passes within ``tol`` of ``p`` and nearer than
    ``q``. The distance along the ray is rounded to the grid."""
    best, out = dist(p, q), q
    for origin, d in rays:
        d = unit(d)
        if d is None:
            continue
        s = dot(sub(p, origin), d)
        if grid > 0:
            s = round(s / grid) * grid
        c = add(origin, mul(d, s))
        gap = dist(p, c)
        if gap <= tol and gap < best:
            best, out = gap, c
    return out


def constrain(p: Point, grid: float, neighbours=(), shift: bool = False, rays=(), tol: float = 0.0) -> Point:
    """The point a click / move at ``p`` stands for: on the grid and, with Shift, constrained by ``neighbours``.
    One neighbour (drawing the next segment, moving an end node): the segment snaps to 0° / 45° / 90° / …; two
    neighbours (moving a middle node): horizontal / vertical to both. Aligned coordinates take the neighbour's exact
    value, which wins over the grid. ``rays`` ((origin, direction) lines: the axes of angled ports) are offered with
    Shift too: a ray within ``tol`` µm of ``p`` and nearer than the 45° / aligned choice wins. Without Shift the
    point is only put on the grid: any angle (Ctrl in the tools is the same, spelled out)."""
    q = snap_grid(p, grid)
    real = [n for n in neighbours if n is not None]
    if shift and len(real) == 1:
        q = snap45(real[0], p, grid)
    elif shift and real:
        q = ortho_between(q, real)
    if shift and rays:
        q = snap_rays(p, q, rays, tol, grid)
    return q


# ---- corners: rounded preview, curvature handle -------------------------------------------------------------------
def turn_angle(prev: Point, p: Point, nxt: Point) -> float:
    v1, v2 = sub(p, prev), sub(nxt, p)
    if norm(v1) < EPS or norm(v2) < EPS:
        return 0.0
    c = max(-1.0, min(1.0, dot(v1, v2) / (norm(v1) * norm(v2))))
    return math.acos(c)


def corner_cut(prev: Point, p: Point, nxt: Point, r: float) -> float:
    """Length of each adjacent straight a bend of radius ``r`` at ``p`` uses (KQC corner model)."""
    theta = turn_angle(prev, p, nxt)
    if theta < 1e-9:
        return 0.0
    return r * math.tan(theta / 2) if theta < math.pi - 1e-9 else math.inf


def _bisector(prev: Point, p: Point, nxt: Point) -> Point | None:
    """Unit vector from corner ``p`` towards the inside of the turn (towards the arc centre)."""
    u, v = sub(p, prev), sub(nxt, p)
    if norm(u) < EPS or norm(v) < EPS:
        return None
    w = sub(mul(v, 1 / norm(v)), mul(u, 1 / norm(u)))
    return None if norm(w) < EPS else mul(w, 1 / norm(w))


def radius_handle(prev: Point, p: Point, nxt: Point, r: float) -> Point | None:
    """Curvature handle of the corner at ``p`` bent to radius ``r``: the middle of the arc, on the bisector."""
    w = _bisector(prev, p, nxt)
    theta = turn_angle(prev, p, nxt)
    if w is None or theta < 1e-6 or theta > math.pi - 1e-6:
        return None
    return add(p, mul(w, r * (1 / math.cos(theta / 2) - 1)))


def radius_from_handle(prev: Point, p: Point, nxt: Point, q: Point) -> float | None:
    """The bend radius whose arc middle is at ``q`` projected on the corner's bisector (inverse of
    :func:`radius_handle`); None on a straight node."""
    w = _bisector(prev, p, nxt)
    theta = turn_angle(prev, p, nxt)
    if w is None or theta < 1e-6 or theta > math.pi - 1e-6:
        return None
    d = max(0.0, dot(sub(q, p), w))
    return d / (1 / math.cos(theta / 2) - 1)


def rounded_points(points: list[Point], radii: list[float], segments_per_90: int = 12) -> list[Point]:
    """Sharp polyline → polyline with every interior corner ``i`` replaced by an arc of radius ``radii[i]`` (index
    by point; the ends are ignored). Radii too big for the legs are clipped so the preview stays drawable."""
    pts = [tuple(q) for q in points]
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        prev, p, nxt = pts[i - 1], pts[i], pts[i + 1]
        r = radii[i] if i < len(radii) and radii[i] else 0.0
        theta = turn_angle(prev, p, nxt)
        if r <= 0 or theta < 1e-6 or theta > math.pi - 1e-6:
            out.append(p)
            continue
        cut = r * math.tan(theta / 2)
        room = min(dist(prev, p), dist(p, nxt)) / 2
        if cut > room:
            cut, r = room, room / math.tan(theta / 2)
        u, v = mul(sub(p, prev), 1 / dist(prev, p)), mul(sub(nxt, p), 1 / dist(p, nxt))
        a, b = add(p, mul(u, -cut)), add(p, mul(v, cut))
        w = _bisector(prev, p, nxt)
        centre = add(p, mul(w, r / math.cos(theta / 2)))
        a0 = math.atan2(a[1] - centre[1], a[0] - centre[0])
        a1 = math.atan2(b[1] - centre[1], b[0] - centre[0])
        sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        n = max(2, int(abs(sweep) / (math.pi / 2) * segments_per_90))
        out += [(centre[0] + r * math.cos(a0 + sweep * k / n), centre[1] + r * math.sin(a0 + sweep * k / n))
                for k in range(n + 1)]
    out.append(pts[-1])
    return out


def tight_segments(points: list[Point], radii: list[float]) -> list[int]:
    """Segments (1-based) too short for the bends at both their ends (the rebuild would fail there)."""
    pts = [tuple(q) for q in points]
    cuts = [0.0] + [corner_cut(pts[i - 1], pts[i], pts[i + 1], radii[i]) for i in range(1, len(pts) - 1)] + [0.0]
    return [k for k in range(1, len(pts)) if dist(pts[k - 1], pts[k]) + 1e-3 < cuts[k - 1] + cuts[k]]


def free_end_dir(end: Point, toward: Point) -> float | None:
    """``FreeEnd.dir`` (degrees, pointing from the end into the route) of a free end at ``end`` whose route comes
    from ``toward``."""
    v = sub(toward, end)
    if norm(v) < EPS:
        return None
    deg = math.degrees(math.atan2(v[1], v[0]))
    return round(deg % 360.0, 9)


def segment_near(polyline: list[Point], p: Point, radius: float) -> int | None:
    """1-based index of the polyline segment within ``radius`` of ``p``, or None."""
    d, seg = dist_point_polyline(p, [tuple(q) for q in polyline])
    return seg if d <= radius and seg else None
