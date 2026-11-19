"""Surrogates (M11) and the co-design loop (M12): extracted parameters → new knob values → new design revision.

**Elements.** Every transmon–readout pair of the filled circuit (:func:`~quantcore_circuits.circuit.fill.fill`:
grounded and floating qubits, λ/4 and λ/2 readouts) reduces to the same 2-node network: ``C_island`` (island →
ground, the qubit mode of a floating transmon), ``Cg`` (island ↔ coupler) and ``C_coupler`` (coupler → ground), plus
the junction ``Lj_nH`` and the resonator line (``length_um``, λ/4 or λ/2).

**Surrogate (knob → element value).** Each capacitance gets a power law in the geometry knobs,
``v = v0 (k/k0)^p · Π (k_j/k_j0)^p_j``, anchored at the latest point (space mapping: the anchor is the measurement —
FEM, or the layout's own estimates — so the surrogate is exact there). The exponents are the local sensitivities of
the component's own LOM model (its fragment re-evaluated at ±2 % of each knob, the branch values scaled by
estimate(k)/estimate(k0) and reduced to the pair), so they hold for every qubit class with a LOM model; an Xmon's
are its calibration exponents (1.0, 1.0, 0.8). With two or more FEM points at different knob values the primary
exponent is refitted (log–log least squares). Junction inductance and resonator length are knobs themselves.

Knobs per class (:data:`QUBIT_KNOBS`: the island-capacitance knob, the coupler knob for C_g; ``<node>`` is the
readout coupler's node in the qubit's LOM, e.g. ``claw_n``, ``cplr1``, ``readout``):

=======================================  ================================  =======================================
class                                    island (C_Σ)                      coupler (C_g)
=======================================  ================================  =======================================
``Xmon``                                 ``cross_length``                  ``claw_length``
``Swissmon``                             ``arm_length.*`` (all four arms)  ``cpl_length.<i>``
``CircularTransmonSingleIsland``         ``r_island``                      ``couplers_arc_amplitude.<i>``
``ConcentricTransmon``                   ``r_inner``                       ``couplers_arc_amplitude.<i>``
``DoublePads(Splines)``                  ``island_island_gap``             ``coupler_extent.0``
``TwoPadTransmon``                       ``pad_height``                    its coupler cell (below)
``Flipmon``                              ``top_circle_radius``             ``coupler_length``
``Gatemon``                              ``island_size.*``                 its coupler cell (below)
``TransmonTaperedInsets``                ``pad_width``                     ``connection_pads.<node>.pad_width``
``metal:TransmonPocket`` (CL, 6, Teeth)  ``pad_width``                     ``connection_pads.<node>.pad_width``
``metal:TransmonCross`` (FL)             ``cross_length``                  ``connection_pads.<node>.claw_length``
``metal:TransmonStar``                   ``arm_length``                    ``connection_pads.<node>.claw_length``
``metal:TransmonConcentric``             ``gap``                           ``res_s``
``metal:TransmonConcentricType2``        ``gap``                           ``finger_<NE|NW|SW>_length``
``metal:TransmonInterdigitated``         ``finger_height``                 ``cc_width`` (bus: ``cc_top*_width``)
``metal:StarQubit``                      ``center_radius``                 ``gap_readout`` / ``gap_couplers``
coupler cells (:data:`COUPLER_KNOBS`)    ``PadCoupler.pad_height``         ``GatemonCoupler.coupling_capacitance``
=======================================  ================================  =======================================

``L_J``: ``<Q>.junction.Lj_nH`` when the design sets it (a drawn junction without a design value is not tuned).
Resonator: the TLres knob (``<R>.length``, a line cell's ``resonator_length`` / ``cpw_len``), or the one meander route
with a length on the resonator's conductor; the rest of the line is a constant ``extra_length_um``. A knob that is
missing, not a number or without effect in the LOM is left out and the surrogate says why (``notes``).

**Forward model.** Elements → the same 2-node network the estimators quantise (:class:`~quantcore_circuits.circuit.
fill.TransmonReadout`, λ/4 or λ/2) → the dressed spectrum of :mod:`quantcore_circuits.circuit.hamiltonian`
(transmon in the charge basis + resonator, no RWA; diagonalised with numpy, the same matrices as the QuTiP model)
→ f_q, α, f_r, g, χ.

**Proposal (L0 + L1).** Bounded least squares over the knobs on ``(predicted − target)/tol`` for the four targets;
a knob whose target is not set stays where it is (no α target: the island knob is kept, and so on). When the
surrogate can re-evaluate the LOM (``surrogate_from_fill`` on a real circuit), the solution is checked against the
LOM at the proposed knobs and the exponents corrected along the move (secant), up to three times, and if that does
not settle the last solve runs on the LOM itself: a large move stays accurate for non-power-law estimates. (The LOM
rounds its estimates to 2–3 significant figures; a rebuilt revision can differ from the proposal by that, and a
second Propose closes the gap.) The result is a new design revision
(``build/<name>/revisions/rev<k>.json``); the source design is never touched unless :func:`accept` is called.

**Loop (L2).** :func:`run` repeats evaluate → update surrogates → propose until every target is within tolerance or
``max_iter``; ``evaluate(design) -> FilledCircuit`` is the FEM step (Q3D/Palace job → :func:`circuit.fill.fill`),
or any stand-in for testing.
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from quantcore_circuits.circuit.fill import FilledCircuit, TransmonReadout


@dataclass
class ElementModel:
    element: str
    knob: str | None  # primary knob (None: the element has no geometry knob and keeps its anchor value)
    k0: float
    v0: float
    p: float = 1.0
    prior_p: float = 1.0
    samples: list[tuple[float, float]] = field(default_factory=list)
    # secondary knobs (additive): knob → [k0, exponent], e.g. a floating qubit's island C on its coupler pad's width
    others: dict[str, list[float]] = field(default_factory=dict)

    def predict(self, k: float) -> float:
        return self.v0 * (k / self.k0) ** self.p

    def value(self, knobs: dict[str, float]) -> float:
        """The element at ``knobs`` (primary and secondary knobs; a knob missing from ``knobs`` stays at its k0)."""
        v = self.predict(knobs[self.knob]) if self.knob is not None and self.knob in knobs else self.v0
        for k, (k0, p) in self.others.items():
            if k in knobs:
                v *= (knobs[k] / k0) ** p
        return v

    def invert(self, v: float) -> float:
        return self.k0 * (v / self.v0) ** (1 / self.p)

    def add(self, k: float | None, v: float, knobs: dict[str, float] | None = None) -> None:
        """New FEM point: re-anchor, and refit the exponent when the knob has moved (the sign of the prior is kept:
        a gap knob lowers its capacitance). ``knobs``: the point's other knob values (re-anchors ``others``)."""
        for name, entry in self.others.items():
            if knobs and name in knobs:
                entry[0] = float(knobs[name])
        if self.knob is None or k is None:
            self.v0 = float(v)
            return
        self.samples.append((float(k), float(v)))
        self.k0, self.v0 = float(k), float(v)
        ks = np.array([s[0] for s in self.samples])
        vs = np.array([s[1] for s in self.samples])
        if len(set(np.round(ks, 9))) >= 2 and (vs > 0).all():
            slope = np.polyfit(np.log(ks), np.log(vs), 1)[0]
            self.p = float(np.clip(slope, 0.1, 3.0) if self.prior_p >= 0 else np.clip(slope, -3.0, -0.1))


@dataclass
class PairSurrogate:
    """Surrogate for one transmon + λ/4 or λ/2 readout pair (module docstring)."""

    qubit: str
    resonator: str
    c_island: ElementModel
    cg: ElementModel
    c_coupler: ElementModel
    lj_nH: float
    cj_fF: float
    length_um: float  # the resonator knob's value (the line is length_um + extra_length_um long)
    a_um: float
    b_um: float
    pdk: str
    # additive fields; the defaults keep the λ/4 + <Q>.junction.Lj_nH + <R>.length surrogate of the synthesis
    kind: str = "lambda/4"
    extra_length_um: float = 0.0
    lj_knob: str | None = ""  # "": <qubit>.junction.Lj_nH; None: L_J is not a knob
    length_knob: str | None = ""  # "": <resonator>.length; None: the resonator length is not a knob
    lj_scale: float = 1.0  # model L_J / knob value (a list of junction values: the first over their mean)
    cell: str = ""
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.lj_knob == "":
            self.lj_knob = f"{self.qubit}.junction.Lj_nH"
        if self.length_knob == "":
            self.length_knob = f"{self.resonator}.length"

    @property
    def knobs(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for m in (self.c_island, self.cg):
            if m.knob is not None:
                out.setdefault(m.knob, m.k0)
        if self.lj_knob:
            out[self.lj_knob] = self.lj_nH / self.lj_scale
        if self.length_knob:
            out[self.length_knob] = self.length_um
        return out

    def elements(self, knobs: dict[str, float]) -> dict[str, float]:
        lj = knobs[self.lj_knob] * self.lj_scale if self.lj_knob and self.lj_knob in knobs else self.lj_nH
        length = knobs[self.length_knob] if self.length_knob and self.length_knob in knobs else self.length_um
        return {
            "C_island_fF": self.c_island.value(knobs),
            "Cg_fF": self.cg.value(knobs),
            "C_coupler_fF": self.c_coupler.value(knobs),
            "Lj_nH": lj,
            "length_um": length + self.extra_length_um,
        }

    def predict(self, knobs: dict[str, float]) -> dict[str, float]:
        return forward(
            self.elements(knobs), self.cj_fF, self.a_um, self.b_um, self.pdk, self.qubit, self.resonator, self.kind
        )

    def to_json(self) -> dict:
        return asdict(self)

    def _with_lom(self, lom, paths: dict) -> PairSurrogate:
        """Attach the LOM re-evaluation (:class:`_PairLom`, not part of :meth:`to_json`) that :func:`propose` uses to
        check and refine a proposal; ``paths``: geometry knob → (instance, parameter path)."""
        self._lom = lom  # pylint: disable=attribute-defined-outside-init
        self._paths = paths  # pylint: disable=attribute-defined-outside-init
        return self


def forward(
    el: dict,
    cj_fF: float,
    a_um: float,
    b_um: float,
    pdk: str,
    qubit: str = "Q",
    resonator: str = "R",
    kind: str = "lambda/4",
) -> dict:
    """Element values → dressed parameters, keyed like the targets. ``el["length_um"]`` is the whole line; ``kind``
    its mode (``"lambda/2"``: twice the λ/4 frequency of the same line, the λ/2 equivalent LC)."""
    from quantcore_circuits.circuit.bridges import tl_resonator  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.fill import _tl_kind, two_node_model  # pylint: disable=import-outside-toplevel

    cg = el["Cg_fF"]
    maxwell = np.array([[el["C_island_fF"] + cg, -cg], [-cg, el["C_coupler_fF"] + cg]])
    tl = tl_resonator(el["length_um"], a_um, b_um, pdk)
    if kind != "lambda/4":
        tl = _tl_kind(tl, kind)
    pair = TransmonReadout(
        qubit, resonator, ["i", "c"], maxwell, el["Lj_nH"], cj_fF, tl["f_GHz"], tl["Z0_ohm"], kind=kind
    )
    tn = two_node_model(pair)
    d = dressed_levels(tn["EJ_GHz"], tn["EC_GHz"], tn["f_r_loaded_GHz"], tn["g_n_MHz"], nq=5, nr=5)
    return {
        f"{qubit}.f_q_GHz": d["f_q_GHz"],
        f"{qubit}.alpha_MHz": d["alpha_MHz"],
        f"{resonator}.f_GHz": d["f_r_GHz"],
        f"{resonator}.g_MHz": d["g_MHz"],
        f"{resonator}.chi_MHz": d["chi_MHz"],
    }


def dressed_levels(ej_GHz: float, ec_GHz: float, f_r_GHz: float, g_n_MHz: float, nq: int = 5, nr: int = 5,
                   ncut: int = 20) -> dict:
    """:func:`quantcore_circuits.circuit.hamiltonian.dressed` of the same model (charge-basis transmon truncated to
    ``nq`` levels + resonator + g_n n̂(a + a†), no RWA), built and diagonalised with numpy instead of QuTiP objects
    (the surrogate's forward model runs it hundreds of times; same matrices, same bare-state labelling)."""
    n = np.arange(-ncut, ncut + 1)
    ht = np.diag(4 * ec_GHz * n.astype(float) ** 2) - ej_GHz / 2 * (np.eye(len(n), k=1) + np.eye(len(n), k=-1))
    e, v = np.linalg.eigh(ht)
    v = v[:, :nq]
    eq = e[:nq] - e[0]
    nmat = v.T @ np.diag(n.astype(float)) @ v
    a = np.diag(np.sqrt(np.arange(1, nr, dtype=float)), 1)
    h = np.kron(np.diag(eq), np.eye(nr)) + f_r_GHz * np.kron(np.eye(nq), a.T @ a)
    h = h + g_n_MHz / 1e3 * np.kron(nmat, a + a.T)
    evals, evecs = np.linalg.eigh(h)
    evals = evals - evals[0]
    idx = np.argmax(np.abs(evecs) ** 2, axis=0)
    labels = [(int(k) // nr, int(k) % nr) for k in idx]

    def lev(qn, rn):
        return float(evals[labels.index((qn, rn))])

    return {
        "f_q_GHz": lev(1, 0),
        "f_r_GHz": lev(0, 1),
        "alpha_MHz": (lev(2, 0) - 2 * lev(1, 0)) * 1e3,
        "chi_MHz": (lev(1, 1) - lev(1, 0) - lev(0, 1)) * 1e3,
        "g_MHz": g_n_MHz * abs(nmat[0, 1]),
    }


PRIORS = {"C_island": 1.0, "Cg": 1.0, "C_coupler": 0.8}

# ---- knobs per qubit class (module docstring) ------------------------------------------------------------------------
_CORNERS = {"pin1": "NE", "pin2": "NW", "pin3": "SW"}
_INTERDIGITATED = {"readout": "cc", "bus1": "cc_topleft", "bus2": "cc_topright"}


def _index(node: str, base: int) -> str | None:
    m = re.search(r"(\d+)$", node or "")
    return str(int(m.group(1)) - base) if m else None


def _pads(option: str):
    return lambda node: f"connection_pads.{node}.{option}" if node else None


# class → (island knob, coupler knob as a function of the readout coupler's local node); paths are under the instance
QUBIT_KNOBS: dict[str, tuple] = {
    "Xmon": ("cross_length", lambda node: "claw_length"),
    "Swissmon": ("arm_length.*", lambda node: f"cpl_length.{_index(node, 0)}" if _index(node, 0) else None),
    "CircularTransmonSingleIsland": (
        "r_island", lambda node: f"couplers_arc_amplitude.{_index(node, 1)}" if _index(node, 1) else None),
    "ConcentricTransmon": (
        "r_inner", lambda node: f"couplers_arc_amplitude.{_index(node, 1)}" if _index(node, 1) else None),
    "DoublePads": ("island_island_gap", lambda node: "coupler_extent.0"),
    "DoublePadsSplines": ("island_island_gap", lambda node: "coupler_extent.0"),
    "TwoPadTransmon": ("pad_height", lambda node: None),
    "Flipmon": ("top_circle_radius", lambda node: "coupler_length"),
    "Gatemon": ("island_size.*", lambda node: None),
    "TransmonTaperedInsets": ("pad_width", _pads("pad_width")),
    "metal:TransmonPocket": ("pad_width", _pads("pad_width")),
    "metal:TransmonPocketCL": ("pad_width", _pads("pad_width")),
    "metal:TransmonPocket6": ("pad_width", _pads("pad_width")),
    "metal:TransmonPocketTeeth": ("pad_width", _pads("pad_width")),
    "metal:TransmonCross": ("cross_length", _pads("claw_length")),
    "metal:TransmonCrossFL": ("cross_length", _pads("claw_length")),
    "metal:TransmonStar": ("arm_length", _pads("claw_length")),
    "metal:TransmonConcentric": ("gap", lambda node: "res_s" if node == "pin1" else None),
    "metal:TransmonConcentricType2": (
        "gap", lambda node: f"finger_{_CORNERS[node]}_length" if node in _CORNERS else None),
    "metal:TransmonInterdigitated": (
        "finger_height", lambda node: f"{_INTERDIGITATED[node]}_width" if node in _INTERDIGITATED else None),
    "metal:StarQubit": (
        "center_radius", lambda node: "gap_readout" if node == "pin_rdout" else ("gap_couplers" if node else None)),
}
# cells that put C_g between a qubit and its readout line (the qubit's own rule has no coupler knob)
COUPLER_KNOBS: dict[str, str] = {"PadCoupler": "pad_height", "GatemonCoupler": "coupling_capacitance"}
SENSITIVITY_STEP = 0.02  # relative knob step of the LOM sensitivities (central difference)
MIN_EXPONENT = 0.02  # |d ln C / d ln k| below this on every element: the knob does nothing in the LOM


def _cell_classes(cell: str) -> list[str]:
    """Rule keys of a cell, most specific first: ``metal:<Class>`` (and its Metal bases), else the class and its MRO."""
    if cell.startswith("metal:"):
        from quantcore_circuits.layouts.metal import canonical_class_name  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom.metal_models import metal_mro  # pylint: disable=import-outside-toplevel

        try:
            name = canonical_class_name(cell.split(":", 1)[1])
        except (ImportError, ValueError):
            name = cell.split(":", 1)[1]
        return [f"metal:{c}" for c in metal_mro(name)]
    try:
        from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

        return [k.__name__ for k in resolve_cell(cell).__mro__]
    except Exception:  # noqa: BLE001  (an unknown cell: no rule)
        return [cell]


def _rule(table: dict, cell: str):
    return next((table[c] for c in _cell_classes(cell) if c in table), None)


def _num_knob(design, knob: str) -> float | None:
    """The knob's value as a positive float, or None (missing, not a number, zero)."""
    from quantcore_circuits.optimise import get_knob, knob_number  # pylint: disable=import-outside-toplevel

    try:
        v = knob_number(get_knob(design, knob))
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    return v if np.isfinite(v) and v > 0 else None


class _PairLom:
    """The LOM side of one pair: re-evaluates the components that own its knobs and reduces the circuit to the pair's
    (C_island, Cg, C_coupler), with every branch scaled from its anchor value by estimate(k) / estimate(k0)."""

    def __init__(self, filled: FilledCircuit, pair, junction: str, cache: dict | None = None):
        from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

        model, values = filled.model, filled.values
        self.design, self.pdk = filled.design, get_pdk(filled.design.pdk)
        gnd = model.ground
        self.nodes = tuple(n for n in model.branches[junction].nodes if n != gnd)
        self.cnode = model.branches[pair.resonator].nodes[0]
        touch = set(self.nodes) | {self.cnode}
        self.branches = {
            b: tuple(x.nodes) for b, x in model.branches.items() if x.type == "C" and touch & set(x.nodes)
        }
        self.anchor = {b: float(values[b].value or 0.0) for b in self.branches}
        cache = {} if cache is None else cache  # shared by the pairs of one circuit: each fragment is built once
        self._est0: dict[str, dict] = cache.setdefault("est0", {})
        self._frag0: dict[str, object] = cache.setdefault("frag0", {})

    def coupling(self) -> list[str]:
        """C branches between the qubit's island(s) and the coupler node, largest first."""
        out = [b for b, n in self.branches.items() if self.cnode in n and set(n) & set(self.nodes)]
        return sorted(out, key=lambda b: -self.anchor[b])

    def reduce(self, vals: dict[str, float]) -> tuple[float, float, float]:
        from types import SimpleNamespace as NS  # pylint: disable=import-outside-toplevel

        from quantcore_circuits.circuit.fill import _c_between, _c_total, _floating_maxwell  # pylint: disable=C0415

        model = NS(branches={b: NS(type="C", nodes=n) for b, n in self.branches.items()})
        values = {b: NS(value=v) for b, v in vals.items()}
        if len(self.nodes) == 2:
            m, _ = _floating_maxwell(model, values, self.nodes[0], self.nodes[1], self.cnode)
        else:
            q = self.nodes[0]
            cg = _c_between(model, values, q, self.cnode)
            m = np.array([[_c_total(model, values, q), -cg], [-cg, _c_total(model, values, self.cnode)]])
        return float(m[0].sum()), float(-m[0, 1]), float(m[1].sum())

    def estimates(self, inst: str, sets: dict[str, float] | None = None) -> dict[str, float]:
        """C estimates of ``inst``'s LOM fragment with its parameters ``sets`` (path under the instance → value)."""
        if not sets and inst in self._est0:
            return self._est0[inst]
        from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom.estimates import exact_values  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.optimise import set_knob  # pylint: disable=import-outside-toplevel

        spec = self.design.instances[inst].model_dump(mode="json", by_alias=True)
        spec["place"] = {"at": [0.0, 0.0]}  # the LOM does not depend on the placement (a snap needs its partner)
        mini = load_design({"schema": "qcc/0.1", "name": "lom", "pdk": self.design.pdk, "instances": {inst: spec}})
        for path, v in (sets or {}).items():
            mini = set_knob(mini, f"{inst}.{path}", v)
        with exact_values():  # unrounded estimates: a ±2 % step must show
            frag = lom_model(mini.instances[inst].cell)(inst, mini.instances[inst], self.pdk)
        out = {e.name: float(e.value["estimate"]) for e in frag.elements
               if e.type == "C" and isinstance(e.value.get("estimate"), (int, float)) and e.value["estimate"] > 0}
        if not sets:
            self._est0[inst] = out
            self._frag0[inst] = frag
        return out

    def port_net(self, port: str) -> str | None:
        """The FEM net label of the conductor a component port ``INST.port`` lands on (its LOM fragment's port node)."""
        inst, _, name = port.partition(".")
        if inst not in self.design.instances:
            return None
        try:
            self.estimates(inst)
        except Exception:  # noqa: BLE001  (a cell without a model)
            return None
        frag = self._frag0.get(inst)
        local = frag.port_nodes.get(name) if frag else None
        if not local or local == "gnd" or local.startswith("control:"):
            return None
        return (frag.nodes.get(local) or {}).get("island")

    def at(self, knobs: dict[str, float], paths: dict[str, tuple[str, str]]) -> tuple[float, float, float]:
        """(C_island, Cg, C_coupler) with ``knobs`` (knob → value; ``paths``: knob → (instance, path))."""
        by_inst: dict[str, dict[str, float]] = {}
        for k, v in knobs.items():
            if k in paths:
                inst, path = paths[k]
                by_inst.setdefault(inst, {})[path] = v
        vals = dict(self.anchor)
        for inst, sets in by_inst.items():
            est0, est = self.estimates(inst), self.estimates(inst, sets)
            for b in vals:
                if b in est and est0.get(b):
                    vals[b] = self.anchor[b] * est[b] / est0[b]
        return self.reduce(vals)


def _owner(branch: str, design) -> str | None:
    for inst in sorted(design.instances, key=len, reverse=True):
        if re.match(rf"^[A-Za-z]+_{re.escape(inst)}(_.*)?$", branch):
            return inst
    return None


def _junction_of(model, pair) -> str | None:
    if f"J_{pair.qubit}" in model.branches:
        return f"J_{pair.qubit}"
    return next((n for n, b in model.branches.items() if b.type in ("JJ", "SQUID") and pair.qubit in b.nodes), None)


def surrogate_from_fill(filled: FilledCircuit, pair_index: int = 0, cache: dict | None = None) -> PairSurrogate:
    """Anchor a surrogate at the point of ``filled`` (FEM or the layout's estimates; knob values read from its design).

    A real circuit (``filled.model``) gets the generic surrogate of the module docstring; a bare ``FilledCircuit``
    without a model (a test stand-in for the FEM step) the Xmon one: cross / claw with the prior exponents.
    ``cache``: shared between the pairs of one circuit (each component's LOM fragment is built once)."""
    if getattr(filled, "model", None) is None:
        return _xmon_surrogate(filled, pair_index)
    return _generic_surrogate(filled, pair_index, cache)


def _xmon_surrogate(filled: FilledCircuit, pair_index: int) -> PairSurrogate:
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.optimise import get_knob  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    p = filled.pairs[pair_index]
    design = filled.design
    q, r = p.qubit, p.resonator
    cross, claw = float(get_knob(design, f"{q}.cross_length")), float(get_knob(design, f"{q}.claw_length"))
    rp = plan_design(design).routes[r]
    pdk = get_pdk(design.pdk)
    models = {}
    for name, knob, k, v in (
        ("C_island", f"{q}.cross_length", cross, p.c_island_fF - p.cj_fF),
        ("Cg", f"{q}.claw_length", claw, p.cg_fF),
        ("C_coupler", f"{q}.claw_length", claw, p.c_coupler_fF),
    ):
        m = ElementModel(name, knob, k, v, PRIORS[name], PRIORS[name])
        m.add(k, v)
        models[name] = m
    return PairSurrogate(
        q,
        r,
        models["C_island"],
        models["Cg"],
        models["C_coupler"],
        p.lj_nH,
        p.cj_fF,
        float(rp.length),
        rp.params.get("a", pdk.cpw_a),
        rp.params.get("b", pdk.cpw_b),
        design.pdk,
        cell="Xmon",
    )


def _generic_surrogate(filled: FilledCircuit, pair_index: int, cache: dict | None = None) -> PairSurrogate:
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    p = filled.pairs[pair_index]
    design, model, values = filled.design, filled.model, filled.values
    pdk = get_pdk(design.pdk)
    q, r = p.qubit, p.resonator
    notes: list[str] = []
    jname = _junction_of(model, p)
    qinst = jname[2:] if jname and jname.startswith("J_") and jname[2:] in design.instances else q.split(".", 1)[0]
    if qinst not in design.instances or jname is None:
        raise ValueError(f"{q}: no qubit instance or junction for the pair {q}/{r}")
    cell = design.instances[qinst].cell
    lom = _PairLom(filled, p, jname, cache)

    # the knobs: island on the qubit; C_g on the owner of the qubit ↔ coupler capacitance
    paths: dict[str, tuple[str, str]] = {}
    island_knob = coupler_knob = None
    rule = _rule(QUBIT_KNOBS, cell)
    if rule is None:
        notes.append(f"{qinst} ({cell}): no knob rule for this class; its LOM's knob annotations are used if numeric")
    island_path = rule[0] if rule else _annotated(model, lom, qinst, island=True)
    if island_path and _num_knob(design, f"{qinst}.{island_path}") is not None:
        island_knob = f"{qinst}.{island_path}"
        paths[island_knob] = (qinst, island_path)
    else:
        notes.append(f"{qinst} ({cell}): no island-capacitance knob ({island_path or 'none'} is not a number in the "
                     "design or the cell defaults); C_Σ is kept")
    cpl = lom.coupling()
    if not cpl:
        raise ValueError(f"{q}/{r}: no capacitance between the qubit and its readout coupler")
    owner = _owner(cpl[0], design)
    node = cpl[0][len(f"Cg_{owner}_"):] if owner and cpl[0].startswith(f"Cg_{owner}_") else None
    if owner is None:
        coupler_path = None
        notes.append(f"{qinst}: its C_g is the declared coupling {cpl[0]!r} (a value, not a geometry knob); kept")
    elif owner == qinst:
        coupler_path = rule[1](node) if rule else _annotated(model, lom, qinst, branch=cpl[0])
    else:
        coupler_path = _rule(COUPLER_KNOBS, design.instances[owner].cell)
        if coupler_path is None:
            coupler_path = _annotated(model, lom, owner, branch=cpl[0])
    if coupler_path and owner and _num_knob(design, f"{owner}.{coupler_path}") is not None:
        coupler_knob = f"{owner}.{coupler_path}"
        paths[coupler_knob] = (owner, coupler_path)
    elif owner is not None:
        notes.append(f"{qinst}: no C_g knob on {owner} ({design.instances[owner].cell}"
                     + (f", {coupler_path} is not a number" if coupler_path else "") + "); C_g is kept")

    # local exponents of (C_island, Cg, C_coupler) in each knob, from the LOM
    base = lom.reduce(lom.anchor)
    expo: dict[str, tuple[float, float, float]] = {}
    for k in list(paths):
        k0 = _num_knob(design, k)
        hi_, lo_ = lom.at({k: k0 * (1 + SENSITIVITY_STEP)}, paths), lom.at({k: k0 * (1 - SENSITIVITY_STEP)}, paths)
        den = math.log((1 + SENSITIVITY_STEP) / (1 - SENSITIVITY_STEP))
        e = tuple(round(math.log(a / b) / den, 6) if a > 0 and b > 0 else 0.0 for a, b in zip(hi_, lo_))
        if max(abs(x) for x in e) < MIN_EXPONENT:
            notes.append(f"{k}: no effect on the qubit's capacitances in the LOM; not used as a knob")
            del paths[k]
            island_knob = None if k == island_knob else island_knob
            coupler_knob = None if k == coupler_knob else coupler_knob
            continue
        expo[k] = e

    def element(name: str, i: int, v0: float, primary: str | None) -> ElementModel:
        prim = primary if primary in expo else None
        p_prim = expo[prim][i] if prim else 1.0
        m = ElementModel(name, prim, _num_knob(design, prim) if prim else 1.0, v0, p_prim, p_prim)
        m.add(m.k0 if prim else None, v0)
        for k, e in expo.items():
            if k != prim and abs(e[i]) >= 1e-6:
                m.others[k] = [_num_knob(design, k), e[i]]
        return m

    c_isl = element("C_island", 0, p.c_island_fF - p.cj_fF, island_knob)
    c_g = element("Cg", 1, p.cg_fF, coupler_knob)
    c_c = element("C_coupler", 2, p.c_coupler_fF, coupler_knob)
    if abs(base[0] - c_isl.v0) > 1e-6 * max(1.0, abs(c_isl.v0)) or abs(base[1] - c_g.v0) > 1e-6 * max(1.0, c_g.v0):
        notes.append(f"{q}/{r}: the pair's capacitances differ from the reduced LOM ({base}); sensitivities are "
                     "approximate")

    # L_J
    inst = design.instances[qinst]
    lj_raw = inst.junction.Lj_nH if inst.junction else None
    lj_knob, lj_scale = None, 1.0
    if isinstance(lj_raw, list) and lj_raw:
        lj_knob = f"{qinst}.junction.Lj_nH.*"
        lj_scale = float(lj_raw[0]) / float(np.mean(lj_raw))
    elif lj_raw is not None:
        lj_knob = f"{qinst}.junction.Lj_nH"
    else:
        notes.append(f"{qinst}: L_J comes from the drawn junction (no junction.Lj_nH in the design): not tuned; set "
                     "junction.Lj_nH to make it a knob")
    lj_scale *= p.ej_sum_ratio  # a flux-biased SQUID: the model's L(Φ) over the knob's zero-flux L_J0

    # the resonator line
    tlv = values[r]
    total = float(tlv.estimate or model.branches[r].value.get("length_um") or 0.0)
    kind = tlv.extra.get("kind", p.kind)
    length_knob, k_len = _length_knob(design, model, lom, r, total)
    if length_knob is None:
        notes.append(f"{r}: no length knob (a line without a numeric length parameter, e.g. a cpw route drawn by its "
                     "waypoints); f_r is kept")
        k_len = total
    bv = model.branches[r].value
    return PairSurrogate(
        q, r, c_isl, c_g, c_c, p.lj_nH, p.cj_fF, k_len,
        float(bv.get("a_um", pdk.cpw_a)), float(bv.get("b_um", pdk.cpw_b)), design.pdk,
        kind=kind, extra_length_um=max(total - k_len, 0.0) if length_knob else 0.0,
        lj_knob=lj_knob, length_knob=length_knob, lj_scale=lj_scale, cell=cell, notes=notes,
    )._with_lom(lom, paths)


def _annotated(model, lom: _PairLom, inst: str, island: bool = False, branch: str | None = None) -> str | None:
    """A knob path from the LOM's own element annotation (``knob: {"param": "<inst>.<path>"}``): of ``branch``, or of
    the qubit's island capacitance (the largest C on its island nodes)."""
    if branch is None and island:
        own = [b for b, n in lom.branches.items() if set(n) & set(lom.nodes) and lom.cnode not in n]
        branch = max(own, key=lambda b: lom.anchor[b], default=None)
    knob = (model.branches[branch].knob or {}).get("param") if branch in model.branches else None
    return knob.split(".", 1)[1] if knob and knob.startswith(f"{inst}.") else None


def _length_knob(design, model, lom: _PairLom, r: str, total: float) -> tuple[str | None, float]:
    """(the resonator's length knob, its value): its TLres knob when that is a length (``<R>.length``, a line cell's
    ``resonator_length``), else the one meander route with a length that ends on the resonator's conductor (a
    coupler cell's line continued by a route: the route's length is the knob, the cell's line a constant)."""
    knob = (model.branches[r].knob or {}).get("param")
    cands = [knob] if knob and re.search(r"len", knob.rsplit(".", 1)[-1]) else []
    nets = set(model.nodes[lom.cnode].nets) if lom.cnode in model.nodes else set()
    routes = [n for n, route in design.routes.items() if route.length and route.type == "meander"
              and any(isinstance(e, str) and lom.port_net(e) in nets for e in (route.from_, route.to))]
    if len(routes) == 1 and f"{routes[0]}.length" not in cands:
        cands.append(f"{routes[0]}.length")
    for k in cands:
        v = _num_knob(design, k)
        if v is not None and v <= total + max(1.0, 1e-3 * total):  # a meander is planned to within a few nm
            return k, v
    return None, total


def update_surrogate(s: PairSurrogate, filled: FilledCircuit, knobs: dict[str, float], pair_index: int = 0) -> None:
    p = filled.pairs[pair_index]
    s.c_island.add(knobs.get(s.c_island.knob) if s.c_island.knob else None, p.c_island_fF - p.cj_fF, knobs)
    s.cg.add(knobs.get(s.cg.knob) if s.cg.knob else None, p.cg_fF, knobs)
    s.c_coupler.add(knobs.get(s.c_coupler.knob) if s.c_coupler.knob else None, p.c_coupler_fF, knobs)
    if s.lj_knob and s.lj_knob in knobs:
        s.lj_nH = knobs[s.lj_knob] * s.lj_scale
    if s.length_knob and s.length_knob in knobs:
        s.length_um = knobs[s.length_knob]


@dataclass
class Proposal:
    knobs: dict[str, float]
    predicted: dict[str, float]
    residuals: dict[str, float]  # (predicted − target)/tol
    elements: dict[str, float]
    start_knobs: dict[str, float]
    objective: float
    at_bounds: list[str] = field(default_factory=list)  # knobs pinned at a bound (the optimum may lie outside)
    notes: list[str] = field(default_factory=list)  # what could not be tuned and why (additive)


REFINE_TOL = 1e-3  # relative LOM ↔ surrogate mismatch at the proposal above which the exponents are corrected


def propose(
    s: PairSurrogate,
    targets: dict,
    bounds: dict[str, tuple[float, float]] | None = None,
    anchor: dict[str, float] | None = None,
    refine: int = 3,
) -> Proposal:
    """Bounded least squares on the surrogate: knobs that put every target inside its tolerance.

    ``anchor``: values measured at the current knobs (e.g. the consensus' chosen estimator). The surrogate's
    predictions are scaled by measured / predicted at the start, so it corrects the measured gap even when its own
    model (the dressed spectrum) and the chosen estimator differ (a surrogate bias correction).

    ``refine``: a surrogate that can re-evaluate its LOM (:func:`surrogate_from_fill`) checks the solution there; when
    an element differs by more than ``REFINE_TOL`` its exponents are corrected along the move (a secant through the
    anchor and the proposal, so the anchor stays exact) and the problem is solved again, at most ``refine`` times. If
    it still differs (two knobs that interact strongly, e.g. a floating qubit's pads and its connection pad), the last
    solve uses the LOM itself (ratio-scaled to the anchor) as the forward model, from the surrogate's solution.

    Only the knobs this pair's targets ask for move (:func:`_free_knobs`); the others keep their value.
    """
    from scipy.optimize import least_squares  # pylint: disable=import-outside-toplevel

    keys = [
        k
        for k in (f"{s.qubit}.f_q_GHz", f"{s.qubit}.alpha_MHz", f"{s.resonator}.f_GHz", f"{s.resonator}.g_MHz")
        if k in targets
    ]
    tv = {k: (targets[k].value if hasattr(targets[k], "value") else targets[k]["value"]) for k in keys}
    tt = {k: (targets[k].tol if hasattr(targets[k], "tol") else targets[k]["tol"]) for k in keys}
    names = _free_knobs(s, keys)
    x0 = np.array([s.knobs[n] for n in names], dtype=float)
    bounds = bounds or {}
    lo = np.array([bounds.get(n, (v * 0.4, v * 2.0))[0] for n, v in zip(names, x0)])
    hi = np.array([bounds.get(n, (v * 0.4, v * 2.0))[1] for n, v in zip(names, x0)])
    pred0 = s.predict(dict(zip(names, x0)))
    x0 = np.clip(x0, lo, hi)
    scale = x0.copy()
    bias = {k: anchor[k] / pred0[k] for k in keys if anchor and anchor.get(k) is not None and pred0.get(k)}
    notes = list(getattr(s, "notes", []) or [])

    fixed = {n: v for n, v in s.knobs.items() if n not in names}  # knobs no target of this pair asks for

    def corrected(knobs):
        pred = s.predict({**fixed, **knobs})
        return {k: v * bias.get(k, 1.0) for k, v in pred.items()}

    def residual(xs):
        pred = corrected(dict(zip(names, xs * scale)))
        return np.array([(pred[k] - tv[k]) / tt[k] for k in keys])

    if not names or not keys:
        knobs = {**fixed, **dict(zip(names, (float(round(v, 3)) for v in x0)))}
        pred = corrected(knobs)
        res = {k: (pred[k] - tv[k]) / tt[k] for k in keys}
        if not s.knobs:
            notes.append(f"{s.qubit}/{s.resonator}: nothing to tune (no knob)")
        return Proposal(knobs, pred, res, s.elements(knobs), dict(s.knobs),
                        float(math.sqrt(sum(r * r for r in res.values()))), [], notes)
    start = x0 / scale
    mismatch = False
    for _ in range(refine + 1):
        sol = least_squares(residual, start, bounds=(lo / scale, hi / scale), x_scale=1.0, diff_step=1e-3)
        knobs = {n: float(round(v, 3)) for n, v in zip(names, sol.x * scale)}
        mismatch = refine > 0 and _refine(s, {**fixed, **knobs})
        if not mismatch:
            break
        start = np.clip(sol.x, lo / scale, hi / scale)
    elements = None
    if mismatch:  # the power laws do not settle (knobs that interact strongly): solve on the LOM itself from here
        lom, paths = s._lom, s._paths  # pylint: disable=protected-access

        def lom_elements(knobs):
            el = s.elements({**fixed, **knobs})
            ci, cg, cc = lom.at({k: v for k, v in {**fixed, **knobs}.items() if k in paths}, paths)
            return {**el, "C_island_fF": ci, "Cg_fF": cg, "C_coupler_fF": cc}

        def corrected(knobs):  # noqa: F811  (the LOM forward replaces the surrogate's)
            pred = forward(lom_elements(knobs), s.cj_fF, s.a_um, s.b_um, s.pdk, s.qubit, s.resonator, s.kind)
            return {k: v * bias.get(k, 1.0) for k, v in pred.items()}

        sol = least_squares(residual, np.clip(sol.x, lo / scale, hi / scale), bounds=(lo / scale, hi / scale),
                            x_scale=1.0, diff_step=1e-3)
        knobs = {n: float(round(v, 3)) for n, v in zip(names, sol.x * scale)}
        elements = lom_elements(knobs)
    # in the surrogate's knob order; an untouched knob keeps its exact value (no change is reported for it)
    knobs = {n: knobs[n] if n in knobs else fixed[n] for n in s.knobs}
    pred = corrected(knobs)
    res = {k: (pred[k] - tv[k]) / tt[k] for k in keys}
    pinned = [n for n, x, a, b in zip(names, sol.x * scale, lo, hi) if min(abs(x - a), abs(x - b)) <= 1e-6 * abs(x)]
    return Proposal(
        knobs, pred, res, elements or s.elements(knobs), dict(s.knobs),
        float(math.sqrt(sum(r * r for r in res.values()))), pinned, notes,
    )


TARGET_OF = {"C_island": "alpha_MHz", "Cg": "g_MHz", "C_coupler": "g_MHz"}


def _free_knobs(s: PairSurrogate, keys: list[str]) -> list[str]:
    """The knobs this pair's targets ask for — L_J for f_q, the island knob for α, the coupler knob for g, the length
    for f_r — in the surrogate's order. A knob with no target of its own stays where it is (with fewer targets than
    knobs the least squares would otherwise drift knobs nobody asked to change)."""
    want = {k.rsplit(".", 1)[1] for k in keys}
    roles: dict[str, set[str]] = {}
    for m in (s.c_island, s.cg, s.c_coupler):
        if m.knob is not None and m.element in TARGET_OF:
            roles.setdefault(m.knob, set()).add(TARGET_OF[m.element])
    if s.lj_knob:
        roles.setdefault(s.lj_knob, set()).add("f_q_GHz")
    if s.length_knob:
        roles.setdefault(s.length_knob, set()).add("f_GHz")
    return [n for n in s.knobs if n not in roles or roles[n] & want]


def _refine(s: PairSurrogate, knobs: dict[str, float]) -> bool:
    """Compare the surrogate's capacitances at ``knobs`` with the LOM's; on a mismatch correct the exponents (Broyden
    secant in log space, the anchor fixed) and return True."""
    lom, paths = getattr(s, "_lom", None), getattr(s, "_paths", None)
    if lom is None or not paths:
        return False
    geo = {k: v for k, v in knobs.items() if k in paths}
    true = lom.at(geo, paths)
    changed = False
    for m, t in zip((s.c_island, s.cg, s.c_coupler), true):
        pred = m.value(knobs)
        if t <= 0 or pred <= 0 or abs(t / pred - 1) <= REFINE_TOL:
            continue
        steps = {}
        if m.knob is not None and m.knob in geo:
            steps[m.knob] = math.log(geo[m.knob] / m.k0)
        for k, (k0, _) in m.others.items():
            if k in geo:
                steps[k] = math.log(geo[k] / k0)
        norm = sum(x * x for x in steps.values())
        if norm < 1e-12:
            continue
        delta = math.log(t / pred)
        for k, x in steps.items():
            if k == m.knob:
                m.p += delta * x / norm
            else:
                m.others[k][1] += delta * x / norm
        changed = True
    return changed


def surrogates_from_fill(filled: FilledCircuit, notes: list[str] | None = None) -> list[PairSurrogate]:
    """One surrogate per qubit (its first, readout, pair) — multi-qubit chips. A pair whose surrogate cannot be built
    is left out with a line in ``notes`` (when given; else the error is raised)."""
    out, seen, cache = [], set(), {}
    for i, p in enumerate(filled.pairs):
        if p.qubit not in seen:
            seen.add(p.qubit)
            try:
                out.append(surrogate_from_fill(filled, i, cache))
            except Exception as e:  # noqa: BLE001
                if notes is None:
                    raise
                notes.append(f"{p.qubit}/{p.resonator}: not tuned ({type(e).__name__}: {e})")
    return out


def unpaired_notes(filled: FilledCircuit) -> list[str]:
    """A line for every qubit (junction) of the circuit that has no readout pair (nothing reads it out, or only a bus
    that several qubits share): Propose cannot tune it."""
    model = getattr(filled, "model", None)
    if model is None:
        return []
    paired = {p.qubit for p in filled.pairs}
    out = []
    for name, b in model.branches.items():
        if b.type not in ("JJ", "SQUID"):
            continue
        q = name[2:] if name.startswith("J_") else name
        if q in paired or any(n in paired for n in b.nodes):
            continue
        out.append(f"{q}: no readout resonator pair (a λ/4 or λ/2 line on a coupler of this qubit alone); not tuned")
    return out


def propose_all(
    surrogates: list[PairSurrogate],
    targets: dict,
    bounds: dict[str, tuple[float, float]] | None = None,
    anchor: dict[str, float] | None = None,
) -> Proposal:
    """:func:`propose` for every pair, merged into one proposal.

    The pairs share no knobs and the surrogate has no qubit–qubit terms, so each pair is solved on its own;
    the merged objective is the norm over all targets. Cross-couplings (buses, ZZ) need a joint model.
    """
    props = [propose(s, targets, bounds, anchor) for s in surrogates]
    if len(props) == 1:
        return props[0]
    merged = Proposal({}, {}, {}, {}, {}, 0.0, [], [])
    for s, p in zip(surrogates, props):
        merged.knobs.update(p.knobs)
        merged.predicted.update(p.predicted)
        merged.residuals.update(p.residuals)
        merged.elements.update({f"{s.qubit}.{k}": v for k, v in p.elements.items()})
        merged.start_knobs.update(p.start_knobs)
        merged.at_bounds += p.at_bounds
        merged.notes += p.notes
    merged.objective = float(math.sqrt(sum(r * r for r in merged.residuals.values())))
    return merged


def apply(design_source, knobs: dict[str, float], follow_ports: bool = True, reach_um: float = 300.0, plan=None):
    """Design with ``knobs`` set (instances' params, junction fields, route fields; the paths of
    :func:`quantcore_circuits.optimise.get_knob`).

    ``follow_ports``: a geometry knob can move a port (a longer Xmon cross moves its flux port). Waypoints that sit
    on such a port's axis within ``reach_um`` of it (e.g. a taper just before the port) move with the port, so the
    route keeps its shape instead of folding back. Only the instances whose parameters change (and those snapped to
    them) are planned again; ``plan``: the source design's plan when the caller has it (else it is planned here).
    """
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.optimise import INSTANCE_FIELDS, set_knob  # pylint: disable=import-outside-toplevel

    design = load_design(design_source)
    changed = set()
    for k in knobs:
        head, _, rest = k.partition(".")
        if head in design.instances and rest.split(".", 1)[0] not in INSTANCE_FIELDS:  # a geometry parameter
            changed.add(head)
    follow_ports = follow_ports and bool(changed)
    before = (plan or plan_design(design)).all_ports() if follow_ports else {}
    for k, v in knobs.items():
        design = set_knob(design, k, v)
    if not follow_ports:
        return design
    after = _ports_without_routes(design, changed)
    data = design.to_json_dict()
    moved = False
    for route in data["routes"].values():
        for end in (route.get("from"), route.get("to")):
            if not isinstance(end, str) or end not in before or end not in after:
                continue
            old, new = before[end], after[end]
            delta = (new.pos.x - old.pos.x, new.pos.y - old.pos.y)
            if abs(delta[0]) < 1e-9 and abs(delta[1]) < 1e-9:
                continue
            for i, node in enumerate(route.get("nodes", [])):
                at = node["at"] if isinstance(node, dict) else node
                rel = (at[0] - old.pos.x, at[1] - old.pos.y)
                along = rel[0] * old.dir.x + rel[1] * old.dir.y
                across = abs(rel[0] * old.dir.y - rel[1] * old.dir.x)
                if across < 1e-3 and 0 < along <= reach_um:
                    new_at = [round(at[0] + delta[0], 4), round(at[1] + delta[1], 4)]
                    if isinstance(node, dict):
                        node["at"] = new_at
                    else:
                        route["nodes"][i] = new_at
                    moved = True
    return design.model_validate(data) if moved else design


def _ports_without_routes(design, only: set[str] | None = None):
    """Instance ports of ``design`` without planning its routes (they may not be routable yet). ``only``: plan just
    these instances, with what they are snapped to and what is snapped to them (the other ports do not move)."""
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel

    data = design.to_json_dict()
    data["routes"] = {}
    data["sim_groups"] = {}
    if only is not None:
        keep = _snap_closure(design, only)
        data["instances"] = {k: v for k, v in data["instances"].items() if k in keep}
        data["couplings"] = {}
        data["targets"] = {}
        data["nets"] = "derived"
    return plan_design(design.model_validate(data)).all_ports()


def _snap_closure(design, names: set[str]) -> set[str]:
    """``names`` plus every instance snapped to one of them and every instance one of them is snapped to."""
    keep = set(names)
    links = []
    for n, inst in design.instances.items():
        to = getattr(inst.place, "to", None)
        if getattr(inst.place, "snap", None) and isinstance(to, str) and to.split(".", 1)[0] in design.instances:
            links.append((n, to.split(".", 1)[0]))
    grew = True
    while grew:
        grew = False
        for a, b in links:
            if (a in keep) != (b in keep):
                keep |= {a, b}
                grew = True
    return keep


def write_revision(design, run_dir: str | Path, iteration: int) -> Path:
    path = Path(run_dir) / "revisions" / f"rev{iteration}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(design.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def accept(revision: str | Path, design_path: str | Path) -> Path:
    """Copy an accepted revision over the source design file (keeps a ``.bak``)."""
    design_path = Path(design_path)
    backup = design_path.with_suffix(design_path.suffix + ".bak")
    backup.write_text(design_path.read_text(encoding="utf-8"), encoding="utf-8")
    design_path.write_text(Path(revision).read_text(encoding="utf-8"), encoding="utf-8")
    return design_path


@dataclass
class LoopStep:
    iteration: int
    knobs: dict[str, float]
    measured: dict[str, float]
    residuals: dict[str, float]
    objective: float
    proposal: Proposal | None
    revision: str | None


def run(
    design_source,
    evaluate,
    targets: dict,
    max_iter: int = 5,
    run_dir: str | Path = "build/codesign",
    bounds=None,
    estimator="scqubits",
    on_step=None,
) -> list[LoopStep]:
    """Co-design loop (module docstring). ``evaluate(design) -> FilledCircuit``; ``on_step(LoopStep)`` is called
    after every iteration (e.g. to update the dashboard)."""
    from quantcore_circuits.circuit.adapters import ADAPTERS  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    design = load_design(design_source)
    surrogate = None
    steps: list[LoopStep] = []
    for it in range(max_iter + 1):
        filled = evaluate(design)
        measured = ADAPTERS[estimator](filled)
        if surrogate is None:
            surrogate = surrogate_from_fill(filled)
        else:
            update_surrogate(surrogate, filled, steps[-1].proposal.knobs)
        keys = [k for k in targets if k in measured]
        res = {k: (measured[k] - _tv(targets[k])) / _tt(targets[k]) for k in keys}
        obj = float(math.sqrt(sum(r * r for r in res.values())))
        done = all(abs(r) <= 1 for r in res.values())
        prop = None if done or it == max_iter else propose(surrogate, targets, bounds)
        rev = None
        if prop is not None:
            design = apply(design, prop.knobs)
            rev = str(write_revision(design, run_dir, it + 1))
        step = LoopStep(it, dict(surrogate.knobs), measured, res, obj, prop, rev)
        steps.append(step)
        if on_step:
            on_step(step)
        if done:
            break
    return steps


def _tv(t):
    return t.value if hasattr(t, "value") else t["value"]


def _tt(t):
    return t.tol if hasattr(t, "tol") else t["tol"]


def copy_targets(targets: dict) -> dict:
    return {k: {"value": _tv(v), "tol": _tt(v)} for k, v in copy.deepcopy(targets).items()}
