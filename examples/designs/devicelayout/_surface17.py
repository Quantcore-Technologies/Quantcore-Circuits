"""Surface-17 chip generator for the Quantcore-PDK rebuilds of DeviceLayout.jl ``DemoQPU17`` and the ETH Zurich
17-qubit device (Krinner et al., Nature 605, 669 (2022); Quantum Metal notebook 53).

Both chips have the same topology:

* 17 star transmons on the 5 × 5 sites ``01100 / 01111 / 11111 / 11110 / 00110``;
* 24 nearest-neighbour CPW couplers;
* per qubit, a λ/4 readout resonator and a λ/4 Purcell filter. The filter is tapped off one of four feedlines by a
  capacitive tee, and each feedline has a series input capacitor;
* an XY (drive) line and a Z (flux) line per qubit.

The source sets the topology, the lattice, the port map and the targets. The geometry is ours, drawn with qcc
components and routes on the Quantcore PDK.

**Qubits** are ``metal:StarQubit`` with Quantcore trilayer SQUIDs. The couplers point E / N / W / S and the readout
pad points along the qubit's readout diagonal. The SQUID sits in the 90° gap between the E and N couplers
(local frame): the Z line reaches it over the qubit's own N coupler, bridged when there is one. The XY end sits
between the readout pad and the W (or E) coupler.

**Readout module.** It is laid out in the qubit's local frame, then mirrored into the quadrant of its feedline
(DeviceLayout's ``MIRRORED_LR`` / ``MIRRORED_UD``). In the local frame the readout diagonal ``u`` points at 135° and
``v`` at 45°.

- The readout λ/4 is a hairpin: from the readout pad along ``u``, legs at ``v = 0, −80, −160``, shorted.
- The Purcell λ/4 is a hairpin from the tee's coupled port back along ``−u``, legs at ``v = 140, 220, …``, shorted.
- The tee (``metal:CapNInterdigitalTee``) sits at the module tip, its feedline running along ``v``.
- The XY line runs along ``v = −260`` and the Z line along ``v = +480``. Both cross the qubit's own feedline next to
  the tee; the Z line then passes over the N coupler to the SQUID.
- The readout–filter tap is a declared capacitance (``Designer.couple``), not drawn.

A qubit in a closed plaquette (the centre qubit) has a shortened readout hairpin. Its Purcell hairpin and tee are laid
out in a *host* qubit's frame: the channel between two parallel modules, next to the plaquette's coupler.

**Crossings** are found on the drawn polylines. The upper line of a crossing is split, and an ``AirbridgeConnection``
is placed over the lower one, as DeviceLayout's ``crossovers!`` does. The order, lowest first: couplers < resonators <
feedlines < Z < XY. :func:`plan_chip` lists each crossing that cannot be bridged cleanly: too near a bend, too
shallow, or two bridges overlapping.

Units µm, degrees. Coordinates are in the Designer frame: chip box ``(0, 0, W, H)``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

SITES = [(1, 2), (1, 3), (2, 2), (2, 3), (2, 4), (2, 5), (3, 1), (3, 2), (3, 3), (3, 4), (3, 5),
         (4, 1), (4, 2), (4, 3), (4, 4), (5, 3), (5, 4)]  # (row, col), row 1 = top (DeviceLayout ACTIVE_SITES)
QUADRANT = {"NW": (False, False), "NE": (True, False), "SE": (True, True), "SW": (False, True)}  # (mirror LR, UD)
R2 = math.sqrt(0.5)

R_PIN = 187.5                 # StarQubit pins sit at 1.25 × radius (radius 150)
PITCH, R_BEND = 80.0, 35.0    # hairpin leg pitch and bend radius
RO_LEGS = [0.0, -80.0, -160.0, -240.0, -320.0]
PF_LEGS = [140.0, 220.0, 300.0, 380.0]
V_XY, V_Z = -260.0, 480.0     # control strips, outside the hairpins
U_NEAR = 650.0                # hairpin legs turn here near the qubit
U_TURN = 600.0                # control lines leave their strip here toward their end at the qubit
JJ_ANGLE = 45.0               # SQUID (local frame): in the 90° gap between the E and N couplers. A 45° gap (next to the
                              # readout pad) has no island arm: StarQubit cut-outs span ±27° at their inner end.
                              # The SQUID leads reach radius + center_radius / 2: keep that inside the pocket
                              # (< radius + connector_length), or the island touches ground (no FEM island net)
AB_HALF = 83.416              # AirbridgeConnection ports at ±83.4 µm
TOL_VERTEX_UPPER = 150.0      # crossing → nearest bend of the bridged (upper) line
TOL_VERTEX_LOWER = 110.0      # crossing → nearest bend of the crossed (lower) line
TOL_ANGLE = 50.0              # minimum crossing angle (deg)

FEED = dict(a=10.0, b=6.0)    # feedlines and control lines (DeviceLayout FEEDLINE_STYLE 10/6)
RES = dict(a=10.0, b=10.0)    # couplers and resonators (DeviceLayout CPW 10/10)
TEE = {"prime_width": 10, "prime_gap": 6, "second_width": 10, "second_gap": 10, "finger_count": 8,
       "finger_length": 60, "cap_width": 8, "cap_gap": 5, "cap_distance": 30}
CIN = {"finger_number": 6, "finger_length": 60, "finger_width": 6, "finger_gap": 4, "a": 10, "b": 6}
AB = {"a": 10, "b": 6, "a2": 10, "b2": 6}
PAD = {"pad_width": 300, "pad_height": 300, "pad_gap": 100, "taper_length": 300}


def star_options(data: bool, star: dict | None = None) -> dict:
    """``metal:StarQubit`` options, scaled from DeviceLayout's ``ExampleStarTransmon``:
    - pocket radius 150 µm (a 135 µm star plus its 15 µm gap);
    - a narrower readout gap on the data qubits, standing in for their bigger readout coupler (inner radius 20 µm)."""
    star = dict(star or {})
    gaps = star.pop("gap_readout", (8, 15))  # (data, auxiliary)
    return {"radius": 150, "center_radius": 70, "gap_couplers": 15, "gap_readout": gaps[0] if data else gaps[1],
            "connector_length": 40, "trap_offset": 11, "junc_h": 30, "number_of_connectors": 4, "resolution": 16,
            **star}


def is_data(site) -> bool:
    """Data qubits sit where row + column is even (DeviceLayout ``DATA_QUBIT``, the ETH D-qubits)."""
    return (site[0] + site[1]) % 2 == 0


# ---- geometry helpers ----------------------------------------------------------------------------------------------
def _ang(p, q) -> float:
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))


def _add(p, d, s=1.0):
    return (p[0] + s * d[0], p[1] + s * d[1])


def _dir(deg):
    return (math.cos(math.radians(deg)), math.sin(math.radians(deg)))


def _dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _rot(p, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


@dataclass
class Frame:
    """Local frame of one qubit: local x / y mirrored into its quadrant, u / v the readout-module axes."""

    centre: tuple[float, float]
    lr: bool
    ud: bool

    def xy(self, x, y):
        return (self.centre[0] + (-x if self.lr else x), self.centre[1] + (-y if self.ud else y))

    def uv(self, u, v):
        return self.xy((-u + v) * R2, (u + v) * R2)

    def pol(self, r, theta):
        return self.xy(r * math.cos(math.radians(theta)), r * math.sin(math.radians(theta)))

    def ang(self, theta) -> float:
        t = math.radians(theta)
        sy, sx = (-1 if self.ud else 1) * math.sin(t), (-1 if self.lr else 1) * math.cos(t)
        return math.degrees(math.atan2(sy, sx)) % 360


def hairpin(u0: float, legs: list[float], u_far: float, u_near: float, length: float, outward: bool):
    """(u, v) nodes of a hairpin meander from ``(u0, legs[0])``, heading ``+u`` (``outward``) or ``−u``.

    The legs alternate between ``u_far`` and ``u_near``. The last leg is cut so that the drawn (filleted,
    r = R_BEND) length is ``length``. Returns (nodes, end point, number of legs used)."""
    cut = (2 - math.pi / 2) * R_BEND  # a 90° fillet shortens the polyline by this
    nodes, u, drawn = [], u0, 0.0
    heading = 1 if outward else -1
    for k, v in enumerate(legs):
        target = u_far if heading > 0 else u_near
        leg = abs(target - u)
        rest = length - drawn
        if rest <= leg or k == len(legs) - 1:
            if rest > leg + 1e-6:
                raise ValueError(f"hairpin: {length:.0f} µm do not fit in {len(legs)} legs ({u_near:.0f}–{u_far:.0f})")
            if k and rest < R_BEND + 10:
                raise ValueError(f"hairpin: last leg {rest:.0f} µm too short (move u_far)")
            return nodes, (u + heading * rest, v), k + 1
        nodes += [(target, v), (target, legs[k + 1])]
        drawn += leg + abs(legs[k + 1] - v) - 2 * cut
        u, heading = target, -heading
    raise ValueError("hairpin: no legs")


def u_far_for(length: float, n_legs: int, u0: float = R_PIN, slack: float = 60.0) -> float:
    """Far turn of an outward hairpin from ``u0`` with ``n_legs`` legs, so that its last leg ends ``slack`` short of
    the turn it heads for."""
    cut = (2 - math.pi / 2) * R_BEND
    turns = (n_legs - 1) * (PITCH - 2 * cut)
    return (length - turns + u0 + (n_legs - 1) * U_NEAR + slack) / n_legs


def _seg_cross(p, q, r, s):
    """Intersection point of segments pq and rs (None if they do not cross)."""
    d1, d2 = (q[0] - p[0], q[1] - p[1]), (s[0] - r[0], s[1] - r[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return None
    t = ((r[0] - p[0]) * d2[1] - (r[1] - p[1]) * d2[0]) / den
    w = ((r[0] - p[0]) * d1[1] - (r[1] - p[1]) * d1[0]) / den
    if 0 < t < 1 and 0 < w < 1:
        return (p[0] + t * d1[0], p[1] + t * d1[1])
    return None


# ---- the plan ------------------------------------------------------------------------------------------------------
@dataclass
class Line:
    """A drawn polyline (one or more routes): ``pts[0]`` / ``pts[-1]`` are its end points (ports or free ends)."""

    name: str
    kind: str                  # coupler | resonator | feed | z | xy
    start: object              # port ref
    end: object                # port ref or free-end dict
    pts: list
    a: float = 10.0
    b: float = 6.0
    r: float = 50.0
    bridges: list = field(default_factory=list)  # (point, segment index, angle): this line passes over another


RANK = {"coupler": 0, "resonator": 1, "feed": 2, "z": 3, "xy": 4}


@dataclass
class Config:
    """One surface-17 chip: what the source fixes (lattice, port map, feedline groups, targets) and the floorplan."""

    name: str
    box: tuple[float, float]
    centre: tuple[float, float]
    pitch: tuple[float, float]             # (column, row) spacing
    labels: dict                           # site → qubit name
    quadrant: dict                         # qubit → "NW" | "NE" | "SE" | "SW" (readout diagonal, feedline side)
    f_ro: dict                             # qubit → readout (and Purcell) target, GHz
    f_q: dict                              # qubit → qubit target, GHz (junction sizing)
    pads: dict                             # pad name → (x, y, port direction deg)
    feedlines: dict                        # line → dict(pad_in, pad_out, qubits [in order], vias {k: [pts]}, …)
    controls: dict                         # "XY_<q>" / "Z_<q>" → dict(pad, vias [pts], u_out, dv)
    shortened: dict = field(default_factory=dict)  # qubit → module overrides (closed plaquette), see module doc
    k_tap_fF: float = 1.2                  # readout–Purcell tap (J ≈ 12 MHz at 7 GHz, assumed)
    length_scale: object = 1.0             # readout (or (data, aux)): drawn λ/4 = scale × v_ph / 4f (LOM-calibrated loading)
    pf_length_scale: float = 1.0           # Purcell filter: the same, loaded by the tee instead of the qubit
    swap_pads: bool = False                # a qubit's Z and XY pads may be exchanged (fewer crossings)
    star: dict = field(default_factory=dict)  # StarQubit option overrides (``gap_readout``: (data, aux))

    def site_xy(self, site):
        r, c = site
        return (self.centre[0] + (c - 3) * self.pitch[0], self.centre[1] - (r - 3) * self.pitch[1])

    def frame(self, q) -> Frame:
        site = next(s for s, n in self.labels.items() if n == q)
        lr, ud = QUADRANT[self.quadrant[q]]
        return Frame(self.site_xy(site), lr, ud)


def lambda4_um(f_GHz: float, scale: float = 1.0) -> float:
    """Drawn λ/4 length of a 10/10 µm CPW on the PDK stack at ``f_GHz`` (times ``scale``)."""
    from quantcore_circuits.circuit.bridges import tl_resonator  # pylint: disable=import-outside-toplevel

    vp = tl_resonator(4500, RES["a"], RES["b"])["vp_m_s"]
    return scale * vp / (4 * f_GHz * 1e9) * 1e6


def _local_ports(cell: str, params: dict) -> dict:
    from quantcore_circuits.designer import _ports  # pylint: disable=import-outside-toplevel

    p = _ports(cell, json.dumps(params, sort_keys=True))
    return {k: (v.pos.x, v.pos.y) for k, v in p.items()}


def neighbours(labels: dict) -> list[tuple[str, str, str]]:
    """(name, left/top qubit, right/bottom qubit) of the 24 couplers."""
    out = []
    for (r, c), q in labels.items():
        if (r, c + 1) in labels:
            out.append((f"CPL_{q}_{labels[(r, c + 1)]}", q, labels[(r, c + 1)]))
        if (r + 1, c) in labels:
            out.append((f"CPL_{q}_{labels[(r + 1, c)]}", q, labels[(r + 1, c)]))
    return out


def plan_chip(cfg: Config) -> dict:
    """Lay the chip out. Returns instances, lines (with their airbridges), couplings and diagnostics."""
    inst: dict[str, dict] = {}
    lines: list[Line] = []
    couplings: list[tuple] = []
    problems: list[str] = []
    tee_local = _local_ports("metal:CapNInterdigitalTee", TEE)
    cin_half = abs(_local_ports("FingerCapacitorSquare", CIN)["a"][0])
    sec = tee_local["second_end"]
    site_of = {q: s for s, q in cfg.labels.items()}
    r_pin = 1.25 * float(cfg.star.get("radius", 150))  # StarQubit pins sit at 1.25 × radius

    # qubits: pins E/N/W/S (cpl1..4), readout on the diagonal, SQUID between the N|S coupler and the readout pad
    for q in cfg.labels.values():
        f = cfg.frame(q)
        rot = {"rotation_cpl1": 90.0, "rotation_cpl2": 180.0, "rotation_cpl3": 270.0, "rotation_cpl4": 0.0,
               "rotation_rdout": round((f.ang(135) + 90) % 360, 3), "rotation_jj": round((f.ang(JJ_ANGLE) + 90) % 360, 3)}
        inst[q] = dict(cell="metal:StarQubit", at=f.centre, rot=0.0,
                       params={**star_options(is_data(site_of[q]), cfg.star), **rot})

    def pin(q, name):
        f = cfg.frame(q)
        ang = f.ang(135) if name == "pin_rdout" else {"pin_cpl1": 0, "pin_cpl2": 90, "pin_cpl3": 180, "pin_cpl4": 270}[name]
        return _add(f.centre, _dir(ang), r_pin)

    for name, a, b in neighbours(cfg.labels):  # couplers: straight between facing pins
        horizontal = abs(cfg.frame(a).centre[1] - cfg.frame(b).centre[1]) < 1
        pa, pb = ("pin_cpl1", "pin_cpl3") if horizontal else ("pin_cpl4", "pin_cpl2")
        lines.append(Line(name, "coupler", f"{a}.{pa}", f"{b}.{pb}", [pin(a, pa), pin(b, pb)], r=50, **RES))

    tee_at: dict[str, dict] = {}
    for q in cfg.labels.values():  # readout modules
        f = cfg.frame(q)
        sp = cfg.shortened.get(q, {})
        ls = cfg.length_scale  # a number, or (data, auxiliary): the qubit pulls its readout by role
        ls = (ls[0] if is_data(site_of[q]) else ls[1]) if isinstance(ls, (list, tuple)) else ls
        length = lambda4_um(cfg.f_ro[q], ls)
        pf_length = lambda4_um(cfg.f_ro[q], cfg.pf_length_scale)
        n_ro = sp.get("ro_legs", 3)
        u_far = sp.get("u_far") or u_far_for(length, n_ro, u0=r_pin)
        nodes, end, _ = hairpin(r_pin, RO_LEGS[:n_ro], u_far, U_NEAR, length, outward=True)
        pts = [pin(q, "pin_rdout")] + [f.uv(*n) for n in nodes] + [f.uv(*end)]
        lines.append(Line(f"RO_{q}", "resonator", f"{q}.pin_rdout",
                          {"at": list(pts[-1]), "dir": _ang(pts[-1], pts[-2]), "term": 0}, pts, r=R_BEND, **RES))
        pf_legs = sp.get("pf_legs", PF_LEGS)
        if "tee" in sp:  # closed plaquette: the tee outside, a lead from its coupled port to the hairpin inside
            tee_c, trot = tuple(sp["tee"]), float(sp["tee_rot"])
        else:
            u_tee = u_far + 300.0
            tee_c = f.uv(u_tee, pf_legs[0])
            trot = round((f.ang(315) + 90) % 360, 6)        # the tee's coupled port (local −y) points along −u
        se = _add(tee_c, _rot(sec, trot))
        ps = _add(tee_c, _rot(tee_local["prime_start"], trot))
        pe = _add(tee_c, _rot(tee_local["prime_end"], trot))
        inst[f"T_{q}"] = dict(cell="metal:CapNInterdigitalTee", at=tee_c, rot=trot, params=dict(TEE))
        tee_at[q] = dict(c=tee_c, rot=trot, ps=ps, pe=pe, se=se)
        if "tee" in sp:
            u0 = float(sp["pf_u0"])
            start = f.uv(u0, pf_legs[0])
            # off the coupled port (it points at trot − 90) until level with the hairpin start, then straight to it:
            # horizontally (lead_axis "y": reach its y first) or vertically ("x": reach its x first)
            ax = 0 if sp.get("lead_axis", "y") == "x" else 1
            t = se[ax] - start[ax]
            d45 = _dir(trot - 90)
            lead = [_add(se, d45, abs(t) / abs(d45[ax]))] if abs(d45[ax]) > 1e-6 and abs(t) > 1e-6 else []
            lead_len = sum(_dist(a, b) for a, b in zip([se] + lead, lead + [start]))
            nodes, end, _ = hairpin(u0, pf_legs, sp.get("pf_u_far", u_far), U_NEAR, pf_length - lead_len, outward=False)
            pts = [se] + lead + [start] + [f.uv(*n) for n in nodes] + [f.uv(*end)]
        else:
            nodes, end, _ = hairpin(u_tee - abs(sec[1]), pf_legs, u_far, U_NEAR, pf_length, outward=False)
            pts = [se] + [f.uv(*n) for n in nodes] + [f.uv(*end)]
        lines.append(Line(f"PF_{q}", "resonator", f"T_{q}.second_end",
                          {"at": list(pts[-1]), "dir": _ang(pts[-1], pts[-2]), "term": 0}, pts, r=R_BEND, **RES))
        couplings.append((f"K_{q}", f"RO_{q}", f"PF_{q}", cfg.k_tap_fF, "readout–Purcell tap (declared, not drawn)"))

    for ln, spec in cfg.feedlines.items():  # feedlines: pad_in → CIN → tees in order → pad_out
        pin_xy, pin_dir = cfg.pads[spec["pad_in"]][:2], cfg.pads[spec["pad_in"]][2]
        pout_xy, pout_dir = cfg.pads[spec["pad_out"]][:2], cfg.pads[spec["pad_out"]][2]
        cin_c = _add(pin_xy, _dir(pin_dir), 700.0)
        inst[f"CIN_{ln}"] = dict(cell="FingerCapacitorSquare", at=cin_c, rot=pin_dir, params=dict(CIN))
        cin_a, cin_b = _add(cin_c, _dir(pin_dir), -cin_half), _add(cin_c, _dir(pin_dir), cin_half)
        lines.append(Line(f"FL{ln}_in", "feed", f"{spec['pad_in']}.a", f"CIN_{ln}.a", [pin_xy, cin_a], **FEED))
        prev_ref, prev_xy, prev_dir = f"CIN_{ln}.b", cin_b, pin_dir
        vias = spec.get("vias", {})
        stub = spec.get("stub", 520.0)

        def stub_of(q, side, _s=spec.get("stubs", {}), _d=stub):
            v = _s.get(q, _d)
            return float(v[0] if side == "in" else v[1]) if isinstance(v, (list, tuple)) else float(v)

        ext_out = 250.0
        for k, q in enumerate(list(spec["qubits"]) + [None]):
            if q is None:
                nxt_ref, nxt_xy, nxt_dir, ext_in = f"{spec['pad_out']}.a", pout_xy, pout_dir, 300.0
            else:
                t = tee_at[q]
                first = tuple((vias.get(k) or [_add(prev_xy, _dir(prev_dir), ext_out)])[-1])
                port_in = spec.get("enter", {}).get(q) or (
                    "prime_start" if _dist(t["ps"], first) <= _dist(t["pe"], first) else "prime_end")
                port_out = "prime_end" if port_in == "prime_start" else "prime_start"
                nxt_ref = f"T_{q}.{port_in}"
                nxt_xy = t["ps"] if port_in == "prime_start" else t["pe"]
                nxt_dir = t["rot"] + (180 if port_in == "prime_start" else 0)
                ext_in = stub_of(q, "in")
            pts = [prev_xy, _add(prev_xy, _dir(prev_dir), ext_out)] + [tuple(p) for p in vias.get(k, [])]
            pts += [_add(nxt_xy, _dir(nxt_dir), ext_in), nxt_xy]
            lines.append(Line(f"FL{ln}_{k}", "feed", prev_ref, nxt_ref, pts, r=spec.get("r", 50.0), **FEED))
            if q is not None:
                prev_ref = f"T_{q}.{port_out}"
                prev_xy = t["pe"] if port_out == "prime_end" else t["ps"]
                prev_dir = t["rot"] + (0 if port_out == "prime_end" else 180)
                ext_out = stub_of(q, "out")

    # control lines: pad → (vias) → strip → turn → end beside the qubit. Where a line joins its strip (u_out) is
    # chosen per line unless given: before the module tip (pad on the qubit's side of its feedline) or past it.
    def control(name, spec, placed):
        """Best candidate (score, Line) for one control line against the lines placed so far."""
        kind, q = name.split("_", 1)
        f = cfg.frame(q)
        pxy, pdir = cfg.pads[spec["pad"]][:2], cfg.pads[spec["pad"]][2]
        vline = (V_XY if kind == "XY" else V_Z) + spec.get("dv", 0.0)
        if kind == "XY":
            end, term, approach = f.pol(r_pin + 63.0, 157.5), 6.0, []
        else:  # over the qubit's own N coupler (bridged when there is one), then down to the SQUID
            end, term = f.pol(r_pin + 45.0, JJ_ANGLE), 0.0
            approach = [f.xy(-250.0, r_pin + 175.0), f.xy(250.0, r_pin + 175.0)]
        head = [pxy, _add(pxy, _dir(pdir), spec.get("pad_stub", 300.0))] + [tuple(p) for p in spec.get("vias", [])]
        best = None
        for u_out in ([spec["u_out"]] if "u_out" in spec else [2700.0, 1500.0, 2200.0, 1100.0]):
            pts = head + [f.uv(u_out, vline), f.uv(U_TURN, vline)] + approach + [end]
            cand = Line(name, kind.lower(), f"{spec['pad']}.a",
                        {"at": list(end), "dir": _ang(end, pts[-2]), "term": term}, pts, **FEED)
            issues, n = _score(cand, placed)
            if best is None or 100 * len(issues) + n < best[0]:
                best = (100 * len(issues) + n, cand)
        return best

    # per qubit: Z first, then XY (XY passes over Z); with ``swap_pads`` the two pads may be exchanged if that
    # crosses less (the source's port map does not know our module layout)
    qubits = sorted({n.split("_", 1)[1] for n in cfg.controls})
    for q in qubits:
        z, xy = cfg.controls.get(f"Z_{q}"), cfg.controls.get(f"XY_{q}")
        options = [(z, xy)]
        if cfg.swap_pads and z and xy and not (z.get("vias") or xy.get("vias")):
            options.append(({**z, "pad": xy["pad"]}, {**xy, "pad": z["pad"]}))
        best = None
        for zs, xs in options:
            chosen, total = [], 0
            for name, spec in ((f"Z_{q}", zs), (f"XY_{q}", xs)):
                if spec is None:
                    continue
                s, line = control(name, spec, lines + chosen)
                chosen.append(line)
                total += s
            if best is None or total < best[0]:
                best = (total, chosen)
        lines.extend(best[1])

    for p, (x, y, dirn) in cfg.pads.items():
        inst[p] = dict(cell="BondPad", at=(x, y), rot=(dirn - 90.0) % 360, params=dict(PAD))

    bridges = _bridge(lines, problems, inst)
    return dict(instances=inst, lines=lines, bridges=bridges, couplings=couplings, problems=problems, tees=tee_at)


def _crossings(la: Line, lb: Line):
    """Crossings of two lines: (point, upper line, lower line, upper segment, lower segment, problems)."""
    out = []
    for k, (p, q) in enumerate(zip(la.pts, la.pts[1:])):
        for m, (r, s) in enumerate(zip(lb.pts, lb.pts[1:])):
            pt = _seg_cross(p, q, r, s)
            if pt is None:
                continue
            up, lo, ku, kl = (la, lb, k, m) if RANK[la.kind] >= RANK[lb.kind] else (lb, la, m, k)
            what = f"{up.name} over {lo.name} at ({pt[0]:.0f}, {pt[1]:.0f})"
            issues = []
            if up.kind == "coupler" or (up.kind == "resonator" and lo.kind != "coupler"):
                issues.append(f"forbidden crossing: {what}")
            a_up, a_lo = _ang(up.pts[ku], up.pts[ku + 1]), _ang(lo.pts[kl], lo.pts[kl + 1])
            rel = abs((a_up - a_lo + 90) % 180 - 90)
            if rel < TOL_ANGLE:
                issues.append(f"shallow crossing ({rel:.0f}°): {what}")
            for line, idx, tol in ((up, ku, TOL_VERTEX_UPPER), (lo, kl, TOL_VERTEX_LOWER)):
                n = len(line.pts)
                inner = [line.pts[j] for j in (idx, idx + 1) if 0 < j < n - 1]
                ends = [line.pts[j] for j in (idx, idx + 1) if j in (0, n - 1)]
                dv = min([_dist(pt, v) for v in inner] or [1e9])
                de = min([_dist(pt, v) for v in ends] or [1e9])
                if dv < tol or de < AB_HALF + 40:
                    issues.append(f"crossing {min(dv, de):.0f} µm from a bend/end of {line.name}: {what}")
            out.append((pt, up, lo, ku, a_up, issues))
    return out


def _score(cand: Line, lines: list[Line]) -> tuple[list[str], int]:
    """Problems and number of crossings of a candidate control line against the lines placed so far."""
    issues, n = [], 0
    for other in lines:
        for _, _, _, _, _, iss in _crossings(cand, other):
            n += 1
            issues += iss
    return issues, n


def _bridge(lines: list[Line], problems: list[str], inst: dict) -> list[dict]:
    """Every crossing between two lines: the higher-ranked line passes over (it is split there)."""
    for i, la in enumerate(lines):
        for lb in lines[i + 1:]:
            for pt, up, _, ku, a_up, issues in _crossings(la, lb):
                problems += issues
                if not any(x.startswith("forbidden") for x in issues):
                    up.bridges.append((pt, ku, a_up))
    out = []
    for line in lines:
        line.bridges.sort(key=lambda b: (b[1], _dist(line.pts[b[1]], b[0])))
        for (p1, _, _), (p2, _, _) in zip(line.bridges, line.bridges[1:]):
            if _dist(p1, p2) < 2 * AB_HALF + 40:
                problems.append(f"{line.name}: bridges at ({p1[0]:.0f}, {p1[1]:.0f}) and ({p2[0]:.0f}, {p2[1]:.0f}) "
                                "overlap")
        for j, (pt, _, ang) in enumerate(line.bridges):
            name = f"AB_{line.name}_{j}"
            inst[name] = dict(cell="AirbridgeConnection", at=pt, rot=round(ang, 6), params=dict(AB))
            out.append(dict(name=name, line=line.name, at=pt, rot=ang))
    return out


def routes_of(line: Line) -> list[dict]:
    """The line as qcc routes: one per section between its airbridges (first section keeps the line's name)."""
    def section(name, start, end, p0, p1, nodes):
        if not nodes and line.kind != "coupler":  # keep the router on the drawn (possibly oblique) line
            nodes = [((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)]
        return dict(name=name, start=start, end=end, nodes=nodes)

    if not line.bridges:
        return [section(line.name, line.start, line.end, line.pts[0], line.pts[-1], line.pts[1:-1])]
    out, start, k0, p0 = [], line.start, 0, line.pts[0]
    for j, (pt, k, ang) in enumerate(line.bridges):
        nodes = [line.pts[i] for i in range(k0 + 1, k + 1)]
        p1 = _add(pt, _dir(ang), -AB_HALF)
        out.append(section(line.name if j == 0 else f"{line.name}_{j}", start, f"AB_{line.name}_{j}.a", p0, p1, nodes))
        start, k0, p0 = f"AB_{line.name}_{j}.b", k, _add(pt, _dir(ang), AB_HALF)
    nodes = [line.pts[i] for i in range(k0 + 1, len(line.pts) - 1)]
    out.append(section(f"{line.name}_{len(line.bridges)}", start, line.end, p0, line.pts[-1], nodes))
    return out


def build(d, plan: dict, junctions: dict) -> None:
    """Add the plan to a :class:`~quantcore_circuits.designer.Designer` (call inside ``d.batch()``).
    ``junctions`` maps a qubit to ``(params, junction)`` from ``registry.trilayer_junction``."""
    for name, s in plan["instances"].items():
        params, jj = junctions.get(name, ({}, None))
        kw = dict(junction=jj) if jj else {}
        d.add(name, s["cell"], at=tuple(s["at"]), rot=s["rot"], **s["params"], **params, **kw)
    for line in plan["lines"]:
        for r in routes_of(line):
            d.route(r["name"], r["start"], r["end"], type="cpw", nodes=[tuple(n) for n in r["nodes"]],
                    a=line.a, b=line.b, r=line.r)
    for name, a, b, c, note in plan["couplings"]:
        d.couple(name, a, b, C_fF=c, note=note)


def summary(plan: dict) -> dict:
    """Counts for the notebook: instances by cell, lines by kind, airbridges, problems."""
    from collections import Counter  # pylint: disable=import-outside-toplevel

    return {
        "instances": dict(Counter(s["cell"] for s in plan["instances"].values())),
        "lines": dict(Counter(line.kind for line in plan["lines"])),
        "routes": sum(len(routes_of(line)) for line in plan["lines"]),
        "airbridges": len(plan["bridges"]),
        "problems": len(plan["problems"]),
    }


# ---- v2 design notebooks (nb-v2-A, 2026-11-18): the layout one stage at a time. Additive: nothing above changed.
def needs(plan: dict, kinds) -> set:
    """The instances the planned lines of ``kinds`` start or end on (not their own airbridges, which the notebook's
    ``add_lines`` places with them): what must be on the chip before those lines are drawn. Feedlines need the pads,
    the input capacitors and the tees; readouts and filters the qubits and the tees; couplers the qubits; Z / XY
    lines only their pads (they end free beside the qubit)."""
    out = set()
    for line in plan["lines"]:
        if line.kind in kinds:
            for end in (line.start, line.end):
                if isinstance(end, str):
                    out.add(end.split(".", 1)[0])
    return out
