"""Netlist check: connections declared in ``design.json`` vs. the geometric netlist KQC extracts from the layout.

*Declared* connections come from routes with two port ends (``from`` ↔ ``to``), from snap placements with
``gap == 0`` (``snap`` ↔ ``to``) and from ``wire`` couplings. Route ends that are free or hangers are declared
*open* (connected to nothing).

*Extracted* connections come from KQC ``export_cell_netlist``: KLayout joins overlapping port texts into nets.
Waveguides, meanders and other unnamed sub-elements inside routes are treated as wire, so following them from one
named-instance pin to the next gives the galvanic connections between design ports.

``check_netlist`` reports ``opens`` (declared, not found in the layout) and ``shorts`` (found, not declared) with
the port coordinates in µm.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from quantcore_circuits.design.schema import CHIP


@dataclass
class NetlistIssue:
    kind: str  # "open" | "short"
    ports: tuple[str, ...]
    where: list[tuple[float, float]]

    def __str__(self) -> str:
        at = ", ".join(f"({x:.1f}, {y:.1f})" for x, y in self.where)
        return f"{self.kind}: {' <-> '.join(self.ports)} at {at}"


@dataclass
class NetlistReport:
    declared: set[frozenset[str]]
    extracted: set[frozenset[str]]
    issues: list[NetlistIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def opens(self) -> list[NetlistIssue]:
        return [i for i in self.issues if i.kind == "open"]

    @property
    def shorts(self) -> list[NetlistIssue]:
        return [i for i in self.issues if i.kind == "short"]


def declared_connections(design, skip=()) -> set[frozenset[str]]:
    """Port groups that ``design`` says are galvanically connected (singletons = open ends). ``skip`` names routes
    that were not built (failed): the check reports them once, as ``route_failed``, not as opens."""
    out: set[frozenset[str]] = set()
    for rname, route in design.routes.items():
        if rname in skip:
            continue
        ends = [e for e in (route.from_, route.to) if isinstance(e, str)]
        if any(e.split(".", 1)[0] == CHIP for e in ends):
            continue  # chip launchers live inside DesignChip itself, not as named instances
        out.add(frozenset(ends))
    for name, inst in design.instances.items():
        p = inst.place
        if p.snap and p.to and abs(p.gap) < 1e-9:
            out.add(frozenset({p.snap if "." in p.snap else f"{name}.{p.snap}", p.to}))
    for c in design.couplings.values():  # wire couplings: galvanic joins of overlapping ports
        if c.type == "wire":
            out.add(frozenset(c.between))
    return out


def extract_netlist(cell) -> dict:
    """KQC ``export_cell_netlist`` of ``cell`` as a dict."""
    from kqcircuits.util.netlist_extraction import export_cell_netlist  # pylint: disable=import-outside-toplevel

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "netlist.json"
        export_cell_netlist(cell, str(path))
        if not path.exists():  # KQC writes nothing when the cell has no circuit (no port texts connect anywhere)
            return {}
        return json.loads(path.read_text(encoding="utf-8"))


def extracted_connections(
    netlist: dict, instance_names: set[str], face_ports: dict[str, dict[str, str]] | None = None
) -> set[frozenset[str]]:
    """Connected groups of named-instance ports in a KQC netlist (unnamed sub-circuits are wire).

    ``face_ports`` (``{instance: {face: port}}``) names the unnamed pins of cells whose ports record their chip face
    (KQC ``FlipChipConnectorRf`` labels both CPW ends ``""``): such a pin is the port on the face of the route piece
    it meets (that piece's ``face_ids[0]``). Other unnamed pins are ``port``."""
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    subs = netlist.get("subcircuits", {})

    def named(sid) -> str | None:
        name = subs.get(str(sid), {}).get("instance_name")
        return name if name in instance_names else None

    circuits = netlist.get("circuits", {})

    def net_face(pins) -> str | None:
        for p in pins:  # a route piece (not a design instance) is drawn on its first face
            sub = subs.get(str(p["subcircuit_id"]), {})
            faces = (circuits.get(sub.get("cell_name")) or {}).get("face_ids")
            if named(p["subcircuit_id"]) is None and faces:
                return str(faces[0])
        return None

    def pin_name(p, pins) -> str:
        if not p["pin"].startswith("$"):
            return p["pin"]
        by_face = (face_ports or {}).get(named(p["subcircuit_id"]))
        return (by_face or {}).get(net_face(pins), "port") if by_face else "port"

    for pins in netlist.get("nets", {}).values():
        # An unnamed KQC port (``add_port("")``, refpoint ``port``, e.g. Launcher) has no pin name: KLayout calls it $N
        keys = [(p["subcircuit_id"], pin_name(p, pins)) for p in pins]
        for k in keys:
            find(k)
            if named(k[0]) is None:  # wire: all pins of an unnamed sub-circuit are one conductor
                union(k, ("wire", k[0]))
        for a, b in zip(keys, keys[1:]):
            union(a, b)
    groups: dict = {}
    for key in list(parent):
        if key[0] == "wire":
            continue
        inst = named(key[0])
        if inst is not None:
            groups.setdefault(find(key), set()).add(f"{inst}.{key[1]}")
    return {frozenset(g) for g in groups.values()}


def _merge_groups(groups: set[frozenset[str]], pairs) -> set[frozenset[str]]:
    """``groups`` with every pair in ``pairs`` joined (union-find over port names)."""
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for g in groups:
        if not g:
            continue
        first, *rest = sorted(g)
        for x in rest:
            parent[find(x)] = find(first)
        find(first)
    for a, b in pairs:
        parent[find(a)] = find(b)
    out: dict[str, set[str]] = {}
    for x in parent:
        out.setdefault(find(x), set()).add(x)
    return {frozenset(g) for g in out.values()}


def check_netlist(result) -> NetlistReport:
    """Compare ``result`` (a :class:`~quantcore_circuits.assembly.BuildResult`) with its design (see module doc)."""
    design = result.design
    # galvanic connectivity is transitive: a port in two declared connections (a feedline pad that is also wired to
    # an overlapping cell) makes one group, as the extraction does
    declared = _merge_groups(declared_connections(design, skip=set(result.plan.failed)), [])
    netlist = extract_netlist(result.cell)
    face_ports: dict[str, dict[str, str]] = {}  # instances whose ports record their face (TSV / bump transitions)
    for name, inst in result.plan.instances.items():
        faces = [p.face for p in inst.local_ports.values() if p.face]
        for port in inst.local_ports.values():
            if port.face and faces.count(port.face) == 1:
                face_ports.setdefault(name, {})[port.face] = port.name
    # two arguments when no port records a face, so callers that replace extracted_connections keep working
    args = (netlist, set(design.instances)) + ((face_ports,) if face_ports else ())
    extracted = extracted_connections(*args)
    ports = result.plan.all_ports()

    def where(names) -> list[tuple[float, float]]:
        return [(ports[n].pos.x, ports[n].pos.y) for n in sorted(names) if n in ports]

    # ``wire`` couplings join metal that overlaps without coinciding port texts, which KLayout's extraction cannot
    # see: the check trusts them and merges each wire pair into the extracted groups.
    extracted = _merge_groups(extracted, [c.between for c in design.couplings.values() if c.type == "wire"])
    # Ports the design does not mention (e.g. an unused claw) are not checked.
    mentioned = set().union(*declared) if declared else set()
    found = {frozenset(g & mentioned) for g in extracted if g & mentioned}
    issues = [NetlistIssue("open", tuple(sorted(g)), where(g)) for g in sorted(declared - found, key=sorted)]
    issues += [NetlistIssue("short", tuple(sorted(g)), where(g)) for g in sorted(found - declared, key=sorted)]
    return NetlistReport(declared, found, issues)
