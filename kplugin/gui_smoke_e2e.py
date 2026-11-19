"""Run (fresh KLAYOUT_HOME with a klayoutrc, so no tip dialog blocks the start):
    set KLAYOUT_HOME=<scratch folder>
    "%APPDATA%\\KLayout\\klayout_app.exe" -e -rm kplugin/load_dev.py -r kplugin/gui_smoke_e2e.py
Results: <temp>/qcc_gui_e2e_*/smoke.txt (every checked step prints PASS / FAIL), plus panel_*.png pictures.

End-to-end GUI flow in ONE KLayout session, driven the way a user drives it: the Quantcore menu items by their menu
paths (``mw.menu().action(path).trigger()``) and the panel's Flow-strip buttons, with every modal question
auto-accepted (its first choice) and the folder dialogs answered with a scratch folder. On a scratch copy of
``examples/q1_r1_feedline.json``:

    Open → Check → LOM → Simulate (Q1 selected, automatic, fast settings, a NEW non-graphical AEDT) → Results →
    Propose → Apply → Undo → Fab export

After each step the Flow strip's marks (✓ done / ⚠ attention / – not yet) are read from the buttons as the panel shows
them (no manual refresh), and the fab files are checked at the end. The AEDT windows that were open before stay
untouched (only the AEDT this run starts is used).
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import traceback
from pathlib import Path

import pya

HERE = Path(tempfile.mkdtemp(prefix="qcc_gui_e2e_"))
OUT = HERE / "smoke.txt"
REPO = Path(__file__).resolve().parents[1] if "__file__" in dir() else Path(os.environ.get("QCC_REPO", "."))
if not (REPO / "examples" / "q1_r1_feedline.json").exists():
    REPO = Path(os.environ.get("QCC_REPO", "."))
lines = []
T0 = time.time()


def say(s):
    lines.append(str(s))
    OUT.write_text("\n".join(lines), encoding="utf-8")


def check(label, ok, extra=""):
    say(f"{'PASS' if ok else 'FAIL'} {label}" + (f": {extra}" if extra else ""))
    return ok


def aedt_pids():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ansysedt.exe", "/FO", "CSV", "/NH"], capture_output=True,
                       text=True, check=False)
    return {int(ln.split('","')[1]) for ln in r.stdout.splitlines() if ln.startswith('"ansysedt')}


try:
    from qcc_kplugin import dock, flow, jobs, session  # noqa: E402  (load_dev.py put kplugin/python on the path)

    QCC = os.environ.get("QCC_EXE", "qcc")
    session.set_config(session.CFG_QCC, QCC)
    S = session.SESSION
    app = pya.Application.instance()
    mw = pya.MainWindow.instance()
    menu = mw.menu()

    def pump(seconds=0.3):
        end = time.time() + seconds
        while time.time() < end:
            app.process_events()
            time.sleep(0.03)

    def wait_until(cond, timeout=120.0):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            pump(0.2)
        return cond()

    def idle(timeout=180.0):
        """No build running and the view reloaded: the session timer (the real one, at 250 ms) did its work."""
        return wait_until(lambda: S.builder is None and S._reload_after is None, timeout)  # noqa: SLF001

    def marks():
        return {k: b.text.rsplit(" ", 1)[-1] for k, b in panel.flow_buttons.items()}

    def shot(name):
        try:
            panel.dock.grab().save(str(HERE / f"panel_{name}.png"))
        except Exception as e:  # noqa: BLE001
            say(f"panel picture {name} skipped: {e!r}")

    def trigger(path):
        action = menu.action(path)
        if not check(f"menu item {path} exists", action is not None and menu.is_valid(path)):
            return False
        action.trigger()
        return True

    # every modal question takes its first answer; folder / file dialogs answer with scratch paths
    pya.QDialog.exec_ = lambda self: 1
    design_path = HERE / "q1_r1_feedline.json"
    shutil.copy(REPO / "examples" / "q1_r1_feedline.json", design_path)
    pya.QFileDialog.getOpenFileName = lambda *a: str(design_path)
    fab_dir = HERE / "build"
    flow.ask_dir = lambda title, start: str(fab_dir)
    say(f"scratch: {HERE}")

    # ---- Open (menu) ----------------------------------------------------------------------------------------------
    t = time.time()
    trigger("qcc_menu.qcc_design_menu.qcc_open")
    ok = wait_until(lambda: S.find_view()[0] is not None and S.data is not None and S.builder is None, 180)
    idle()
    check("Design > Open design builds the example and shows it", ok and S.chip_cell() is not None,
          f"{time.time() - t:.1f} s, error {S.last_error}")
    trigger("qcc_menu.qcc_dock")
    panel = dock.DOCK[0]
    panel.dock.resize(420, 900)
    pump(0.5)
    m = marks()
    say(f"marks after open: {m}")
    check("Flow strip after Open: Design ✓, the later steps not done (–)",
          m["design"] == "✓" and all(m[k] == "–" for k in ("check", "lom", "simulate", "results", "fab")), str(m))
    check("the hint names the next step", panel.flow_hint.text == "Next: Check", panel.flow_hint.text)
    shot("1_open")

    # ---- Check (Flow button) --------------------------------------------------------------------------------------
    t = time.time()
    panel.flow_buttons["check"].click()
    job = jobs.RUNNING[-1] if jobs.RUNNING else None
    check("Flow Check runs in the background (KLayout stays usable)", job is not None and not job.finished)
    wait_until(lambda: job is None or job.finished, 300)
    pump(0.3)
    m = marks()
    say(f"check took {time.time() - t:.1f} s; marks {m}")
    check("Flow strip after Check: Check ✓ or ⚠ (done)", m["check"] in ("✓", "⚠"), str(m))

    # ---- LOM (menu) -----------------------------------------------------------------------------------------------
    t = time.time()
    trigger("qcc_menu.qcc_check_menu.qcc_run_lom")
    job = jobs.RUNNING[-1] if jobs.RUNNING else None
    check("Check and LOM > Run LOM runs in the background", job is not None and not job.finished)
    wait_until(lambda: job is None or job.finished, 600)
    pump(0.3)
    m = marks()
    say(f"LOM took {time.time() - t:.1f} s; marks {m}")
    check("LOM job ok", job is not None and job.ok, job.output[-300:] if job else "")
    check("Flow strip after LOM: LOM ✓", m["lom"] == "✓", str(m))
    rows = {panel.lom_params.item(i, 0).text: panel.lom_params.item(i, 3).text for i in range(panel.lom_params.rowCount)}
    check("LOM tab compares Q1 / R1 with their targets", "Q1.f_q_GHz" in rows and rows["Q1.f_q_GHz"] in (
        "within tolerance", "off"), json.dumps(rows))
    shot("2_lom")

    # ---- Simulate (Flow button, Q1 selected): new non-graphical AEDT --------------------------------------------------
    chip = S.chip_cell()
    view = S.find_view()[0]
    q1 = next(i for i in chip.each_inst() if i.property("id") == "Q1")
    sel = pya.ObjectInstPath()
    sel.top = chip.cell_index()
    sel.append_path(pya.InstElement.new(q1))
    view.object_selection = [sel]
    check("Q1 selected with KLayout's own selection", flow.selected_names() == ["Q1"], str(flow.selected_names()))
    before = aedt_pids()
    say(f"AEDT processes open before (must stay untouched): {sorted(before)}")
    n_hist = len(S.history)
    t = time.time()
    panel.flow_buttons["simulate"].click()
    job = flow._running("Simulate")  # noqa: SLF001
    check("Flow Simulate starts the automatic run", job is not None and not job.finished)
    args = job.steps[0] if job else []
    from qcc_kplugin import simsetup  # noqa: E402

    # G11: the dialog's settings are prefilled with the fast values and always sent as --full --set k=v
    sets = {args[i + 1] for i, a in enumerate(args[:-1]) if a == "--set"}
    fast = {f"{k}={v}" for k, v in simsetup.FAST[simsetup.Q3D].items()}
    check("... of Q1 in a new non-graphical AEDT (batch), the dialog's fast values (--full --set ...)",
          "--instances" in args and args[args.index("--instances") + 1] == "Q1" and args[args.index("--aedt") + 1]
          == "batch" and "--full" in args and fast <= sets, " ".join(args))
    responsive = []
    while job is not None and not job.finished and time.time() - t < 1200:
        t_ev = time.time()
        pump(1.0)
        responsive.append(time.time() - t_ev)
    secs = time.time() - t
    say(f"simulate took {secs:.0f} s (status {job.status() if job else None})")
    check("Simulate finished ok", job is not None and job.ok, job.output[-600:] if job else "")
    check("KLayout answered during the run (event loop never blocked > 2 s)", responsive and max(responsive) < 2.0,
          f"max {max(responsive or [0]):.2f} s")
    check("the AEDT windows that were open are untouched", before <= aedt_pids())
    check("no AEDT process of this run is left", not (aedt_pids() - before), str(sorted(aedt_pids() - before)))
    check("the sim group written by qcc is not an undo step of its own", len(S.history) == n_hist,
          f"{n_hist} -> {len(S.history)}")
    check("the sim group is in design.json", "gui_sim" in json.loads(design_path.read_text(encoding="utf-8")).get(
        "sim_groups", {}))
    idle()
    wait_until(lambda: bool((S.data or {}).get("results")), 60)
    pump(0.5)
    m = marks()
    say(f"marks after Simulate: {m}")
    check("Flow strip after Simulate: Simulate ✓, Results ✓ or ⚠", m["simulate"] == "✓" and m["results"] in ("✓", "⚠"),
          str(m))
    check("Flow strip after Simulate: Check and LOM still current (writing the sim group did not stale them)",
          m["check"] in ("✓", "⚠") and m["lom"] == "✓", str(m))
    q1_res = ((S.data or {}).get("results") or {}).get("Q1", {})
    fq = next((p for p in q1_res.get("params", []) if "f_q" in (p.get("key") or "")), None)
    check("Results carry Q1's FEM-based f_q against its target", fq is not None and fq.get("value") and fq.get("target"),
          json.dumps(fq))
    shot("3_simulate")

    # ---- Results (Flow button) ------------------------------------------------------------------------------------
    for w in flow.DIALOGS:  # the window the run opened itself
        w.dialog.close()
    panel.flow_buttons["results"].click()
    pump(0.5)
    rw = next((w for w in reversed(flow.DIALOGS) if isinstance(w, flow.ResultsDialog)), None)
    check("Flow Results shows the values against the targets (window + Results tab)",
          rw is not None and rw.dialog.isVisible() and any(r[0] == "Q1" for r in rw.rows)
          and panel.tabs.tabText(panel.tabs.currentIndex) == "Results", str(rw.rows[:3] if rw else None))

    # ---- Propose (menu) and Apply (window button) ---------------------------------------------------------------------
    knobs_before = json.loads(design_path.read_text(encoding="utf-8"))["instances"]["Q1"].get("params", {})
    t = time.time()
    trigger("qcc_menu.qcc_results_menu.qcc_propose")
    job = flow._running("Propose")  # noqa: SLF001
    wait_until(lambda: job is None or job.finished, 600)
    pump(0.5)
    pw = next((w for w in reversed(flow.DIALOGS) if isinstance(w, flow.ProposalWindow)), None)
    say(f"propose took {time.time() - t:.1f} s: {json.dumps(pw.proposal.get('knobs') if pw else None)}")
    check("Results > Propose shows old → new knob values with Apply", pw is not None and pw.proposal.get("tunable")
          and "apply" in pw.buttons and pw.table.rowCount > 0, pw.proposal.get("message", "") if pw else "")
    n_hist = len(S.history)
    t = time.time()
    if pw is not None and "apply" in pw.buttons:
        pw.buttons["apply"].click()
    job = flow._running("Apply")  # noqa: SLF001
    wait_until(lambda: job is None or job.finished, 300)
    idle()
    pump(0.5)
    after = json.loads(design_path.read_text(encoding="utf-8"))
    changed = {k["knob"]: k["new"] for k in (pw.proposal["knobs"] if pw else [])}
    q1p = after["instances"]["Q1"].get("params", {})
    check("Apply wrote the proposed knobs (one undo step) and rebuilt",
          bool(changed) and len(S.history) == n_hist + 1 and S.last_error is None
          and all(abs(q1p.get(k.split(".", 1)[1], 1e9) - v) < 1e-6 for k, v in changed.items() if k.startswith("Q1.")
                  and k.count(".") == 1), f"{time.time() - t:.1f} s; {changed}; error {S.last_error}")
    check("the sim group survived Apply", "gui_sim" in after.get("sim_groups", {}))
    m = marks()
    say(f"marks after Apply: {m}")
    check("Flow strip after Apply: LOM ⚠ (out of date), Simulate ⚠ (stale results), Check – (not run on this revision)",
          m["lom"] == "⚠" and m["simulate"] == "⚠" and m["check"] == "–", str(m))
    shot("4_apply")

    # ---- Undo (menu) ------------------------------------------------------------------------------------------------
    trigger("qcc_menu.qcc_edit_menu.qcc_undo")
    idle()
    wait_until(lambda: not any(e.get("stale") for e in ((S.data or {}).get("results") or {}).values()), 60)
    pump(0.5)
    back = json.loads(design_path.read_text(encoding="utf-8"))
    check("Edit > Undo restores the knobs and keeps the sim group", back["instances"]["Q1"].get("params", {})
          == knobs_before and "gui_sim" in back.get("sim_groups", {}))
    m = marks()
    say(f"marks after Undo: {m}")
    check("Flow strip after Undo: LOM ✓ and Simulate ✓ again (the simulated revision is back)",
          m["lom"] == "✓" and m["simulate"] == "✓", str(m))

    # ---- Fab export (Flow button) -----------------------------------------------------------------------------------
    for w in flow.DIALOGS:
        w.dialog.close()
    t = time.time()
    panel.flow_buttons["fab"].click()
    job = flow._running("Fab")  # noqa: SLF001
    check("Flow Fab runs in the background", job is not None and not job.finished)
    wait_until(lambda: job is None or job.finished, 600)
    pump(0.5)
    files = sorted(p.name for p in fab_dir.iterdir() if p.is_file())
    say(f"fab took {time.time() - t:.1f} s; {files}")
    want = {"q1_r1_feedline_fab.oas", "q1_r1_feedline.circuit.json", "q1_r1_feedline.py", "q1_r1_feedline.png"}
    check("Fab wrote the mask, netlist, design.py and PNG", job is not None and job.ok and want <= set(files),
          (job.output[-300:] if job else "") + str(files))
    check("the fab mask is not empty", (fab_dir / "q1_r1_feedline_fab.oas").stat().st_size > 10000)
    m = marks()
    say(f"marks after Fab: {m}")
    check("Flow strip after Fab: Fab ✓", m["fab"] == "✓", str(m))
    shot("5_fab")
    say(f"total {time.time() - T0:.0f} s")
    say("DONE")
except Exception:  # noqa: BLE001
    say("EXCEPTION\n" + traceback.format_exc())
finally:
    try:
        say("log tail:\n" + "\n".join(session.LOG.read_text(encoding="utf-8").splitlines()[-15:]))
    except Exception:  # noqa: BLE001
        pass
    pya.Application.instance().exit(0)
