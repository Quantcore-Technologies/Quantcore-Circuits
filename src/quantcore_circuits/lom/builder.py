"""Layout → LOM: compose the components' LOM fragments along the design's connectivity into a ``circuit.json``.

Mapping (see :mod:`quantcore_circuits.lom.fragment` for the component side):

=====================================  =============================================================================
layout                                 lumped model
=====================================  =============================================================================
component                              its fragment: nodes (FEM islands), elements, port → node map
``cpw`` route port ↔ port              a wire: both ports' nodes become one conductor (named after the route when it
                                       joins pads, e.g. the feedline ``FL``)
route port → hanger / short free end   λ/4 resonator ``TLres`` from the port's node to ground (+ ``HANGER``
                                       coupling element to the feedline node: coupled-line κ)
route port → open free end             λ/2 resonator (open–open) to ground
route free end → hanger (no port)      a resonator on its own node ``<route>.line`` (island ``<route>``): λ/4 when
                                       exactly one end is shorted (``term=0`` / ``end="short"``), else λ/2
``meander`` route port ↔ port          λ/2 bus resonator: both end nodes join one resonator node
route on a ``control:*`` port          control line (flux bias of that qubit's SQUID), no circuit element; the
                                       conductor is grounded at the qubit, so its pad's port is dropped
snap placement (gap 0)                 the two ports' nodes join (galvanic)
``design.couplings``                   C / L between the resolved ends (an end may be a route: its conductor); a
                                       value-less C from a cell's coupled section (``Fragment.hangers``) is a HANGER
line end on a zero-length termination  wired / snapped to it, or drawn on its body: the line end takes its
                                       termination (CpweOpenEnd: open)
component lines joined end to end      one line (a chain: route between two line ports, wire / snap between
                                       them): its two free ends decide wire / λ/4 / λ/2, its length is the sum; a
                                       pass-through cell (taper, ``Line.through``) only extends it (one Z0: the
                                       width step is not modelled), the TLres takes the main line's or route's name
=====================================  =============================================================================

Values are component estimates (calibration, CPW formulas, coupled-line κ); :func:`quantcore_circuits.circuit.
fill.fill` replaces capacitances by FEM C-matrix values where the island labels match. Element names follow the
convention used everywhere else: ``C_<Q>``, ``J_<Q>``, ``Cg_<Q>_<claw>``, ``Cc_<Q>_<claw>``, ``<route>`` (TLres),
``K_<route>`` (hanger), ``Port_<pad>``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quantcore_circuits.circuit.schema import CircuitModel
from quantcore_circuits.lom.fragment import QUBIT_NODES, Element, Fragment, generic_fragment, lom_model

DRIVE_C_FF = 0.1  # charge-line ↔ island capacitance when nothing better is known (rough)
DEFAULT_TOL = {"f_q_GHz": 0.02, "alpha_MHz": 10.0, "f_GHz": 0.01, "g_MHz": 10.0, "chi_MHz": 0.1, "kappa_MHz": 0.2}


class _UF:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if rb == "gnd":
                ra, rb = rb, ra
            self.parent[rb] = ra


@dataclass
class LomBuild:
    model: CircuitModel
    notes: list[str] = field(default_factory=list)
    port_map: dict[str, str] = field(default_factory=dict)  # "Q1.claw_n" → circuit node
    unconnected: list[str] = field(default_factory=list)  # component ports with a node but no connection


def lom_from_design(source, select: list[str] | None = None, name: str | None = None, plan=None) -> LomBuild:
    """Build the lumped circuit of ``source`` (all of it, or the instances/routes in ``select``)."""
    from quantcore_circuits.assembly.last_good import plan_for_lom, resolve  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.bridges import tl_resonator  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design.schema import CHIP, FreeEnd, HangerEnd  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.calibration import hanger_k, hanger_kappa_MHz  # pylint: disable=C0415
    from quantcore_circuits.lom.metal_models import metal_only_without_pocket  # pylint: disable=C0415
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    design = load_design(source)
    pdk = get_pdk(design.pdk)
    # a route that failed to build is replaced by its last good one (with a warning), or named as missing
    plan = resolve(plan) if plan is not None else plan_for_lom(design, source)
    chosen = set(select) if select else set(design.instances) | set(design.routes)
    notes: list[str] = list(getattr(plan, "warnings", []))
    uf = _UF()
    uf.find("gnd")
    nodes: dict[str, dict] = {}  # global node → {"island": ...}
    elements: list[Element] = []
    port_map: dict[str, str] = {}
    knobs: dict = {}
    kind_of: dict[str, str] = {}  # global node → "qubit" | "coupler" | "pad" | ...
    used_ports: set[str] = set()
    line_states: list[dict] = []  # component lines (see lom.fragment.Line)
    port_line: dict[str, tuple[dict, int]] = {}  # 'INST.port' -> (line state, end index)
    main_node: dict[str, str] = {}  # instance → node holding its junction (or its 'island')
    sole_node: dict[str, str] = {}  # instance → its only node (a feedline segment, a pad), for couplings to it
    line_of: dict[tuple[str, str], dict] = {}  # (instance, line name) → line state
    ext_hangers: dict[str, list[dict]] = {}  # instance → Fragment.hangers
    straps: list[str] = []  # global nodes of Fragment.straps (grounded when no port on them is joined)

    def glob(inst: str, local: str) -> str:
        if local == "gnd":
            return "gnd"
        return inst if local == "island" else f"{inst}.{local}"

    for iname, inst in design.instances.items():
        if iname not in chosen:
            continue
        fn = lom_model(inst.cell)
        ports = sorted(plan.instances[iname].local_ports)
        if fn:
            frag = fn(iname, inst, pdk)
            no_pocket = metal_only_without_pocket(design, plan, iname)
            if no_pocket:  # a metal-only Metal cell on the ground plane: nothing electrical
                frag = Fragment(port_nodes={p: "gnd" for p in set(frag.port_nodes) | set(ports)}, notes=[no_pocket])
        else:  # a cell without ports (label, marker, finger shape) has nothing to map: no note either
            frag = generic_fragment(iname, inst, ports) if ports else Fragment()
        notes += frag.notes
        knobs.update(frag.knobs)
        for local, spec in frag.nodes.items():
            g = glob(iname, local)
            nodes[g] = dict(spec)
            kind_of[g] = "qubit" if local in QUBIT_NODES else ("pad" if local == "pad" else "coupler")
            uf.find(g)
        if len(frag.nodes) == 1:
            sole_node[iname] = glob(iname, next(iter(frag.nodes)))
        if frag.hangers:
            ext_hangers[iname] = list(frag.hangers)
        straps += [glob(iname, n) for n in frag.straps if n in frag.nodes]
        for line in frag.lines:
            st = {"line": line, "inst": iname, "node": glob(iname, line.node), "state": [None, None], "extra": 0.0}
            st["hangers"], st["ext"], st["routes"], st["free_routes"] = [], [], [], []
            st["peer"] = [None, None]  # (line state, end) of another line joined to that end
            st["length"] = line.length_um
            if line.through and line.length_um <= 0:  # a pass-through cell without a length parameter
                st["length"] = _port_distance(plan, iname, line.ports)
            line_of[(iname, line.name)] = st
            kind_of.setdefault(st["node"], "line")
            line_states.append(st)
            for i, port in enumerate(line.ports):
                if port:
                    port_line[f"{iname}.{port}"] = (st, i)
        for e in frag.elements:
            elements.append(Element(e.name, e.type, tuple(glob(iname, n) for n in e.nodes), e.value, e.knob, e.note))
            if e.type in ("JJ", "SQUID") and iname not in main_node:
                main_node[iname] = glob(iname, next(n for n in e.nodes if n != "gnd"))
        if iname not in main_node and "island" in frag.nodes:
            main_node[iname] = iname
        for port, local in frag.port_nodes.items():
            port_map[f"{iname}.{port}"] = local if local.startswith("control:") else glob(iname, local)

    # chip-frame launchers ("chip.WN", ...): a 50 Ω port each, like a BondPad
    for rname, route in design.routes.items():
        if rname not in chosen:
            continue
        for end in (route.from_, route.to):
            if isinstance(end, str) and end.startswith(f"{CHIP}.") and end not in port_map:
                launcher = end.split(".", 1)[1]
                nodes[end] = {"island": end}
                kind_of[end] = "pad"
                uf.find(end)
                elements.append(
                    Element(
                        f"Port_{launcher}",
                        "R",
                        (end, "gnd"),
                        {"R_ohm": 50.0, "source": "design"},
                        note="chip-frame launcher (sample-holder port)",
                    )
                )
                port_map[end] = end

    # declared couplings (design.couplings): ``wire`` couplings join two ports galvanically (overlapping metal), like
    # a snap with no gap; C/L couplings are resolved after the route pass (an end may name a route's conductor)
    wired: dict[str, str] = {}  # 'INST.port' → the port it is wired to
    coupling_at = len(elements)  # C/L coupling elements keep their place in the netlist
    for cname, c in design.couplings.items():
        if c.type != "wire":
            continue
        pa, pb = (port_map.get(e) for e in c.between)
        if any(e.split(".", 1)[0] not in chosen for e in c.between):
            continue  # an end outside the selection
        if pa is None or pb is None or pa.startswith("control:") or pb.startswith("control:"):
            notes.append(f"wire {cname}: cannot resolve {list(c.between)} to circuit nodes (skipped)")
            continue
        uf.union(pa, pb)
        used_ports.update(c.between)
        wired[c.between[0]], wired[c.between[1]] = c.between[1], c.between[0]

    # snap placement with no gap: the two ports touch (galvanic)
    for iname, inst in design.instances.items():
        pl = inst.place
        if iname not in chosen or not (pl.snap and pl.to):
            continue
        own = pl.snap if "." in pl.snap else f"{iname}.{pl.snap}"
        pa, pb = port_map.get(own), port_map.get(pl.to)
        if pa is None or pb is None or pa.startswith("control:") or pb.startswith("control:"):
            continue
        if pl.gap:
            notes.append(f"{iname}: snapped to {pl.to} with a {pl.gap:g} µm gap (not connected in the LOM)")
            continue
        uf.union(pa, pb)

    controls: dict[str, dict] = {}
    resonators: list[tuple[str, object]] = []
    route_conductor: dict[str, str] = {}  # cpw route → a node on its conductor
    route_node: dict[str, str | None] = {}  # any route → the node a coupling to it attaches to (None: none)
    wire_length: dict[str, float] = {}  # cpw route (a wire) → its length
    for rname, route in design.routes.items():
        if rname not in chosen:
            continue
        specs = [route.from_, route.to]
        if not isinstance(specs[0], str) and isinstance(specs[1], str):
            specs.reverse()  # a free end given as "from": the port end is the resonator's coupler end
        ends = []
        for end in specs:
            if isinstance(end, str):
                used_ports.add(end)
                ends.append(port_map.get(end, f"unknown:{end}"))
            elif isinstance(end, HangerEnd):
                ends.append(f"hanger:{end.hanger}")
            elif isinstance(end, FreeEnd):
                ends.append("gnd" if end.term == 0 else "open")
        a, b = ends
        rp = plan.routes[rname]
        length = rp.length or route.length
        if any(e.startswith("control:") for e in ends):
            ctl = next(e for e in ends if e.startswith("control:"))
            qubit_port = specs[0] if ends[0] == ctl else specs[1]
            other = b if ends[0] == ctl else a
            qubit = qubit_port.split(".", 1)[0]
            ctl_kind = ctl.split(":", 1)[1]
            controls[rname] = {
                "kind": ctl_kind if ctl_kind == "drive" else ctl_kind + "_bias",
                "target": f"J_{qubit}",
                "line": rname,
                "length_um": length,
            }
            real = other not in ("gnd", "open") and not other.startswith(("hanger:", "unknown:", "control:"))
            route_node[rname] = other if real and ctl_kind == "drive" else None  # a flux line is grounded
            if ctl_kind == "drive":
                # a charge line ends open next to the qubit: its conductor keeps its port, with a small C to the
                # island (drive coupling, Purcell/T1 through the drive port)
                if real and qubit in main_node:
                    elements.append(
                        Element(
                            f"Cd_{qubit}",
                            "C",
                            (main_node[qubit], other),
                            {
                                "estimate": DRIVE_C_FF,
                                "unit": "fF",
                                "fem": "cmatrix",
                                "estimate_source": "rough: typical open-ended charge line next to a transmon",
                                "estimate_kind": "rough",
                                "uncertainty": "±100%",
                            },
                            note="drive (charge) line coupling",
                        )
                    )
                continue
            if real:
                uf.union("gnd", other)  # the bias line is shorted to ground at the qubit
            continue
        if any(e.startswith("unknown:") for e in ends):
            notes.append(f"route {rname}: end(s) {[e for e in ends if e.startswith('unknown:')]} not in the selection")
            continue
        if not any(isinstance(sp, str) for sp in specs):
            # no port at either end (a free end ↔ a hanger, two free ends): a resonator on its own conductor
            own = f"{rname}.line"
            nodes[own] = {"island": rname}
            kind_of[own] = "line"
            uf.find(own)
            route_node[rname] = own
            resonators.append((rname, (own, b, route, rp, length, specs)))
            continue
        far = b
        la = port_line.get(specs[0]) if isinstance(specs[0], str) else None
        lb = port_line.get(specs[1]) if isinstance(specs[1], str) else None
        if la and (far.startswith("hanger:") or far in ("gnd", "open")):
            # the route continues a component's line to a free end / hanger: one longer line
            st, idx = la
            st["extra"] += length or 0.0
            st["routes"].append(rname)
            route_node[rname] = st["node"]
            if far.startswith("hanger:"):
                st["state"][idx] = "short" if specs[1].end == "short" else "open"
                st["hangers"].append((rname, specs[1], far.split(":", 1)[1]))
            else:
                st["state"][idx] = "short" if far == "gnd" else "open"
                st["free_routes"].append(rname)
            continue
        meander_bus = route.type == "meander" and far in nodes and not (la or lb)
        route_node[rname] = a  # a resonator route: its coupler-end node; a wire: its conductor
        if far.startswith("hanger:") or far in ("gnd", "open") or meander_bus:
            resonators.append((rname, (a, far, route, rp, length, [] if meander_bus else [specs[1]])))
            continue
        # cpw between two conductors: one wire (a component line it touches gets the route's length)
        for line_end, other in ((la, b), (lb, a)):
            if line_end:
                st, idx = line_end
                st["extra"] += (length or 0.0) / (2 if la and lb else 1)
                st["state"][idx] = "joined" if la and lb else other
                st["routes"].append(rname)
        if la and lb:  # line → route → line: one line (see the component lines below)
            la[0]["peer"][la[1]], lb[0]["peer"][lb[1]] = lb, la
        uf.union(a, b)
        route_conductor[rname] = a  # what a hanger on this route couples to (after all wires merge)
        if not (la or lb):
            wire_length[rname] = length or 0.0
        if kind_of.get(a) == "pad" and kind_of.get(b) == "pad":
            nodes.setdefault(f"route:{rname}", {})
            uf.union(a, f"route:{rname}")
            kind_of[f"route:{rname}"] = "feedline"

    def ensure_feedline(fl: str) -> str:
        fl_node = f"route:{fl}"
        if fl_node not in nodes and fl in route_conductor:  # e.g. one segment of a feedline split by tees
            return route_conductor[fl]
        if fl_node not in nodes:  # feedline outside the selection: keep its conductor + both port loads
            nodes[fl_node] = {}
            kind_of[fl_node] = "feedline"
            elements.append(
                Element(
                    f"Port_{fl}",
                    "R",
                    (fl_node, "gnd"),
                    {"R_ohm": 25.0, "source": "design"},
                    note="feedline seen from the resonator: two 50 Ω ports in parallel",
                )
            )
        return fl_node

    def facing_gap(h, rname):
        """The hanger's ground strip as the calibration sees it: narrowed facing gaps (``coupler_gap`` /
        ``line_gap``) bring the conductors closer by what they save, as a narrower strip between full gaps would."""
        if h.coupler_gap is None and h.line_gap is None:
            return h.ground_gap
        b_r = plan.routes[rname].params.get("b", pdk.cpw_b)
        b_l = plan.routes[h.hanger].params.get("b", pdk.cpw_b) if h.hanger in plan.routes else pdk.cpw_b
        saved = (b_r - (h.coupler_gap if h.coupler_gap is not None else b_r)) + (
            b_l - (h.line_gap if h.line_gap is not None else b_l))
        return h.ground_gap - saved

    def hanger_element(ename, node, other, coupling_um, gap_um, end, tl, kind, knob):
        kappa = None
        if tl:
            kappa = hanger_kappa_MHz(tl["f_GHz"], tl["vp_m_s"], coupling_um, gap_um)
            if kind == "lambda/2":
                kappa /= 2  # same coupled section, twice the stored energy of a λ/4 at the same end voltage
        src = "coupled-line Q_ext (calibration)" + (" / 2 for a λ/2 mode (rough)" if kind == "lambda/2" else "")
        return Element(
            ename,
            "HANGER",
            (node, other),
            {
                "coupling_length_um": coupling_um,
                "ground_gap_um": gap_um,
                "end": end,
                "k": hanger_k(gap_um),
                "kappa_MHz": kappa,
                "estimate_source": src,
            },
            {"param": knob} if knob else None,
        )

    def tl_value(kind, length, a_um, b_um):
        tl = tl_resonator(length, a_um, b_um, design.pdk) if length else {}
        value = {
            "kind": kind,
            "length_um": length,
            "a_um": a_um,
            "b_um": b_um,
            "source": "layout",
            **{k: tl[k] for k in ("f_GHz", "Z0_ohm", "vp_m_s") if k in tl},
            # kinetic inductance of the film (decision #45): L_k beside L_geo, nH/m, and the fraction of the line's L
            **{k: round(tl[k], 6) for k in ("L_geo_nH_per_m", "L_k_nH_per_m", "alpha_k") if k in tl},
        }
        if kind == "lambda/2" and tl:
            value["f_GHz"] = tl["f_GHz"] * 2
        return value, tl

    # declared C/L couplings: one element each between the resolved nodes (a value-less C from a component line's
    # coupled section to a conductor no port carries is that line's HANGER instead)
    coupling_elements: list[Element] = []
    for cname, c in design.couplings.items():
        if c.type == "wire":
            continue
        ends_c, outside = [], []
        for end in c.between:
            inst_name, _, rest = end.partition(".")
            if inst_name in design.instances:
                if inst_name not in chosen:
                    outside.append(end)
                elif not rest:
                    ends_c.append(main_node.get(inst_name) or sole_node.get(inst_name))
                elif end in port_map:
                    ends_c.append(port_map[end])
                else:
                    ends_c.append(glob(inst_name, rest) if glob(inst_name, rest) in nodes else None)
            elif end in design.routes:  # the route's conductor
                if end not in chosen:
                    outside.append(end)
                else:
                    ends_c.append(route_node.get(end))
            else:
                ends_c.append(None)
        is_hanger = c.type == "C" and c.value is None
        if outside:
            # a resonator in the selection hanging off a feedline route outside it: keep the feedline + port loads
            # (as for a route's hanger end); any other coupling with an end outside the selection is left out
            fl = outside[0]
            inside = c.between[1] if c.between[0] == fl else c.between[0]
            if (
                is_hanger
                and len(outside) == 1
                and fl in design.routes
                and ends_c[0]
                and ext_hangers.get(inside.partition(".")[0])
            ):
                ends_try = [ends_c[0], f"route:{fl}"] if c.between[1] == fl else [f"route:{fl}", ends_c[0]]
                hanger = _hanger_coupling(c, ends_try, ext_hangers, line_of, glob)
                if hanger:
                    st, spec, _ = hanger
                    st["ext"].append(
                        (cname if cname.startswith("K_") else f"K_{cname}", ensure_feedline(fl), spec, c.note)
                    )
            continue
        if None in ends_c or any(n.startswith("control:") for n in ends_c):
            notes.append(f"coupling {cname}: cannot resolve {list(c.between)} to circuit nodes (skipped)")
            continue
        hanger = _hanger_coupling(c, ends_c, ext_hangers, line_of, glob) if is_hanger else None
        if hanger:  # a component line's coupled section to a conductor no port carries: HANGER, not a C
            st, spec, other = hanger
            st["ext"].append((cname if cname.startswith("K_") else f"K_{cname}", other, spec, c.note))
            continue
        value = {"estimate": c.value, "estimate_source": "declared", "estimate_kind": "declared"}
        if c.type == "C":
            value["unit"] = "fF"
            if c.fem:
                value["fem"] = "cmatrix"
        else:
            value |= {"unit": "nH", "L_nH": c.value}
        coupling_elements.append(Element(f"{c.type}_{cname}", c.type, tuple(ends_c), value, note=c.note))
    elements[coupling_at:coupling_at] = coupling_elements

    # component lines (lom.fragment.Line): what each end meets decides wire, λ/4 or λ/2. Lines joined end to end (a
    # route between two line ports, a wire coupling or snap between them, a zero-length termination on a line end)
    # are one line, a chain: e.g. a shorted end → route → taper → route → hanger is one λ/4
    snapped = {p for p in port_map if _snapped(design, p)}
    # zero-length terminations (CpweOpenEnd, OpenToGround, ...): a line end joined to one (wire / snap) takes its
    # termination; an unjoined line end drawn on one (the legacy "resonatorGnd" cut box) does too
    terms = {p: v for p, v in port_line.items() if _is_termination(v[0]["line"])}
    on_term = _ends_on_terminations(plan, design, line_states, terms, used_ports | snapped)
    order = sorted(line_states, key=lambda s: _is_termination(s["line"]))  # terminations last
    for st in order:
        line, inst = st["line"], st["inst"]
        for i, port in enumerate(line.ports):
            if st["state"][i] is not None:
                continue  # a route reached it, or a line joined to it did
            ref = f"{inst}.{port}" if port else None
            partner = (wired.get(ref) or _snap_partner(design, ref)) if ref else None
            peer = port_line.get(partner) if partner else None
            if ref in on_term:
                tport, dist = on_term[ref]
                tst, tidx = terms[tport]
                _join(st, i, tst, tidx)
                used_ports.update((ref, tport))
                uf.union(st["node"], tst["node"])  # the cut box sits on the line end: one conductor, as if wired
                notes.append(
                    f"{ref}: nothing joined, but the end lies on the termination {tport} ({dist:.1f} µm apart): "
                    f"modelled {tst['line'].term[tidx]} (declare a wire coupling {ref} ↔ {tport} to make it explicit)"
                )
            elif ref is None or (ref not in used_ports and ref not in snapped):
                st["state"][i] = line.term[i]
            elif peer and peer[0]["state"][peer[1]] is None and peer[0] is not st:
                _join(st, i, *peer)  # wired / snapped to another line's end (a termination: its end condition)
            elif partner and partner in port_map and not peer:
                st["state"][i] = port_map[partner]  # snapped / wired to another component's conductor (see below)
            else:
                st["state"][i] = "through"  # joined to something this model cannot follow: a wire
    chain_uf = _UF()
    for st in order:
        for peer in st["peer"]:
            if peer:
                chain_uf.union(str(id(st)), str(id(peer[0])))
    chains: dict[str, list[dict]] = {}  # in line order: a chain sits where its first non-termination line is
    for st in order:
        chains.setdefault(chain_uf.find(str(id(st))), []).append(st)
    chain_info: list[dict] = []
    wire_on, wire_len = dict(route_conductor), dict(wire_length)  # wires on a resonator's conductor (_tap_extra)
    for members in chains.values():
        outer = [m["state"][i] for m in members for i in (0, 1) if m["state"][i] != "joined"]
        kinds = []
        for s_ in outer:
            if s_ in ("short", "open", "through"):
                kinds.append(s_)
            else:  # the conductor a route / wire / snap joined this end to
                kinds.append("through" if kind_of.get(s_) in ("pad", "feedline") else "coupler")
        free = [k for k in kinds if k in ("short", "open")]
        extra = sum(m["extra"] for m in members)
        touched = any(
            f"{m['inst']}.{p}" in used_ports or f"{m['inst']}.{p}" in snapped
            for m in members
            for p in m["line"].ports
            if p
        )
        info = {
            "members": members,
            "kinds": kinds,
            "length": sum(m["length"] for m in members) + extra,
            "extra": extra,
            # terminations alone, or pass-through sections nothing joins: no line of their own
            "zero": not extra
            and (
                all(_is_termination(m["line"]) for m in members)
                or (all(m["line"].through for m in members) and not touched)
            ),
            "wire": "through" in kinds
            or len(outer) != 2  # a ring, or a line joined at a branch point
            or not (any(m["line"].resonator for m in members) or free),
        }
        chain_info.append(info)
        if info["wire"] and extra and info["length"] > 0:  # a wire through line(s): its routes and lines extend
            label = "+".join(m["line"].name for m in members)  # a resonator on its conductor (see _tap_extra)
            wire_on[label], wire_len[label] = members[0]["node"], info["length"]

    # a resonator route on a conductor that wires (cpw routes) extend away from any port, feedline or qubit island,
    # e.g. a readout drawn as claw → straight → splitter → shorted tail: the wires are part of the resonator line
    tap_extra = _tap_extra(resonators, uf, nodes, kind_of, wire_on, wire_len)
    for rname, (a, far, route, rp, length, far_specs) in resonators:
        a_um, b_um = rp.params.get("a", pdk.cpw_a), rp.params.get("b", pdk.cpw_b)
        extra_wires = tap_extra.get(rname)
        if extra_wires:
            length = (length or 0.0) + sum(extra_wires.values())
        if far_specs:  # free / hanger end(s); a port end is the coupler (open) end
            ends_t = [_end_term(sp) for sp in far_specs] + ["open"] * (2 - len(far_specs))
            kind = "lambda/4" if ends_t.count("short") == 1 else "lambda/2"
        else:  # a meander port ↔ port: a λ/2 bus joining both ends
            kind = "lambda/2"
            uf.union(a, far)
        value, tl = tl_value(kind, length, a_um, b_um)
        if extra_wires:
            value["extra_length_um"] = round(sum(extra_wires.values()), 3)
            value["source"] = f"layout: {rname} + the wire route(s) {sorted(extra_wires)} on its conductor"
            notes.append(
                f"{rname}: one {kind} line of {length:.0f} µm = route + {sorted(extra_wires)} (the wires join it to "
                "its coupler end; any other branch on that conductor is a tap, not modelled as a separate line)"
            )
        if len(far_specs) == 2:
            notes.append(f"{rname}: no port at either end ({' / '.join(ends_t)}): a {kind} line on its own conductor")
        elements.append(Element(rname, "TLres", (a, "gnd"), value, {"param": f"{rname}.length"}))
        if route.length:
            knobs[f"{rname}.length"] = (round(route.length * 0.8, 1), round(route.length * 1.25, 1))
        hangers_ = [sp for sp in far_specs if isinstance(sp, HangerEnd)]
        for i, h in enumerate(hangers_):
            fl_node = ensure_feedline(h.hanger)
            elements.append(
                hanger_element(
                    f"K_{rname}" + (f"_{i}" if i else ""),
                    a,
                    fl_node,
                    h.length,
                    facing_gap(h, rname),
                    h.end,
                    tl,
                    kind,
                    f"{rname}.coupler_length",
                )
            )

    def route_len(r: str) -> float:
        return plan.routes[r].length or design.routes[r].length or 0.0

    for info in chain_info:
        members, kinds = info["members"], info["kinds"]
        if info["zero"]:  # terminations / pass-through sections only, nothing on them
            st = members[0]
            line, inst = st["line"], st["inst"]
            if all(m["line"].through for m in members):  # a lone taper: its unterminated ends join the ground plane
                for m in members:
                    uf.union("gnd", m["node"])
                notes.append(
                    f"{'+'.join(m['line'].name for m in members)}: pass-through section with nothing joined (ground)"
                )
            elif (
                len(members) == 1
                and _is_termination(line)
                and not any(f"{inst}.{p}" in used_ports or f"{inst}.{p}" in snapped for p in line.ports if p)
            ):
                notes.append(f"{line.name}: termination with nothing joined (no element; its port maps to ground)")
                for p in line.ports:
                    if p:
                        port_map[f"{inst}.{p}"] = "gnd"  # no conductor of its own (an end condition only)
            continue  # zero length: nothing to model on its own
        if info["wire"]:
            for m in members:
                lname = m["line"].name
                if m["line"].resonator:
                    notes.append(f"{lname}: resonator line with an end on a port/feedline, modelled as a wire")
                for ename, *_ in m["ext"]:
                    notes.append(f"{ename}: {lname} is a wire here, so its coupled section is not a hanger (dropped)")
                for rname, *_ in m["hangers"]:
                    notes.append(f"K_{rname}: {lname} is a wire here, so the hanger of {rname} is dropped")
            continue  # a wire: its ports are one conductor already
        shorts = kinds.count("short")
        kind = "lambda/4" if shorts == 1 else "lambda/2"
        length = info["length"]
        routes = list(dict.fromkeys(r for m in members for r in m["routes"]))
        named = [m for m in members if not (m["line"].through or _is_termination(m["line"]))]
        main = max(named, key=lambda m: (m["line"].resonator, m["length"])) if named else None
        if main:
            ename, knob, a_um, b_um = main["line"].name, main["line"].knob, main["line"].a_um, main["line"].b_um
        elif routes:  # terminations / pass-through sections only: the route is the line (one to a hanger or free end)
            ends_ = [r for m in members for r, *_ in m["hangers"]] + [r for m in members for r in m["free_routes"]]
            ename = ends_[0] if ends_ else max(routes, key=route_len)
            knob = f"{ename}.length"
            rpp = plan.routes[ename].params
            a_um, b_um = rpp.get("a", pdk.cpw_a), rpp.get("b", pdk.cpw_b)
        else:
            m0 = members[0]["line"]
            ename, knob, a_um, b_um = m0.name, m0.knob, m0.a_um, m0.b_um
        value, tl = tl_value(kind, length, a_um, b_um)
        if not main and routes and length - route_len(ename) > 1e-6:  # fill() rebuilds f from route + extra
            value["extra_length_um"] = round(length - route_len(ename), 3)
        names_ = [m["line"].name for m in members]
        # one line, possibly ended by terminations wired / snapped / drawn on it (no route between them)
        plain = main and all(m is main or (_is_termination(m["line"]) and not m["extra"]) for m in members)
        if plain:
            extra = info["extra"]
            value["source"] = "layout (component line)" + (f" + {extra:.0f} µm of routes" if extra else "")
        elif len(members) == 1 and len(routes) == 1 and _is_termination(members[0]["line"]):
            value["source"] = f"layout: route {ename} ending in {names_[0]}"
        else:
            value["source"] = "layout: " + " + ".join(names_) + (f" + route(s) {', '.join(routes)}" if routes else "")
            through = [m["line"].name for m in members if m["line"].through]
            notes.append(
                f"{ename}: one {kind} line of {length:.0f} µm through {names_}"
                + (f" and route(s) {routes}" if routes else "")
                + (
                    f"; pass-through section(s) {through} enter by (equivalent) length only, the width step is not "
                    f"modelled (one Z0, a/b {a_um:g}/{b_um:g} µm)"
                    if through
                    else ""
                )
            )
        node = (main or members[0])["node"]
        elements.append(Element(ename, "TLres", (node, "gnd"), value, {"param": knob} if knob else None))
        for m in members:
            line, inst = m["line"], m["inst"]
            if not m["ext"] and any(h["line"] == line.name for h in ext_hangers.get(inst, [])):
                notes.append(
                    f"{line.name}: its coupler section runs next to a conductor no port carries; declare "
                    f"d.couple('K_{line.name}', '{inst}', '<feedline instance>') for the hanger κ"
                )
            for hname, other, spec, cnote in m["ext"]:
                el = hanger_element(
                    hname,
                    node,
                    other,
                    spec["coupling_length_um"],
                    spec["ground_gap_um"],
                    spec.get("end", "short"),
                    tl,
                    kind,
                    None,
                )
                if spec.get("source"):
                    el.value["estimate_source"] += f"; {spec['source']}"
                el.note = cnote or (
                    f"{line.name}: coupled section next to a conductor no port carries (declared coupling)"
                )
                elements.append(el)
            for i, c in enumerate(line.couplings):
                elements.append(
                    hanger_element(
                        f"K_{line.name}" + (f"_{i}" if i else ""),
                        node,
                        glob(inst, c["node"]),
                        c["coupling_length_um"],
                        c["ground_gap_um"],
                        "short" if shorts else "open",
                        tl,
                        kind,
                        None,
                    )
                )
            for rname, h, fl in m["hangers"]:
                elements.append(
                    hanger_element(
                        f"K_{rname}",
                        node,
                        ensure_feedline(fl),
                        h.length,
                        facing_gap(h, rname),
                        h.end,
                        tl,
                        kind,
                        f"{rname}.coupler_length",
                    )
                )

    # ground straps (airbridges): with no port on them joined they land on the ground plane on both sides
    grounded = []
    for g in straps:
        on = [p for p, n in port_map.items() if n == g]
        if uf.find(g) != uf.find("gnd") and not any(p in used_ports or p in snapped for p in on):
            uf.union("gnd", g)
            grounded.append(g.rsplit(".", 1)[0])
    if grounded:
        shown = ", ".join(grounded[:6]) + (f", … ({len(grounded)} in all)" if len(grounded) > 6 else "")
        notes.append(f"airbridge(s) with no port joined are ground straps (ports → gnd, no element): {shown}")

    # resolve conductors → circuit nodes
    classes: dict[str, list[str]] = {}
    for n in list(nodes) + ["gnd"]:
        classes.setdefault(uf.find(n), []).append(n)
    names: dict[str, str] = {}
    for root, members in classes.items():
        if uf.find("gnd") == root:
            for m in members:
                names[m] = "gnd"
            continue
        routes_ = [m.split(":", 1)[1] for m in members if m.startswith("route:")]
        prefer = [m for m in members if kind_of.get(m) == "qubit"] or [
            m for m in members if kind_of.get(m) == "coupler"
        ]
        names_ = routes_ or prefer or sorted(members)
        nm = names_[0]
        for m in members:
            names[m] = nm
    out_nodes: dict[str, dict] = {"gnd": {"ground": True}}
    for members in classes.values():
        nm = names[members[0]]
        if nm == "gnd":
            continue
        islands = [nodes[m]["island"] for m in members if nodes.get(m, {}).get("island")]
        if any(m.startswith("route:") for m in members):
            islands = [nm, *islands]
        layout = {"island": islands[0]} if islands else {}
        if len(islands) > 1:
            layout["aliases"] = islands[1:]
        out_nodes[nm] = {"layout": layout}

    branches: dict[str, dict] = {}
    for e in elements:
        n1, n2 = (names.get(n, n) for n in e.nodes)
        if n1 == n2:
            notes.append(f"{e.name}: both ends on {n1} after merging conductors (dropped)")
            continue
        branches[e.name] = {"type": e.type, "nodes": [n1, n2], "value": e.value, **({"knob": e.knob} if e.knob else {})}
    for port, n in list(port_map.items()):
        port_map[port] = names.get(n, n)
    referenced = {n for b in branches.values() for n in b["nodes"]}
    for nm in [n for n in out_nodes if n != "gnd" and n not in referenced]:
        notes.append(f"node {nm} has no elements (dropped)")
        del out_nodes[nm]
    # sub-circuits with no element path to ground (e.g. a lone junction or capacitor that nothing connects to)
    # cannot be part of the lumped circuit: drop them with a note instead of failing the whole build
    reached, changed = {"gnd"}, True
    while changed:
        changed = False
        for b in branches.values():
            n1, n2 = b["nodes"]
            if (n1 in reached) != (n2 in reached):
                reached |= {n1, n2}
                changed = True
    floating = sorted(set(out_nodes) - reached)
    if floating:
        dropped = [bn for bn, b in branches.items() if b["nodes"][0] in floating or b["nodes"][1] in floating]
        notes.append(f"node(s) {floating} have no path to ground; dropped with their elements {dropped}")
        for bn in dropped:
            del branches[bn]
        for nm in floating:
            del out_nodes[nm]

    targets = {}
    for inst, tgt in design.targets.items():
        for q, v in tgt.items():
            targets[f"{inst}.{q}"] = {"value": v, "tol": DEFAULT_TOL.get(q, abs(v) * 0.01)}
    unconnected = sorted(
        p
        for p, n in port_map.items()
        if p not in used_ports
        and not n.startswith("control:")
        and p.rsplit(".", 1)[1] not in ("squid_a", "squid_b")  # junction ends: not connection ports
        and p.split(".", 1)[0] in chosen
        and not _snapped(design, p)
    )
    model = CircuitModel.model_validate(
        {
            "name": name or f"{design.name}_lom",
            "design": design.name,
            "nodes": out_nodes,
            "branches": branches,
            "knobs": knobs,
            "targets": targets,
            "controls": controls,
        }
    )
    return LomBuild(model, notes, port_map, unconnected)


def _hanger_coupling(c, ends, ext_hangers, line_of, glob):
    """(line state, hanger spec, other node) when coupling ``c`` (no value) joins a component that declares a
    coupled section to an outside conductor (``Fragment.hangers``) to that conductor; else None."""
    for i, end in enumerate(c.between):
        inst, _, rest = end.partition(".")
        for spec in ext_hangers.get(inst, []):
            st = line_of.get((inst, spec["line"]))
            if st is None or (rest and glob(inst, rest) != st["node"]):
                continue
            other = ends[1 - i]
            if other != st["node"]:
                return st, spec, other
    return None


def _tap_extra(resonators, uf, nodes, kind_of, route_conductor, wire_length) -> dict[str, dict[str, float]]:
    """{resonator route: {wire route: length}} for resonator routes (to a free end or hanger) that start on a
    conductor which cpw wires extend, when that conductor has no port, feedline or qubit island and carries only
    this one resonator."""
    members: dict[str, list[str]] = {}
    for n in nodes:
        members.setdefault(uf.find(n), []).append(n)
    per_root: dict[str, list[str]] = {}
    for rname, (a, far, *_rest) in resonators:
        if far.startswith("hanger:") or far in ("gnd", "open"):
            per_root.setdefault(uf.find(a), []).append(rname)
    out = {}
    for root, rnames in per_root.items():
        if len(rnames) != 1 or root == uf.find("gnd"):
            continue
        if any(kind_of.get(m) in ("pad", "feedline", "qubit") for m in members.get(root, [])):
            continue
        wires = {w: wire_length[w] for w, n in route_conductor.items() if w in wire_length and uf.find(n) == root}
        if any(wires.values()):
            out[rnames[0]] = wires
    return out


def _end_term(spec) -> str:
    """``"short"`` / ``"open"`` of a route end that is not a port (a hanger's termination, a free end's ``term``)."""
    if hasattr(spec, "hanger"):
        return "short" if spec.end == "short" else "open"
    return "short" if spec.term == 0 else "open"


def _join(st, i, other, j) -> None:
    """Join end ``i`` of line state ``st`` to end ``j`` of ``other``: one line through both."""
    st["state"][i] = other["state"][j] = "joined"
    st["peer"][i], other["peer"][j] = (other, j), (st, i)


def _port_distance(plan, inst: str, ports) -> float:
    """Straight distance (µm) between an instance's two line ports in the plan (0 if one is missing)."""
    placed = plan.instances.get(inst)
    pts = [placed.ports[p].pos for p in ports if p and placed and p in placed.ports]
    return (pts[0] - pts[1]).length() if len(pts) == 2 else 0.0


def _is_termination(line) -> bool:
    """A zero-length line with one port (CpweOpenEnd, Metal OpenToGround / ShortToGround): only an end condition."""
    return line.length_um <= 0 and sum(1 for p in line.ports if p) == 1


def _ends_on_terminations(plan, design, line_states, terms, joined, tol=1.0) -> dict[str, tuple[str, float]]:
    """{line-end port: (termination port, distance µm)} for unjoined line ends (no wire, snap or route) that lie on
    the drawn body of an unjoined termination: the body runs ``length`` (cell parameter; else the gap) from the
    termination's port against its direction, ``a/2 + b`` to each side (± ``tol``). Each termination ends one line
    (the nearest end)."""
    free_terms = {}
    for tport, (tst, _idx) in terms.items():
        if tport in joined or tst["routes"]:
            continue
        inst, _, pname = tport.partition(".")
        placed = plan.instances.get(inst)
        port = placed.ports.get(pname) if placed else None
        if port is None or port.dir is None:
            continue
        line = tst["line"]
        try:
            depth = float(design.instances[inst].params.get("length", line.b_um))
        except (TypeError, ValueError):
            depth = line.b_um
        free_terms[tport] = (port, depth, line.a_um / 2 + line.b_um)
    if not free_terms:
        return {}
    best: dict[str, tuple[str, float]] = {}
    for st in line_states:
        line = st["line"]
        if _is_termination(line):
            continue
        for i, pname in enumerate(line.ports):
            ref = f"{st['inst']}.{pname}" if pname else None
            if ref is None or ref in joined or st["state"][i] is not None:
                continue
            placed = plan.instances.get(st["inst"])
            port = placed.ports.get(pname) if placed else None
            if port is None:
                continue
            for tport, (tp, depth, half) in free_terms.items():
                v = port.pos - tp.pos
                along = -(v.x * tp.dir.x + v.y * tp.dir.y)
                across = abs(v.x * tp.dir.y - v.y * tp.dir.x)
                if -tol <= along <= depth + tol and across <= half + tol:
                    dist = v.length()
                    if tport not in best or dist < best[tport][1]:
                        best[tport] = (ref, dist)
    return {ref: (tport, dist) for tport, (ref, dist) in best.items()}


def _snapped(design, port: str) -> bool:
    return _snap_partner(design, port) is not None


def _snap_partner(design, port: str) -> str | None:
    """The port that ``port`` is snapped to (either side of a snap placement), or None."""
    for name, other in design.instances.items():
        pl = other.place
        if pl.snap and pl.to:
            snap = pl.snap if "." in pl.snap else f"{name}.{pl.snap}"
            if port == snap:
                return pl.to
            if port == pl.to:
                return snap
    return None
