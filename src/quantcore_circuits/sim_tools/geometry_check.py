"""Geometry checks of an exported Ansys job folder (no solver, no AEDT): what Q3D / HFSS reject or silently get wrong.

The checks read what AEDT imports: ``<sim>.json`` (KQC layers with z, thickness and excitation; ports) and
``<sim>.gds`` (one AEDT object per GDS polygon, named ``<layer>_<k>``).

* **nets disjoint** — two metal objects of different excitations (KQC nets) must not touch or overlap where their
  z ranges meet: Q3D stops with ``Object 'a' in Net 'x' and object 'b' in Net 'y' are touching``.
* **no point / edge contacts** — two objects of the *same* net that touch without overlapping (e.g. a junction pad
  ending on a curved island at one polygon vertex) count as connected for KQC (``Region.interacting``) but not for
  Q3D's ``AutoIdentifyNets``, which splits the net and then reports the same "touching" error.
* **one piece per net** — a signal net in two disconnected pieces becomes two Q3D nets (C-matrix rows mislabelled).
* **floating metal off the boundary** — a signal object reaching the top or bottom of the simulation domain (an
  indium bump with no opposite face) is shorted to the outer boundary in HFSS and adds a pillar's capacitance in Q3D.
* **junction ports** — each junction port has a polygon that KQC itself could build (its signal and ground points on
  metal edges: no ``Unable to create polygon for port`` warning), the sheet lies in the gap (no metal inside it), its
  signal and ground edges touch two *different* nets, neither island net reaches the box edge (joined to the ground
  plane), and the signal net carries the port's island label.
* **line / pad ports** — every other internal port has a polygon (a line end the box edge cuts in a bend or a taper
  has none) and its signal and ground points lie on it (AEDT draws the port's current line between them).

Use :func:`check_job` (``{"errors": [...], "warnings": [...]}``) or ``python scripts/check_sim_export.py <job>...``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from kqcircuits.pya_resolver import pya

AREA_EPS_UM2 = 1e-6  # overlap below this is a touch, not a galvanic join
PORT_METAL_EPS_UM2 = 0.05  # metal allowed inside a port sheet (rounding at its corners)


@dataclass
class MetalObject:
    """One AEDT object: a GDS polygon of a KQC metal layer."""

    name: str  # AEDT-style name, ``<layer>_<k>``
    layer: str
    excitation: int
    z0: float
    z1: float
    region: pya.Region
    bbox: pya.Box


def _read(job: Path) -> tuple[dict, dict, pya.Layout]:
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    sim_name = meta.get("simulation_name") or job.name
    sim = json.loads((job / f"{sim_name}.json").read_text(encoding="utf-8"))
    layout = pya.Layout()
    layout.read(str(job / sim.get("gds_file", f"{sim_name}.gds")))
    return meta, sim, layout


def metal_objects(sim: dict, layout: pya.Layout) -> list[MetalObject]:
    """The metal objects AEDT creates: one per GDS polygon of every layer with an ``excitation``."""
    top = layout.top_cell()
    out = []
    for name, d in sim.get("layers", {}).items():
        if "excitation" not in d or "layer" not in d:
            continue
        li = layout.find_layer(int(d["layer"]), 0)
        if li is None:
            continue
        z = float(d.get("z", 0.0))
        t = float(d.get("thickness", 0.0))
        it = top.begin_shapes_rec(li)
        k = 0
        while not it.at_end():
            shape = it.shape()
            if shape.is_polygon() or shape.is_box() or shape.is_path() or shape.is_simple_polygon():
                poly = shape.polygon.transformed(it.trans())
                region = pya.Region(poly)
                out.append(MetalObject(f"{name}_{k}", name, int(d["excitation"]), min(z, z + t), max(z, z + t),
                                       region, poly.bbox()))
                k += 1
            it.next()
    return out


def _domain_z(sim: dict) -> tuple[float, float]:
    zs = [float(d.get("z", 0.0)) for d in sim.get("layers", {}).values()]
    zs += [float(d.get("z", 0.0)) + float(d.get("thickness", 0.0)) for d in sim.get("layers", {}).values()]
    return (min(zs), max(zs)) if zs else (0.0, 0.0)


def _where(region: pya.Region, dbu: float) -> str:
    b = region.bbox().to_dtype(dbu)
    return f"({b.center().x:.1f}, {b.center().y:.1f}) µm"


def check_nets(objs: list[MetalObject], dbu: float, z_eps: float = 1e-9) -> tuple[list[str], list[str]]:
    """Net disjointness, same-net point/edge contacts and pieces per net (see module docstring)."""
    errors, warnings = [], []
    parent = list(range(len(objs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    area_eps = AREA_EPS_UM2 / dbu**2
    for i, a in enumerate(objs):
        for j in range(i + 1, len(objs)):
            b = objs[j]
            if a.z0 > b.z1 + z_eps or b.z0 > a.z1 + z_eps or not a.bbox.touches(b.bbox):
                continue
            if a.region.interacting(b.region).is_empty():
                continue
            overlap = (a.region & b.region).area()
            if a.excitation != b.excitation:
                kind = "overlap" if overlap > area_eps else "touch"
                errors.append(
                    f"nets {a.excitation} and {b.excitation} {kind}: {a.name} / {b.name} at "
                    f"{_where(a.region & b.region if overlap else (a.region.sized(1) & b.region.sized(1)), dbu)}"
                )
            elif overlap <= area_eps and a.excitation != 0:
                # ground objects are separate Q3D ground nets anyway; a signal net joined at a point/edge is split
                errors.append(
                    f"net {a.excitation}: {a.name} and {b.name} touch without overlapping (AEDT sees two "
                    f"conductors) at {_where(a.region.sized(1) & b.region.sized(1), dbu)}"
                )
            else:
                parent[find(i)] = find(j)
    pieces: dict[int, set[int]] = {}
    for i, o in enumerate(objs):
        pieces.setdefault(o.excitation, set()).add(find(i))
    for exc, roots in sorted(pieces.items()):
        if exc != 0 and len(roots) > 1:
            warnings.append(f"net {exc} is {len(roots)} separate conductors (Q3D makes one net of each)")
    return errors, warnings


def _excitation_at(objs: list[MetalObject], point: pya.DPoint, dbu: float, z: float) -> int | None:
    p = point.to_itype(dbu)
    probe = pya.Region(pya.Box(p.x - 1, p.y - 1, p.x + 1, p.y + 1))
    hits = {
        o.excitation for o in objs if o.z0 - 1e-9 <= z <= o.z1 + 1e-9 and not o.region.interacting(probe).is_empty()
    }
    return hits.pop() if len(hits) == 1 else (None if not hits else -1)


def _touches_box_edge(sim: dict, objs: list[MetalObject], excitation: int, dbu: float) -> bool:
    box = sim.get("box") or {}
    try:
        b = pya.DBox(box["p1"]["x"], box["p1"]["y"], box["p2"]["x"], box["p2"]["y"]).to_itype(dbu)
    except (KeyError, TypeError):
        return False
    edges = pya.Region(b).edges()
    return any(o.excitation == excitation and not o.region.interacting(edges).is_empty() for o in objs)


def check_junction_ports(meta: dict, sim: dict, objs: list[MetalObject], dbu: float) -> tuple[list[str], list[str]]:
    """Junction-port polygons (see module docstring)."""
    from kqcircuits.simulations.export.util import find_edge_from_point_in_polygons  # pylint: disable=C0415

    errors, warnings = [], []
    labels = {int(k): v for k, v in (meta.get("nets") or {}).items()}
    info = {p["number"]: p for p in meta.get("ports") or []}
    capacitance = meta.get("analysis") in ("q3d_cmatrix", "elmer_cap", "palace_cap")
    edge_ports = [p for p in sim.get("ports") or [] if p.get("type") == "EdgePort" and p.get("signal_location")]
    for port in sim.get("ports") or []:
        if not port.get("junction"):
            continue
        n = port["number"]
        name = (info.get(n) or {}).get("name", f"port {n}")
        sig, gnd = port.get("signal_location"), port.get("ground_location")
        if sig is None or gnd is None:
            continue
        z = float(sig[2]) if len(sig) > 2 else 0.0
        same_z = [o for o in objs if o.z0 - 1e-9 <= z <= o.z1 + 1e-9 and o.z0 == o.z1]
        polys = [p for o in same_z for p in o.region.each()]
        kqc_ok = True
        for what, loc in (("signal", sig), ("ground", gnd)):
            try:
                find_edge_from_point_in_polygons(polys, pya.DPoint(loc[0], loc[1]), dbu)
            except (ValueError, IndexError):
                kqc_ok = False
                errors.append(
                    f"{name} (port {n}): KQC finds no metal edge at the {what} point ({loc[0]:.2f}, {loc[1]:.2f}) — "
                    "'Unable to create polygon for port' (the polygon in the job is a stand-in, if any)"
                )
        if "polygon" not in port:
            errors.append(f"{name} (port {n}): no port polygon (AEDT skips the port)")
            continue
        if not kqc_ok:  # narrow_junction_port drew a stand-in sheet: does it still bridge two nets?
            name = f"{name} [stand-in sheet]"
        poly = pya.DPolygon([pya.DPoint(p[0], p[1]) for p in port["polygon"]]).to_itype(dbu)
        sheet = pya.Region(poly)
        metal = pya.Region()
        for o in same_z:
            metal += o.region
        inside = (sheet & metal.merged()).area() * dbu**2
        if inside > PORT_METAL_EPS_UM2:
            errors.append(
                f"{name} (port {n}): {inside:.2f} µm² of metal inside the port sheet (the junction is shorted)"
            )
        s, g = pya.DPoint(sig[0], sig[1]), pya.DPoint(gnd[0], gnd[1])
        v = s - g
        if v.length() == 0:
            errors.append(f"{name} (port {n}): signal and ground points coincide")
            continue
        v = v * (min(0.05, v.length() / 4) / v.length())
        e_sig = _excitation_at(objs, s + v, dbu, z)
        e_gnd = _excitation_at(objs, g - v, dbu, z)
        if e_sig is None or e_gnd is None:
            errors.append(f"{name} (port {n}): no metal beyond the {'signal' if e_sig is None else 'ground'} edge")
        elif e_sig == e_gnd:
            errors.append(f"{name} (port {n}): both port edges are on net {e_sig} (the junction is shorted)")
        else:
            for side, e in (("signal", e_sig), ("far", e_gnd)):
                if e > 0 and _touches_box_edge(sim, objs, e, dbu):
                    cut = [p["number"] for p in edge_ports
                           if _excitation_at(objs, pya.DPoint(*p["signal_location"][:2]), dbu, z) == e]
                    if capacitance and cut:  # Q3D: a line of this net ends in an EdgePort at the box (a cut line)
                        warnings.append(f"{name} (port {n}): the {side}-side island (net {e}) includes a line cut by "
                                        f"the box at edge port(s) {cut}: its capacitance includes the cut line")
                        continue
                    errors.append(f"{name} (port {n}): the {side}-side island (net {e}) reaches the simulation box "
                                  "edge — joined to the ground plane (e.g. an unconnected lead port) or to a line "
                                  "that leaves the box")
            want = (info.get(n) or {}).get("excitation")
            if want and labels.get(e_sig) != want:
                warnings.append(f"{name} (port {n}): signal side is net {e_sig} = {labels.get(e_sig)!r}, not {want!r}")
            if port.get("floating") and e_gnd != 0 and e_gnd not in labels:
                warnings.append(f"{name} (port {n}): far island (net {e_gnd}) has no label")
            if not port.get("floating") and e_gnd != 0:
                errors.append(f"{name} (port {n}): grounded junction port ends on net {e_gnd}, not on ground")
    return errors, warnings


def check_other_ports(meta: dict, sim: dict) -> list[str]:
    """Internal ports that are not junctions (50 Ω pad / edge-lumped ports, waveguide stubs) without a polygon: KQC
    logged ``Unable to create polygon for port`` and AEDT skips the port (that line end is left open). An edge-lumped
    port has one wherever the box edge crosses a straight section of its line, square or at an angle (the builder
    then puts the port on the line's own axis); a bend or a taper at the edge is what remains."""
    info = {p["number"]: p for p in meta.get("ports") or []}
    out = []
    for port in sim.get("ports") or []:
        if port.get("junction") or port.get("type") != "InternalPort" or "polygon" in port:
            continue
        p = info.get(port["number"]) or {}
        hint = (" (the box edge cuts this line in a bend or a taper: change margin_um so it crosses a straight "
                "section)" if p.get("kind") == "edge_lumped" else "")
        out.append(f"{p.get('name', '?')} (port {port['number']}, {p.get('kind', '?')}): no port polygon — KQC found "
                   f"no metal edge at its signal/ground point, AEDT skips the port{hint}")
    return out


PORT_LINE_TOL_UM = 1e-7  # AEDT refused a current-line end 1e-5 µm outside its port sheet (m53 FLNE_3, 2026-11-18)


def check_port_lines(meta: dict, sim: dict) -> list[str]:
    """Non-junction internal ports whose signal or ground point lies outside the port polygon: AEDT's Lumped RLC /
    lumped port current line runs between those points and must lie on the sheet ("Both endpoints of the directed
    line must lie on the boundary face"); on a slanted port a point off the database grid misses the polygon by a
    fraction of a nm."""
    info = {p["number"]: p for p in meta.get("ports") or []}
    out = []
    for port in sim.get("ports") or []:
        if port.get("junction") or port.get("type") != "InternalPort" or "polygon" not in port:
            continue
        poly = pya.DPolygon([pya.DPoint(p[0], p[1]) for p in port["polygon"]])
        for what in ("signal", "ground"):
            loc = port.get(f"{what}_location")
            if loc is None:
                continue
            pt = pya.DPoint(loc[0], loc[1])
            off = 0.0 if poly.inside(pt) else min(e.distance_abs(pt) for e in poly.each_edge())
            if off > PORT_LINE_TOL_UM:
                p = info.get(port["number"]) or {}
                out.append(f"{p.get('name', '?')} (port {port['number']}, {p.get('kind', '?')}): the {what} point lies "
                           f"{off:.2g} µm outside the port polygon — AEDT refuses the port's current line")
    return out


GDS_SIGNED_RECORD_POINTS = 4095  # an XY record of more points is longer than 0x8000 bytes


def check_gds_records(objs: list[MetalObject]) -> list[str]:
    """Polygons whose GDS XY record exceeds 0x7fff bytes (> 4095 points): KLayout reads them as unsigned with a
    warning; readers that take the record length as signed (not verified for AEDT) reject or truncate them."""
    big = [(o.name, p.num_points()) for o in objs for p in o.region.each() if p.num_points() > GDS_SIGNED_RECORD_POINTS]
    return [f"{name}: {n} points in one GDS polygon (> {GDS_SIGNED_RECORD_POINTS}: XY record > 0x8000 bytes)"
            for name, n in big]


def check_gds_other_layers(sim: dict, layout: pya.Layout) -> list[str]:
    """:func:`check_gds_records` for the non-metal layers of the GDS (gap layers AEDT imports as mesh-seed sheets)."""
    top = layout.top_cell()
    out = []
    for name, d in sim.get("layers", {}).items():
        if "excitation" in d or "layer" not in d:
            continue
        li = layout.find_layer(int(d["layer"]), 0)
        if li is None:
            continue
        for k, p in enumerate(pya.Region(top.begin_shapes_rec(li)).each()):
            if p.num_points() > GDS_SIGNED_RECORD_POINTS:
                out.append(f"{name} polygon {k}: {p.num_points()} points in one GDS polygon (> "
                           f"{GDS_SIGNED_RECORD_POINTS}: XY record > 0x8000 bytes)")
    return out


def check_boundary(sim: dict, objs: list[MetalObject]) -> list[str]:
    """Signal metal reaching the top or bottom of the simulation domain (a bump without its opposite face)."""
    z_lo, z_hi = _domain_z(sim)
    out = []
    for o in objs:
        if o.excitation != 0 and o.z1 > o.z0 and (math.isclose(o.z1, z_hi) or math.isclose(o.z0, z_lo)):
            out.append(f"{o.name} (net {o.excitation}) reaches the {'top' if math.isclose(o.z1, z_hi) else 'bottom'}"
                       f" of the domain ({o.z0:g}–{o.z1:g} µm): metal to the outer boundary")
    return out


def check_job(job_dir: str | Path) -> dict:
    """All checks of one exported Ansys job folder: ``{"job", "errors", "warnings", "nets", "objects"}``."""
    job = Path(job_dir)
    meta, sim, layout = _read(job)
    dbu = layout.dbu
    objs = metal_objects(sim, layout)
    errors, warnings = check_nets(objs, dbu)
    e2, w2 = check_junction_ports(meta, sim, objs, dbu)
    errors += e2
    warnings += w2
    errors += check_boundary(sim, objs)
    capacitance = meta.get("analysis") in ("q3d_cmatrix", "elmer_cap", "palace_cap")
    # Q3D solves nets, not ports: a missing line-port polygon matters for HFSS (eigenmode / driven) only
    (warnings if capacitance else errors).extend(check_other_ports(meta, sim) + check_port_lines(meta, sim))
    warnings += check_gds_records(objs) + check_gds_other_layers(sim, layout)
    excitations = sorted({o.excitation for o in objs if o.excitation})
    labels = {int(k) for k in (meta.get("nets") or {})}
    if capacitance:
        unnamed = [e for e in excitations if e not in labels]
        if unnamed:
            warnings.append(f"nets without a design label: {unnamed}")
    return {"job": str(job), "errors": errors, "warnings": warnings, "nets": len(excitations), "objects": len(objs)}
