"""Quantum Metal side of the ``metal:<Class>`` wrapper: class lookup, option handling and geometry extraction.

Quantum Metal is imported lazily (the first import takes 5–13 s), so importing this module is cheap and works
inside the KLayout GUI, where Metal is usually not installed.

* :func:`qlibrary_index` lists the ``qiskit_metal.qlibrary`` components by reading their source (no import).
* :func:`template_options` / :func:`normalise_options` validate user options against the class defaults. Bare
  numbers on length options (defaults such as ``'30um'``) are µm, as everywhere in quantcore_circuits.
* :func:`metal_geometry` instantiates the component once in a shared headless ``DesignPlanar`` at the origin with
  orientation 0, reads its rows of ``design.qgeometry.tables`` (``poly``, ``path``, ``junction``) and its pins,
  converts design units (mm) to µm, then deletes the component. Results are cached per (class, options, a, b).

The Element's ``a``/``b`` drive Metal's design variables ``cpw_width``/``cpw_gap``, so Metal pins that default to
``cpw_width`` match the chip's CPW.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import itertools
import json
import logging
import math
import re
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path

from kqcircuits.pya_resolver import pya

_LENGTH = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*(nm|um|µm|mm|cm|m)\s*$")
_NUMBER = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$")

# options set by our placement, never by the user (Metal components are built at the origin, orientation 0)
PLACEMENT_OPTIONS = ("pos_x", "pos_y", "orientation")

# Metal qlibrary sub-package → quantcore category (refined per class in METAL_CATEGORY_OVERRIDES)
METAL_PACKAGE_CATEGORY = {
    "qubits": "qubit",
    "couplers": "coupler",
    "lumped": "capacitor",
    "resonators": "resonator",
    "terminations": "launcher",
    "tlines": "waveguide",
    "sample_shapes": "shape",
    "user_components": "other",
}
METAL_CATEGORY_OVERRIDES = {
    "jj_dolan": "junction",
    "jj_manhattan": "junction",
    "SNAIL": "junction",
    "SQUID_LOOP": "junction",
    "BridgeFreeJunction": "junction",
    "OpenToGround": "termination",
    "ShortToGround": "termination",
    "ResonatorCoilRect": "resonator",
    "Airbridge": "airbridge",
}
# Metal routes need other components' pins: they are not cells. Map them onto qcc routes instead.
ROUTE_MAPPING = {
    "RouteStraight": 'route type "cpw" between the two ports (no nodes)',
    "RouteFramed": 'route type "cpw" with Manhattan "nodes" (the router adds the corners)',
    "RouteAnchors": 'route type "cpw" with the anchors as "nodes"',
    "RoutePathfinder": 'route type "cpw" (the qcc router finds a Manhattan path; add "nodes" to steer it)',
    "RouteMeander": 'route type "meander" with "length" (total_length in µm)',
    "RouteMixed": 'route type "meander" with "length" and the anchors as "nodes"',
}
# per-class rendering of non-base layers (qgeometry row name → KQC layer, None = skip)
SPECIAL_LAYERS = {"Airbridge": {"bridge": "airbridge_flyover", "pads": "airbridge_pads", "posts": None}}

_log = logging.getLogger(__name__)


# ---- class lookup (no Metal import) -----------------------------------------------------------------------------
@dataclass(frozen=True)
class MetalClassInfo:
    name: str
    module: str  # qiskit_metal.qlibrary.<pkg>.<module>
    package: str  # qlibrary sub-package (qubits, couplers, ...)
    category: str
    description: str
    is_route: bool


@cache
def qlibrary_root() -> Path | None:
    spec = importlib.util.find_spec("qiskit_metal")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(list(spec.submodule_search_locations)[0]) / "qlibrary"


@cache
def qlibrary_index() -> dict[str, MetalClassInfo]:
    """All public QComponent classes of ``qiskit_metal.qlibrary``, read from source (fast, no import)."""
    root = qlibrary_root()
    if root is None:
        return {}
    raw = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] == "core" or path.stem.startswith("_") or len(rel.parts) < 2:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        module = "qiskit_metal.qlibrary." + ".".join(rel.with_suffix("").parts)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                continue
            methods = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
            if "make" not in methods:
                continue
            bases = [ast.unparse(b).rsplit(".", 1)[-1] for b in node.bases]
            doc = (ast.get_docstring(node) or "").strip()
            first = next((ln.strip() for ln in doc.splitlines() if ln.strip() and not ln.strip().startswith("..")), "")
            raw[node.name] = (module, rel.parts[0], bases, first[:160])
    routes = {"QRoute"}
    changed = True
    while changed:
        changed = False
        for name, (_, _, bases, _) in raw.items():
            if name not in routes and routes.intersection(bases):
                routes.add(name)
                changed = True
    out = {}
    for name, (module, pkg, _, doc) in raw.items():
        cat = METAL_CATEGORY_OVERRIDES.get(name, METAL_PACKAGE_CATEGORY.get(pkg, "other"))
        out[name] = MetalClassInfo(name, module, pkg, cat, doc, name in routes)
    return out


def find_class_info(name: str) -> MetalClassInfo | None:
    """Look up a qlibrary class by name: exact, case-insensitive, or by module name (``JJ_Manhattan``)."""
    index = qlibrary_index()
    if name in index:
        return index[name]
    low = name.lower()
    for info in index.values():
        if info.name.lower() == low:
            return info
    by_module = [i for i in index.values() if i.module.rsplit(".", 1)[-1].lower() == low]
    return by_module[0] if len(by_module) == 1 else None


def canonical_class_name(metal_class: str) -> str:
    """Canonical spelling of a Metal class reference (qlibrary class name, or a dotted path kept as is)."""
    if "." in metal_class:
        return metal_class
    info = find_class_info(metal_class)
    if info is None:
        known = ", ".join(sorted(qlibrary_index())) or "(Quantum Metal not installed)"
        raise ValueError(f"unknown Quantum Metal component {metal_class!r}; qlibrary has: {known}")
    return info.name


@cache
def metal_class(metal_class_ref: str):
    """The QComponent class for a qlibrary name or a dotted path (imports Quantum Metal)."""
    name = canonical_class_name(metal_class_ref)
    if "." in name:
        module_name, _, cls_name = name.rpartition(".")
    else:
        info = qlibrary_index()[name]
        if info.is_route:
            raise ValueError(f"metal:{name} is a Metal route, not a cell: use a qcc {ROUTE_MAPPING.get(name, 'route')}")
        module_name, cls_name = info.module, name
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ValueError(f"Quantum Metal component {name!r} cannot be imported: {e}") from e
    cls = getattr(module, cls_name, None)
    if cls is None:
        raise ValueError(f"{module_name!r} has no Quantum Metal component {cls_name!r}")
    return cls


# ---- shared design ----------------------------------------------------------------------------------------------
_counter = itertools.count()


@cache
def shared_design():
    """One headless ``DesignPlanar`` reused for every component (components are deleted after reading)."""
    from qiskit_metal import designs  # pylint: disable=import-outside-toplevel

    design = designs.DesignPlanar({}, overwrite_enabled=True)
    design.logger.setLevel(logging.ERROR)
    return design


def _plain(obj):
    """Metal ``Dict``/numpy values → plain JSON-able Python."""
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            return obj.item()
        except (TypeError, ValueError):
            pass
    return obj


@cache
def _template_options_json(metal_class_ref: str) -> str:
    cls = metal_class(metal_class_ref)
    return json.dumps(_plain(cls.get_template_options(shared_design())), sort_keys=True, default=str)


def template_options(metal_class_ref: str) -> dict:
    """Default options of a Metal class (fresh copy; nested dicts included, e.g. ``_default_connection_pads``)."""
    return json.loads(_template_options_json(metal_class_ref))


def user_options(metal_class_ref: str) -> list[str]:
    """Option names a user may set (the defaults minus placement and private ``_default_*`` templates)."""
    return sorted(k for k in template_options(metal_class_ref) if not k.startswith("_") and k not in PLACEMENT_OPTIONS)


# Metal's default design variables (qiskit_metal/_defaults.py: cpw_width "10 um", cpw_gap "6 um"); an option whose
# default is one of them (LaunchpadWirebond* trace_width/trace_gap, couplers' cpw widths) is a length too
METAL_LENGTH_VARIABLES = ("cpw_width", "cpw_gap")


def is_length(default) -> bool:
    """A Metal option default that is a length: ``'455um'``-style, or one of :data:`METAL_LENGTH_VARIABLES`."""
    return isinstance(default, str) and (bool(_LENGTH.match(default)) or default.strip() in METAL_LENGTH_VARIABLES)


def _normalise(value, default, fallback=None):
    if isinstance(value, dict):
        tmpl = default if isinstance(default, dict) else {}
        return {str(k): _normalise(v, tmpl.get(k, fallback)) for k, v in value.items()}
    if isinstance(value, bool) or value is None:
        return value
    if is_length(default):
        if isinstance(value, (int, float)):
            return f"{value}um"
        if isinstance(value, str) and _NUMBER.match(value):
            return f"{value.strip()}um"
    return value


def flat_options(params: dict | None) -> dict:
    """A metal cell's ``params`` with its ``options`` (a dict, or the JSON text of the PCell form, e.g. what the KLayout
    plugin's parameter table writes) merged into the flat keys; a flat key wins, as in ``MetalComponent.qcc_params``.
    The LOM and the design checks read the flat form."""
    p = dict(params or {})
    opts = p.pop("options", None)
    if isinstance(opts, str):
        opts = json.loads(opts) if opts.strip() else {}
    return {**(opts or {}), **p}


def normalise_options(metal_class_ref: str, options: dict) -> dict:
    """Validate and normalise user options: unknown or placement options raise; bare numbers on length options
    become µm strings (``455`` → ``'455um'``); nested dicts (``connection_pads``) are normalised against their
    ``_default_<name>`` template."""
    defaults = template_options(metal_class_ref)
    placement = sorted(set(options) & set(PLACEMENT_OPTIONS))
    if placement:
        raise ValueError(
            f"metal:{metal_class_ref}: {placement} are set by the placement; use place at/rot instead (Metal "
            "components are built at the origin with orientation 0)"
        )
    unknown = sorted(k for k in options if k not in defaults or k.startswith("_"))
    if unknown:
        raise ValueError(
            f"metal:{metal_class_ref}: unknown option(s) {unknown}; options: {user_options(metal_class_ref)}"
        )
    return {k: _normalise(v, defaults.get(k), defaults.get(f"_default_{k}")) for k, v in options.items()}


def parse_um(value, a: float = 10.0, b: float = 6.0) -> float:
    """A Metal length (``'455um'``, ``'0.455mm'``, ``'cpw_width'``, or a bare number in mm) in µm."""
    design = shared_design()
    design.variables["cpw_width"], design.variables["cpw_gap"] = f"{a}um", f"{b}um"
    return float(design.parse_value(value)) * 1000.0


# ---- geometry ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MetalPin:
    name: str
    middle: tuple[float, float]  # µm
    normal: tuple[float, float]  # outward unit vector
    width: float  # µm
    gap: float  # µm


@dataclass(frozen=True)
class MetalJunction:
    name: str
    points: tuple[tuple[float, float], ...]  # µm, the junction line
    width: float  # µm


@dataclass(frozen=True)
class MetalGeometry:
    """A Metal component's geometry in µm (polygons as ``pya.DPolygon``, paths already buffered)."""

    metal_class: str
    subtract: tuple = ()  # DPolygons removed from ground
    metal: tuple = ()  # DPolygons of (non-subtract) metal
    layers: dict = field(default_factory=dict)  # KQC layer name → DPolygons (special layers, e.g. airbridges)
    junctions: tuple[MetalJunction, ...] = ()
    pins: dict = field(default_factory=dict)  # name → MetalPin
    options: dict = field(default_factory=dict)  # resolved Metal options (strings, as Metal sees them)


def _shapely_polygons(geom):
    gtype = geom.geom_type
    if gtype == "Polygon":
        return [geom]
    if gtype in ("MultiPolygon", "GeometryCollection"):
        return [g for part in geom.geoms for g in _shapely_polygons(part)]
    return []


def _dpolygon(poly, scale: float) -> pya.DPolygon:
    hull = [pya.DPoint(x * scale, y * scale) for x, y in list(poly.exterior.coords)[:-1]]
    out = pya.DPolygon(hull)
    for ring in poly.interiors:
        out.insert_hole([pya.DPoint(x * scale, y * scale) for x, y in list(ring.coords)[:-1]])
    return out


def fillet_polyline(points: list[pya.DPoint], radius: float, n: int = 64) -> list[pya.DPoint]:
    """Round the interior corners of a polyline with circular arcs of ``radius`` (reduced where segments are too
    short: each corner may use half of an interior segment, all of an end segment)."""
    if radius <= 0 or len(points) < 3:
        return list(points)
    out = [points[0]]
    seg = [(points[i + 1] - points[i]).length() for i in range(len(points) - 1)]
    for i in range(1, len(points) - 1):
        p0, p1, p2 = points[i - 1], points[i], points[i + 1]
        v1, v2 = p1 - p0, p2 - p1
        l1, l2 = v1.length(), v2.length()
        if l1 == 0 or l2 == 0:
            continue
        u1, u2 = v1 / l1, v2 / l2
        turn = math.atan2(u1.x * u2.y - u1.y * u2.x, u1.x * u2.x + u1.y * u2.y)
        if abs(turn) < 1e-9:
            out.append(p1)
            continue
        room1 = seg[i - 1] if i == 1 else seg[i - 1] / 2
        room2 = seg[i] if i == len(points) - 2 else seg[i] / 2
        t = min(radius * math.tan(abs(turn) / 2), room1, room2)
        r = t / math.tan(abs(turn) / 2)
        start = p1 - u1 * t
        normal = pya.DVector(-u1.y, u1.x) * (1 if turn > 0 else -1)
        centre = start + normal * r
        a0 = math.atan2(start.y - centre.y, start.x - centre.x)
        steps = max(2, int(math.ceil(abs(turn) / (2 * math.pi) * n)))
        for k in range(steps + 1):
            a = a0 + turn * k / steps
            out.append(pya.DPoint(centre.x + r * math.cos(a), centre.y + r * math.sin(a)))
    out.append(points[-1])
    return out


def _path_polygon(coords, width: float, fillet: float | None, scale: float) -> pya.DPolygon:
    pts = [pya.DPoint(x * scale, y * scale) for x, y in coords]
    w = width * scale
    # Metal's GDS renderer bends a path only when fillet >= width / 2
    if fillet is not None and not math.isnan(fillet) and fillet > 0 and fillet >= 0.5 * width:
        pts = fillet_polyline(pts, fillet * scale)
    return pya.DPath(pts, w, 0, 0).polygon()


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


@lru_cache(maxsize=512)
def metal_geometry(metal_class_ref: str, options_json: str = "{}", a: float = 10.0, b: float = 6.0) -> MetalGeometry:
    """Instantiate a Metal component headless and return its geometry in µm (cached; treat the result as
    read-only). ``options_json`` holds normalised options (see :func:`normalise_options`)."""
    name = canonical_class_name(metal_class_ref)
    cls = metal_class(name)
    design = shared_design()
    design.variables["cpw_width"], design.variables["cpw_gap"] = f"{a}um", f"{b}um"
    options = json.loads(options_json)
    options.update(pos_x="0um", pos_y="0um", orientation="0")
    comp_name = f"qcc_metal_{next(_counter)}"
    scale = 1000.0 if design.get_units() == "mm" else 1.0
    special = SPECIAL_LAYERS.get(name.rsplit(".", 1)[-1], {})
    try:
        comp = cls(design, comp_name, options=options)
        subtract, metal, layers, junctions = [], [], {}, []
        for table_name in ("poly", "path"):
            table = design.qgeometry.tables[table_name]
            rows = table[table["component"] == comp.id]
            for _, row in rows.iterrows():
                if bool(row.get("helper", False)):
                    continue
                fillet = _num(row.get("fillet"))
                if table_name == "poly":
                    polys = [_dpolygon(p, scale) for p in _shapely_polygons(row.geometry)]
                    if fillet:
                        polys = [_round(p, fillet * scale) for p in polys]
                else:
                    width = _num(row.get("width")) or 0.0
                    if row.geometry.geom_type != "LineString" or width <= 0:
                        continue
                    polys = [_path_polygon(list(row.geometry.coords), width, fillet, scale)]
                row_name = str(row["name"])
                if row_name in special:
                    if special[row_name] is not None:
                        layers.setdefault(special[row_name], []).extend(polys)
                    continue
                (subtract if bool(row.get("subtract", False)) else metal).extend(polys)
        table = design.qgeometry.tables["junction"]
        for _, row in table[table["component"] == comp.id].iterrows():
            if row.geometry.geom_type != "LineString":
                continue
            pts = tuple((x * scale, y * scale) for x, y in row.geometry.coords)
            junctions.append(MetalJunction(str(row["name"]), pts, (_num(row.get("width")) or 0.0) * scale))
        pins = {}
        for pin_name, pin in comp.pins.items():
            mid, nrm = pin["middle"], pin["normal"]
            norm = math.hypot(float(nrm[0]), float(nrm[1])) or 1.0
            pins[str(pin_name)] = MetalPin(
                str(pin_name),
                (round(float(mid[0]) * scale, 6), round(float(mid[1]) * scale, 6)),
                (_snap(float(nrm[0]) / norm), _snap(float(nrm[1]) / norm)),
                round(float(pin["width"]) * scale, 6),
                round(float(pin["gap"]) * scale, 6),
            )
        resolved = _plain(comp.options)
    finally:
        if comp_name in design.name_to_id:
            design.delete_component(comp_name)
    for k in PLACEMENT_OPTIONS:
        resolved.pop(k, None)
    return MetalGeometry(
        name,
        tuple(subtract),
        tuple(metal),
        {k: tuple(v) for k, v in layers.items()},
        tuple(junctions),
        pins,
        resolved,
    )


def _snap(x: float) -> float:
    r = round(x)
    return float(r) if abs(x - r) < 1e-9 else x


def _round(poly: pya.DPolygon, radius: float) -> pya.DPolygon:
    return poly.round_corners(radius, radius, 64)
