"""Subset simulation: render and simulate only some qubits of a chip, keep the netlist whole.

The user names the qubits (and optionally their readout resonators) to simulate, e.g. ``pairs=[("Q3", "R3"), ("Q5",
"R5")]``; :func:`plan_subset` turns that into ordinary sim groups (:class:`~quantcore_circuits.design.schema.SimGroup`)
that the builder, the exporters, AEDT and the read-back already understand. ``Designer.sim_subset`` wraps it.

What goes into a subset box, and why:

* **The chosen qubits and their readout chains.** A readout chain is everything between the qubit and the feedline:
  the readout resonator route, then any series capacitor, Purcell filter, tee or airbridge connection on the way
  (walked through routes, instances and declared route–route couplings such as a readout–Purcell tap), up to the
  first *feedline* route.
* **The feedline is never selected; it is always in the box and cut by it.** A feedline route is a hanger host, a
  route ending on a bond pad / launcher (a 50 Ω port line, e.g. tutorial 02's readout line ``L_Q2``), or a route on
  a pad-to-pad backbone through tees (surface-17's ``FL2_*``). The box (selection bounding box + margin) cuts it,
  and the builder ends each cut in a 50 Ω port: an edge port (Q3D: its own net; driven: the S21 ports) or a lumped
  50 Ω termination 1 µm inside the edge (eigenmode). A line that is not grounded is always terminated where the box
  cuts it, so the group needs no ``ports`` entry for it (``"edge"`` is written only for a grounded feedline).
* **Buses and couplers between chosen qubits come in** (the bus route, its tees and stubs) when the bus reaches at
  least two chosen qubits; a stub of that bus towards a qubit outside the subset is cut. A declared coupling between
  two chosen qubits (facing arms) needs no geometry; it only puts both qubits in one box.
* **A bus to a qubit outside the subset is cut** (``ports={"<bus>": "cut"}``): the route is removed for every
  analysis. Q3D: the chosen qubit's coupling pad keeps a 100 µm stub ending in a port, so the pad is its own net
  (``<Q>.<port>``) and its capacitances to the qubit and to ground are extracted. Eigenmode / driven: the pad is left
  open — it still loads the qubit through its coupling capacitance, the bus mode is gone and nothing radiates (a
  stub port inside a pocket has no port polygon, so AEDT would skip a termination there). The LOM keeps the bus.
  The cut end at a tee or another non-qubit component is left open.
* **Disjoint pairs get one box each** (``split="auto"``): pairs that share a bus or a declared coupling stay in one
  box; others are separate groups ``<name>_<Q>…``. AEDT solves them one at a time, so peak memory is the largest box,
  not the sum, and no box spans the chip between two distant qubits. ``split="one"`` forces one box.

Read-back: ``circuit.fill.fill(whole_chip_model, design, [job, …])`` fills only the branches owned by the chosen
components (and their couplings to the feedline); every other branch keeps its estimate, marked as outside the
subset. See :mod:`quantcore_circuits.circuit.fill`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quantcore_circuits.design import Design, load_design, split_port_ref
from quantcore_circuits.design.schema import CHIP, HangerEnd

WHOLE = "whole"


@dataclass
class SubsetGroup:
    """One box of a subset: the sim group spec and what it holds."""

    name: str
    select: list[str]
    ports: dict[str, str]
    qubits: list[str]
    resonators: dict[str, list[str]]  # qubit → its readout chain (routes and instances)
    buses: list[str] = field(default_factory=list)  # bus parts that came in (both ends chosen)
    cut: list[str] = field(default_factory=list)  # buses cut at a chosen qubit (other end outside the subset)
    feedlines: list[str] = field(default_factory=list)  # feedline routes next to the chain (cut by the box)
    notes: list[str] = field(default_factory=list)

    def spec(self, margin_um: float, analyses, settings) -> dict:
        out = {"select": list(self.select), "margin_um": margin_um, "analyses": list(analyses)}
        if self.ports:
            out["ports"] = dict(self.ports)
        if settings:
            out["settings"] = dict(settings)
        return out


def _is_pad(design: Design, inst: str) -> bool:
    from quantcore_circuits.assembly.drc import _bond_pad  # pylint: disable=import-outside-toplevel

    i = design.instances.get(inst)
    return i is not None and _bond_pad(i.cell)


def has_junction(design: Design, inst: str) -> bool:
    """A qubit for the subset: its LOM model has a junction (JJ / SQUID). Wrapped Metal tees and couplers carry a
    ``junction_type`` parameter and the ``coupler`` category, so neither tells a qubit from a tee. A junction cell on
    its own (KQC ``Junction`` subclasses, Quantcore trilayer cells, Metal ``junction`` category,
    :func:`~quantcore_circuits.sim_tools.builder.is_junction_cell`) is not a qubit: it belongs in a qubit's gap."""
    from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.builder import is_junction_cell  # pylint: disable=import-outside-toplevel

    i = design.instances.get(inst)
    if i is None or i.cell.startswith("static:") or is_junction_cell(i.cell):
        return False
    fn = lom_model(i.cell)
    if fn is not None:
        try:
            return any(e.type in ("JJ", "SQUID") for e in fn(inst, i, get_pdk(design.pdk)).elements)
        except Exception:  # noqa: BLE001  (a model that cannot evaluate: fall back to the cell category)
            pass
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    try:
        return getattr(resolve_cell(i.cell), "qcc_category", "") == "qubit"
    except Exception:  # noqa: BLE001
        return False


_is_qubit = has_junction


class _Graph:
    """Instances and routes of a design as a graph: route ends, the routes at each instance, route couplings."""

    def __init__(self, design: Design):
        self.design = design
        self.ends: dict[str, list[str | None]] = {}  # route → [instance or None (free / hanger end), ...]
        self.hanger_host: dict[str, str] = {}  # route → the route it hangs on
        self.at: dict[str, list[str]] = {}  # instance → routes with an end on it
        self.pads = {n for n in design.instances if _is_pad(design, n)}
        self.qubits = {n for n in design.instances if _is_qubit(design, n)}
        for rname, r in design.routes.items():
            ends = []
            for e in (r.from_, r.to):
                if isinstance(e, str):
                    head = split_port_ref(e)[0]
                    ends.append(CHIP if head == CHIP else head)
                    self.at.setdefault(ends[-1], []).append(rname)
                else:
                    ends.append(None)
                    if isinstance(e, HangerEnd):
                        self.hanger_host[rname] = e.hanger
            self.ends[rname] = ends
        for name, inst in design.instances.items():  # a snap with no gap joins two instances like a wire
            pl = inst.place
            if pl.snap and pl.to and not pl.gap:
                other = split_port_ref(pl.to)[0]
                self.at.setdefault(name, []).append(f"snap:{other}")
                self.at.setdefault(other, []).append(f"snap:{name}")
        self.route_couplings: dict[str, set[str]] = {}  # route → routes / instances a declared C couples it to
        self.qubit_couplings: list[tuple[str, str]] = []  # declared couplings between two qubits
        for c in design.couplings.values():
            if c.type == "wire":
                continue
            heads = [e if e in design.routes else e.split(".", 1)[0] for e in c.between]
            if all(h in self.qubits for h in heads):
                self.qubit_couplings.append((heads[0], heads[1]))
            for a, b in ((heads[0], heads[1]), (heads[1], heads[0])):
                if a in design.routes:
                    self.route_couplings.setdefault(a, set()).add(b)
        self.feedlines = self._feedlines()

    def is_pad(self, inst: str | None) -> bool:
        return inst == CHIP or inst in self.pads

    def _feedlines(self) -> set[str]:
        """Hanger hosts, routes with a pad / launcher end, and the pad-to-pad backbone through tees (routes left after
        pruning every dead end of the instance graph without the qubits)."""
        out = set(self.hanger_host.values())
        out |= {r for r, ends in self.ends.items() if any(self.is_pad(e) for e in ends)}
        edges = {r: ends for r, ends in self.ends.items() if not any(e in self.qubits for e in ends)}
        alive = set(edges)
        changed = True
        while changed:
            changed = False
            degree: dict[str, int] = {}
            for r in alive:
                for e in edges[r]:
                    if e is not None:
                        degree[e] = degree.get(e, 0) + 1
            for r in list(alive):
                ends = edges[r]
                if any(e is None or (not self.is_pad(e) and degree.get(e, 0) <= 1) for e in ends):
                    alive.discard(r)
                    changed = True
        return out | alive

    def neighbours(self, node: str) -> list[str]:
        """Routes at an instance, or the instances / coupled routes of a route (``snap:<inst>`` resolved)."""
        if node in self.design.routes:
            out = [e for e in self.ends[node] if e is not None]
            return out + sorted(self.route_couplings.get(node, ()))
        return [n.split(":", 1)[1] if n.startswith("snap:") else n for n in self.at.get(node, [])]

    def walk(self, start: str, stop: set[str]) -> tuple[list[str], set[str], set[str]]:
        """Breadth-first from route ``start`` through routes and instances that are not qubits, pads or feedlines.
        Returns (visited components in order, qubits reached, feedline routes reached)."""
        order, seen, queue = [], {start}, [start]
        qubits, feeds = set(), set()
        while queue:
            node = queue.pop(0)
            order.append(node)
            if node in self.hanger_host:
                feeds.add(self.hanger_host[node])
            for nb in self.neighbours(node):
                if nb in seen or nb in stop or nb == CHIP:
                    continue
                seen.add(nb)
                if nb in self.qubits:
                    qubits.add(nb)
                elif nb in self.feedlines:
                    feeds.add(nb)
                elif nb in self.pads:
                    continue
                else:
                    queue.append(nb)
        return order, qubits, feeds


def readout_of(design, qubit: str) -> str | None:
    """The readout resonator route of ``qubit``: a route at one of its ports whose walk (through capacitors, tees,
    Purcell filters) reaches a feedline or a free / hanger end but no other qubit. None if there is none."""
    design = load_design(design)
    g = _Graph(design)
    for r in sorted(g.at.get(qubit, [])):
        if r.startswith("snap:") or r in g.feedlines:
            continue
        _, others, feeds = g.walk(r, {qubit})
        if others:
            continue
        ends = g.ends[r]
        if feeds or None in ends:
            return r
    return None


def plan_subset(
    design,
    name: str,
    pairs=None,
    qubits=None,
    split: str = "auto",
    readouts: bool = True,
) -> list[SubsetGroup]:
    """The sim groups of a subset (module docstring). ``pairs``: ``[("Q3", "R3"), ...]`` (resonator None → the
    qubit's readout, :func:`readout_of`); or ``qubits``: ``["Q3", "Q5"]`` (each with its readout). ``split``:
    ``"auto"`` (pairs joined by a chosen bus or a declared coupling share a box, other pairs get one box each) or
    ``"one"`` (one box for everything).

    ``readouts=False``: the qubits alone (an eigenmode box that fits a workstation, tutorial 01's ``Q1_q`` recipe):
    the readout chain is not selected, so the box (qubit + margin) cuts the readout line and the builder terminates
    it in 50 Ω (``ports={readout: "edge"}`` for a grounded λ/4); the job gives the qubit mode (f_q, α, p_J) and the
    read-back fills the qubit's own branches only."""
    design = load_design(design)
    g = _Graph(design)
    chosen: list[tuple[str, str | None]] = []
    for item in list(pairs or []) + [(q, None) for q in (qubits or [])]:
        q, r = (item, None) if isinstance(item, str) else (item[0], item[1] if len(item) > 1 else None)
        if q not in design.instances or q not in g.qubits:
            raise ValueError(f"subset {name}: {q!r} is not a qubit of {design.name}; qubits: {sorted(g.qubits)}")
        if r is not None and r not in design.routes:
            hint = {k: readout_of(design, k) for k in sorted(g.qubits)}
            raise ValueError(f"subset {name}: no route {r!r} (readout of {q}?); readouts found: {hint}")
        chosen.append((q, r))
    if not chosen:
        raise ValueError(f"subset {name}: name at least one qubit (pairs=[('Q1', 'R1')] or qubits=['Q1'])")
    qset = [q for q, _ in chosen]
    notes: list[str] = []

    chains: dict[str, list[str]] = {}
    feeds_of: dict[str, set[str]] = {}
    for q, r in chosen:
        r = r or readout_of(design, q)
        if r is None:
            notes.append(f"{q}: no readout resonator found; the qubit is simulated alone")
            chains[q], feeds_of[q] = [], set()
            continue
        order, others, feeds = g.walk(r, {q})
        if others:
            notes.append(f"{q}/{r}: the readout walk also reaches {sorted(others)} (a shared line?)")
        chains[q] = order
        feeds_of[q] = feeds

    # buses: routes at a chosen qubit's ports that are not its readout chain, not feedlines / control lines
    parent = {q: q for q in qset}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    bus_parts: dict[str, list[str]] = {}  # root bus route → included parts
    cut: dict[str, str] = {}
    for q in qset:
        for r in sorted(g.at.get(q, [])):
            if r.startswith("snap:") or r in g.feedlines or r in chains[q] or r in cut:
                continue
            if any(r in parts for parts in bus_parts.values()):
                continue
            order, reached, _ = g.walk(r, {q})
            reached_in = sorted(x for x in reached if x in qset)
            if not reached and None in g.ends[r]:
                continue  # an open stub / control line ending near the qubit: geometry only
            if reached_in:
                bus_parts[r] = order
                for x in reached_in:
                    parent[find(x)] = find(q)
                for part in order:  # a stub of this bus towards a qubit outside the subset is cut
                    if part in design.routes and any(e in g.qubits and e not in qset for e in g.ends[part]):
                        cut[part] = "cut"
            else:
                cut[r] = "cut"
    for a, b in g.qubit_couplings:
        if a in parent and b in parent:
            parent[find(a)] = find(b)

    roots: dict[str, list[str]] = {}
    for q in qset:
        roots.setdefault(find(q) if split == "auto" else qset[0], []).append(q)
    if split not in ("auto", "one"):
        raise ValueError(f"split must be 'auto' or 'one', not {split!r}")
    groups = []
    for members in roots.values():
        gname = name if len(roots) == 1 else f"{name}_{'_'.join(members)}"
        resonators = {q: chains[q] for q in members}
        select = list(members)
        for q in members if readouts else ():  # resonator routes first, then the rest of each chain
            select += [x for x in chains[q][:1] if x not in select]
        for q in members if readouts else ():
            select += [x for x in chains[q][1:] if x not in select]
        buses = []
        for root, parts in bus_parts.items():
            if any(root in g.at.get(q, []) for q in members):
                buses += [p for p in parts if p not in buses and p not in cut]
        select += [b for b in buses if b not in select]
        inside = set(select)
        ports = {r: "cut" for r in cut if any(e in inside for e in g.ends[r])}
        from quantcore_circuits.sim_tools.builder import grounded_routes  # pylint: disable=import-outside-toplevel

        grounded = grounded_routes(design)
        feeds = sorted(set().union(*(feeds_of[q] for q in members)))
        for f in feeds:
            if f in grounded:
                ports[f] = "edge"
        if not readouts:  # the readout itself is cut by the box: a grounded λ/4 needs "edge" to be terminated
            for q in members:
                if chains[q] and chains[q][0] in grounded:
                    ports[chains[q][0]] = "edge"
        groups.append(SubsetGroup(gname, select, ports, members, resonators, buses, sorted(ports), feeds,
                                  list(notes)))
    return groups


def subset_scope(design, group: str) -> set[str] | None:
    """The components a job of ``group`` fills: its selected instances and routes (None for the whole chip)."""
    from quantcore_circuits.sim_tools.builder import CHIP_GROUP, group_spec  # pylint: disable=import-outside-toplevel

    design = load_design(design)
    if group == CHIP_GROUP and group not in design.sim_groups:
        return None
    try:
        return set(group_spec(design, group).select)
    except ValueError:
        return None


def describe(groups: list[SubsetGroup]) -> str:
    """Markdown: one row per box (what is rendered and simulated, what is cut)."""
    out = ["| group (box) | qubits | readout chain | buses in | buses cut at the qubit | feedline (cut by the box) |",
           "|---|---|---|---|---|---|"]
    for sg in groups:
        chain = "; ".join(f"{q}: {', '.join(c) or '–'}" for q, c in sg.resonators.items())
        cut = ", ".join(r for r, h in sg.ports.items() if h == "cut") or "–"
        out.append(f"| `{sg.name}` | {', '.join(sg.qubits)} | {chain} | {', '.join(sg.buses) or '–'} | {cut} | "
                   f"{', '.join(sg.feedlines) or '–'} |")
    notes = [n for sg in groups for n in sg.notes]
    if notes:
        out += ["", *(f"- {n}" for n in dict.fromkeys(notes))]
    return "\n".join(out)
