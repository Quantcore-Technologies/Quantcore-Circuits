"""Run: set KLAYOUT_HOME to a folder holding a seeded klayoutrc, then
    klayout_app.exe -e -rm kplugin/load_dev.py -r kplugin/gui_smoke_components.py
(results in <temp>/qcc_gui_comp_*/smoke.txt; every checked step prints PASS / FAIL; QCC_CELLS=A,B limits the cells).

Places EVERY cell of `qcc components --json --source quantcore` through the plugin, each in a fresh scratch design:
panel select (parameter table fills) → arm placement (double-click path) → mouse move (ghost redraw) → rotate / mirror →
click to drop → rebuild → edit dialog (change one parameter) → rebuild → native move syncs → Connect a directed
port to a BondPad port → rebuild. Handler exceptions are caught and reported; no modal dialog may open.
Then: Check and Run LOM on a design with no qubit (clear message, no traceback), and the readout-resonator check
(Xmon claw → feedline hanger) in a design with a feedline."""
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import pya

REPO = Path(os.environ.get("QCC_REPO", "."))
HERE = Path(__import__("tempfile").mkdtemp(prefix="qcc_gui_comp_"))
OUT = HERE / "smoke.txt"
lines = []


def say(s):
    lines.append(str(s))
    OUT.write_text("\n".join(lines), encoding="utf-8")


RESULTS = {}  # cell → {step: "ok" | "FAIL: ..." | "n/a: ..."}

try:
    sys.path.insert(0, str(Path(os.environ.get("QCC_REPO", ".")) / "kplugin" / "python"))
    from qcc_kplugin import design_io, dock, jobs, session, tools  # noqa: E402

    QCC = os.environ.get("QCC_EXE", "qcc")
    session.set_config(session.CFG_QCC, QCC)
    MODAL = []  # message boxes that would have blocked the user

    pya.QDialog.exec_ = lambda self: 1
    pya.MessageBox.warning = staticmethod(lambda *a, **k: MODAL.append(("warning", a[1:2])) or pya.MessageBox.Ok)
    pya.MessageBox.info = staticmethod(lambda *a, **k: MODAL.append(("info", a[1:2])) or pya.MessageBox.Ok)
    # the edit dialog: change the first numeric parameter by +10 %
    CHANGE = {}
    _fill_exec = pya.QDialog.exec_

    def exec_change(self):
        table = getattr(self, "param_table", None)
        if table is not None and CHANGE.get("on"):
            for i, p in enumerate(self.param_rows):
                d = p["default"]
                if isinstance(d, (int, float)) and not isinstance(d, bool) and d not in (0,):
                    new = round(d * 1.1) if isinstance(d, int) and abs(d) >= 10 else (d + 1 if isinstance(d, int) else round(d * 1.1, 3))
                    table.item(i, 1).setText(json.dumps(new))
                    CHANGE["param"], CHANGE["value"] = p["name"], new
                    break
            else:
                CHANGE["param"] = None
        return 1

    pya.QDialog.exec_ = exec_change

    def build_blank(path):
        r = subprocess.run([QCC, "build", str(path), "-o", str(path.parent / "build" / (path.stem + ".oas"))],
                           capture_output=True, text=True, env=session.clean_env(), check=False, encoding="utf-8",
                           errors="replace")
        return None if r.returncode == 0 else (r.stderr or r.stdout)[-400:]

    mw = pya.MainWindow.instance()
    S = session.SESSION
    app = pya.Application.instance()
    menu = mw.menu()

    def settle():
        for _ in range(400):
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
        app.process_events()

    def design_of(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    all_cells = json.loads(subprocess.run([QCC, "components", "--json", "--source", "quantcore"], capture_output=True,
                                          text=True, env=session.clean_env(), check=True).stdout)
    only = [c for c in os.environ.get("QCC_CELLS", "").split(",") if c]
    cells = only or all_cells
    say(f"{len(all_cells)} quantcore cells; testing {len(cells)}")

    dock.show_dock()
    panel = dock.DOCK[0]
    panel.load_components()
    from qcc_kplugin import qcache  # noqa: E402
    qcache.wait()  # the list loads in the background now
    items = {panel.components.item(i).text: panel.components.item(i) for i in range(panel.components.count)}

    def check(res, step, ok, extra=""):
        res[step] = "ok" if ok else f"FAIL: {extra}"[:300]
        say(f"{'PASS' if ok else 'FAIL'} {res['cell']} {step}" + (f": {extra}" if extra and not ok else ""))
        return ok

    def na(res, step, why):
        res[step] = f"n/a: {why}"
        say(f"N/A  {res['cell']} {step}: {why}")

    def step(res, name, fn):
        """Run a step; an exception is a FAIL (it would have been a Script Error)."""
        errs0, modal0 = len(session.ERRORS), len(MODAL)
        try:
            fn()
        except Exception:  # noqa: BLE001
            check(res, name, False, "EXC " + traceback.format_exc().strip().splitlines()[-1])
            return
        if len(MODAL) > modal0:
            check(res, name + "-nomodal", False, str(MODAL[modal0:]))
        if len(session.ERRORS) > errs0:
            check(res, name + "-noerror", False, str(session.ERRORS[errs0:]))

    for ci, cell in enumerate(cells):
        res = RESULTS.setdefault(cell, {"cell": cell})
        t0 = time.time()
        say(f"--- {ci + 1}/{len(cells)} {cell}")
        dpath = HERE / f"c{ci:02d}_{cell}.json"
        d0 = design_io.new_design(f"c{ci:02d}_{cell}")
        dpath.write_text(json.dumps(d0), encoding="utf-8")
        err = build_blank(dpath)
        if err:
            check(res, "blank", False, err)
            continue
        mw.load_layout(str(dpath.parent / "build" / (dpath.stem + ".oas")), 0)
        S.open(str(dpath))
        settle()
        PENDING = tools.PENDING_PLACE
        tools.PENDING_PLACE.clear()

        item = items.get(cell)
        if item is None:
            check(res, "listed", False, "not in the Components list")
            continue

        def s_select():
            panel.components.setCurrentItem(item)
            panel.cell = None
            panel._select(item)  # noqa: SLF001
            from qcc_kplugin import qcache as _qc; _qc.wait()  # noqa: E702  (loads run in the background)
            rows = len(tools.schema(cell))
            check(res, "table", panel.table.rowCount == rows and rows > 0, f"{panel.table.rowCount} rows, schema {rows}")
        step(res, "table", s_select)

        def s_arm():
            panel._place(item)  # noqa: SLF001
            from qcc_kplugin import qcache as _qc; _qc.wait()  # noqa: E702  (loads run in the background)
            snap = tools.ACTIVE[0] if tools.ACTIVE else None
            ok = snap is not None and PENDING.get("cell") == cell
            check(res, "arm", ok, f"pending={PENDING.get('cell')} tool={type(snap).__name__}")
            if ok:
                g = PENDING.get("ghost")
                check(res, "outline", bool(g) and ("bbox" in g), f"ghost={bool(g)}")
                note = tools.size_note(cell, g)
                check(res, "size-note", bool(note) == (cell == "WaferMap75"), f"note={note!r}")
        step(res, "arm", s_arm)

        def s_ghost():
            snap = tools.ACTIVE[0]
            for pt in ((3000, 3000), (3750.4, 3750.9)):
                snap.mouse_moved_event(pya.DPoint(*pt), 0, True)
            tools.rotate(90)
            snap.mouse_moved_event(pya.DPoint(3750, 3750), 0, True)
            PENDING["mirror"] = True  # as a duplicated mirrored component would arm it
            snap.mouse_moved_event(pya.DPoint(3750, 3750), 0, True)
            PENDING["mirror"] = False
            tools.rotate(-90)
            snap.mouse_moved_event(pya.DPoint(3750, 3750), 0, True)
            check(res, "ghost", PENDING.get("rot") == 0.0, f"rot {PENDING.get('rot')}")
        step(res, "ghost", s_ghost)

        def s_drop():
            snap = tools.ACTIVE[0]
            tools.rotate(90)
            tools.rotate(-90)
            n0 = len(session.ERRORS)
            snap.mouse_click_event(pya.DPoint(3750, 3750), tools.LEFT, True)
            des = design_of(dpath)
            ok = len(des.get("instances", {})) == 1 and not PENDING
            check(res, "drop", ok, f"instances {list(des.get('instances', {}))} pending {bool(PENDING)} errors {session.ERRORS[n0:]}")
        step(res, "drop", s_drop)

        placed = design_of(dpath).get("instances", {})
        if not placed:
            continue
        iname = next(iter(placed))
        settle()
        check(res, "build", S.last_error is None, S.last_error or "")
        S.reload_sidecar(force=True)
        sc_inst = (S.data or {}).get("instances", {}).get(iname)
        check(res, "sidecar", sc_inst is not None, "no instance in the sidecar")
        ports = {n: v for n, v in (S.data or {}).get("ports", {}).items() if n.split(".", 1)[0] == iname}
        res["ports"] = sorted(ports)

        def s_edit():
            CHANGE.clear()
            CHANGE["on"] = True
            snap = tools.ACTIVE[0] if tools.ACTIVE else None
            if snap is None or not snap.active:
                mw.menu().action("@toolbar.qcc_snap").trigger()
                snap = tools.ACTIVE[0]
            des = design_of(dpath)
            out = tools.edit_instance_dialog(iname, des["instances"][iname], des.get("targets", {}).get(iname, {}))
            check(res, "edit-dialog", out is not None, "dialog returned None")
            if out is None:
                return
            what = tools.apply_instance_edit(des, iname, out)
            S.commit(des, what)
            if CHANGE.get("param"):
                got = design_of(dpath)["instances"][iname].get("params", {}).get(CHANGE["param"])
                check(res, "edit-applied", got == CHANGE["value"], f"{CHANGE['param']}: wrote {got}, wanted {CHANGE['value']}")
            else:
                na(res, "edit-applied", "no numeric parameter")
            settle()
            check(res, "edit-build", S.last_error is None, S.last_error or "")
            # double-click path
            bb = S.data["instances"].get(iname, {}).get("bbox")
            if bb:
                snap.mouse_double_click_event(pya.DPoint((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2), tools.LEFT, True)
                settle()
                check(res, "edit-dblclick", S.last_error is None, S.last_error or "")
        step(res, "edit", s_edit)
        CHANGE["on"] = False

        def s_native():
            chip = S.chip_cell()
            inst = next((i for i in chip.each_inst() if i.property("id") == iname), None)
            if inst is None:
                return check(res, "native-move", False, "instance not in the chip cell")
            disp = inst.dcplx_trans.disp
            inst.dcplx_trans = pya.DCplxTrans(1.0, 0.0, False, pya.DVector(disp.x + 100.0, disp.y - 50.0))
            S.sync_native_moves()
            at = design_of(dpath)["instances"][iname]["place"].get("at")
            check(res, "native-move", at is not None and abs(at[0] - (3750 + 100)) < 150, f"place {at}")
            settle()
            check(res, "native-move-build", S.last_error is None, S.last_error or "")
            return None
        step(res, "native", s_native)

        # Connect a directed port to a BondPad port
        S.reload_sidecar(force=True)
        directed = {n: v for n, v in ((S.data or {}).get("ports", {})).items()
                    if n.split(".", 1)[0] == iname and v.get("dir") is not None and v.get("pos")}
        if not directed:
            na(res, "connect", "no directed port")
        else:
            pname, pv = next(iter(sorted(directed.items())))

            def s_connect():
                import math
                dvec = tuple(pv["dir"])
                ang = math.degrees(math.atan2(dvec[1], dvec[0]))
                pos = pv["pos"]
                far = (pos[0] + dvec[0] * 1500.0, pos[1] + dvec[1] * 1500.0)
                des = design_of(dpath)
                design_io.add_instance(des, "PADX", "BondPad", far, (ang + 90.0) % 360.0)
                dpath.write_text(json.dumps(des), encoding="utf-8")
                S.commit(des, "test pad")
                settle()
                S.reload_sidecar(force=True)
                pp = S.data["ports"].get("PADX.a")
                if pp is None:
                    return check(res, "connect", False, "BondPad port missing after build")
                mw.menu().action("@toolbar.qcc_connect").trigger()
                con = tools.ACTIVE[0]
                n0 = len(session.ERRORS)
                for pt in (pv["pos"], pp["pos"]):
                    con.mouse_moved_event(pya.DPoint(*pt), 0, True)
                    con.mouse_click_event(pya.DPoint(*pt), tools.LEFT, True)
                routes = design_of(dpath).get("routes", {})
                made = any({r.get("from"), r.get("to")} == {pname, "PADX.a"} for r in routes.values())
                check(res, "connect-made", made, f"routes {routes} errors {session.ERRORS[n0:]}")
                settle()
                if cell == "SpiralLine" and "RoutingError" in (S.last_error or ""):
                    # known library limit: the ports are 2 um CPW, 1.8 deg off-axis; the router says so, the
                    # plugin shows it in the status bar, the user undoes it
                    na(res, "connect-build", "expected: " + S.last_error[-120:])
                    S.undo()
                    settle()
                    check(res, "connect-undo-rebuilds", S.last_error is None, S.last_error or "")
                    return None
                check(res, "connect-build", S.last_error is None, S.last_error or "")
                return None
            step(res, "connect", s_connect)
        mw.menu().action("@toolbar.qcc_snap").trigger()
        say(f"    {cell}: {time.time() - t0:.0f} s")
        json.dump(RESULTS, open(HERE / "results.json", "w"), indent=1)

    # ==== Check + Run LOM on a design with a non-qubit component only =========================================
    if not only:
        say("=== Check / LOM on a design without a qubit")
        res = RESULTS.setdefault("[no-qubit design]", {"cell": "[no-qubit design]"})
        dpath = HERE / "noqubit.json"
        d0 = design_io.new_design("noqubit")
        design_io.add_instance(d0, "BP1", "BondPad", (1125, 3750), 270)
        design_io.add_instance(d0, "BP2", "BondPad", (6375, 3750), 90)
        d0["routes"] = {"R1": {"from": "BP1.a", "to": "BP2.a", "type": "cpw", "r": 100.0}}
        dpath.write_text(json.dumps(d0), encoding="utf-8")
        err = build_blank(dpath)
        check(res, "build", err is None, err or "")
        mw.load_layout(str(HERE / "build" / "noqubit.oas"), 0)
        S.open(str(dpath))
        settle()
        S.reload_sidecar(force=True)
        panel.flow_buttons["check"].click()
        job = jobs.RUNNING[-1] if jobs.RUNNING else None
        if job is not None:
            job.wait(300)
        check(res, "check-job", job is not None and job.finished, "no job")
        modal0 = len(MODAL)
        panel.flow_buttons["lom"].click()
        job = jobs.RUNNING[-1] if jobs.RUNNING else None
        if job is not None:
            job.wait(300)
        txt = panel.lom_status.text
        say(f"LOM status text: {txt}")
        check(res, "lom-message", "nothing to simulate" in txt and "Traceback" not in txt, txt)
        check(res, "lom-run-reenabled", panel.lom_run.enabled, "Run button stuck disabled")
        check(res, "lom-no-modal", len(MODAL) == modal0, str(MODAL[modal0:]))

    # ==== readout resonator: Xmon claw -> feedline hanger ======================================================
    if not only:
        say("=== readout resonator checks")
        res = RESULTS.setdefault("[readout resonator]", {"cell": "[readout resonator]"})
        dpath = HERE / "readout.json"
        d0 = design_io.new_design("readout")
        design_io.add_instance(d0, "PAD_W", "BondPad", (1125, 3750), 270)
        design_io.add_instance(d0, "PAD_E", "BondPad", (6375, 3750), 90)
        design_io.add_instance(d0, "Q1", "Xmon", (2975, 2200), 0, {"claws": ["n"], "junction_type": "Trilayer Squid"})
        d0["routes"] = {"R1": {"from": "PAD_W.a", "to": "PAD_E.a", "type": "cpw", "r": 100.0}}
        dpath.write_text(json.dumps(d0), encoding="utf-8")
        err = build_blank(dpath)
        check(res, "build", err is None, err or "")
        mw.load_layout(str(HERE / "build" / "readout.oas"), 0)
        S.open(str(dpath))
        settle()
        S.reload_sidecar(force=True)
        mw.menu().action("@toolbar.qcc_connect").trigger()
        con = tools.ACTIVE[0]
        for pt in (S.data["ports"]["Q1.claw_n"]["pos"], (3125, 3752)):
            con.mouse_moved_event(pya.DPoint(*pt), 0, True)
            con.mouse_click_event(pya.DPoint(*pt), tools.LEFT, True)
        r2 = design_of(dpath).get("routes", {}).get("R2", {})
        check(res, "hanger-route", isinstance(r2.get("to"), dict) and r2["to"].get("hanger") == "R1", json.dumps(r2))
        settle()
        check(res, "hanger-build", S.last_error is None, S.last_error or "")
        rr = (S.data or {}).get("routes", {}).get("R2", {})
        say(f"R2 sidecar length {rr.get('length')}")
        check(res, "hanger-length", bool(rr.get("length")) and 3000 < rr["length"] < 6000, str(rr.get("length")))
        drc = subprocess.run([QCC, "design", "drc", str(dpath)], capture_output=True, text=True, env=session.clean_env(),
                             check=False, encoding="utf-8", errors="replace")
        errs = [ln for ln in drc.stdout.splitlines() if ln.startswith("error")]
        say(f"drc of the readout design: rc {drc.returncode}, errors {errs}")
        check(res, "hanger-drc-no-errors", not errs, str(errs))

    # ==== Run LOM: progress bar + live log, and the time limit stops a long run ================================
    if not only:
        say("=== Run LOM progress / time limit")
        res = RESULTS.setdefault("[LOM progress]", {"cell": "[LOM progress]"})
        dpath = HERE / "q1_r1_feedline.json"
        shutil.copy(REPO / "examples" / "q1_r1_feedline.json", dpath)
        err = build_blank(dpath)
        check(res, "build", err is None, err or "")
        mw.load_layout(str(HERE / "build" / "q1_r1_feedline.oas"), 0)
        S.open(str(dpath))
        settle()
        S.reload_sidecar(force=True)
        seen = []
        real_progress = type(panel)._lom_progress  # noqa: SLF001

        def spy(self, job):
            real_progress(self, job)
            seen.append(self.lom_bar.format if not callable(self.lom_bar.format) else self.lom_bar.format())
        type(panel)._lom_progress = spy  # noqa: SLF001
        try:
            panel.flow_buttons["lom"].click()
            job = jobs.RUNNING[-1] if jobs.RUNNING else None
            if job is not None:
                job.wait(600)
            fmt = panel.lom_bar.format if not callable(panel.lom_bar.format) else panel.lom_bar.format()
            log_text = panel.lom_log.toPlainText()
            say(f"LOM bar formats seen: {sorted(set(f.split(' · ')[0] for f in seen))}; final {fmt!r}")
            check(res, "lom-ok", job is not None and job.ok, panel.lom_status.text)
            check(res, "lom-bar-stages", any("QuCat" in f for f in seen) and fmt.startswith("done in"), f"{seen[-3:]} {fmt}")
            check(res, "lom-log-live", "[lom] solving" in log_text and panel.lom_log.visible, log_text[-300:])
            session.set_config(session.CFG_LOM_LIMIT, 0.002)  # 0.12 s: the run is stopped by the time limit
            panel.flow_buttons["lom"].click()
            job = jobs.RUNNING[-1] if jobs.RUNNING else None
            if job is not None:
                job.wait(120)
            fmt = panel.lom_bar.format if not callable(panel.lom_bar.format) else panel.lom_bar.format()
            check(res, "lom-time-limit-stops", job is not None and job.timed_out and job.proc.poll() is not None
                  and fmt.startswith("stopped at the time limit") and "stopped" in panel.lom_status.text,
                  f"{fmt} / {panel.lom_status.text}")
            check(res, "lom-run-reenabled-after-stop", panel.lom_run.enabled, "Run button stuck disabled")
        finally:
            type(panel)._lom_progress = real_progress  # noqa: SLF001
            session.set_config(session.CFG_LOM_LIMIT, 30)

    # ==== a handler that raises must never reach KLayout (no "Script Error") ===================================
    if not only:
        res = RESULTS.setdefault("[handler guard]", {"cell": "[handler guard]"})
        mw.menu().action("@toolbar.qcc_snap").trigger()
        snap = tools.ACTIVE[0]
        real = type(snap).redraw

        def boom(self):
            raise RuntimeError("test: ghost exploded")
        type(snap).redraw = boom
        n0 = len(session.ERRORS)
        try:
            r1 = snap.mouse_moved_event(pya.DPoint(100, 100), 0, True)
            r2 = snap.mouse_click_event(pya.DPoint(100, 100), tools.RIGHT, True)
            ok = len(session.ERRORS) > n0
            check(res, "mouse handlers swallow errors", ok, f"errors {session.ERRORS[n0:]} -> {r1} {r2}")
        except Exception:  # noqa: BLE001
            check(res, "mouse handlers swallow errors", False, "EXC " + traceback.format_exc().strip().splitlines()[-1])
        finally:
            type(snap).redraw = real
        n1 = len(session.ERRORS)
        try:
            __import__("qcc_kplugin.menu", fromlist=["_safe"])._safe(lambda: 1 / 0, "test action")()
            check(res, "menu actions are wrapped", len(session.ERRORS) > n1, "error not recorded")
        except Exception:  # noqa: BLE001
            check(res, "menu actions are wrapped", False, "EXC " + traceback.format_exc().strip().splitlines()[-1])

    # ---- summary ----
    json.dump(RESULTS, open(HERE / "results.json", "w"), indent=1)
    fails = [(c, k, v) for c, r in RESULTS.items() for k, v in r.items() if isinstance(v, str) and v.startswith("FAIL")]
    say(f"SUMMARY: {len(RESULTS)} cells, {len(fails)} FAIL steps")
    for c, k, v in fails:
        say(f"  FAIL {c} {k}: {v}")
    say("DONE")
except Exception:  # noqa: BLE001
    say("EXCEPTION\n" + traceback.format_exc())
finally:
    try:
        say("log tail:\n" + "\n".join(session.LOG.read_text(encoding="utf-8").splitlines()[-12:]))
    except Exception:  # noqa: BLE001
        pass
    pya.Application.instance().exit(0)
