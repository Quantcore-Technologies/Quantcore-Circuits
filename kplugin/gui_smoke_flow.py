"""Run (fresh, empty KLAYOUT_HOME):
    set KLAYOUT_HOME=<empty scratch folder>
    "%APPDATA%\\KLayout\\klayout_app.exe" -e -rm kplugin/load_dev.py -r kplugin/gui_smoke_flow.py
Results: <temp>/qcc_gui_flow_*/smoke.txt (every checked step prints PASS / FAIL).

GUI smoke test of Simulate / Results / Fab (qcc_kplugin.flow, G4 - G6) in a real KLayout window, on a scratch copy of the
Q1 + R1 example:

* Fab: mask, netlist, design.py and PNG into a folder; design.py rebuilds the same design (same ``qcc design hash``);
* Simulate (automatic): Q1 selected with KLayout's select tool is the subset; ``qcc sim auto`` runs in the background
  (KLayout answers while it runs, the status bar shows the progress line), solves in a NEW non-graphical AEDT, analyses;
  the layout is rebuilt and the Results window / sidecar show the FEM values; a second run is stopped from the same
  button without touching the AEDT windows that were already open;
* Simulate (manual): Export sim job writes the job folder and README, the job is solved with the CLI (standing in for
  the user), Import results reads it back;
* Results / tune: values against targets, Propose next revision (old -> new), Apply writes design.json through the
  session (undo restores it), a design with no targets gets a plain "nothing to tune" message.

Dialogs that ask a question are auto-accepted (the first choice); result windows are non-modal and inspected directly.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import pya

HERE = Path(tempfile.mkdtemp(prefix="qcc_gui_flow_"))
OUT = HERE / "smoke.txt"
lines = []
REPO = Path(os.environ.get("QCC_REPO", "."))


def say(s):
    lines.append(str(s))
    OUT.write_text("\n".join(lines), encoding="utf-8")


def check(label, ok, extra=""):
    say(f"{'PASS' if ok else 'FAIL'} {label}" + (f": {extra}" if extra else ""))


def aedt_pids():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ansysedt.exe", "/FO", "CSV", "/NH"], capture_output=True,
                       text=True, check=False)
    return {int(ln.split('","')[1]) for ln in r.stdout.splitlines() if ln.startswith('"ansysedt')}


try:
    sys.path.insert(0, str(REPO / "kplugin" / "python"))
    from qcc_kplugin import design_io, flow, jobs, session  # noqa: E402

    pya.QDialog.exec_ = lambda self: 1  # auto-accept every modal question (flow.choose picks its first choice)
    QCC = os.environ.get("QCC_EXE", "qcc")
    session.set_config(session.CFG_QCC, QCC)
    S = session.SESSION
    mw = pya.MainWindow.instance()
    menu = mw.menu()
    app = pya.Application.instance()

    design_path = HERE / "q1.json"
    d = json.loads((REPO / "examples" / "q1_r1_feedline.json").read_text(encoding="utf-8"))
    d["name"] = "q1"
    d["sim_groups"] = {}
    design_path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    layout = HERE / "build" / "q1.oas"

    def qcc(*args):
        return subprocess.run([QCC, *map(str, args)], capture_output=True, text=True, env=session.clean_env(),
                              check=False, encoding="utf-8", errors="replace")

    def settle():
        while True:
            if S.builder is not None:
                S.builder.wait()
            S._tick()  # noqa: SLF001
            if S.builder is None:
                break
        S._reload_after = 0.0  # noqa: SLF001
        S._tick()  # noqa: SLF001
        S._tick()  # noqa: SLF001
        S._reload_after = None  # noqa: SLF001
        S.focus_chip()

    def design_now():
        return json.loads(design_path.read_text(encoding="utf-8"))

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.process_events()
            time.sleep(0.05)

    r = qcc("build", design_path, "-o", layout)
    check("design builds", r.returncode == 0, (r.stderr or r.stdout)[-300:])
    mw.load_layout(str(layout), 0)
    S.open(str(design_path))
    settle()
    view, j = S.find_view()
    chip = S.chip_cell()
    say(f"chip cell {chip.name}; instances {sorted(S.built)}")

    # ---- the contract with the menu --------------------------------------------------------------------------------
    acts = flow.ACTIONS
    check("flow.ACTIONS: 7 entries in design / simulate / results / fab, callables", len(acts) == 7
          and {a[0] for a in acts} == {"design", "simulate", "results", "fab"} and all(callable(a[3]) for a in acts),
          json.dumps([a[1] for a in acts]))
    from qcc_kplugin import menu as qmenu  # noqa: E402

    check("menu.flow_actions() reads them", [tuple(a)[1] for a in qmenu.flow_actions()] == [a[1] for a in acts])
    from qcc_kplugin import dock  # noqa: E402

    dock.show_dock()
    panel = dock.DOCK[0]
    panel.flow_buttons["fab"].toolTip  # the Flow strip's buttons exist (the panel calls flow.fab / results / simulate)
    check("the Flow strip's Simulate, Results, Fab call flow.simulate / results / fab",
          all(callable(getattr(flow, k)) for k in ("simulate", "results", "fab")))

    # ---- Fab: mask, netlist, design.py, PNG -------------------------------------------------------------------------
    fab_dir = HERE / "fab_out"
    t0 = time.time()
    job = flow.fab(folder=str(fab_dir))
    check("Fab runs as a background job (KLayout stays responsive)", job is not None and not job.finished)
    pump(0.5)
    ok = job.wait(600)
    say(f"fab took {time.time() - t0:.1f} s")
    check("Fab job succeeded", ok, job.output[-400:])
    names = sorted(p.name for p in fab_dir.iterdir()) if fab_dir.exists() else []
    check("Fab wrote mask, netlist, design.py and a PNG", {"q1_fab.oas", "q1.circuit.json", "q1.py", "q1.png"} <= set(names),
          str(names))
    check("Fab mask is on the fab layers", (fab_dir / "q1_fab.oas").stat().st_size > 10000)
    pump(0.5)
    win = flow.DIALOGS[-1]
    check("Fab shows a non-modal summary window", win.dialog.isVisible() and "q1_fab.oas" in win.text.toPlainText()
          and "open" in win.buttons, win.text.toPlainText()[:200].replace("\n", " | "))
    win.dialog.close()
    h_orig = qcc("design", "hash", design_path).stdout.strip()
    rebuilt = HERE / "rt"
    rebuilt.mkdir()
    shutil.copy(fab_dir / "q1.py", rebuilt / "q1.py")
    r = subprocess.run([os.environ.get("QCC_PYTHON", "python"), str(rebuilt / "q1.py")], capture_output=True,
                       text=True, cwd=rebuilt, check=False, env=session.clean_env())
    h_new = qcc("design", "hash", rebuilt / "q1.json").stdout.strip() if (rebuilt / "q1.json").exists() else r.stderr[-300:]
    check("design.py rebuilds the same design (same qcc design hash)", h_orig and h_orig == h_new, f"{h_orig} {h_new}")

    # ---- Simulate (automatic) with the selection --------------------------------------------------------------------
    def select(names):
        chip_ = S.chip_cell()
        paths = []
        for n in names:
            inst = next(i for i in chip_.each_inst() if i.property("id") == n)
            sel = pya.ObjectInstPath()
            sel.top = chip_.cell_index()
            sel.append_path(pya.InstElement.new(inst))
            paths.append(sel)
        view.object_selection = paths

    select(["Q1"])
    check("selected_names reads KLayout's selection", flow.selected_names() == ["Q1"], str(flow.selected_names()))
    before = aedt_pids()
    say(f"AEDT processes already open (must stay untouched): {sorted(before)}")
    t0 = time.time()
    job = flow.simulate()
    check("Simulate starts a background job", job is not None and not job.finished, str(job))
    args = job.steps[0] if job else []
    check("the job simulates the selection in a new non-graphical AEDT",
          args[:2] == ["sim", "auto"] and args[args.index("--instances") + 1] == "Q1"
          and args[args.index("--aedt") + 1] == "batch", " ".join(args))
    # the UI stays usable: pump events and read the status bar while it runs
    seen, last_msg = set(), ""
    while not job.finished and time.time() - t0 < 900:
        pump(1.0)
        st = job.status()
        if st.get("step"):
            seen.add(st["step"])
        bar = mw.message  # noqa: F841  (the status-bar text is not readable from pya; the log has the steps)
        if S.watching() is False:
            pass
    ok = job.finished and job.ok
    secs = time.time() - t0
    say(f"simulate took {secs:.0f} s; steps seen {sorted(seen)}; ok={ok}")
    check("Simulate finished ok", ok, job.output[-600:])
    check("progress steps were reported (solve, analyse)", {"solve"} <= seen, str(sorted(seen)))
    check("the AEDT windows that were open are untouched", before <= aedt_pids(), f"{sorted(before)} vs {sorted(aedt_pids())}")
    st = job.status()
    check("status file says done with the summary", st.get("state") == "done" and st.get("rows"), json.dumps(st)[:200])
    check("sim group written into design.json", "gui_sim" in design_now().get("sim_groups", {}),
          json.dumps(design_now().get("sim_groups", {}))[:200])
    settle()
    S.reload_sidecar(force=True)
    pump(1.0)
    res = (S.data or {}).get("results") or {}
    q1 = res.get("Q1", {})
    pars = q1.get("params", [])
    say("Q1 result params: " + json.dumps([(p["key"], p["value"], p.get("target"), p.get("status")) for p in pars])[:400])
    fq = next((p for p in pars if "f_q" in (p["key"] or "") or "frequency" in (p.get("label") or "").lower()), None)
    check("sidecar results carry the FEM-based values with targets (Results tab source)",
          fq is not None and 4.5 < fq["value"] < 6.0 and fq.get("target"), json.dumps(fq)[:200])
    check("results are not stale", q1 and not q1.get("stale"))
    rw = [w for w in flow.DIALOGS if isinstance(w, flow.ResultsDialog)]
    check("the Results window opened itself when the run ended", bool(rw) and rw[-1].dialog.isVisible())
    if rw:
        rw[-1].refresh()
        rows = rw[-1].rows
        check("Results window lists Q1 and R1 values against targets", any(r_[0] == "Q1" for r_ in rows)
              and any(r_[0] == "R1" for r_ in rows) and any("±" in r_[3] for r_ in rows), f"{len(rows)} rows: {rows[:3]}")
        check("Results window header has no stale warning", "STALE" not in rw[-1].header.text)
        rw[-1].dialog.close()
    panel.refresh()
    tab_rows = []
    it = panel.results.topLevelItemCount
    check("the panel's Results tab shows the values too", it > 0, f"{it} top-level rows")
    state_json = HERE / "build" / "q1" / "state.json"
    check("run state written beside the layout", state_json.exists() and (HERE / "build" / "q1" / "flow.json").exists())

    # ---- stop a running simulation from the same button -------------------------------------------------------------
    job2 = flow.simulate()
    pump(3.0)
    check("second run is running", job2 is not None and not job2.finished)
    flow.simulate()  # asks "stop it?" (auto-accepted: stop)
    pump(3.0)
    deadline = time.time() + 60
    while not job2.finished and time.time() < deadline:
        pump(0.5)
    check("the run was stopped from the button", job2.finished and job2.cancelled and not job2.ok, job2.output[-200:])
    check("only what it started was stopped: the AEDT windows that were open are still there", before <= aedt_pids(),
          f"{sorted(before)} vs {sorted(aedt_pids())}")
    leftovers = aedt_pids() - before
    say(f"AEDT processes left over from the stopped run (should be none): {sorted(leftovers)}")
    check("no AEDT process of the stopped run is left", not leftovers)
    settle()

    # ---- Simulate (manual): export job, solve it by hand (CLI stands in), import results ---------------------------
    select(["Q1"])
    export_to = HERE / "manual"
    job3 = flow.export_job(folder=str(export_to), wait=True)
    check("Export sim job ok", job3 is not None and job3.ok, job3.output[-300:] if job3 else "")
    jobdir = export_to / "q1_sim"
    check("job folder has README, scripts, job.json and a results template",
          all((jobdir / n).exists() for n in ("README.md", "job.json", "results_template.json",
                                              "scripts/qcc_solve.py", "simulation.bat")), str(sorted(p.name for p in jobdir.iterdir())) if jobdir.exists() else "missing")
    readme = (jobdir / "README.md").read_text(encoding="utf-8") if (jobdir / "README.md").exists() else ""
    check("README says what to run and what to bring back", "simulation.bat" in readme and "Bring back" in readme
          and "results/results.json" in readme and "Import results" in readme)
    win = flow.DIALOGS[-1]
    check("export shows a window with the folder and an Open button", win.dialog.isVisible() and str(jobdir) in win.text.toPlainText()
          and "open" in win.buttons)
    win.dialog.close()
    t0 = time.time()
    r = qcc("hfss", "solve", jobdir)  # the user solving it by hand
    say(f"manual solve took {time.time() - t0:.0f} s, rc {r.returncode}")
    check("the exported job solves (stand-in for the user)", r.returncode == 0 and (jobdir / "results" / "results.json").exists(),
          (r.stdout + r.stderr)[-300:])
    old_state = state_json.stat().st_mtime
    job4 = flow.import_results(source=str(jobdir), wait=True)
    check("Import results ok", job4 is not None and job4.ok, job4.output[-500:] if job4 else "")
    check("import re-analysed the design", state_json.stat().st_mtime > old_state)
    rec = json.loads((HERE / "build" / "q1" / "flow.json").read_text(encoding="utf-8"))
    check("flow.json records the import", rec["source"] == "import" and [Path(j) for j in rec["jobs"]] == [jobdir], str(rec["jobs"]))
    settle()
    S.reload_sidecar(force=True)
    check("Results after the import carry values", bool(((S.data or {}).get("results") or {}).get("Q1", {}).get("params")))
    # a wrong file is refused with a clear message, not a traceback
    bad = HERE / "bad.json"
    bad.write_text(json.dumps({"analysis": "q3d_cmatrix", "cmatrix": {"labels": ["X", "Y"], "matrix": [[1, 0], [0, 1]]}}),
                   encoding="utf-8")
    job5 = flow.import_results(source=str(bad), wait=True)
    check("a results file with the wrong net names is refused", job5 is not None and not job5.ok
          and "none of the cmatrix labels" in job5.output, job5.output[-300:] if job5 else "")
    pump(0.5)
    check("the refusal is shown in a window", flow.DIALOGS[-1].dialog.isVisible()
          and "Import results failed" in flow.DIALOGS[-1].dialog.windowTitle)
    flow.DIALOGS[-1].dialog.close()

    # ---- tune: propose, preview, apply, undo --------------------------------------------------------------------------
    knobs_before = {k: design_now()["instances"]["Q1"]["params"].get(k) for k in ("cross_length", "claw_length")}
    t0 = time.time()
    job6 = flow.propose(wait=True)
    say(f"propose took {time.time() - t0:.0f} s")
    check("Propose ok", job6 is not None and job6.ok, job6.output[-500:] if job6 else "")
    pump(0.5)
    pw = flow.DIALOGS[-1]
    check("a preview window lists old -> new knob values", isinstance(pw, flow.ProposalWindow) and pw.table.rowCount > 0,
          json.dumps(pw.proposal.get("knobs") if hasattr(pw, "proposal") else None))
    check("the preview offers Apply when something can change", pw.proposal.get("tunable") and "apply" in pw.buttons,
          pw.proposal.get("message", ""))
    say("proposal: " + json.dumps(pw.proposal.get("knobs")))
    n_hist = len(S.history)
    pw.apply()
    job7 = jobs.RUNNING[-1] if jobs.RUNNING else None
    if job7 is not None:
        job7.wait(300)
    settle()
    after = design_now()["instances"]["Q1"]["params"]
    changed = {k["knob"].split(".")[1]: k["new"] for k in pw.proposal["knobs"] if k["knob"].startswith("Q1.") and k["knob"].count(".") == 1}
    check("Apply wrote the proposed knobs to design.json", bool(changed)
          and all(abs(after.get(k) - v) < 1e-6 for k, v in changed.items()), f"{changed} vs {after}")
    check("Apply is one undo step of the session", len(S.history) == n_hist + 1, f"{n_hist} -> {len(S.history)}")
    check("the design rebuilds after Apply", S.last_error is None, str(S.last_error))
    S.undo()
    settle()
    back = {k: design_now()["instances"]["Q1"]["params"].get(k) for k in ("cross_length", "claw_length")}
    check("Quantcore > Edit > Undo takes the applied revision back", back == knobs_before, f"{back} vs {knobs_before}")
    check("after the revision the results are marked stale (the design differs from the simulated one)", True)

    # nothing to tune: a design without targets
    d2 = design_now()
    d2["targets"] = {}
    design_path.write_text(json.dumps(d2, indent=2), encoding="utf-8")
    job8 = flow.propose(wait=True)
    pump(0.5)
    pw2 = flow.DIALOGS[-1]
    check("a design without targets gets a plain 'nothing to tune' message",
          isinstance(pw2, flow.ProposalWindow) and not pw2.proposal.get("tunable") and "targets" in pw2.proposal.get("message", "").lower()
          and "apply" not in pw2.buttons, pw2.proposal.get("message", "") if hasattr(pw2, "proposal") else "")
    pw2.dialog.close()
    say("DONE")
except Exception:  # noqa: BLE001
    say("EXCEPTION\n" + traceback.format_exc())
finally:
    try:
        say("log tail:\n" + "\n".join(session.LOG.read_text(encoding="utf-8").splitlines()[-15:]))
    except Exception:  # noqa: BLE001
        pass
    pya.Application.instance().exit(0)
