"""Component LOM models and the netlist features they rely on: legacy cells, wire / hanger couplings, readouts made
of several routes, terminations, capacitor-only nodes in the QuCat solve, and static ZZ between qubits."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
KQC = ROOT / "examples" / "designs" / "kqc"
E, H, HBAR = 1.602176634e-19, 6.62607015e-34, 1.054571817e-34


def _legacy_feedline_chip():
    """chip_01-like: ConnectorPad ─ CpwSegment ─ ConnectorPad, a CoupledResonator next to the segment, its end drawn
    into an Xmon claw (wire coupling), its coupler declared as a hanger to the segment."""
    from quantcore_circuits.designer import Designer

    d = Designer("legacy_like", box=(0, 0, 7500, 7500), verbose=False)
    d.add("FL", "CpwSegment", at=(3750, 3750), length=5950)
    d.add("PL", "ConnectorPad", snap="a", to="FL.a")
    d.add("PR", "ConnectorPad", snap="a", to="FL.b")
    d.add(
        "R1",
        "CoupledResonator",
        at=(1750, 3776),
        mirror=True,
        cpw_len=5000,
        clength=300,
        cgap=2,
        width=300,
        flip=False,
        neck_length=500,
    )
    d.add("Q1", "Xmon", at=(1750, 6000), rot=180, claws=["n"], junction={"Lj_nH": 12.0, "Cj_fF": 2.0})
    d.couple("W_Q1", "Q1.claw_n", "R1.end", wire=True)
    d.couple("K_R1", "R1", "FL")
    return d


def test_legacy_feedline_chip_is_node_connected():
    """Wire coupling merges the claw and the resonator end; the value-less coupling to the CpwSegment is a HANGER."""
    d = _legacy_feedline_chip()
    lb = d.lom()
    m = lb.model
    assert lb.unconnected == []
    assert lb.port_map["Q1.claw_n"] == lb.port_map["R1.end"]  # one conductor
    feed = lb.port_map["FL.a"]
    assert lb.port_map["PL.a"] == lb.port_map["PR.a"] == lb.port_map["FL.b"] == feed
    r1 = m.branches["R1"]
    assert r1.type == "TLres" and r1.value["kind"] == "lambda/4"
    assert r1.nodes[0] == lb.port_map["R1.end"]
    assert r1.value["length_um"] == pytest.approx(5000, rel=1e-3)  # the drawn centre line
    k = m.branches["K_R1"]
    assert k.type == "HANGER" and set(k.nodes) == {r1.nodes[0], feed}
    assert k.value["coupling_length_um"] == 300 and k.value["ground_gap_um"] == 2 and k.value["kappa_MHz"] > 0
    ports = [b for b in m.branches.values() if b.type == "R"]
    assert len(ports) == 2 and all(b.nodes[0] == feed for b in ports)
    assert "C_K_R1" not in m.branches and not any(n.startswith("wire") for n in m.branches)


@pytest.mark.analysis
def test_legacy_feedline_chip_simulates():
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.simulate import simulate

    d = _legacy_feedline_chip()
    res = simulate(fill(d.lom().model, d.design))
    assert 3 < res.params["Q1.f_q_GHz"] < 9
    assert -400 < res.params["Q1.alpha_MHz"] < -100
    assert 5 < res.params["R1.f_GHz"] < 7 and 0.01 < res.params["R1.kappa_MHz"] < 5


def test_undeclared_hanger_is_noted():
    from quantcore_circuits.designer import Designer

    d = Designer("res_only", verbose=False)
    d.add("R1", "CoupledResonator", at=(3000, 3000))
    lb = d.lom()
    assert lb.model.branches["R1"].type == "TLres"
    assert any("d.couple('K_R1', 'R1'" in n for n in lb.notes)


@pytest.mark.parametrize(
    "cell, ports, kinds",
    [
        ("TwoPadTransmon", {"left": "island1", "right": "island2"}, {"C", "JJ"}),
        ("PadCoupler", {"left": "left", "right": "right"}, {"C"}),
        ("ConnectorPad", {"a": "pad"}, {"R"}),
        ("CpweBondPad", {"a": "pad"}, {"R"}),
        ("CpweFingerCapacitor", {"a": "a", "b": "b"}, {"C"}),
        ("CpweGapCapacitor", {"a": "a", "b": "b"}, {"C"}),
        ("CpweFingerLine", {"a": "line", "b": "line"}, {"C"}),
        ("TaperedPad", {"finger": "pad"}, {"C"}),
        ("CpwSegment", {"a": "line", "b": "line"}, set()),
        ("CpweTaper", {"a": "line", "b": "line"}, set()),
    ],
)
def test_legacy_model_ports_and_ranges(cell, ports, kinds):
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    inst = Instance.model_validate({"cell": cell, "place": {"at": [0, 0]}, "junction": {"Lj_nH": 10.0, "Cj_fF": 1.0}})
    frag = lom_model(cell)("X", inst, get_pdk("quantcore_nb_sapphire_v1"))
    assert {p: frag.port_nodes[p] for p in ports} == ports
    assert {e.type for e in frag.elements} == kinds
    for e in frag.elements:
        if e.type == "C":
            assert 0.01 <= e.value["estimate"] <= 300, (e.name, e.value)
            assert e.value["estimate_kind"] in ("analytic", "rough")
        if e.type == "R":
            assert e.value["R_ohm"] == 50.0


def test_legacy_resonator_lines():
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    pdk = get_pdk("quantcore_nb_sapphire_v1")
    for cell, term in (("CoupledResonator", ("short", "open")), ("QubitResonator", ("short", "open"))):
        frag = lom_model(cell)("R", Instance.model_validate({"cell": cell, "place": {"at": [0, 0]}}), pdk)
        (line,) = frag.lines
        assert line.term == term and line.resonator and line.ports == (None, "end")
        assert line.length_um == pytest.approx(4000, rel=1e-3)
        assert frag.hangers[0]["line"] == "R" and frag.hangers[0]["end"] == "short"
    frag = lom_model("CpweQuarterWaveResonator")(
        "R", Instance.model_validate({"cell": "CpweQuarterWaveResonator", "place": {"at": [0, 0]}}), pdk
    )
    assert frag.lines[0].term == ("open", "short") and frag.lines[0].length_um == pytest.approx(5300, rel=1e-3)
    assert frag.hangers[0]["end"] == "open"


def test_readout_through_a_splitter_is_one_line():
    """KQC XMonsDirectCoupling: claw → straight RS1 → splitter → shorted tail RR1 is one λ/4 of the summed length."""
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.designer import Designer

    d = Designer.load(KQC / "xmonsdirectcoupling.json", live=False, verbose=False)
    lb = d.lom()
    plan_len = d.show().route_lengths()
    for i in (1, 2, 3):
        b = lb.model.branches[f"RR{i}"]
        total = plan_len[f"RR{i}"] + plan_len[f"RS{i}"]
        assert b.value["length_um"] == pytest.approx(total, abs=0.01)
        assert 6.0 < b.value["f_GHz"] < 7.5  # was ≈ 13–14 GHz with the tail alone
        assert b.nodes[0] == f"QB{i}.cplr1"
    filled = fill(lb.model, d.design)
    assert filled.values["RR1"].extra["f_GHz"] == pytest.approx(lb.model.branches["RR1"].value["f_GHz"], rel=1e-6)


def test_route_into_a_termination_names_the_resonator():
    from quantcore_circuits.designer import Designer

    d = Designer("term", verbose=False)
    q = d.add("Q1", "Xmon", at=(2000, 2000), claws=["n"], junction={"Lj_nH": 12.0})
    t = d.add("T0", "CpweOpenEnd", at=(2000, 6000), rot=90)
    d.route("R_T0", q.claw_n, t.a)
    m = d.lom().model
    assert "R_T0" in m.branches and "T0" not in m.branches
    b = m.branches["R_T0"]
    assert b.type == "TLres" and b.value["kind"] == "lambda/2" and b.knob == {"param": "R_T0.length"}
    assert len(d.lom(select=["Q1", "R_T0", "T0"]).model.branches) == len(m.branches)


def test_no_lom_skips_cells_without_ports():
    from quantcore_circuits.designer import Designer

    d = Designer("portless", verbose=False)
    from quantcore_circuits.assembly.drc import check

    d.add("JP", "JunctionGroundPad", at=(3000, 3000))
    d.add("RX", "WaveguideCoplanarSplitter", at=(5000, 3000))  # has ports and a model: still checked
    assert not [i for i in check(d.design, netlist=False).issues if i.rule == "no_lom"]


@pytest.mark.analysis
def test_capacitor_only_nodes_are_eliminated_before_qucat():
    """kqc/demo QB1 + RR1 + RC1: unused couplers and the far capacitor plate hold no charge (Kron reduction); QuCat
    used to return a spurious ω ≈ 0 root (A ≈ 1e16 MHz) for them."""
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.builder import lom_from_design
    from quantcore_circuits.lom.simulate import simulate

    src = KQC / "demo.json"
    res = simulate(fill(lom_from_design(src, select=["QB1", "RR1", "RC1"]).model, src))
    assert [m.label for m in res.modes] == ["QB1", "RR1"]
    assert not any("zero-frequency artefact" in n for n in res.notes)
    assert any("Kron reduction" in n for n in res.notes)
    assert 3 < res.params["QB1.f_q_GHz"] < 6 and -400 < res.params["QB1.alpha_MHz"] < -100
    assert all(abs(m.anharmonicity_MHz) < 1e4 for m in res.modes)


# ---- static ZZ ------------------------------------------------------------------------------------------------------
def _qubits_circuit(c_fF, lj_nH, couplings):
    from quantcore_circuits.circuit.schema import CircuitModel

    nodes = {"gnd": {"ground": True}} | {f"Q{i + 1}": {} for i in range(len(c_fF))}
    branches = {}
    for i, (c, lj) in enumerate(zip(c_fF, lj_nH)):
        q = f"Q{i + 1}"
        branches[f"C_{q}"] = {"type": "C", "nodes": [q, "gnd"], "value": {"estimate": c}}
        branches[f"J_{q}"] = {"type": "JJ", "nodes": [q, "gnd"], "value": {"Lj_nH": lj, "Cj_fF": 0.0}}
    for (a, b), cc in couplings.items():
        branches[f"C_{a}{b}"] = {"type": "C", "nodes": [a, b], "value": {"estimate": cc}}
    return CircuitModel.model_validate({"name": "zz", "nodes": nodes, "branches": branches})


def _transmon(ec, ej, ncut=20, nq=8):
    n = np.arange(-ncut, ncut + 1)
    h = np.diag(4 * ec * n**2.0) - ej / 2 * (np.eye(len(n), k=1) + np.eye(len(n), k=-1))
    w, v = np.linalg.eigh(h)
    v = v[:, :nq]
    return w[:nq] - w[0], v.T @ np.diag(n * 1.0) @ v


def _charge_basis_zz(c1, c2, cc, l1, l2, nq=8):
    """Independent reference: two transmons in the charge basis, H = Σ 4E_C n² − E_J cos φ + (2e)²(C⁻¹)₁₂ n₁n₂.
    Returns (ζ MHz, f01 MHz ×2, α MHz ×2, n01 ×2, n12 ×2, g_n MHz)."""
    inv = np.linalg.inv(np.array([[c1 + cc, -cc], [-cc, c2 + cc]]) * 1e-15)
    phi0 = HBAR / (2 * E)
    ec = [E**2 * inv[i, i] / 2 / H / 1e6 for i in range(2)]
    ej = [phi0**2 / (lj * 1e-9) / H / 1e6 for lj in (l1, l2)]
    g_n = (2 * E) ** 2 * inv[0, 1] / H / 1e6
    (e1, n1), (e2, n2) = _transmon(ec[0], ej[0], nq=nq), _transmon(ec[1], ej[1], nq=nq)
    eye = np.eye(nq)
    w, v = np.linalg.eigh(np.kron(np.diag(e1), eye) + np.kron(eye, np.diag(e2)) + g_n * np.kron(n1, n2))

    def lev(i, j):
        return w[np.argmax(np.abs(v[i * nq + j, :]))]

    zz = lev(1, 1) - lev(1, 0) - lev(0, 1) + lev(0, 0)
    return {
        "zz": zz,
        "f": (e1[1], e2[1]),
        "alpha": (e1[2] - 2 * e1[1], e2[2] - 2 * e2[1]),
        "n01": (abs(n1[0, 1]), abs(n2[0, 1])),
        "n12": (abs(n1[1, 2]), abs(n2[1, 2])),
        "g_n": g_n,
        "inv": inv,
    }


@pytest.mark.analysis
@pytest.mark.parametrize("cc, lj2", [(0.5, 16.0), (1.0, 18.0), (0.5, 10.0)])
def test_zz_two_transmons_with_a_coupling_capacitor(cc, lj2):
    """Static ZZ (QuCat normal modes → QuTiP) vs. an exact charge-basis diagonalisation of the same lumped circuit and
    vs. second-order perturbation theory in the coupling.

    Perturbation (Δ = f1 − f2, α < 0): |11⟩ couples to |20⟩ and |02⟩ only, so
    ζ = g_n² [(n01¹ n12²)² / (Δ − α2) − (n12¹ n01²)² / (Δ + α1)], which for harmonic matrix elements
    (n12 = √2 n01, g = g_n n01¹ n01²) is the textbook ζ = 2g²(α1 + α2)/((Δ + α1)(Δ − α2)) (e.g. Krantz et al.,
    Appl. Phys. Rev. 6, 021318 (2019), §V; Sung et al., PRX 11, 021058 (2021)). The textbook form with the harmonic
    (linear-mode) g overestimates |ζ| by ≈ 15 % here (transmon n01 and n12/n01 are below their harmonic values).
    """
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.simulate import simulate

    c, lj1 = 80.0, 12.0
    res = simulate(fill(_qubits_circuit([c, c], [lj1, lj2], {("Q1", "Q2"): cc}), None))
    assert set(res.zz_MHz) == {"Q1-Q2"}
    zz = res.zz_MHz["Q1-Q2"]
    assert res.dressed["zz"][0]["neighbours"] and not res.dressed["zz"][0]["hybridised"]

    ref = _charge_basis_zz(c, c, cc, lj1, lj2)
    assert zz == pytest.approx(ref["zz"], rel=0.02)  # exact reference of the same circuit
    assert res.params["Q1.f_q_GHz"] * 1e3 == pytest.approx(ref["f"][0], rel=1e-3)
    assert res.params["Q2.alpha_MHz"] == pytest.approx(ref["alpha"][1], rel=0.02)

    (a1, a2), (n01a, n01b), (n12a, n12b) = ref["alpha"], ref["n01"], ref["n12"]
    delta = (res.params["Q1.f_q_GHz"] - res.params["Q2.f_q_GHz"]) * 1e3
    pert = ref["g_n"] ** 2 * ((n01a * n12b) ** 2 / (delta - a2) - (n12a * n01b) ** 2 / (delta + a1))
    assert zz == pytest.approx(pert, rel=0.03)

    inv = ref["inv"]  # harmonic g of the linear modes, textbook formula: same sign, within 20 %
    w = [1 / math.sqrt(lj * 1e-9 / inv[i, i]) for i, lj in enumerate((lj1, lj2))]
    g = 0.5 * inv[0, 1] / math.sqrt(inv[0, 0] * inv[1, 1]) * math.sqrt(w[0] * w[1]) / (2 * math.pi) / 1e6
    a1s, a2s = res.params["Q1.alpha_MHz"], res.params["Q2.alpha_MHz"]
    textbook = 2 * g**2 * (a1s + a2s) / ((delta + a1s) * (delta - a2s))
    assert zz < 0 and textbook < 0 and abs(zz / textbook - 1) < 0.2


@pytest.mark.analysis
def test_zz_reported_for_neighbours_only():
    """A chain Q1 – Q2 – Q3: ζ for (Q1, Q2) and (Q2, Q3) in ``zz_MHz``; (Q1, Q3), not neighbours, only in
    ``dressed``."""
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.simulate import simulate

    model = _qubits_circuit([80, 80, 80], [12.0, 16.0, 10.0], {("Q1", "Q2"): 0.5, ("Q2", "Q3"): 0.5})
    res = simulate(fill(model, None))
    assert set(res.zz_MHz) == {"Q1-Q2", "Q2-Q3"}
    far = next(z for z in res.dressed["zz"] if z["pair"] == "Q1-Q3")
    assert not far["neighbours"] and abs(far["zz_MHz"]) < 0.2 * abs(res.zz_MHz["Q1-Q2"])
    ref = _charge_basis_zz(80, 80, 0.5, 12.0, 16.0)["zz"]
    assert res.zz_MHz["Q1-Q2"] == pytest.approx(ref, rel=0.1)  # Q3 shifts it slightly


def test_cells_without_ports_or_model_add_no_note():
    from quantcore_circuits.designer import Designer

    d = Designer("labels", verbose=False)
    d.add("L1", "TextLabel", at=(3000, 3000))
    d.add("FH", "FluxHoleArray", at=(4000, 3000))
    lb = d.lom()
    assert not any("L1" in n or "FH" in n for n in lb.notes)


# ---- FEM-free cross-check: Quantum Metal tutorial 4.01 -----------------------------------------------------------
# docs/tut/4-Analysis/4.01-Capacitance-and-LOM.ipynb (qiskit-metal): Q3D Maxwell matrix (fF) of the default
# TransmonPocket Q1 with readout + two bus connection pads, last adaptive pass; LOM with Lj = 12.31 nH, Cj = 2 fF.
# Published (pass 6): f_Q 5.424935 GHz, EC 311.976959 MHz, alpha −363.792421 MHz. Order: bus1, bus2, ground,
# pad_bot, pad_top, readout.
METAL_401_NETS = ["bus1", "bus2", "ground", "pad_bot", "pad_top", "readout"]
METAL_401_C = [
    [49.77794, -0.42560, -33.50861, -1.57029, -13.15538, -0.20494],
    [-0.42560, 54.01885, -35.77522, -13.99741, -1.82852, -1.01319],
    [-33.50861, -35.77522, 237.69029, -31.53485, -37.88741, -36.55732],
    [-1.57029, -13.99741, -31.53485, 98.20667, -30.07382, -18.86490],
    [-13.15538, -1.82852, -37.88741, -30.07382, 87.85076, -2.20122],
    [-0.20494, -1.01319, -36.55732, -18.86490, -2.20122, 59.92347],
]


def _metal_401_circuit(pads_grounded: bool, resonators: dict | None = None):
    from quantcore_circuits.circuit.schema import CircuitModel

    def node(n):
        return "gnd" if n == "ground" or (pads_grounded and n not in ("pad_top", "pad_bot")) else n

    caps: dict[tuple[str, str], float] = {}
    for i, a in enumerate(METAL_401_NETS):
        for j, b in enumerate(METAL_401_NETS[i + 1 :], i + 1):
            na, nb = node(a), node(b)
            if na != nb:
                key = tuple(sorted((na, nb)))
                caps[key] = caps.get(key, 0.0) - METAL_401_C[i][j]
    used = {n for k in caps for n in k}
    branches = {f"C_{a}_{b}": {"type": "C", "nodes": [a, b], "value": {"estimate": c}} for (a, b), c in caps.items()}
    branches["J_Q"] = {"type": "JJ", "nodes": ["pad_top", "pad_bot"], "value": {"Lj_nH": 12.31, "Cj_fF": 2.0}}
    for pad, f in (resonators or {}).items():
        branches[f"R_{pad}"] = {
            "type": "TLres",
            "nodes": [pad, "gnd"],
            "value": {"kind": "lambda/2", "f_GHz": f, "Z0_ohm": 50.0, "length_um": 1.0},
        }
    nodes = {"gnd": {"ground": True}} | {n: {} for n in sorted(used - {"gnd"})}
    return CircuitModel.model_validate({"name": "metal401", "nodes": nodes, "branches": branches})


@pytest.mark.analysis
def test_metal_tutorial_401_lom_numbers():
    """Same C-matrix and junction as the Metal LOM tutorial, coupling pads grounded as Metal's
    ``extract_transmon_coupled_Noscillator`` treats them: QuCat → QuTiP gives the published f_Q / EC / α."""
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.simulate import simulate

    res = simulate(fill(_metal_401_circuit(pads_grounded=True), None))
    (mode,) = res.modes
    assert mode.anharmonicity_MHz == pytest.approx(311.976959, rel=1e-4)  # first-order A = E_C
    assert res.params["Q.f_q_GHz"] == pytest.approx(5.424935, rel=1e-3)
    assert res.params["Q.alpha_MHz"] == pytest.approx(-363.792421, rel=0.01)


@pytest.mark.analysis
def test_floating_transmon_between_resonators_uses_the_lossless_solve():
    """The tutorial's pads loaded by their λ/2 resonators (7.0 / 6.0 / 6.2 GHz, 50 Ω): QuCat's root derivative gives
    A ≈ 0.15 MHz for a mode with 73 % junction participation; the lossless normal-mode solve takes over."""
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.simulate import simulate

    res = simulate(
        fill(_metal_401_circuit(False, {"readout": 7.0, "bus1": 6.0, "bus2": 6.2}), None),
        max_modes=2,
    )
    assert any("lossless normal-mode solve" in n for n in res.notes)
    q = next(m for m in res.modes if m.label == "Q")
    a_expected = 311.98 * q.participation["J_Q"] ** 2  # E_C × p² for one junction (first order)
    assert q.anharmonicity_MHz == pytest.approx(a_expected, rel=0.15)
    assert -400 < res.params["Q.alpha_MHz"] < -50


def test_pairs_include_half_wave_readouts_and_skip_buses():
    """kqc/demo and kqc/munchqubits read out through λ/2 meanders: fill() pairs them (the consensus path needs it);
    munchqubits' CPL couples QB1 and QB2, a bus, not a readout."""
    from quantcore_circuits.circuit.fill import fill, two_node_model
    from quantcore_circuits.lom.builder import lom_from_design

    demo = fill(lom_from_design(KQC / "demo.json").model, KQC / "demo.json")
    assert {(p.qubit, p.resonator, p.kind) for p in demo.pairs} == {
        (f"QB{i}", f"RR{i}", "lambda/2") for i in (1, 2, 3, 4)
    }
    munch = fill(lom_from_design(KQC / "munchqubits.json").model, KQC / "munchqubits.json")
    assert {(p.qubit, p.resonator) for p in munch.pairs} == {("QB1", "RR1"), ("QB2", "RR2"), ("QB3", "RR3")}
    assert any(n.startswith("CPL: reached by 2 qubits") for n in munch.notes)
    p = next(p for p in demo.pairs if p.qubit == "QB1")
    tn = two_node_model(p)
    assert tn["C_r_fF"] == pytest.approx(math.pi / (2 * 2 * math.pi * p.f_r_GHz * 1e9 * p.z0_ohm) / 1e-15, rel=1e-9)
    assert 3 < tn["f_r_loaded_GHz"] < p.f_r_GHz


# ---- couplings to a route -------------------------------------------------------------------------------------------
def _routed_feedline_chip():
    """As _legacy_feedline_chip, but the feedline is a route ``FL`` between two BondPads (chip_09-like)."""
    from quantcore_circuits.designer import Designer

    d = Designer("routed_fl", box=(0, 0, 7500, 7500), verbose=False)
    pl = d.add("PL", "BondPad", at=(700, 3750), rot=270)
    pr = d.add("PR", "BondPad", at=(6800, 3750), rot=90)
    d.route("FL", pl.a, pr.a)
    d.add("R1", "CoupledResonator", at=(1750, 3776), mirror=True, cpw_len=5000, clength=300, cgap=2, width=300,
          flip=False, neck_length=500)  # fmt: skip
    d.add("Q1", "Xmon", at=(1750, 6000), rot=180, claws=["n"], junction={"Lj_nH": 12.0, "Cj_fF": 2.0})
    d.couple("W_Q1", "Q1.claw_n", "R1.end", wire=True)
    d.couple("K_R1", "R1", "FL")
    return d


def test_hanger_and_c_coupling_to_a_route():
    """``d.couple("K_R1", "R1", "FL")`` with FL a *route*: a HANGER to the feedline conductor; a C coupling from a
    qubit to the route lands on the same conductor; a selection without FL keeps the feedline as a port load."""
    d = _routed_feedline_chip()
    d.add("Q2", "Xmon", at=(5000, 5000), claws=["n"], junction={"Lj_nH": 12.0, "Cj_fF": 2.0})
    d.couple("Cq_Q2", "Q2", "FL", C_fF=0.3)
    lb = d.lom()
    m = lb.model
    feed = lb.port_map["PL.a"]
    assert feed == lb.port_map["PR.a"] == "FL"
    assert lb.unconnected == ["Q2.claw_n"]
    k = m.branches["K_R1"]
    assert k.type == "HANGER" and set(k.nodes) == {m.branches["R1"].nodes[0], feed} and k.value["kappa_MHz"] > 0
    c = m.branches["C_Cq_Q2"]
    assert c.type == "C" and set(c.nodes) == {"Q2", feed} and c.value["estimate"] == 0.3
    assert not any("cannot resolve" in n for n in lb.notes)
    sub = d.lom(select=["R1", "Q1"]).model  # FL outside the selection: its conductor + both port loads stay
    assert set(sub.branches["K_R1"].nodes) == {sub.branches["R1"].nodes[0], "FL"}
    assert sub.branches["Port_FL"].value["R_ohm"] == 25.0
    assert "C_Cq_Q2" not in sub.branches


@pytest.mark.analysis
def test_routed_feedline_hanger_simulates():
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.simulate import simulate

    d = _routed_feedline_chip()
    res = simulate(fill(d.lom().model, d.design))
    assert 3 < res.params["Q1.f_q_GHz"] < 9 and -400 < res.params["Q1.alpha_MHz"] < -100
    assert 5 < res.params["R1.f_GHz"] < 7 and 0.01 < res.params["R1.kappa_MHz"] < 5


# ---- line ends on terminations --------------------------------------------------------------------------------------
def _ungrounded_resonator(term: str | None):
    """A CoupledResonator with ``ground=False`` (no end cap: the tail runs into the ground plane) and, at its tail,
    nothing (``None``), a CpweOpenEnd drawn over the tail (``"drawn"``, the legacy cut box) or one wired to it."""
    from quantcore_circuits.assembly import plan_design
    from quantcore_circuits.designer import Designer

    d = Designer(f"tail_{term}", box=(0, 0, 7500, 7500), verbose=False)
    d.add("R1", "CoupledResonator", at=(3000, 3000), cpw_len=4500, ground=False, clength=300)
    if term:
        end = plan_design(d.design).instances["R1"].ports["end"]
        rot = math.degrees(math.atan2(-end.dir.y, -end.dir.x)) - 180
        at = (end.pos.x - 9 * end.dir.x + 4 * end.dir.y, end.pos.y - 9 * end.dir.y - 4 * end.dir.x)
        d.add("CUT", "CpweOpenEnd", at=at, rot=rot, length=10, a=10, b=5)
        if term == "wired":
            d.couple("W_R1", "R1.end", "CUT.a", wire=True)
    return d


@pytest.mark.parametrize("term, kind", [(None, "lambda/2"), ("drawn", "lambda/4"), ("wired", "lambda/4")])
def test_ungrounded_tail_on_an_open_termination(term, kind):
    """chip_05 R8: the tail without an end cap is shorted when nothing is there (λ/2, short–short); a CpweOpenEnd
    drawn over it, or wired to it, opens it (λ/4). The termination itself adds no element."""
    lb = _ungrounded_resonator(term).lom()
    r1 = lb.model.branches["R1"]
    assert r1.type == "TLres" and r1.value["kind"] == kind
    assert "CUT" not in lb.model.branches
    assert not any("modelled as a wire" in n for n in lb.notes)
    assert lb.unconnected == ([] if term else ["R1.end"])
    assert any("lies on the termination CUT.a" in n for n in lb.notes) == (term == "drawn")
    if term:  # the termination's port is the line end (test_examples: every port maps to a circuit node)
        assert lb.port_map["CUT.a"] == r1.nodes[0]
    f_quarter = lb.model.branches["R1"].value["f_GHz"]
    assert 6 < f_quarter < 8 if kind == "lambda/4" else 12 < f_quarter < 16


def test_chip05_r8_is_open():
    from quantcore_circuits.lom.builder import lom_from_design

    # after decisions #11/#26 the cut boxes (CUT8, CUT7) are gone: R8 and R7 end in their own open end
    src = ROOT / "examples" / "designs" / "legacy" / "chip_05_flux_tlqubits.json"
    lb = lom_from_design(src)
    r8 = lb.model.branches["R8"]
    assert r8.value["kind"] == "lambda/4" and 6.5 < r8.value["f_GHz"] < 7.5
    assert "CUT8" not in lb.model.branches and lb.port_map["R8.end"] == r8.nodes[0]
    c3 = lom_from_design(ROOT / "examples" / "designs" / "legacy" / "chip_03_trilayer.json")
    r7 = c3.model.branches["R7"]
    assert r7.value["kind"] == "lambda/4" and 6780 < r7.value["length_um"] < 6800  # uncut 6790 µm line (#26)
    assert "CUT7" not in c3.model.branches and c3.port_map["R7.end"] == r7.nodes[0]
    from quantcore_circuits.designer import Designer

    d = Designer("lone_term", verbose=False)
    d.add("CUT", "CpweOpenEnd", at=(2000, 2000))
    lone = d.lom()  # a termination with nothing joined: no element, its port on ground
    assert lone.port_map["CUT.a"] == "gnd" and not lone.model.branches


# ---- mode labels ----------------------------------------------------------------------------------------------------
def test_mode_labels_are_one_to_one():
    from quantcore_circuits.lom.simulate import _unique_labels

    tie = {"J_Q1": 0.452, "J_Q2": 0.452, "bus": 0.096}
    assert _unique_labels([tie, {"J_Q1": 0.5, "J_Q2": 0.5}, {"bus": 0.9, "J_Q1": 0.05}]) == ["J_Q1", "J_Q2", "bus"]
    assert _unique_labels([{"J_Q2": 0.7, "J_Q1": 0.3}, {"J_Q2": 0.6, "J_Q1": 0.4}]) == ["J_Q2", "J_Q1"]
    assert _unique_labels([{"a": 0.6}, {"a": 0.9}, {"a": 0.5}]) == [None, "a", None]  # more modes than elements


@pytest.mark.analysis
def test_identical_bus_coupled_transmons_get_both_labels():
    """metal/a2: two identical TransmonPockets on a λ/2 bus hybridise; QuCat also returns a ω ≈ 0 root (dropped).
    Each qubit name labels exactly one mode (was `Q2` twice, ZZ key "Q2-Q2")."""
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.builder import lom_from_design
    from quantcore_circuits.lom.simulate import simulate

    src = ROOT / "examples" / "designs" / "metal" / "a2_two_coupled_transmons.json"
    res = simulate(fill(lom_from_design(src, select=["Q1", "Q2", "coupler_bus"]).model, src))
    labels = [m.label for m in res.modes]
    assert sorted(labels) == ["Q1", "Q2", "coupler_bus"]
    assert [m.label for m in res.modes if m.kind == "qubit"] == ["Q1", "Q2"]  # lower mode → Q1
    assert [z["pair"] for z in res.dressed["zz"]] == ["Q1-Q2"]
    assert "Q1.f_q_GHz" in res.params and "Q2.f_q_GHz" in res.params


# ---- metal-only Metal cells -----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "cell, elements",
    [
        ("metal:TunableCoupler02", {"J_C", "C_C_12"}),
        ("metal:TransmonConcentricType2", {"J_C", "C_C_12"}),
        ("metal:ResonatorLumped", {"C"}),
        ("metal:NSquareSpiral", {"C"}),
    ],
)
def test_metal_only_cells_need_a_pocket(cell, elements):
    """Metal draws these as metal only: alone they are ground plane (no elements, ports grounded, a note); on a
    metal:Rectangle pocket (the catalog recipe) their model applies."""
    from quantcore_circuits.designer import Designer

    for pocket in (False, True):
        d = Designer("pocket", box=(0, 0, 6000, 6000), live=False, verbose=False)
        if pocket:
            d.add("P", "metal:Rectangle", at=(3000, 3000), width=4200, height=1800, subtract=True)
        d.add("C", cell, at=(3000, 2625))
        lb = d.lom()
        if pocket:
            assert elements <= set(lb.model.branches)
            assert not any("draws metal only" in n for n in lb.notes)
        else:
            assert lb.model.branches == {}
            assert all(n == "gnd" for p, n in lb.port_map.items())
            assert any("draws metal only" in n and "no pocket" in n for n in lb.notes)


def test_n_square_spiral_line_length():
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    inst = Instance.model_validate({"cell": "metal:NSquareSpiral", "place": {"at": [0, 0]}})
    frag = lom_model("metal:NSquareSpiral")("S", inst, get_pdk("quantcore_nb_sapphire_v1"))
    (line,) = frag.lines
    # Metal defaults n 3, width 1, gap 4, radius 40: per turn 8·(20 + 5k) + 2·5 µm
    assert line.length_um == pytest.approx(sum(8 * (20 + 5 * k) + 10 for k in range(3)), rel=1e-9)
    assert frag.port_nodes == {"spiralPin": "spiral"} and line.term == ("open", "open")


def test_fingerless_metal_idc_is_a_gap_capacitor():
    """metal:CapNInterdigitalTee / CapNInterdigital with finger_length 0: two plates across cap_gap, not 0 fF."""
    from types import SimpleNamespace

    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    pdk = get_pdk()
    for cell in ("metal:CapNInterdigitalTee", "metal:CapNInterdigital"):
        values = {}
        for fl in (0, 50):
            inst = SimpleNamespace(cell=cell, params={"finger_length": fl, "finger_count": 8}, junction=None)
            frag = lom_model(cell)("C1", inst, pdk)
            values[fl] = next(e.value for e in frag.elements if e.name == "C_C1")
        assert 1.0 < values[0]["estimate"] < values[50]["estimate"], (cell, values)
        assert values[0]["estimate_kind"] == "rough"


# ---- resonators without a port, pass-through sections ------------------------------------------------------------
def _hanger_chip(name: str):
    """BondPad ─ FL ─ BondPad; a hanger coupler at x = 2850 µm (s = 2300, 300 µm long) on the +y side."""
    from quantcore_circuits.designer import Designer

    d = Designer(name, box=(0, 0, 7500, 7500), verbose=False)
    pl = d.add("PL", "BondPad", at=(700, 3750), rot=270)
    pr = d.add("PR", "BondPad", at=(6800, 3750), rot=90)
    return d, d.route("FL", pl.a, pr.a)


@pytest.mark.parametrize(
    "term, end, kind",
    [
        (6.0, "short", "lambda/4"),
        (0.0, "open", "lambda/4"),
        (6.0, "open", "lambda/2"),
        (0.0, "short", "lambda/2"),
    ],  # fmt: skip
)
def test_free_end_to_hanger_is_a_resonator(term, end, kind):
    """``route(free_end(...), fl.hanger(...))`` (builder-b: "unknown node 'open'"): a TLres on the route's own node
    plus its HANGER; λ/4 when exactly one end is shorted (free end ``term=0`` or hanger ``end="short"``)."""
    from quantcore_circuits.designer import Designer

    d, fl = _hanger_chip(f"fe_{end}_{term:g}")
    d.route("R", Designer.free_end((2850, 6400), dir=270, term=term), fl.hanger(s=2300, length=300, end=end))
    lb = d.lom()
    m = lb.model
    r, k = m.branches["R"], m.branches["K_R"]
    assert r.type == "TLres" and r.value["kind"] == kind and r.nodes == ("R.line", "gnd")
    assert r.value["length_um"] == pytest.approx(d.show().route_lengths()["R"], abs=0.01)
    assert m.nodes["R.line"].island == "R"  # the route's C-matrix net
    assert k.type == "HANGER" and k.nodes == ("R.line", "FL") and k.value["end"] == end and k.value["kappa_MHz"] > 0
    f = r.value["f_GHz"]  # 2843 µm: λ/4 ≈ 11.3 GHz, λ/2 twice that
    assert 10 < f < 12.5 if kind == "lambda/4" else 20 < f < 25
    assert lb.unconnected == [] and any("no port at either end" in n for n in lb.notes)


def _taper_chain(start: str, cell: str = "WaveguideCoplanarTaper"):
    """``start`` (a metal:ShortToGround, a shorted free end, or an Xmon claw) → route RN → pass-through ``T`` →
    route RM → hanger on FL (open for a shorted start, shorted after a claw): one λ/4 in every case."""
    from quantcore_circuits.designer import Designer

    d, fl = _hanger_chip(f"taper_{start}")
    kw = {"a": 10, "b": 6, "a2": 2, "b2": 6, "taper_length": 100} if cell == "WaveguideCoplanarTaper" else {}
    t = d.add("T", cell, at=(2850, 5500), rot=90, **kw)
    if start == "short":
        s = d.add("S", "metal:ShortToGround", at=(2850, 6400), rot=90)
        d.route("RN", s.short, t.b)
    elif start == "free":
        d.route("RN", t.b, Designer.free_end((2850, 6400), dir=270, term=0))
    else:
        q = d.add("Q", "Xmon", at=(2850, 6800), rot=180, claws=["n"], junction={"Lj_nH": 12.0, "Cj_fF": 2.0})
        d.route("RN", q.claw_n, t.b)
    d.route("RM", t.a, fl.hanger(s=2300, length=300, end="short" if start == "claw" else "open"))
    return d


@pytest.mark.parametrize("start", ["short", "free", "claw"])
def test_taper_inside_a_resonator_extends_it(start):
    """builder-b (QPDK neck): route → WaveguideCoplanarTaper → route → hanger is one λ/4 of the summed length named
    after the hanger route, not a λ/2 plus a short λ/4; the width step is noted as not modelled."""
    d = _taper_chain(start)
    lb = d.lom()
    m = lb.model
    lengths = d.show().route_lengths()
    tl = {n: b for n, b in m.branches.items() if b.type == "TLres"}
    assert list(tl) == ["RM"]
    rm = tl["RM"]
    assert rm.value["kind"] == "lambda/4" and rm.knob == {"param": "RM.length"}
    assert rm.value["length_um"] == pytest.approx(lengths["RN"] + 100 + lengths["RM"], abs=0.01)
    assert (rm.value["a_um"], rm.value["b_um"]) == (10, 6)  # RM's CPW (the taper's wide end)
    assert 9 < rm.value["f_GHz"] < 12
    k = m.branches["K_RM"]
    assert k.type == "HANGER" and set(k.nodes) == {rm.nodes[0], "FL"}
    assert any("section(s) ['T'] enter by (equivalent) length only" in n for n in lb.notes)
    assert lb.port_map["T.a"] == lb.port_map["T.b"] == rm.nodes[0] and lb.unconnected == []
    if start == "short":
        assert lb.port_map["S.short"] == rm.nodes[0] and "S" not in m.branches
    if start == "claw":
        assert rm.nodes[0] == lb.port_map["Q.claw_n"]


def test_airbridge_connection_is_a_pass_through():
    """KQC AirbridgeConnection inside a resonator: extends it by its port-to-port length; alone it adds nothing."""
    from quantcore_circuits.assembly import plan_design
    from quantcore_circuits.designer import Designer

    d = _taper_chain("free", cell="AirbridgeConnection")
    ports = plan_design(d.design).instances["T"].ports
    span = (ports["a"].pos - ports["b"].pos).length()
    assert 50 < span < 500
    lb = d.lom()
    rm = lb.model.branches["RM"]
    lengths = d.show().route_lengths()
    assert rm.value["kind"] == "lambda/4"
    assert rm.value["length_um"] == pytest.approx(lengths["RN"] + span + lengths["RM"], abs=0.01)
    alone = Designer("ab_alone", verbose=False)
    alone.add("A", "AirbridgeConnection", at=(2000, 2000))
    alone.add("C", "CpweTaper", at=(3000, 2000), length=150)
    lb_alone = alone.lom()
    assert not lb_alone.model.branches  # unterminated KQC / CPW-E ends join the ground plane
    assert {lb_alone.port_map[p] for p in ("A.a", "A.b", "C.a", "C.b")} == {"gnd"}


@pytest.mark.parametrize("cell", ["AirbridgeRectangular", "metal:Airbridge"])
def test_unjoined_airbridge_is_a_ground_strap(cell):
    """kqc/test_chips/airbridge_crossings (builder-c): bridges over port-less straights join nothing: ground straps,
    ports → gnd, no element; a bridge whose pad a route reaches stays a wire on that conductor."""
    from quantcore_circuits.designer import Designer

    d = Designer(f"strap_{cell.replace(':', '_')}", box=(0, 0, 6000, 6000), verbose=False)
    d.add("AB1", cell, at=(1000, 1000))
    lb = d.lom()
    assert lb.port_map["AB1.a"] == lb.port_map["AB1.b"] == "gnd" and not lb.model.branches
    assert any("ground straps" in n and "AB1" in n for n in lb.notes)
    pl = d.add("PL", "BondPad", at=(3000, 3000))
    d.add("AB2", cell, at=(3000, 4500), rot=180 if cell == "AirbridgeRectangular" else 90)  # pad a faces PL.a
    d.route("W", pl.a, "AB2.a")
    lb = d.lom()
    assert lb.port_map["AB2.a"] == lb.port_map["AB2.b"] == lb.port_map["PL.a"] != "gnd"
    assert lb.port_map["AB1.a"] == "gnd"


@pytest.mark.analysis
def test_taper_chain_simulates_one_resonator():
    from quantcore_circuits.circuit.fill import fill
    from quantcore_circuits.lom.simulate import simulate

    d = _taper_chain("claw")
    m = d.lom().model
    filled = fill(m, d.design)
    assert filled.values["RM"].extra["f_GHz"] == pytest.approx(m.branches["RM"].value["f_GHz"], rel=1e-6)
    res = simulate(filled)
    assert 3 < res.params["Q.f_q_GHz"] < 9 and -400 < res.params["Q.alpha_MHz"] < -100
    # kinetic inductance (decision #45): RM f was just above 9 GHz (9.01), now 8.87; lower bound 9 -> 8.5
    assert 8.5 < res.params["RM.f_GHz"] < 12 and res.params["RM.kappa_MHz"] > 0
    assert not any(k.startswith(("RN.", "T.")) for k in res.params)


def test_neck_termination_ends_a_quarter_wave():
    """QPDK vortex neck (builder-b, components' NeckTermination): hanger (open) → route → neck is one λ/4 named after
    the route; taper + neck count at their inductive equivalent length (> drawn: narrow strip in a wide window)."""
    d, fl = _hanger_chip("neck")
    d.add("N", "NeckTermination", at=(2850, 6000), rot=90)  # o1 faces the feedline
    d.route("R", "N.o1", fl.hanger(s=2300, length=300, end="open"))
    lb = d.lom()
    r = lb.model.branches["R"]
    drawn = d.show().route_lengths()["R"]
    extra = r.value["extra_length_um"]
    assert r.value["kind"] == "lambda/4" and r.value["length_um"] == pytest.approx(drawn + extra, abs=0.01)
    assert 425 * 1.5 < extra < 425 * 6  # 100 µm taper + 325 µm neck, L' of a 2 µm strip in a 380 µm window
    assert "N" not in lb.model.branches and lb.port_map["N.o1"] == r.nodes[0] and lb.unconnected == []
    assert set(lb.model.branches["K_R"].nodes) == {r.nodes[0], "FL"}
    assert any(n.startswith("N: taper 100 µm + neck 325 µm counted as") for n in lb.notes)


# ---- QPDK / SQDMetal cells (components 04:46) ---------------------------------------------------------------------
def _floating_csum(c1: float, c2: float, c12: float) -> float:
    return c12 + c1 * c2 / (c1 + c2)


def test_qpdk_sqdmetal_qubit_models():
    """Flipmon / TransmonTaperedInsets floating (island1 + island2 + junction), Gatemon grounded with a JJ for the
    nanotube; C_Σ in 30–300 fF, every capacitance 0.1–200 fF, labelled estimates."""
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    pdk = get_pdk()
    j = {"Lj_nH": 12.0}
    for cell, params in (
        ("Flipmon", {}),
        ("Gatemon", {}),
        ("TransmonTaperedInsets", {"connection_pads": {"readout": {}}}),
    ):
        inst = Instance.model_validate({"cell": cell, "params": params, "place": {"at": [0, 0]}, "junction": j})
        frag = lom_model(cell)("X", inst, pdk)
        cs = {e.name: e.value for e in frag.elements if e.type == "C"}
        assert all(0.1 <= v["estimate"] <= 200 and v["estimate_kind"] in ("analytic", "rough") for v in cs.values())
        jj = [e for e in frag.elements if e.type in ("JJ", "SQUID")]
        assert len(jj) == 1 and jj[0].value["Lj_nH"] == 12.0
        if cell == "Gatemon":
            assert jj[0].type == "JJ" and jj[0].nodes == ("island", "gnd") and frag.port_nodes["readout"] == "island"
            assert 30 < cs["C_X"]["estimate"] < 300 and frag.port_nodes["gate"] == "gate"
            continue
        assert jj[0].nodes == ("island1", "island2")
        c12 = sum(v["estimate"] for n, v in cs.items() if n.startswith("C_X_12"))
        c1 = cs["C_X_1"]["estimate"]
        c2 = sum(v["estimate"] for n, v in cs.items() if n.startswith("C_X_2"))
        assert 30 < _floating_csum(c1, c2, c12) < 300, cell
    flip = lom_model("Flipmon")("X", Instance.model_validate({"cell": "Flipmon", "place": {"at": [0, 0]}}), pdk)
    assert flip.port_nodes == {"squid_a": "island2", "squid_b": "island1", "coupler": "cplr"}
    assert any("face 2b1" in n for n in flip.notes)


def test_gatemon_on_its_coupler_and_semicircle_capacitor_on_a_pin():
    """Snapped ``G.readout`` ↔ ``K.qubit``: the coupler's nominal C links its line and the gatemon island (two nodes);
    a SmoothCapacitorSemicircle snapped to a TransmonTaperedInsets corner pin couples to that pad, not galvanically."""
    from quantcore_circuits.designer import Designer

    d = Designer("gatemon_k", box=(0, 0, 6000, 6000), verbose=False)
    pl = d.add("PL", "BondPad", at=(700, 3000), rot=270)
    k = d.add("K", "GatemonCoupler", at=(2000, 3000))
    pr = d.add("PR", "BondPad", at=(5300, 3000), rot=90)
    d.route("FA", pl.a, k.o1)
    d.route("FB", k.o2, pr.a)
    d.add("G", "Gatemon", snap="readout", to="K.qubit", junction={"Lj_nH": 15.0})
    lb = d.lom()
    m = lb.model
    cg = m.branches["Cg_K"]
    island = lb.port_map["G.readout"]
    assert lb.port_map["K.qubit"] == island and lb.port_map["K.o1"] == lb.port_map["PL.a"] != island
    assert set(cg.nodes) == {island, lb.port_map["K.o1"]} and cg.value["estimate"] == pytest.approx(5.4)
    assert m.branches["J_G"].type == "JJ" and m.branches["J_G"].nodes == (island, "gnd")

    d2 = Designer("semicircle", box=(0, 0, 6000, 6000), verbose=False)
    d2.add("Q1", "TransmonTaperedInsets", at=(3000, 3000), junction={"Lj_nH": 13.0})
    d2.add("SC", "SmoothCapacitorSemicircle", snap="target", to="Q1.top_right_pin", rect_width=160, rect_length=80,
           semi_radius=60)  # fmt: skip
    lb2 = d2.lom()
    c = lb2.model.branches["C_SC"]
    assert set(c.nodes) == {lb2.port_map["SC.a"], lb2.port_map["Q1.squid_a"]} and lb2.port_map["SC.a"] != "gnd"
    assert lb2.port_map["Q1.top_pocket_pin"] == "gnd" and 1 < c.value["estimate"] < 60


def test_hyperbolic_vertex_coupler_pins():
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    for q, pairs in ((2, 1), (3, 3), (5, 5)):
        inst = Instance.model_validate({"cell": "HyperbolicVertexCoupler", "params": {"q": q}, "place": {"at": [0, 0]}})
        frag = lom_model("HyperbolicVertexCoupler")("V", inst, get_pdk())
        assert frag.port_nodes == {f"o{k + 1}": f"o{k + 1}" for k in range(q)}
        mutual = [e for e in frag.elements if "gnd" not in e.nodes]
        assert len(mutual) == pairs and all(0.1 < e.value["estimate"] < 50 for e in frag.elements)


@pytest.mark.parametrize("taps", [{"rp": [0.75, 4.7]}, '{"pu_D1": [1.5, 5.4], "pu_D2": [1.5, 5.0]}'])
def test_polyline_cpw_taps_are_on_the_line(taps):
    """metal:PolylineCPW tap pins (Wallraff 17q ``RO_*.rp``, ``FEED_*.pu_*``) map to the line's node like start/end."""
    from types import SimpleNamespace

    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    params = {"points": [[0, 0], [0.5, 0], [0.5, 0.3]], "trace_width": "8.5um", "trace_gap": "5.5um", "taps": taps}
    frag = lom_model("metal:PolylineCPW")("RO", SimpleNamespace(cell="metal:PolylineCPW", params=params, junction=None),
                                         get_pdk())  # fmt: skip
    names = taps if isinstance(taps, dict) else {"pu_D1": 0, "pu_D2": 0}
    assert frag.port_nodes == {"start": "line", "end": "line", **dict.fromkeys(names, "line")}
    assert frag.lines[0].length_um == pytest.approx(800.0) and any("tap pin(s)" in n for n in frag.notes)
