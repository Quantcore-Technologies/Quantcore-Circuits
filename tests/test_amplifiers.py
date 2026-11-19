"""Parametric-amplifier cells (``layouts/others/amplifiers.py``) and models (``analysis/amplifiers.py``), fast.

Cells: build with defaults and with ``junction_type="Sim"`` through the design-plan path, ports with directions,
junction fingers landing on metal on both sides (island and ground), LOM fragments (nodes, port map, elements,
SQUID equivalent length, chain and resonator counts), the KI ladder against twpa-sim's NbN cell. Models: the QPDK
JTWPA cold mismatch and gain trend, the SQUID-terminated λ/4 resonance, the single-mode paramp threshold law.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from quantcore_circuits.analysis import amplifiers as amp

CELLS = ["SquidTermination", "LumpedJpa", "JtwpaChain", "KiTwpaSerpentine"]
BIG_JJ = {"finger_width": 2.0, "second_finger_width": 2.0}  # the largest PDK trilayer junction


def _design(cell: str, **params):
    from quantcore_circuits.design import load_design

    return load_design(
        {
            "schema": "qcc/0.1",
            "name": "amp_probe",
            "instances": {"X": {"cell": cell, "params": params, "place": {"at": [0, 0]}}},
        }
    )


def _plan(cell: str, **params):
    from quantcore_circuits.assembly import plan_design

    return plan_design(_design(cell, **params)).instances["X"]


def _fragment(cell: str, junction=None, **params):
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    design = _design(cell, **params)
    inst = design.instances["X"]
    if junction:
        from quantcore_circuits.design.schema import Junction

        inst.junction = Junction(**junction)
    return lom_model(cell)("X", inst, get_pdk())


@pytest.mark.parametrize("cell", CELLS)
def test_cell_resolves_builds_and_ports_have_directions(cell):
    from quantcore_circuits.layouts.registry import resolve_cell

    cls = resolve_cell(cell)
    assert cls.__module__.endswith("layouts.others.amplifiers")
    placed = _plan(cell)
    routing = {n: p for n, p in placed.local_ports.items() if not n.startswith("squid")}
    assert routing, f"{cell}: no routing ports"
    assert all(p.dir is not None for p in routing.values()), f"{cell}: a routing port without direction"


@pytest.mark.parametrize(
    "cell, params",
    [
        ("SquidTermination", {"junction_params": BIG_JJ}),
        ("LumpedJpa", {"junction_params": BIG_JJ, "shunt_fingers": 4}),
        ("LumpedJpa", {"coupling": "inductive", "shunt_fingers": 4}),
        (
            "LumpedJpa",
            {"junction_type": "Quantcore Squid", "flux_line": True, "shunt_fingers": 4, "junction_params": BIG_JJ},
        ),
        ("JtwpaChain", {"cells": 4, "junction_params": BIG_JJ}),
    ],
)
def test_junction_fingers_land_on_metal(cell, params):
    """Every trilayer window: the straight finger (2/0) touches metal on the island side, the bent finger (4/0) on
    the ground side (a SQUID's two straight fingers sit ±8 µm off-axis: the cells give them a landing head)."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.layouts.registry import resolve_cell

    ly = pya.Layout()
    ly.dbu = 0.001
    cls = resolve_cell(cell)
    c = cls.create(ly, **cls.qcc_params(params))

    def layer(suffix):
        for li in ly.layer_indexes():
            if ly.get_info(li).name.endswith(suffix):
                return pya.Region(c.begin_shapes_rec(li)).merged()
        return pya.Region()

    metal = pya.Region(c.bbox().enlarged(20000)) - (layer("base_metal_gap_wo_grid") - layer("base_metal_addition"))
    s2, s4 = layer("_SIS_junction"), layer("_SIS_junction_2")
    windows = list(s2.each())
    assert windows, f"{cell}: no junction drawn"
    n_sq = (
        2 if "Squid" in str(params.get("junction_type", "Quantcore Squid" if cell == "SquidTermination" else "")) else 1
    )
    for poly in windows:
        w = pya.Region(poly.bbox())
        outside = metal - w
        straight = ((w - s2).sized(5) & outside).merged()
        bent = ((w - s4).sized(5) & outside).merged()
        assert straight.count() >= n_sq, f"{cell}: straight finger(s) float at {poly.bbox().to_dtype(0.001)}"
        assert bent.count() >= 1, f"{cell}: bent finger floats at {poly.bbox().to_dtype(0.001)}"


@pytest.mark.parametrize("cell", ["SquidTermination", "LumpedJpa", "JtwpaChain"])
def test_sim_junction_type_draws_no_junction(cell):
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.layouts.registry import resolve_cell

    ly = pya.Layout()
    cls = resolve_cell(cell)
    c = cls.create(ly, junction_type="Sim")
    names = {ly.get_info(li).name for li in ly.layer_indexes() if not pya.Region(c.begin_shapes_rec(li)).is_empty()}
    assert not any(n.endswith("SIS_junction") or n.endswith("SIS_junction_2") for n in names)


def test_squid_termination_lom_equivalent_length():
    from quantcore_circuits.layouts.others.amplifiers import SquidTermination, cpw_inductance_per_m

    frag = _fragment("SquidTermination", junction_params=BIG_JJ)
    assert frag.port_nodes == {"a": "lead", "pump": "control:flux"}
    (line,) = frag.lines
    sq = SquidTermination.qcc_squid({"junction_params": BIG_JJ})
    assert sq["squid"] and sq["Ls0_nH"] == pytest.approx(0.2533, rel=0.02)  # two 2 × 2 µm PDK junctions
    extra = sq["Ls_nH"] * 1e-9 / cpw_inductance_per_m(10, 6) * 1e6
    assert line.length_um == pytest.approx(10 + 6 + extra, rel=1e-6) and line.through and line.term[1] == "short"
    biased = SquidTermination.qcc_squid({"junction_params": BIG_JJ, "flux_phi0": 1 / 3})
    assert biased["Ls_nH"] == pytest.approx(2 * sq["Ls0_nH"], rel=1e-6)  # 1 / |cos(π/3)|
    designed = _fragment("SquidTermination", junction={"Lj_nH": 0.0686, "Cj_fF": 1.0})
    assert designed.lines[0].length_um < line.length_um  # the design's junction wins over the drawn one


def test_lumped_jpa_lom_capacitive_and_inductive():
    cap = _fragment("LumpedJpa", junction_params=BIG_JJ)
    types = {e.name: e.type for e in cap.elements}
    assert types == {"C_X": "C", "J_X": "JJ"} and cap.port_nodes["signal"] == "island"
    c_sh = next(e for e in cap.elements if e.name == "C_X").value["estimate"]
    assert 250 < c_sh < 800  # 20 fingers / side, 100 µm, 4/4 µm IDC (Igreja–Dias): ≈ 0.4 pF
    ind = _fragment("LumpedJpa", coupling="inductive")
    assert ind.port_nodes["signal"] == "tap"
    jj = next(e for e in ind.elements if e.type == "JJ")
    assert set(jj.nodes) == {"island", "tap"}
    ltap = next(e for e in ind.elements if e.name == "Ltap_X").value
    assert 0.02 < ltap["L_nH"] < 0.3 and ltap["L_k_nH"] > 0
    squid = _fragment("LumpedJpa", junction_type="Quantcore Squid", flux_line=True, flux_phi0=0.2)
    j = next(e for e in squid.elements if e.name == "J_X")
    assert j.type == "SQUID" and j.value["bias_phi0"] == 0.2 and squid.port_nodes["flux"] == "control:flux"
    assert j.value["Lj_nH"] == pytest.approx(j.value["Lj0_nH"] / math.cos(math.pi * 0.2), rel=1e-5)


def test_jtwpa_chain_lom_counts():
    frag = _fragment("JtwpaChain", cells=12, resonator_every=4, resonator_offset=2, junction_params=BIG_JJ)
    jjs = [e for e in frag.elements if e.type == "JJ"]
    assert len(jjs) == 12 and frag.port_nodes == {"a": "n0", "b": "n12"}
    assert sorted(n for n in frag.nodes if n.startswith("r")) == ["r10", "r2", "r6"]
    assert {e.type for e in frag.elements} == {"C", "JJ", "L"}
    lj = jjs[0].value["Lj_nH"]
    assert lj == pytest.approx(0.5066, rel=0.02)  # 2 × 2 µm PDK junction: I_c ≈ 0.65 µA
    cg = {e.name: e.value["estimate"] for e in frag.elements if e.name.startswith("Cg_")}
    assert cg["Cg_X_0"] < cg["Cg_X_1"] and cg["Cg_X_2"] < cg["Cg_X_1"]  # half shunt at the end, loaded node


def test_ki_ladder_source_and_pdk_film():
    from quantcore_circuits.layouts.others.amplifiers import KiTwpaSerpentine

    src = KiTwpaSerpentine.qcc_ladder({}, sheet_pH_sq=20.0)
    assert src["L_k_pH"] == pytest.approx(20 * 1.5 / 0.58, rel=1e-9)
    assert src["L_cell_pH"] == pytest.approx(53.8, rel=0.06)  # twpa-sim v2 cell: 20 pH/□ × 1.5/0.58 × 1.04
    assert 15 < src["C_cell_fF"] < 35 and src["C_loaded_fF"] < src["C_cell_fF"]  # twpa-sim: 22.3 / 8.4 fF
    nb = KiTwpaSerpentine.qcc_ladder({})
    assert nb["sheet_pH_sq"] == pytest.approx(0.1158, rel=0.02) and nb["Z_cell_ohm"] < 15 < 40 < src["Z_cell_ohm"]
    full = KiTwpaSerpentine.qcc_ladder({"rows": 16, "periods_per_row": 55})
    assert full["cells"] == 49950  # twpa-sim reference size
    frag = _fragment("KiTwpaSerpentine")
    assert frag.port_nodes == {"a": "line", "b": "line"} and frag.lines[0].length_um == pytest.approx(
        KiTwpaSerpentine.qcc_ladder({})["length_um"]
    )


def test_jtwpa_models_reproduce_the_qpdk_trend():
    lj, cj, cg = amp.lj_from_ic(3.4e-6), 55e-15, 45e-15
    res = (30e-15, 170e-12, 2.8153e-12)
    fp, fs = 7.12e9, np.array([5e9])
    ip, xi = 3.7e-6 / 2, 1 / (2 * 3.4e-6**2)
    out = {}
    for name, every, r, cgl in (("uniform", 0, None, None), ("loaded", 4, res, 15e-15)):
        m = every or 1

        def q(f, every=every, r=r, cgl=cgl, m=m):
            return amp.bloch(amp.jtwpa_unit(np.atleast_1d(f), lj, cj, cg, every, r, cgl)).imag / m

        kp = float(q(fp)[0])
        mismatch = float((2 * kp - q(fs) - q(2 * fp - fs))[0])
        gain, _, _ = amp.cme_gain(q(fs), q(2 * fp - fs), kp, 2047, ip, xi=xi)
        out[name] = (mismatch, float(amp.db(gain)[0]))
    # QPDK notebook: loaded cold mismatch − Kerr = +0.0013 rad/junction at 5 GHz, i.e. cold ≈ 0.0049; ≈ 25 vs 5 dB
    assert out["loaded"][0] == pytest.approx(0.0049, abs=4e-4)
    assert out["loaded"][1] > 18 and out["uniform"][1] < 10


def test_cpw_jpa_resonance_and_paramp_laws():
    f = np.linspace(5.5e9, 7.0e9, 150001)
    z0, vp = 55.1, 1.26e8
    f0, k0 = amp.resonance(f, amp.cpw_jpa_s11(f, 28e-15, z0, vp, 4680, amp.lj_from_ic(4.8e-6)))
    f1, _ = amp.resonance(f, amp.cpw_jpa_s11(f, 28e-15, z0, vp, 4680, amp.squid_ls(amp.lj_from_ic(4.8e-6), 0.3)))
    assert 6.0e9 < f0 < 6.5e9 and 150 < f0 / k0 < 350 and f1 < f0  # QPDK: 6.07 GHz, Q_ext ≈ 290 on its stack
    lp = vp / (4 * 4680e-6)  # bare λ/4: the SQUID pulls f down by about L_s / (L' ℓ)
    assert f0 < lp
    assert amp.db(amp.flux_pumped_gain(0.0, 20e6, 0.9))[()] == pytest.approx(amp.db(amp.flux_pumped_peak_gain(0.9)))
    assert amp.flux_pumped_gain(5e6, 20e6, 0.9) < amp.flux_pumped_gain(0.0, 20e6, 0.9)
    assert math.isclose(float(amp.squid_ls(1.0, 0.25)), math.sqrt(2), rel_tol=1e-9)


def test_kerr_pump_roots_and_bistability():
    kappa = 2 * np.pi * 20e6
    kerr = -2 * np.pi * 0.5e6
    delta = -2.5 * kappa  # pump below resonance (K < 0): bistable at high power
    roots = amp.kerr_pump_photons(delta, kerr, kappa, 0.0, 1e14)
    assert roots and all(n >= 0 for n, _ in roots)
    low = amp.kerr_pump_photons(delta, kerr, kappa, 0.0, 1e9)
    assert len(low) == 1 and low[0][1]  # weak pump: one stable state


@pytest.mark.parametrize("rows", [2, 3, 4])
def test_ki_serpentine_keepout_covers_its_etch(rows):
    """The 3/0 hook's filled boxes (rows, turns, launches) cover every etched shape of the serpentine."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.layouts.others.amplifiers import KiTwpaSerpentine

    params = {"rows": rows, "periods_per_row": 2}
    ly = pya.Layout()
    ly.dbu = 0.001
    c = KiTwpaSerpentine.create(ly, **params)
    li = next(i for i in ly.layer_indexes() if ly.get_info(i).name.endswith("base_metal_gap_wo_grid"))
    etch = pya.Region(c.begin_shapes_rec(li))
    boxes = KiTwpaSerpentine.qcc_keepout(params)
    assert len(boxes) == rows + (rows - 1) + 2
    cover = pya.Region()
    for b in boxes:
        cover.insert(b.to_itype(ly.dbu))
    assert (etch - cover).is_empty()


def test_unwrap_bloch_recovers_a_long_unit_phase():
    """A 54-cell LC unit (KI-TWPA supercell scale) passes the zone edge: the unfolded phase is 54 × the cell phase."""
    f = np.linspace(0.1e9, 12e9, 3000)
    cell = amp.ki_cell(f, 53.8e-12, 22.3e-15)
    unit = amp.power(cell, 54)
    true = 54 * amp.bloch(cell).imag
    got = amp.unwrap_bloch(amp.bloch(unit).imag)
    assert np.max(np.abs(got - true)) < 1e-3 and true[-1] > np.pi  # past the zone edge (arccosh is soft near π)


def test_jtwpa_resonator_leads_join_their_islands():
    """Fab mask (negative: drawn = etched): each loading resonator's coupling bus is metal connected to its chain
    island through the trench, and neither touches the ground."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.layouts.others.amplifiers import JtwpaChain
    from quantcore_circuits.layouts.registry import resolve_cell

    params = dict(cells=12, resonator_every=4, resonator_offset=2, junction_type="Sim")
    lay = JtwpaChain.qcc_layout(params)
    assert len(lay["resonators"]) == 3
    ly = pya.Layout()
    cell = resolve_cell("JtwpaChain").create(ly, **params)
    li = ly.layer(pya.LayerInfo(130, 1))
    etch = pya.Region(cell.begin_shapes_rec(li))
    box = etch.bbox().enlarged(200, 200)
    metal = (pya.Region(box) - etch).merged()
    dbu = ly.dbu
    half, wall = lay["trench"], 10.0
    ground = metal.interacting(pya.Region(pya.Box(box.p1, pya.Point(box.p1.x + 100, box.p1.y + 100))))
    for k, side in lay["resonators"].items():
        xa, xb = lay["islands"][k]
        xc = (xa + xb) / 2
        probe = lambda y: pya.Region(pya.DBox(xc - 0.5, y - 0.5, xc + 0.5, y + 0.5).to_itype(dbu))  # noqa: E731
        island = metal.interacting(probe(0.0))
        bus = metal.interacting(probe(side * (half + wall + 10 + 2)))  # inside the coupling bus
        assert island.count() == 1 and bus.count() == 1
        assert not (island & bus).is_empty(), f"resonator at node {k}: the bus is cut off from its island"
        assert (island & ground).is_empty(), "the island touches the ground"
