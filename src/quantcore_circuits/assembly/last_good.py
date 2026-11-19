"""Last good routes: what a route looked like the last time it built.

A ``qcc build --keep-going`` (the KLayout plugin's builds) leaves a failed route out of the layout. So that nothing
downstream loses it, every successful keep-going build stores each route's polyline and length in
``<name>.last_good_routes.json`` next to the layout; a route that builds again replaces its entry, a route that fails
keeps the old one. The sidecar's ``failed_routes`` carries the entry of each failed route, the plugin draws it, and the
LOM (``lom_from_design``) uses it, with a warning, instead of the missing route.

Strict builds (scripts, notebooks, tests, fab export) never read or write this file.
"""

from __future__ import annotations

import json
import os
import tempfile
import warnings
from dataclasses import replace
from pathlib import Path

from kqcircuits.pya_resolver import pya
from kqcircuits.util.node import Node

from quantcore_circuits.route.router import RoutePlan, RoutingError

SCHEMA = "qcc-last-good-routes/0.1"


def store_path(layout_path: str | Path) -> Path:
    """``<layout stem>.last_good_routes.json`` beside the layout."""
    p = Path(layout_path)
    return p.with_name(p.stem + ".last_good_routes.json")


def design_store_path(design_path: str | Path) -> Path:
    """Where the plugin's builds of a design file keep it: ``<design dir>/build/<design stem>...``."""
    p = Path(design_path)
    return p.parent / "build" / f"{p.stem}.last_good_routes.json"


def load(path: str | Path | None) -> dict:
    """``{route: entry}`` of a store file; empty when there is none (or it cannot be read)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    routes = data.get("routes") if isinstance(data, dict) else None
    return dict(routes) if isinstance(routes, dict) else {}


def entry_of(rp: RoutePlan, route) -> dict:
    """What is stored of a built route: its sharp polyline, length and CPW, enough to stand in for it."""
    return {
        "polyline": [[round(p.x, 4), round(p.y, 4)] for p in rp.polyline()],
        "length": rp.length,
        "target_length": rp.target_length,
        "type": route.type,
        "a": rp.params.get("a"),
        "b": rp.params.get("b"),
        "r": rp.params.get("r"),
    }


def update(path: str | Path, plan, previous: dict | None = None) -> dict:
    """Write the store after a keep-going build: the routes of the design, as they built now, or as they last built
    (``previous``, or what the file holds) when they failed now. Returns the new ``{route: entry}``."""
    path = Path(path)
    old = load(path) if previous is None else previous
    routes = plan.design.routes
    out = {n: e for n, e in old.items() if n in routes}
    for name, rp in plan.routes.items():
        out[name] = entry_of(rp, routes[name])
    data = json.dumps({"schema": SCHEMA, "design": plan.design.name, "routes": out}, indent=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)
    return out


def standin(name: str, entry: dict, defaults: dict | None = None) -> RoutePlan:
    """A :class:`RoutePlan` rebuilt from a stored entry (not drawn: used where a length / width is needed)."""
    params = {k: entry[k] for k in ("a", "b", "r") if entry.get(k) is not None}
    for k, v in (defaults or {}).items():
        params.setdefault(k, v)
    nodes = [Node(pya.DPoint(*p)) for p in entry.get("polyline") or []]
    return RoutePlan(name, nodes, params, entry.get("target_length"), entry.get("length"))


def resolve(plan):
    """``plan`` with each failed route replaced by its last good route (a copy; ``plan`` itself is not changed), for
    the LOM and other readers of route lengths. Each replacement is named in ``plan.warnings`` and in a Python
    warning. A failed route without a last good one raises :class:`RoutingError` naming it. Plans without failures
    come back as they are."""
    if not getattr(plan, "failed", None):
        return plan
    routes, warns, missing = dict(plan.routes), list(getattr(plan, "warnings", [])), []
    for name, f in plan.failed.items():
        if f.last_good and f.last_good.get("polyline"):
            routes[name] = standin(name, f.last_good)
            length = f.last_good.get("length")
            warns.append(
                f"WARNING: route {name} failed to build ({_reason(f.error, name)}); using its last good route"
                + (f" ({length:.1f} µm)" if isinstance(length, (int, float)) else "")
            )
        else:
            missing.append(f"{name} ({_reason(f.error, name)})")
    if missing:
        raise RoutingError(
            "no route for " + "; ".join(missing) + ": it failed to build and no earlier good route is stored; "
            "fix the route (it is drawn in red in KLayout), then build again"
        )
    for w in warns[len(getattr(plan, "warnings", [])):]:
        warnings.warn(w, RuntimeWarning, stacklevel=3)
    out = replace(plan, routes=routes, failed={})
    out.warnings = warns
    return out


def _reason(error: str, name: str) -> str:
    head = f"route {name}: "
    return error[len(head):] if error.startswith(head) else error


def plan_for_lom(design, source=None):
    """The build plan the LOM reads. A design file whose plugin builds stored last good routes beside the layout
    (``build/<stem>.last_good_routes.json``) is planned with ``keep_going``: a failed route is replaced by its last
    good one with a warning (:func:`resolve`). Everything else is the strict plan, which raises on a failed route."""
    from quantcore_circuits.assembly.plan import plan_design  # pylint: disable=import-outside-toplevel

    store = {}
    if isinstance(source, (str, Path)):
        store = load(design_store_path(source))
    if not store:
        return plan_design(design)
    return resolve(plan_design(design, keep_going=True, last_good=store))
