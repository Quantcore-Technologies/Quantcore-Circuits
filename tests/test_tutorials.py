"""The tutorials in ``examples/tutorials/`` stay teachable and runnable.

* **Fast** (no notebook execution): every tutorial (saved with its outputs) keeps ``RUN_FEM = False`` (no AEDT
  run by accident), honours ``QCC_LIVE`` through ``T.live_mode()``, and walks through the educative template (PDK →
  pads at the edge → components → routes → DRC → netlist / LOM → FEM send / bring back → iterate → fab export →
  snapshots → summary). The helpers in ``_tut.py`` work on a tiny design, and the kept chip-12 FEM results (when
  present) fill the LOM by net name.
* **Slow**: tutorials 0 and 1 run as scripts (code cells in one process, ``QCC_LIVE=0``, no kernel) and their key
  results hold (DRC clean, pads at the pad rule, the FEM bring-back tables when results are kept). Every notebook under
  ``examples/`` is also executed by ``tests/test_examples.py -m slow``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TUT = ROOT / "examples" / "tutorials"
NOTEBOOKS = sorted(TUT.glob("[0-9][0-9]_*.ipynb"))
_JUNCTION_NOTE = re.compile(r"^\S+: junction L ")  # sim_tools.builder.lumped_junction: where a port's L / C come from
EXPECTED = [
    "00_quickstart_klive_and_pdk",
    "01_chip12_coupled_chip",
    "02_ibm_bowtie_5q",
    "03_surface17",
    "04_two_qubit_feedback_loop",
]

# the template steps (the educative notebook): a phrase each tutorial's code must use
TEMPLATE_CALLS = {
    "PDK facts": ("get_pdk",),
    "live / headless": ("T.live_mode()", "live=LIVE"),
    "pads at the pad rule": ('edge="auto"', "pads_to_edge("),
    "trilayer junctions": ("trilayer_junction(", "L.lj_for_rn(", "junction="),
    "DRC": ("T.drc(",),
    "netlist / LOM": ("d.lom(", "lom_from_design("),
    "LOM simulation": ("simulate_groups(", "simulate_lom(", "simulate("),
    "FEM send": ("T.send(", "export_sims(", "export_job("),
    "FEM flag + bring back": ("RUN_FEM = False",),
    "solve / load": ("T.solve_or_load(",),
    "iterate before/after": ("T.before_after_md(",),
    "fab export": ("export_fab(",),
    "snapshots": ("T.snap(",),
}


def _nb(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _code(nb: dict) -> str:
    return "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")


def test_all_tutorials_exist():
    assert [p.stem for p in NOTEBOOKS] == EXPECTED
    assert (TUT / "README.md").exists() and (TUT / "_tut.py").exists()


# (test_tutorial_is_saved_clean dropped, 2026-11-18: the tutorials are saved WITH their outputs, so they read
# with results on GitHub / in Jupyter before anyone runs them)


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_tutorial_follows_the_template(path):
    code = _code(_nb(path))
    missing = [step for step, phrases in TEMPLATE_CALLS.items() if not any(p in code for p in phrases)]
    assert not missing, f"{path.name}: template steps without their call: {missing}"
    assert not re.search(r"^RUN_FEM\s*=\s*True", code, re.M), f"{path.name}: RUN_FEM must default to False"
    assert "run_pyepr_t1_estimate" not in code, f"{path.name}: KQC's pyEPR script quits a running AEDT"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_tutorial_markdown_explains_each_step(path):
    """Many small steps, each explained: more Markdown than a design notebook's five cells, a summary at the end."""
    nb = _nb(path)
    md = [("".join(c["source"])) for c in nb["cells"] if c["cell_type"] == "markdown"]
    assert len(md) >= 12, f"{path.name}: only {len(md)} Markdown cells"
    assert "Summary" in md[-1], f"{path.name}: the last cell should be the summary"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_tutorial_says_what_is_simulated(path):
    """Phase C: one cell near the top names the part of the chip that is rendered and simulated (``SIM_SUBSET``), next
    to the FEM switches."""
    nb = _nb(path)
    code_cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    top = next((i for i, c in enumerate(code_cells) if re.search(r"^SIM_SUBSET\s*=", c, re.M)), None)
    assert top is not None and top <= 2, f"{path.name}: no SIM_SUBSET cell near the top"
    for switch in ("RUN_FEM", "FEM_FAST", "AEDT_MODE"):
        assert re.search(rf"^{switch}\s*=", code_cells[top], re.M), f"{path.name}: {switch} is not next to SIM_SUBSET"
    assert "T.sim_subset(" in "".join(code_cells), f"{path.name}: SIM_SUBSET is not used"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_tutorial_has_two_fem_stages(path):
    """Decision, 2026-11-14: stage 1 is the subset FEM with its check (``T.subset_check``: convergence, raw FEM values,
    filled C vs estimates); stage 2 fills those values into the whole netlist and runs the LOM on it. The whole-chip
    FEM is an opt-in switch (``FEM_WHOLE = False``), next to ``RESOLVE`` / ``RUN_FEM``."""
    nb = _nb(path)
    code = _code(nb)
    md = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown").lower()
    assert "T.subset_check(" in code, f"{path.name}: no subset check"
    assert "subset" in md and "whole lom" in md, f"{path.name}: the two FEM stages are not named"
    assert re.search(r"^FEM_WHOLE\s*=\s*False", code, re.M), f"{path.name}: the whole-chip FEM is not opt-in"
    assert re.search(r"^RESOLVE\s*=", code, re.M) and "force=RESOLVE" in code, f"{path.name}: no RESOLVE switch"
    assert "feedback on the subset only" not in md, f"{path.name}: feedback from a subset"


def test_bowtie_and_chip12_fill_the_whole_netlist_and_feed_back():
    """02 and 01: stage 2 fills the stage-1 subset jobs (or, with ``FEM_WHOLE``, the whole-chip ``chip`` jobs) into the
    whole netlist, runs the LOM on it and feeds back on every component → revision, DRC, fab."""
    for name in ("02_ibm_bowtie_5q", "01_chip12_coupled_chip"):
        code = _code(_nb(TUT / f"{name}.ipynb"))
        assert 'WHOLE_ANALYSES = ["q3d_cmatrix"]' in code and 'build_simulation(DESIGN, "chip", a)' in code, name
        assert "if FEM_WHOLE else {}" in code and "FILL_Q3D" in code, name
        assert "fill(d.lom().model, DESIGN, FILL_Q3D)" in code and "FEEDBACK" in code, name
        assert "export_fab(T.built(d_fb)" in code and "loop.analyse(DESIGN, " in code, name
    code02 = _code(_nb(TUT / "02_ibm_bowtie_5q.ipynb"))
    assert "for n in F_Q:" in code02 and "BUS_FB" in code02  # all five qubits / readouts and both buses


def test_surface17_fills_the_whole_netlist_and_renders_the_chip_on_request():
    code = _code(_nb(TUT / "03_surface17.ipynb"))
    assert "fill(d.lom().model, DESIGN, q3d)" in code
    assert 'T.render_or_load(DESIGN, "chip", "q3d_cmatrix", RUN_FEM and FEM_WHOLE' in code


def test_q1_r1_notebooks_start_aedt_only_with_run_fem():
    """``q1_r1_first_run`` (render, Q3D) and ``q1_r1_loop`` (run_job, the optimiser) start AEDT only with
    ``RUN_FEM = True``."""
    first = _code(_nb(ROOT / "examples" / "q1_r1_first_run.ipynb"))
    loop_ = _code(_nb(ROOT / "examples" / "q1_r1_loop.ipynb"))
    assert re.search(r"^RUN_FEM\s*=\s*False", first, re.M) and re.search(r"^RUN_FEM\s*=\s*False", loop_, re.M)
    assert "if RUN_FEM and find_ansys_executable():\n    r = hfss.render(DESIGN, \"chip\"" in first
    assert "run_job(job, aedt=AEDT_MODE) if RUN_FEM and HAVE_AEDT" in loop_ and "if RUN_FEM and HAVE_AEDT:" in loop_


@pytest.fixture()
def tut(monkeypatch):
    monkeypatch.setenv("QCC_LIVE", "0")
    monkeypatch.syspath_prepend(str(TUT))
    cwd = os.getcwd()
    import _tut  # pylint: disable=import-outside-toplevel

    yield _tut
    os.chdir(cwd)


def test_live_mode_is_headless_with_qcc_live_0(tut, capsys):
    assert tut.live_mode() is False
    assert "QCC_LIVE=0" in capsys.readouterr().out


def test_pdk_tables_carry_the_rules(tut):
    text = tut.pdk_md()
    for fact in ("sapphire", "100 µm", "40–50 kΩ", "6.73 nH", "3/0 keep-out", "cheese", "corner rounding"):
        assert fact in text, fact
    layers = tut.fab_layers_md()
    for row in ("| 1/0 |", "| 3/0 |", "| 50/0 |", "| 1000/0 |"):
        assert row in layers, row


def test_helpers_on_a_tiny_design(tut, tmp_path, monkeypatch):
    """Pad rule, DRC table, junction zoom, before/after table on a two-pad, one-qubit design."""
    from quantcore_circuits.designer import Designer  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.registry import trilayer_junction  # pylint: disable=import-outside-toplevel

    tut.setup("pytest")
    monkeypatch.setattr(tut, "IMG", tmp_path)
    d = Designer("pytest_tut_tiny", box=(0, 0, 7500, 7500), live=False, out=tmp_path / "tiny.oas")
    pw = d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270, edge="auto")
    pe = d.add("PAD_E", "BondPad", at=(6375, 3750), rot=90, edge="auto")
    fl = d.route("FL", pw.a, pe.a)
    params, junction = trilayer_junction("Xmon")
    q1 = d.add("Q1", "Xmon", at=(2975, 2100), cross_length=450, claws=["n"], junction=junction, **params)
    d.route("R1", q1.claw_n, fl.hanger(near=(3125, 3750), length=300, side="right"), meander=4000, r=50)
    rep = tut.drc(d)
    assert rep.ok
    assert "DRC clean" in tut.drc_md(rep)
    edges = tut.pad_edges_md(d)
    assert edges.count("| 100.0 |") == 2, edges  # the pad rule (100 µm since 2026-11-10)
    x0, y0, x1, y1 = tut.junction_box(d, "Q1")
    bx = tut.inst_box(d, "Q1")
    assert bx[0] <= x0 < x1 <= bx[2] and bx[1] <= y0 < y1 <= bx[3]
    png = tut.snap(d, "tiny", size=(200, 200), show=False)
    assert png.exists() and png.parent == tmp_path
    table = tut.before_after_md({"a": 1.0, "b": None}, {"a": 1.1, "b": 2.0})
    assert "+10.0 %" in table and "| `b` | – |" in table


def test_kept_chip12_fem_results_fill_the_lom(tut):
    """The solved chip-12 ``Q1_R1`` Q3D job kept with the tutorials replaces the capacitance estimates by net name."""
    keep = TUT / "fem" / "t01_chip12_Q1_R1_q3d_cmatrix"
    design = TUT / "designs" / "t01_chip12.json"
    if not (keep / "results" / "results.json").exists() or not design.exists():
        pytest.skip("chip-12 FEM results not kept (run tutorial 1 with RUN_FEM = True)")
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom import lom_from_design  # pylint: disable=import-outside-toplevel

    res = json.loads((keep / "results" / "results.json").read_text(encoding="utf-8"))
    assert res["cmatrix"]["labels"] == ["Q1.island", "Q1.a"]
    model = lom_from_design(design, ["Q1", "R1"]).model
    filled = fill(model, design, keep)
    fem = {r["branch"]: r for r in filled.branch_table() if r["extracted"] is not None}
    assert {"C_Q1", "Cg_Q1_a", "Cc_Q1_a"} <= set(fem), sorted(fem)
    for r in fem.values():  # FEM values replace the estimates (the claw C_g is ≈ 2× the estimate: see the tutorial)
        assert r["extracted"] > 0 and r["value"] == r["extracted"] and r["origin"] == "fem", r
    assert "<table" not in tut.cmatrix_md(keep) and "Q1.island" in tut.cmatrix_md(keep)


def test_kept_chip12_eigenmode_results_read_back(tut):
    """The chip-12 eigenmode groups sized for a workstation (2026-11-10): ``Q1_q`` (the qubit, its lines cut by the box
    and terminated in 50 Ω) and ``Q1_R1e`` (qubit + readout, 100 µm margin)."""
    kept = [TUT / "fem" / f"t01_chip12_{g}_eigenmode_epr" for g in ("Q1_q", "Q1_R1e")]
    kept = [k for k in kept if (k / "results" / "results.json").exists()]
    if not kept:
        pytest.skip("chip-12 eigenmode results not kept (run tutorial 1 with RUN_FEM = True)")
    for keep in kept:
        res = json.loads((keep / "results" / "results.json").read_text(encoding="utf-8"))
        assert res["eigenmodes"] and res["epr"]["junction_names"] == ["Q1.junction"]
        assert max(p[0] for p in res["epr"]["p_mj"]) > 0.9  # one mode is the qubit
        assert "| 1 |" in tut.eigen_md(keep)


# ---- the FEM round-trip helpers (no AEDT is ever started by these tests) ------------------------------------------
def _fake_job(root: Path, name: str, analysis: str, design_hash: str = "abc", settings=None) -> Path:
    job = root / name
    job.mkdir(parents=True)
    meta = {"simulation_name": name, "design_hash": design_hash, "group": "G", "analysis": analysis,
            "settings": settings or {"percent_error": 0.5}}
    (job / "job.json").write_text(json.dumps(meta), encoding="utf-8")
    return job


def test_solve_or_load_reuses_kept_results_and_honours_analysis_sets(tut, tmp_path, monkeypatch, capsys):
    """``RUN_FEM`` may be a set of analyses; kept results of the same job (design hash, group, analysis, settings)
    are not solved again; a changed design is reported. ``solve_job`` must not be reached in any of these cases."""
    import quantcore_circuits.sim_tools.hfss as hfss  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(tut, "FEM", tmp_path / "fem")
    monkeypatch.setattr(hfss, "solve_job", lambda *a, **k: pytest.fail("solve_job must not run"))
    job = _fake_job(tmp_path / "jobs", "t_G_q3d_cmatrix", "q3d_cmatrix")
    assert tut.solve_or_load(job, {"eigenmode_epr"}) is None  # not in the set: nothing solved, nothing kept
    keep = tmp_path / "fem" / job.name
    (keep / "results").mkdir(parents=True)
    (keep / "results" / "results.json").write_text("{}", encoding="utf-8")
    (keep / "job.json").write_text((job / "job.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert tut.kept_matches(job)
    assert tut.solve_or_load(job, True) == keep and "not solved again" in capsys.readouterr().out
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    (job / "job.json").write_text(json.dumps({**meta, "design_hash": "new"}), encoding="utf-8")
    assert not tut.kept_matches(job)
    assert tut.solve_or_load(job, False) == keep and "another revision" in capsys.readouterr().out


def test_epr_values_assign_modes_by_junction(tut, tmp_path):
    """The 2024 R1 eigenmode fixture (Q1 + R1): the qubit mode by its junction's participation, the resonator mode by
    the nearest guess; pyEPR's dressed values come back keyed like the targets."""
    import shutil  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.analysis.results import collect_results  # pylint: disable=import-outside-toplevel

    job = tmp_path / "eig"
    shutil.copytree(ROOT / "tests" / "data" / "aedt_2024r1" / "eigenmode_epr", job)
    collect_results(job)
    v = tut.epr_values(job, {"Q1": "R1"}, {"R1": 6.6})
    assert v["modes"] == {"Q1": 0, "R1": 1}
    assert v["Q1.f_q_GHz"] == pytest.approx(5.0036, abs=1e-3) and v["Q1.alpha_MHz"] == pytest.approx(-282.7, abs=0.1)
    assert v["R1.chi_MHz"] == pytest.approx(-0.677, abs=1e-3) and 0.1 < v["R1.kappa_MHz"] < 0.4


def test_chip12_qubit_group_ports_have_polygons(recwarn, monkeypatch):
    """Tutorial 1's qubit-only eigenmode group ``Q1_q``: with a 150 µm margin every 50 Ω termination (flux lines, the
    readout cut by the box via ``ports={"R1": "edge"}``) gets its port polygon; a 250 µm margin cuts R1 in its bend,
    which the box straightening (C6) repairs by moving the box edge; without it the builder reports the missing
    polygon (KQC only logs it)."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import build_simulation  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import builder  # pylint: disable=import-outside-toplevel

    path = TUT / "designs" / "t01_chip12.json"
    data = load_design(path).to_json_dict()
    if "Q1_q" not in data["sim_groups"]:
        pytest.skip("t01_chip12.json predates the Q1_q group (re-run tutorial 1)")
    assert data["sim_groups"]["Q1_q"]["margin_um"] == 150 and data["sim_groups"]["Q1_q"]["ports"] == {"R1": "edge"}
    good = build_simulation(path, "Q1_q", "eigenmode_epr")
    assert ("edge_lumped", "R1") in [(p.kind, p.name) for p in good.ports]
    # the only notes allowed: C6 nudging a box edge (here top +2 µm) so FLX_Q2 leaves the box on a straight at 90°, and
    # the junction's L / C source (``lumped_junction``: "Q1: junction L … nH, C … fF (design; …)")
    assert not [n for n in good.notes if not n.startswith("box edge(s) moved") and not _JUNCTION_NOTE.match(n)], \
        good.notes
    assert all("polygon" in d for d in good.simulation.get_port_data())
    data["sim_groups"]["Q1_q"]["margin_um"] = 250
    moved = build_simulation(load_design(data), "Q1_q", "eigenmode_epr")
    assert any(n.startswith("box edge(s) moved") and "R1" in n for n in moved.notes), moved.notes
    assert not [n for n in moved.notes if "no port polygon" in n], moved.notes
    assert all("polygon" in d for d in moved.simulation.get_port_data())
    monkeypatch.setattr(builder, "straighten_box", lambda result, box, *a, **k: (box, []))  # the box as asked
    bad = build_simulation(load_design(data), "Q1_q", "eigenmode_epr")
    assert any("no port polygon" in n and "(R1, edge_lumped)" in n for n in bad.notes), bad.notes
    assert any("no port polygon" in str(w.message) for w in recwarn)


# ---- tutorial 4: the two-qubit feedback loop ------------------------------------------------------------------------
T04 = TUT / "04_two_qubit_feedback_loop.ipynb"
T04_DESIGNS = sorted((TUT / "designs").glob("t04_two_qubit*.json"))


def test_two_qubit_tutorial_is_a_loop():
    """Tutorial 4 is written as a loop: design(knobs) → LOM loop → FEM (Q3D + eigenmode, driven exported) → bring back
    → FEM − LOM correction → rebuild → re-simulate, then a user target and the fab layout."""
    code = _code(_nb(T04))
    for phrase in ("def design(knobs", "def lom_values(", "def update(", "def lom_loop(", "def fem_point(",
                   "def corrected_targets(", "CC.add(", "T.epr_values(", "T.exchange_on(", "F_Q1_WANTED =",
                   # phase C: the groups come from the SIM_SUBSET cell (both pairs = the PAIR / ALL groups)
                   'SIM_SUBSET = [("Q1", "R1"), ("Q2", "R2")]', 'T.sim_subset(d, SIM_SUBSET, name="PAIR"',
                   'T.sim_subset(d, SIM_SUBSET, name="ALL"', '"q3d_cmatrix"',
                   '"eigenmode_epr"', '"hfss_driven"',
                   '"mesh_size": {"1t1_gap": 10}', '"n_modes": 5', "export_fab(", "C.pdk_report(", "size_junction("):
        assert phrase in code, phrase
    # every revision of the loop goes through FEM with the same send / solve / bring back
    assert code.count("send(d") >= 3 and code.count("solve(jobs") >= 3 and code.count("fem_point(DESIGN") >= 3


def test_two_qubit_designs_build_clean():
    """The saved revisions build, DRC clean with no PDK design warning, two trilayer Xmons, the coupling declared, and
    the sim groups carry the FEM-loop recipe."""
    if not T04_DESIGNS:
        pytest.skip("tutorial 4 not run yet (no examples/tutorials/designs/t04_two_qubit*.json)")
    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.drc import check  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    for path in T04_DESIGNS:
        design = load_design(path)
        rep = check(build(design))
        assert rep.ok and not [i for i in rep.issues if i.severity in ("error", "design")], (path.name, rep.issues)
        assert {"Q1", "Q2", "R1", "R2", "FL"} <= set(design.instances) | set(design.routes)
        assert all(design.instances[q].params["junction_type"] == "Quantcore Junction" for q in ("Q1", "Q2"))
        assert tuple(design.couplings["C_Q1Q2"].between) == ("Q1", "Q2") and design.couplings["C_Q1Q2"].value > 0
        g = design.sim_groups
        assert g["PAIR"].select == ["Q1", "Q2", "R1", "R2"] and g["PAIR"].analyses == ["q3d_cmatrix"]
        assert g["ALL"].analyses == ["eigenmode_epr", "hfss_driven"]
        assert g["ALL"].settings["eigenmode_epr"]["n_modes"] >= 5
        drv = g["ALL"].settings["hfss_driven"]
        assert drv["mesh_size"] == {"1t1_gap": 10} and drv["sweep_count"] <= 25000


def test_two_qubit_jobs_export_with_named_nets():
    """The Q3D group names all four nets (both islands, both claws: the readouts are cut at the claws); the eigenmode
    group terminates both cut feedline ends in 50 Ω and models both junctions, in a workstation-sized box."""
    path = TUT / "designs" / "t04_two_qubit.json"
    if not path.exists():
        pytest.skip("tutorial 4 not run yet")
    from quantcore_circuits.sim_tools import build_simulation  # pylint: disable=import-outside-toplevel

    q3d = build_simulation(path, "PAIR", "q3d_cmatrix")
    assert {"Q1.island", "Q2.island", "Q1.claw_n", "Q2.claw_n"} <= set(q3d.nets.values()), q3d.nets
    eig = build_simulation(path, "ALL", "eigenmode_epr")
    kinds = [(p.kind, p.name) for p in eig.ports]
    assert kinds.count(("edge_lumped", "FL")) == 2 and [k for k, _ in kinds].count("junction") == 2
    # the only notes: each junction's L / C source (``lumped_junction``)
    assert sum(1 for n in eig.notes if _JUNCTION_NOTE.match(n)) == 2 and all(_JUNCTION_NOTE.match(n) for n in eig.notes)
    assert eig.box.width() < 1600 and eig.box.height() < 2400


def test_kept_two_qubit_fem_results_parse(tut):
    """Kept FEM results of tutorial 4 (any revision): the Q3D fills the coupling C_C_Q1Q2 by net name; the eigenmode gives both
    qubits' and both resonators' dressed frequencies."""
    kept = [k for k in sorted((TUT / "fem").glob("t04_two_qubit*_*")) if (k / "results" / "results.json").exists()]
    if not kept:
        pytest.skip("no tutorial-4 FEM results kept (run it with RUN_FEM = True)")
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom import lom_from_design  # pylint: disable=import-outside-toplevel

    for keep in kept:
        meta = json.loads((keep / "job.json").read_text(encoding="utf-8"))
        res = json.loads((keep / "results" / "results.json").read_text(encoding="utf-8"))
        design = TUT / "designs" / f"{meta['design']}.json"
        if meta["analysis"] == "q3d_cmatrix":
            assert {"Q1.island", "Q2.island"} <= set(res["cmatrix"]["labels"])
            c12 = fill(lom_from_design(design).model, design, keep).values["C_C_Q1Q2"]  # the coupling "C_Q1Q2" → element C_C_Q1Q2
            assert c12.origin == "fem" and c12.extracted > 0, c12
        elif meta["analysis"] == "eigenmode_epr":
            v = tut.epr_values(keep, {"Q1": "R1", "Q2": "R2"}, {"R1": 7.0, "R2": 7.3})
            for k in ("Q1.f_q_GHz", "Q2.f_q_GHz", "R1.f_GHz", "R2.f_GHz", "R1.chi_MHz", "Q1-Q2.zz_MHz"):
                assert v.get(k) is not None, (keep.name, k)
            assert 4.0 < v["Q1.f_q_GHz"] < v["Q2.f_q_GHz"] < 8.0 and v["R1.f_GHz"] < v["R2.f_GHz"]


def _run_as_script(path: Path, timeout: int) -> str:
    """Code cells of ``path`` in one fresh Python process, QCC_LIVE=0, IPython display printing Markdown."""
    runner = (
        "import json, sys, IPython.display as ipd\n"
        "def show(*objs, **kw):\n"
        "    for o in objs:\n"
        "        print(o.data if isinstance(o, ipd.Markdown) else repr(o)[:300])\n"
        "ipd.display = show\n"
        "nb = json.load(open(sys.argv[1], encoding='utf-8'))\n"
        "ns = {'__name__': '__main__', 'display': show}\n"
        "for c in nb['cells']:\n"
        "    if c['cell_type'] == 'code':\n"
        "        src = '\\n'.join(l for l in ''.join(c['source']).splitlines() if not l.lstrip().startswith('%'))\n"
        "        exec(compile(src, 'cell', 'exec'), ns)\n"
        "print('TUTORIAL OK')\n"
    )
    env = {**os.environ, "QCC_LIVE": "0", "PYTHONIOENCODING": "utf-8", "BROWSER": "qcc-no-browser"}
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", runner, str(path)], cwd=TUT, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout, check=False,
    )
    assert proc.returncode == 0 and "TUTORIAL OK" in proc.stdout, proc.stdout[-3000:] + proc.stderr[-3000:]
    return proc.stdout


@pytest.mark.slow
def test_quickstart_runs_and_lands_on_target():
    out = _run_as_script(TUT / "00_quickstart_klive_and_pdk.ipynb", 900)
    assert "DRC clean" in out
    assert "PAD_W.a at (1225.0, 3750.0)" in out  # the pad slid to the 100 µm rule (was 1150 at 25 µm)
    assert "step 1: R1" in out  # the iterate loop ran


@pytest.mark.slow
def test_chip12_runs_with_the_fem_round_trip():
    out = _run_as_script(TUT / "01_chip12_coupled_chip.ipynb", 1800)
    assert out.count("| 100.0 |") == 12  # all twelve launchpads at the PDK pad distance (100 µm since 2026-11-10)
    assert "DRC clean" in out and "0 PDK design warnings" in out  # SQUIDs judged on their device R_n (45 kΩ)
    if (TUT / "fem" / "t01_chip12_Q1_R1_q3d_cmatrix" / "results" / "results.json").exists():
        assert "Q3D C-matrix of `t01_chip12_Q1_R1_q3d_cmatrix`" in out
        assert "LOM on subset Q3D" in out  # the subset round trip (nb-flow: subset check, then the whole chip)


@pytest.mark.slow
def test_two_qubit_loop_runs():
    out = _run_as_script(TUT / "04_two_qubit_feedback_loop.ipynb", 1800)
    assert "DRC clean" in out
    # the fab report is of the user revision: its readouts moved the content (+16 µm in y), inside the PDK's 50 µm
    # centring tolerance (center_in_die)
    m = re.search(r"content centre − die centre \| \(([+-]\d+), ([+-]\d+)\) µm", out)
    assert m and max(abs(int(m[1])), abs(int(m[2]))) <= 50, m and m[0]
    assert out.count("| 100.0 |") == 2  # both pads at the PDK pad distance
    assert "LOM loop:" in out and "residual / tolerance:" in out


def test_epr_values_keep_the_readouts_in_frequency_order(tut, tmp_path):
    """Tutorial 04 rev 0 (2026-11-13, fast FEM): both readouts came out ≈ 0.17 GHz below the LOM (6.828 / 7.127 GHz)
    and the greedy nearest-guess choice gave R1 (guess 7.08) R2's mode. The assignment keeps the frequency order."""
    keep = tmp_path / "eig"
    (keep / "results").mkdir(parents=True)
    modes = [{"mode": i + 1, "f_GHz": f, "Q": q} for i, (f, q) in enumerate(
        [(5.1082, 1.2e6), (5.3917, 1.2e6), (6.8278, 2.7e4), (7.1269, 2.4e4), (15.39, 5e8)])]
    chi = [[-152.1, -0.23, -0.156, -0.0002, 0.0], [-0.23, -148.6, -0.00005, -0.168, 0.0],
           [-0.156, -0.00005, 0.0, 0.0, 0.0], [-0.0002, -0.168, 0.0, 0.0, 0.0], [0.0] * 5]
    epr = {"p_mj": [[0.986, 0.0], [0.0, 0.985], [0.0005, 0.0], [0.0, 0.0005], [0.0, 0.0]],
           "f_GHz": [4.9618, 5.2481, 6.8277, 7.1268, 15.39], "chi_MHz": chi,
           "junction_names": ["Q1.junction", "Q2.junction"]}
    (keep / "results" / "results.json").write_text(json.dumps({"eigenmodes": modes, "epr": epr}), encoding="utf-8")
    v = tut.epr_values(keep, {"Q1": "R1", "Q2": "R2"}, {"R1": 7.08, "R2": 7.30})
    assert v["modes"] == {"Q1": 0, "Q2": 1, "R1": 2, "R2": 3}
    assert v["R1.f_GHz"] < v["R2.f_GHz"] and v["R1.chi_MHz"] == pytest.approx(-0.156)


def test_kept_bowtie_readout_coupling_merges_the_half_wave_nets(tut):
    """Tutorial 02 ``Q2_read`` (fast Q3D, 2026-11-14): the λ/2 readout is one LOM node with two nets in the box (its
    pad at the qubit, ``Q2.ro``, and its pad at the coupling capacitor, ``C_Q2.b``). They are merged: the qubit's
    readout coupling is ≈ 17.7 fF (estimate 15.8), not the far pad's 0.002 fF; the unphysical (negative) island →
    ground values of this unconverged run keep their estimates."""
    keep = TUT / "fem" / "t02_ibm_bowtie_5q_Q2_read_q3d_cmatrix"
    design = TUT / "designs" / "t02_ibm_bowtie_5q.json"
    if not (keep / "results" / "results.json").exists() or not design.exists():
        pytest.skip("tutorial-2 Q2_read results not kept (run tutorial 2 with RUN_FEM = True)")
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom import lom_from_design  # pylint: disable=import-outside-toplevel

    filled = fill(lom_from_design(design, ["Q2", "R_Q2", "C_Q2", "L_Q2", "P_Q2"]).model, design, keep)
    assert any("Q2.ro → C_Q2.b" in n for n in filled.notes)
    assert 10.0 < filled.values["Cg_Q2_ro"].extracted < 30.0
    assert all(v.value > 0 for v in filled.values.values() if v.type == "C")
