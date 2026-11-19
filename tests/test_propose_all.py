"""Propose for every qubit class with a LOM model (``codesign`` generic surrogate, ``optimise`` knob paths,
``loop.feedback`` notes, the estimates cache, deferred dashboard writes).

One small design holds a grounded Xmon (λ/2 open hanger), a floating Metal TransmonPocket (λ/4 hanger), a floating
KQC DoublePads (λ/4 free end, shorted), a legacy TwoPadTransmon read out through a PadCoupler (λ/2 free end, open)
and a gatemon through its GatemonCoupler (the coupler's line + a route, λ/4). Everything runs on the layout's own
LOM estimates (no FEM, no estimators): fast."""

from __future__ import annotations

import copy
import json
import math

import numpy as np
import pytest

from tests.conftest import EXAMPLE

FL_Y, ROW_Y = 2000.0, 3900.0
J = {"Lj_nH": 12.0, "Cj_fF": 2.0}


def _mini() -> dict:
    """Five qubit classes, five readout kinds (readout ports turned to face down, towards the feedline)."""
    xs = [1500.0, 3400.0, 5300.0, 7200.0, 9100.0]
    d = {
        "schema": "qcc/0.1",
        "name": "propose_all_mini",
        "pdk": "quantcore_nb_sapphire_v1",
        "chip": {"box": [0, 0, 10500, 6000], "params": {"with_grid": False, "name_chip": "PALL"}},
        "instances": {
            "PAD_W": {"cell": "BondPad", "place": {"at": [600, FL_Y], "rot": 270}},
            "PAD_E": {"cell": "BondPad", "place": {"at": [9900, FL_Y], "rot": 90}},
            "QA": {"cell": "Xmon",
                   "params": {"cross_length": 300, "claws": ["n"], "junction_type": "Quantcore Junction"},
                   "place": {"at": [xs[0], ROW_Y], "rot": 180}, "junction": dict(J)},
            "QB": {"cell": "metal:TransmonPocket",
                   "params": {"connection_pads": {"readout": {"loc_W": 1, "loc_H": 1}},
                              "junction_type": "Quantcore Junction"},
                   "place": {"at": [xs[1], ROW_Y], "rot": 270}, "junction": {"Lj_nH": 15.0, "Cj_fF": 2.0}},
            "QC": {"cell": "DoublePads", "params": {"junction_type": "Quantcore Junction"},
                   "place": {"at": [xs[2], ROW_Y], "rot": 180}, "junction": dict(J)},
            "QD": {"cell": "TwoPadTransmon", "params": {"pad_thickness": 150, "pad_height": 400, "gap": 30,
                                                       "lead_length": 10, "pocket_margin": 40},
                   "place": {"at": [xs[3], ROW_Y], "rot": 270}, "junction": {"Lj_nH": 9.0, "Cj_fF": 2.0}},
            "CD": {"cell": "PadCoupler", "params": {"pad_thickness": 60, "pad_height": 200, "gap": 10,
                                                   "lead_length": 10, "pocket_margin": 40},
                   "place": {"snap": "CD.left", "to": "QD.right"}},
            "KE": {"cell": "GatemonCoupler", "params": {"length": 600.0, "qubit_side": "bottom"},
                   "place": {"at": [xs[4], ROW_Y], "rot": 270}},
            "QE": {"cell": "Gatemon", "params": {}, "place": {"snap": "QE.readout", "to": "KE.qubit"},
                   "junction": {"Lj_nH": 13.0, "Cj_fF": 2.0}},
        },
        "routes": {
            "FL": {"from": "PAD_W.a", "to": "PAD_E.a", "type": "cpw"},
            "RA": {"from": "QA.claw_n", "to": {"hanger": "FL", "s": xs[0] - 450, "length": 300, "side": "left",
                                                "end": "open"}, "type": "meander", "length": 8400},
            "RB": {"from": "QB.readout", "to": {"hanger": "FL", "s": xs[1] - 450, "length": 300, "side": "left"},
                   "type": "meander", "length": 4300},
            "RC": {"from": "QC.cplr", "to": {"at": [xs[2], 2700.0], "dir": 90, "term": 0}, "type": "meander",
                   "length": 4400},
            "RD": {"from": "CD.right", "to": {"at": [xs[3], 2700.0], "dir": 90, "term": 6}, "type": "meander",
                   "length": 8600},
            "RE": {"from": "KE.o2", "to": {"hanger": "FL", "s": xs[4] - 450, "length": 300, "side": "left",
                                            "end": "open"}, "type": "meander", "length": 3700},
        },
    }
    return d


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    path = tmp_path_factory.mktemp("propose_all") / "mini.json"
    path.write_text(json.dumps(_mini(), indent=1), encoding="utf-8")
    return path


def _filled(design):
    from quantcore_circuits.circuit.derive import circuit_from_design
    from quantcore_circuits.circuit.fill import fill

    return fill(circuit_from_design(design, "chip"), design, None, synthesis={})


@pytest.fixture(scope="module")
def filled(mini):
    return _filled(mini)


@pytest.fixture(scope="module")
def surrogates(filled):
    from quantcore_circuits import codesign as cd

    notes: list[str] = []
    out = {s.qubit: s for s in cd.surrogates_from_fill(filled, notes)}
    assert not notes, notes
    return out


# ---- knob paths ---------------------------------------------------------------------------------------------------
def test_knob_paths_lists_nested_options_and_units(mini):
    from quantcore_circuits.design import load_design
    from quantcore_circuits.optimise import get_knob, knob_number, knob_path, set_knob

    d = load_design(mini)
    assert knob_number("30um") == 30.0 and knob_number("0.1mm") == pytest.approx(100.0) and knob_number([1, 3]) == 2.0
    # a Metal option left at its default reads as µm; setting it creates it
    assert get_knob(d, "QB.pad_width") == 455.0
    assert get_knob(d, "QB.connection_pads.readout.pad_width") == 125.0  # from _default_connection_pads
    d2 = set_knob(d, "QB.connection_pads.readout.pad_width", 140.0)
    assert d2.instances["QB"].params["connection_pads"]["readout"] == {"loc_W": 1, "loc_H": 1, "pad_width": 140.0}
    # list parameters: one element, or all scaled together (the knob is their mean); unset lists start from default
    assert get_knob(d, "QC.coupler_extent.0") == 150
    assert set_knob(d, "QC.coupler_extent.0", 180.0).instances["QC"].params["coupler_extent"] == [180.0, 20]
    assert get_knob(d, "QE.island_size.*") == 150.0
    assert set_knob(d, "QE.island_size.*", 165.0).instances["QE"].params["island_size"] == [165.0, 165.0]
    # a unit string keeps its unit; instance fields and route fields as before
    d3 = set_knob(set_knob(d, "QB.pad_width", 400.0), "QB.pad_width", 420.0)
    assert get_knob(d3, "QB.pad_width") == 420.0
    d4 = load_design({**_mini(), "instances": {**_mini()["instances"],
                                               "QB": {**_mini()["instances"]["QB"],
                                                      "params": {"pad_width": "0.45mm"}}}})
    assert set_knob(d4, "QB.pad_width", 500.0).instances["QB"].params["pad_width"] == "0.5mm"
    assert get_knob(d, "QA.junction.Lj_nH") == 12.0 and get_knob(d, "RB.length") == 4300
    assert knob_path(d, "QC.coupler_extent.0") == ("instances", "QC", "params", "coupler_extent", 0)
    assert knob_path(d, "QA.junction.Lj_nH") == ("instances", "QA", "junction", "Lj_nH")
    with pytest.raises(KeyError):
        get_knob(d, "QB.connection_pads.missing_pad.pad_width")


def test_json_text_options_are_edited_in_place():
    """A wrapper cell's ``options`` stored as JSON text (what the plugin's parameter table writes) stays JSON text."""
    from quantcore_circuits.design import load_design
    from quantcore_circuits.optimise import get_knob, set_knob

    d = load_design({"schema": "qcc/0.1", "name": "o", "instances": {
        "Q": {"cell": "metal:TransmonCross", "params": {"options": json.dumps({"cross_length": "210um"})},
              "place": {"at": [0, 0]}}}})
    assert get_knob(d, "Q.cross_length") == 210.0
    d2 = set_knob(d, "Q.cross_length", 230.0)
    assert json.loads(d2.instances["Q"].params["options"]) == {"cross_length": "230um"}


# ---- the generic surrogate ------------------------------------------------------------------------------------------
def test_every_pair_gets_class_knobs(filled, surrogates):
    assert {(p.qubit, p.resonator, p.kind) for p in filled.pairs} == {
        ("QA", "RA", "lambda/2"), ("QB", "RB", "lambda/4"), ("QC", "RC", "lambda/4"), ("QD", "RD", "lambda/2"),
        ("QE", "KE", "lambda/4")}
    want = {
        "QA": ["QA.cross_length", "QA.claw_length", "QA.junction.Lj_nH", "RA.length"],
        "QB": ["QB.pad_width", "QB.connection_pads.readout.pad_width", "QB.junction.Lj_nH", "RB.length"],
        "QC": ["QC.island_island_gap", "QC.coupler_extent.0", "QC.junction.Lj_nH", "RC.length"],
        "QD": ["QD.pad_height", "CD.pad_height", "QD.junction.Lj_nH", "RD.length"],  # C_g: the coupler cell
        "QE": ["QE.island_size.*", "KE.coupling_capacitance", "QE.junction.Lj_nH", "RE.length"],  # line + route
    }
    for q, knobs in want.items():
        s = surrogates[q]
        assert list(s.knobs) == knobs, (q, list(s.knobs))
        assert s.kind == {"QA": "lambda/2", "QD": "lambda/2"}.get(q, "lambda/4")
    assert surrogates["QE"].extra_length_um == pytest.approx(600.0)  # the coupler cell's own line
    assert surrogates["QC"].c_island.p < 0  # a wider island gap lowers C_Σ
    assert surrogates["QB"].cg.p > 0 and surrogates["QE"].cg.p == pytest.approx(1.0)  # the nominal C itself


def test_surrogate_starts_on_the_pair(filled, surrogates):
    """At the current knobs the surrogate reproduces the filled pair (λ/2 lines included): no hidden offset."""
    from quantcore_circuits import codesign as cd
    from quantcore_circuits.circuit.fill import two_node_model

    for p in filled.pairs:
        s = surrogates[p.qubit]
        el = s.elements(s.knobs)
        assert el["C_island_fF"] == pytest.approx(p.c_island_fF - p.cj_fF, rel=1e-9)
        assert el["Cg_fF"] == pytest.approx(p.cg_fF, rel=1e-9) and el["Lj_nH"] == p.lj_nH
        pred = s.predict(s.knobs)
        tn = two_node_model(p)
        d = cd.dressed_levels(tn["EJ_GHz"], tn["EC_GHz"], tn["f_r_loaded_GHz"], tn["g_n_MHz"])
        assert pred[f"{p.resonator}.f_GHz"] == pytest.approx(d["f_r_GHz"], rel=1e-6), p.qubit
        assert pred[f"{p.qubit}.f_q_GHz"] == pytest.approx(d["f_q_GHz"], rel=1e-6), p.qubit


def test_numpy_dressed_levels_match_qutip():
    from quantcore_circuits import codesign as cd
    from quantcore_circuits.circuit import hamiltonian as H

    ref = H.dressed(H.TransmonResonator(15.0, 0.25, 7.1, 140.0, nq=5, nr=5))
    mine = cd.dressed_levels(15.0, 0.25, 7.1, 140.0)
    for k in ("f_q_GHz", "f_r_GHz", "alpha_MHz", "chi_MHz", "g_MHz"):
        assert mine[k] == pytest.approx(ref[k], abs=1e-9), k


def _targets(surrogates, shift=True) -> dict:
    out = {}
    for s in surrogates.values():
        p = s.predict(s.knobs)
        out[f"{s.qubit}.f_q_GHz"] = {"value": p[f"{s.qubit}.f_q_GHz"] - 0.12, "tol": 0.02}
        out[f"{s.qubit}.alpha_MHz"] = {"value": p[f"{s.qubit}.alpha_MHz"] * 0.92, "tol": 10.0}
        out[f"{s.resonator}.f_GHz"] = {"value": p[f"{s.resonator}.f_GHz"] + 0.06, "tol": 0.01}
        out[f"{s.resonator}.g_MHz"] = {"value": p[f"{s.resonator}.g_MHz"] * 1.15, "tol": 10.0}
    return out


@pytest.fixture(scope="module")
def proposal(filled, surrogates):
    from quantcore_circuits import codesign as cd

    fresh = cd.surrogates_from_fill(filled)  # propose refines a surrogate's exponents: not the shared ones
    return cd.propose_all(fresh, _targets(surrogates), {**filled.model.knobs}), _targets(surrogates)


def test_proposal_reaches_the_targets_on_the_lom(proposal):
    prop, _ = proposal
    assert prop.objective < 0.5, prop.residuals
    assert all(abs(r) < 0.5 for r in prop.residuals.values()), prop.residuals
    assert len(prop.knobs) == 20 and not prop.notes


def test_applied_revision_moves_toward_the_targets(mini, filled, proposal, tmp_path):
    """Apply → re-derive the circuit → every pair is closer to its targets (the LOM rounds its estimates, so the
    rebuilt pair can sit a little off the proposal)."""
    from quantcore_circuits import codesign as cd

    prop, targets = proposal
    rev = tmp_path / "rev1.json"
    rev.write_text(json.dumps(cd.apply(mini, prop.knobs).to_json_dict()), encoding="utf-8")
    after = _filled(rev)

    def measured(f):
        out = {}
        for p in f.pairs:
            from quantcore_circuits.circuit.fill import two_node_model

            tn = two_node_model(p)
            d = cd.dressed_levels(tn["EJ_GHz"], tn["EC_GHz"], tn["f_r_loaded_GHz"], tn["g_n_MHz"])
            out |= {f"{p.qubit}.f_q_GHz": d["f_q_GHz"], f"{p.qubit}.alpha_MHz": d["alpha_MHz"],
                    f"{p.resonator}.f_GHz": d["f_r_GHz"], f"{p.resonator}.g_MHz": d["g_MHz"]}
        return out

    m0, m1 = measured(filled), measured(after)
    for k, t in targets.items():
        r0, r1 = (m0[k] - t["value"]) / t["tol"], (m1[k] - t["value"]) / t["tol"]
        assert abs(r1) < abs(r0), (k, r0, r1)
        assert abs(r1) < 2.5, (k, r0, r1)


def test_knobs_without_a_target_stay(filled):
    """Only f_q asked for: L_J moves, the geometry and the line do not."""
    from quantcore_circuits import codesign as cd

    s = cd.surrogate_from_fill(filled, next(i for i, p in enumerate(filled.pairs) if p.qubit == "QB"))
    p0 = s.predict(s.knobs)
    prop = cd.propose(s, {"QB.f_q_GHz": {"value": p0["QB.f_q_GHz"] - 0.1, "tol": 0.02}}, refine=0)
    changed = [k for k, v in prop.knobs.items() if v != prop.start_knobs[k]]
    assert changed == ["QB.junction.Lj_nH"] and abs(prop.residuals["QB.f_q_GHz"]) < 0.1


def test_xmon_matches_the_prior_surrogate(example_path):
    """The generic surrogate of an Xmon is the old cross / claw one (calibration exponents 1, 1, 0.8)."""
    from quantcore_circuits import codesign as cd

    f = _filled(example_path)
    new, old = cd.surrogate_from_fill(f, 0), cd._xmon_surrogate(f, 0)
    assert list(new.knobs) == list(old.knobs) == ["Q1.cross_length", "Q1.claw_length", "Q1.junction.Lj_nH",
                                                  "R1.length"]
    assert (new.c_island.p, new.cg.p, new.c_coupler.p) == (1.0, 1.0, 0.8)
    assert not new.c_island.others and not new.cg.others and not new.c_coupler.others
    for scale in (0.7, 1.0, 1.4):
        k = {n: v * scale for n, v in old.knobs.items()}
        a, b = new.predict(k), old.predict(k)
        assert all(a[q] == pytest.approx(b[q], rel=1e-9) for q in a)
    targets = {"Q1.f_q_GHz": {"value": 5.1, "tol": 0.02}, "Q1.alpha_MHz": {"value": -220, "tol": 10},
               "R1.f_GHz": {"value": 7.2, "tol": 0.01}, "R1.g_MHz": {"value": 90, "tol": 10}}
    bounds = {**f.model.knobs, "Q1.claw_length": (40.0, 220.0)}
    assert cd.propose(new, targets, bounds).knobs == cd.propose(old, targets, bounds).knobs


def test_notes_say_what_is_not_tuned(example_dict, tmp_path):
    """A drawn junction (no design L_J), a cpw readout without a length and a qubit without a readout: notes, no
    failure."""
    from quantcore_circuits import codesign as cd

    d = example_dict
    d["instances"]["Q1"].pop("junction")
    d["routes"]["R1"]["type"] = "cpw"  # its length is the drawn path's: not a knob
    d["routes"]["R1"].pop("length")
    d["instances"]["Q2"] = {"cell": "Xmon", "params": {"claws": ["n"], "junction_type": "Quantcore Junction"},
                            "place": {"at": [5000, 2200]}, "junction": {"Lj_nH": 12.0}}
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    f = _filled(path)
    notes = cd.unpaired_notes(f)
    s = cd.surrogates_from_fill(f, notes)[0]
    assert s.lj_knob is None and s.length_knob is None and list(s.knobs) == ["Q1.cross_length", "Q1.claw_length"]
    text = " ".join(notes + s.notes)
    assert "drawn junction" in text and "no length knob" in text and "Q2: no readout" in text


# ---- speed: the estimates cache, deferred dashboard writes, plans ---------------------------------------------------
def test_estimates_cache_reuses_and_invalidates(filled, tmp_path):
    from quantcore_circuits import loop

    calls = []

    def fake(f):
        calls.append(1)
        return {"x": {f"{p.qubit}.f_q_GHz": p.lj_nH for p in f.pairs}}

    a = loop._solve_cached(filled, tmp_path, fake)
    b = loop._solve_cached(filled, tmp_path, fake)
    assert a == b and len(calls) == 1
    other = copy.copy(filled)
    other.pairs = [copy.copy(p) for p in filled.pairs]
    other.pairs[0].lj_nH += 0.5  # what an estimator reads changed: solved again
    loop._solve_cached(other, tmp_path, fake)
    assert len(calls) == 2
    loop._solve_cached(filled, None, fake)  # no out_dir: no cache
    assert len(calls) == 3


def test_deferred_run_writes_once_per_step(tmp_path):
    from quantcore_circuits.track import Run

    run = Run(EXAMPLE, tmp_path / "run", reset=True)
    writes = []
    real = run.save

    def counting(force=False):
        writes.append(force)
        return real(force)

    run.save = counting
    try:
        with run.deferred():
            run.start("extract")
            for i in range(20):
                run.log(f"note {i}")
                run.plot({"id": f"p{i}", "title": "t", "tab": "plots", "kind": "xy", "series": []})
            run.done("extract", "ok")
        assert sum(1 for w in writes if w) == 2  # start + done write through
        st = json.loads(run.path.read_text(encoding="utf-8"))
        assert len(st["plots"]) == 20 and st["log"][-1]["msg"].startswith("Extract")
    finally:
        del run.save


def test_apply_plans_only_the_changed_instances(mini, monkeypatch):
    """Ports of the instances a knob changes (with what is snapped to them) are planned; the rest is not."""
    from quantcore_circuits import codesign as cd

    seen = []
    real = cd._ports_without_routes

    def spy(design, only=None):
        seen.append(set(only or ()))
        return real(design, only)

    monkeypatch.setattr(cd, "_ports_without_routes", spy)
    cd.apply(mini, {"QD.pad_height": 420.0, "RB.length": 4400.0, "QA.junction.Lj_nH": 11.0})
    assert seen == [{"QD"}]
    from quantcore_circuits.design import load_design

    assert cd._snap_closure(load_design(mini), {"QD"}) == {"QD", "CD"}  # the coupler snapped to it moves with it
    seen.clear()
    cd.apply(mini, {"RB.length": 4400.0})  # no geometry parameter: nothing planned
    assert seen == []


def test_lambda_half_forward_doubles_the_line():
    from quantcore_circuits import codesign as cd

    el = {"C_island_fF": 70.0, "Cg_fF": 1e-6, "C_coupler_fF": 1e-6, "Lj_nH": 12.0, "length_um": 8400.0}
    quarter = cd.forward(el, 2.0, 10, 6, "quantcore_nb_sapphire_v1")["R.f_GHz"]
    half = cd.forward(el, 2.0, 10, 6, "quantcore_nb_sapphire_v1", kind="lambda/2")["R.f_GHz"]
    assert half == pytest.approx(2 * quarter, rel=1e-4) and math.isfinite(half)
    assert np.isfinite(cd.forward(el, 2.0, 10, 6, "quantcore_nb_sapphire_v1", kind="lambda/2")["Q.f_q_GHz"])
