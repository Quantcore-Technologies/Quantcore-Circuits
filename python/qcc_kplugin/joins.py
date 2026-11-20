"""How a route ends on another line: a hanger coupler beside it, or merged into it with a T-junction.

``merge`` splits the line at a point into two routes joined by a KQC ``WaveguideCoplanarSplitter`` (a T: ports
``a`` / ``b`` along the line, ``c`` the stem) and returns the stem port for the new route to end on. ``unmerge``
undoes it: the two halves become one route again and the stem route ends as a hanger coupler at the T's place.
``hanger_to_merge`` / ``merge_to_hanger`` convert an existing route end. The LOM model of the splitter is one
conductor, so a capacitor or a resonator on the stem is galvanically on the line.

Plain Python (no pya): unit-tested outside KLayout. Functions change the design dict in place and raise
``ValueError`` with a message fit for the status bar.
"""

from __future__ import annotations

import math

TEE_CELL = "WaveguideCoplanarSplitter"
TEE_ARM = 11.0  # µm: KQC splitter default port distance from its centre (lengths [11, 11, 11])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _norm(a):
    return math.hypot(a[0], a[1])


def _r(v: float) -> float:
    return round(float(v), 4)


def _node_xy(node):
    return tuple(node["at"]) if isinstance(node, dict) else tuple(node)


def arclength(pts, p) -> tuple[float, int, tuple]:
    """(arclength of the point of polyline ``pts`` nearest ``p``, its segment (1-based), that point)."""
    best, acc, out = None, 0.0, (0.0, 1, tuple(pts[0]))
    for i in range(1, len(pts)):
        a, b = tuple(pts[i - 1]), tuple(pts[i])
        v = _sub(b, a)
        seg = _norm(v)
        u = 0.0 if seg == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * v[0] + (p[1] - a[1]) * v[1]) / (seg * seg)))
        q = (a[0] + v[0] * u, a[1] + v[1] * u)
        d = _norm(_sub(q, p))
        if best is None or d < best - 1e-9:
            best, out = d, (acc + u * seg, i, q)
        acc += seg
    return out


def point_at(pts, s: float) -> tuple:
    """The point at arclength ``s`` along polyline ``pts``."""
    acc = 0.0
    for i in range(1, len(pts)):
        a, b = tuple(pts[i - 1]), tuple(pts[i])
        seg = _norm(_sub(b, a))
        if s <= acc + seg + 1e-9 and seg > 0:
            u = (s - acc) / seg
            return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
        acc += seg
    return tuple(pts[-1])


def side_normal(pts, segment: int, side: str) -> tuple:
    """Unit normal of segment ``segment`` (1-based) of ``pts`` on ``side`` ("left" / "right" of the travel)."""
    a, b = tuple(pts[segment - 1]), tuple(pts[segment])
    t = _sub(b, a)
    n = _norm(t)
    t = (t[0] / n, t[1] / n)
    return (-t[1], t[0]) if side == "left" else (t[1], -t[0])


def _unique(design: dict, base: str) -> str:
    taken = set(design.get("instances", {})) | set(design.get("routes", {}))
    i = 1
    while f"{base}{i}" in taken:
        i += 1
    return f"{base}{i}"


def _ends(route: dict):
    return [("from", route.get("from")), ("to", route.get("to"))]


def merge(design: dict, host: str, polyline, point, side: str, r: float, tee_params: dict | None = None,
          tee: str | None = None) -> dict:
    """Split route ``host`` (built ``polyline``, bend radius ``r``) at the point nearest ``point`` with a T whose stem
    points to ``side`` of the line. Returns ``{"tee", "stem", "stem_pos", "stem_dir", "second"}``: the T's name, its
    stem port (``"T1.c"``), the stem port's position and direction, and the name of the second half."""
    routes = design.get("routes", {})
    if host not in routes:
        raise ValueError(f"no route {host!r}")
    h = routes[host]
    if h.get("type") == "meander":
        raise ValueError(f"{host} is a meander: merge into a plain cpw line (a feedline)")
    pts = [tuple(p) for p in polyline]
    s_p, seg, p = arclength(pts, point)
    a, b = pts[seg - 1], pts[seg]
    # the T's arm, then a port stub, then the bend at a corner (or the far port's stub) must fit on this straight
    need = TEE_ARM + 2 * r
    s_a = sum(_norm(_sub(pts[i], pts[i - 1])) for i in range(1, seg))
    s_b = s_a + _norm(_sub(b, a))
    if s_p - s_a < need - 1e-6 or s_b - s_p < need - 1e-6:
        raise ValueError(f"merge into {host}: the T needs {need:g} µm of straight line on both sides; this point "
                         f"has {s_p - s_a:.0f} / {s_b - s_p:.0f} µm (move it along the line)")
    t = _sub(b, a)
    t = (t[0] / _norm(t), t[1] / _norm(t))
    n = side_normal(pts, seg, side)
    rot = (math.degrees(math.atan2(n[1], n[0])) + 90.0) % 360.0  # the splitter's stem c points along -y at rot 0
    rot = round(rot, 6) % 360.0
    a_dir = (math.cos(math.radians(rot)), math.sin(math.radians(rot)))
    back, fwd = ("a", "b") if a_dir[0] * t[0] + a_dir[1] * t[1] < 0 else ("b", "a")
    tee = tee or _unique(design, "T")
    second = _unique(design, host + "_")
    inst = {"cell": TEE_CELL, "place": {"at": [_r(p[0]), _r(p[1])], "rot": rot}}
    if tee_params:
        inst["params"] = dict(tee_params)
    design.setdefault("instances", {})[tee] = inst

    before, after = [], []
    for node in h.get("nodes", []):
        (before if arclength(pts, _node_xy(node))[0] < s_p else after).append(node)
    h2 = {k: v for k, v in h.items() if k not in ("from", "to", "nodes", "length", "meander_segment")}
    h2["from"] = f"{tee}.{fwd}"
    h2["to"] = h["to"]
    if after:
        h2["nodes"] = after
    h["to"] = f"{tee}.{back}"
    if before:
        h["nodes"] = before
    else:
        h.pop("nodes", None)
    new_routes = {}
    for k, v in routes.items():  # the second half right after the first
        new_routes[k] = v
        if k == host:
            new_routes[second] = h2
    design["routes"] = new_routes

    for name, route in design["routes"].items():  # hangers on the line: on the half they sit on
        end = route.get("to")
        if isinstance(end, dict) and end.get("hanger") == host:
            near = end.get("near") or point_at(pts, float(end.get("s", 0.0)))
            if "s" in end:
                end.pop("s")
                end["near"] = [_r(near[0]), _r(near[1])]
            if arclength(pts, near)[0] > s_p:
                end["hanger"] = second
    for g in (design.get("sim_groups") or {}).values():
        if host in g.get("select", []):
            g["select"].append(second)
    stem_pos = (p[0] + n[0] * TEE_ARM, p[1] + n[1] * TEE_ARM)
    return {"tee": tee, "stem": f"{tee}.c", "stem_pos": stem_pos, "stem_dir": n, "second": second}


def tee_of(design: dict, route: str) -> str | None:
    """The merge T at an end of ``route`` (an instance of :data:`TEE_CELL` whose stem ``c`` the route ends on)."""
    r = design.get("routes", {}).get(route, {})
    for _, end in _ends(r):
        if isinstance(end, str) and end.endswith(".c"):
            inst = end.split(".", 1)[0]
            if design.get("instances", {}).get(inst, {}).get("cell") == TEE_CELL:
                return inst
    return None


def _halves(design: dict, tee: str):
    """(first half, its port, second half, its port) of the line through T ``tee``."""
    first = second = None
    for name, route in design.get("routes", {}).items():
        to, src = route.get("to"), route.get("from")
        if isinstance(to, str) and to in (f"{tee}.a", f"{tee}.b"):
            first = (name, to)
        if isinstance(src, str) and src in (f"{tee}.a", f"{tee}.b"):
            second = (name, src)
    if first is None or second is None or first[1] == second[1]:
        raise ValueError(f"{tee}: not a line merge (a route into {tee}.a or .b and one out of the other are needed)")
    return first[0], second[0]


def unmerge(design: dict, tee: str) -> tuple[str, tuple]:
    """Remove merge T ``tee``: its two halves become one route again (named as the first). Returns (that route,
    the T's position)."""
    inst = design.get("instances", {}).get(tee)
    if inst is None or inst.get("cell") != TEE_CELL:
        raise ValueError(f"{tee} is not a merge T")
    first, second = _halves(design, tee)
    routes = design["routes"]
    h, h2 = routes[first], routes.pop(second)
    h["to"] = h2["to"]
    nodes = list(h.get("nodes", [])) + list(h2.get("nodes", []))
    if nodes:
        h["nodes"] = nodes
    for route in routes.values():
        end = route.get("to")
        if isinstance(end, dict) and end.get("hanger") == second:
            end["hanger"] = first
    for g in (design.get("sim_groups") or {}).values():
        if second in g.get("select", []):
            g["select"] = [e for e in g["select"] if e != second]
            if first not in g["select"]:
                g["select"].append(first)
    for c in (design.get("couplings") or {}).values():
        c["between"] = [first if e == second else e for e in c.get("between", [])]
    (design.get("targets") or {}).pop(second, None)
    at = tuple(inst["place"]["at"])
    del design["instances"][tee]
    return first, at


def merge_to_hanger(design: dict, route: str, polyline_of, coupler: float = 300.0, ground_gap: float = 6.0,
                    end: str = "short") -> str:
    """Route ``route`` ends on a merge T's stem: remove the T and end the route as a hanger coupler there instead.
    ``polyline_of(name)`` gives a built route's polyline (the sidecar). Returns the line it now hangs from."""
    tee = tee_of(design, route)
    if tee is None:
        raise ValueError(f"{route} does not end on a merge T")
    r = design["routes"][route]
    if r.get("from") == f"{tee}.c":  # a hanger end is always the route's "to": turn the route around
        r["from"], r["to"] = r["to"], r["from"]
        if r.get("nodes"):
            r["nodes"] = list(reversed(r["nodes"]))
    rot = float(design["instances"][tee]["place"].get("rot", 0.0))
    stem = (math.sin(math.radians(rot)), -math.cos(math.radians(rot)))  # c at rot 0 points along -y
    first, at = unmerge(design, tee)
    pts = [tuple(p) for p in polyline_of(first)]
    _, seg, _ = arclength(pts, at)
    side = "left" if side_normal(pts, seg, "left")[0] * stem[0] + side_normal(pts, seg, "left")[1] * stem[1] > 0 \
        else "right"
    r["to"] = {"hanger": first, "near": [_r(at[0]), _r(at[1])], "length": float(coupler), "side": side, "end": end,
               "ground_gap": float(ground_gap)}
    return first


def hanger_to_merge(design: dict, route: str, polyline_of, r: float, tee_params: dict | None = None) -> str:
    """Route ``route`` ends as a hanger coupler: merge it into that line with a T instead. Returns the T's name."""
    rr = design["routes"][route]
    end = rr.get("to")
    if not (isinstance(end, dict) and end.get("hanger")):
        raise ValueError(f"{route} does not hang from a line")
    host = end["hanger"]
    pts = [tuple(p) for p in polyline_of(host)]
    near = end.get("near") or point_at(pts, float(end.get("s", 0.0)))
    out = merge(design, host, pts, near, end.get("side", "left"), r, tee_params)
    rr["to"] = out["stem"]
    if rr.get("type") == "meander" and not rr.get("length"):
        rr["type"] = "cpw"
    return out["tee"]
