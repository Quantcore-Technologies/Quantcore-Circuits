"""Run (fresh KLAYOUT_HOME seeded with a klayoutrc):
    set KLAYOUT_HOME=<scratch folder with a klayoutrc>
    "%APPDATA%\\KLayout\\klayout_app.exe" -e -rm kplugin/load_dev.py -r kplugin/gui_smoke_pcell.py
Results: <temp>/qcc_gui_pcell_*/smoke.txt (every checked step prints PASS / FAIL, timings print as TIME).

GUI smoke test of the live PCells (G7, qcc_kplugin.pcells) in a real KLayout window, on a scratch copy of the Q1 + R1
example: Settings > live PCells on registers the "Quantcore" library (one ``qcc components --schemas`` call); after
each build the components are library PCells whose geometry equals the build's; KLayout's own Instance tool (driven
with ``send_mouse_*`` events) places a Quantcore Xmon with a parameter, which is written to design.json with its
``id``; a parameter changed through the PCell API (what the PCell dialog does) is written back; rebuilds give the same
geometry; Quantcore Undo restores both; native moves still sync; the palette placement still works; off again gives
the static cells back.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import pya

HERE = Path(tempfile.mkdtemp(prefix="qcc_gui_pcell_"))
OUT = HERE / "smoke.txt"
lines = []
REPO = Path(os.environ.get("QCC_REPO", "."))


def say(s):
    lines.append(str(s))
    OUT.write_text("\n".join(lines), encoding="utf-8")


def check(label, ok, extra=""):
    say(f"{'PASS' if ok else 'FAIL'} {label}" + (f": {extra}" if extra else ""))


def timing(label, seconds):
    say(f"TIME {label}: {seconds * 1000:.0f} ms")


try:
    sys.path.insert(0, str(REPO / "kplugin" / "python"))
    from qcc_kplugin import actions, design_io, pcells, session, tools  # noqa: E402

    pya.QDialog.exec_ = lambda self: 1
    QCC = os.environ.get("QCC_EXE", "qcc")
    session.set_config(session.CFG_QCC, QCC)
    S = session.SESSION
    L = pcells.LIVE
    mw = pya.MainWindow.instance()
    app = pya.Application.instance()

    design_path = HERE / "q1p.json"
    d = json.loads((REPO / "examples" / "q1_r1_feedline.json").read_text(encoding="utf-8"))
    d["name"] = "q1p"
    design_path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    layout_path = HERE / "build" / "q1p.oas"

    def qcc(*args):
        return subprocess.run([QCC, *map(str, args)], capture_output=True, text=True, env=session.clean_env(),
                              check=False, encoding="utf-8", errors="replace")

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.process_events()
            time.sleep(0.03)

    def settle():
        """Wait for the build that a commit started, reload the view (the session's own path), let it liven."""
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
        app.process_events()

    def design_now():
        return json.loads(design_path.read_text(encoding="utf-8"))

    def chip():
        return S.chip_cell()

    def inst_by_id(name):
        c = chip()
        return next((i for i in c.each_inst() if str(i.property("id") or "") == name), None)

    def regions(cell):
        out = {}
        ly = cell.layout()
        for li in ly.layer_indexes():
            r = pya.Region()
            r.insert(cell.begin_shapes_rec(li))
            if not r.is_empty():
                out[str(ly.get_info(li))] = r
        return out

    def built_regions(name):
        """The instance's cell as qcc wrote it (the OAS on disk, static), by layer."""
        ly = pya.Layout()
        ly.read(str(layout_path))
        top = ly.top_cell()
        dchip = design_io.find_chip_cell(top)
        inst = next(i for i in dchip.each_inst() if str(i.property("id") or "") == name)
        return regions(ly.cell(inst.cell_index))

    def same_geometry(a, b):
        if set(a) != set(b):
            return False, f"layers {sorted(set(a) ^ set(b))}"
        bad = [k for k in a if not (a[k] ^ b[k]).is_empty()]
        return not bad, f"differs on {bad}" if bad else f"{len(a)} layers equal"

    def live_geometry_ok(name):
        inst = inst_by_id(name)
        if inst is None:
            return False, "no instance"
        return same_geometry(regions(chip().layout().cell(inst.cell_index)), built_regions(name))

    def is_live(name):
        inst = inst_by_id(name)
        return inst is not None and pcells.library_cell_name(inst, chip().layout()) is not None

    r = qcc("build", design_path, "-o", layout_path)
    check("design builds", r.returncode == 0, (r.stderr or r.stdout)[-300:])
    mw.load_layout(str(layout_path), 0)
    S.open(str(design_path))
    settle()
    names = sorted(design_now()["instances"])
    check("default off: components are static cells", not L.enabled() and not any(is_live(n) for n in names))

    # ---- Settings > live PCells on: the library ------------------------------------------------------------------
    t0 = time.time()
    session.set_config(pcells.CFG_LIVE, "true")
    L.start(wait=True)
    timing("schemas (qcc components --schemas) + library registration + liven", time.time() - t0)
    lib = pya.Library.library_by_name(pcells.LIB_NAME)
    cells = lib.layout().pcell_names() if lib is not None else []
    check("the 'Quantcore' library is registered with the PDK cells", lib is not None and {"Xmon", "BondPad",
          "QubitResonator"} <= set(cells), f"{len(cells)} cells")
    check("library cells carry the schema as PCell parameters (Xmon: junction_type with choices, a as double)",
          lib is not None and any(p.name == "junction_type" and p.choice_values() for p in
                                  lib.layout().pcell_declaration("Xmon").get_parameters()))

    # after the library arrived, the components in the view are library PCells with the built geometry
    t0 = time.time()
    settle()
    timing("rebuild-free liven of the open view (focus)", time.time() - t0)
    live = [n for n in names if is_live(n)]
    check("every Quantcore component is now a live library PCell (routes stay static)", live == names
          and not is_live("FL"), f"live {live}")
    check("each keeps its id property and transform", sorted(S.built) == sorted(design_io.placed_instances(chip())))
    for n in names:
        ok, why = live_geometry_ok(n)
        check(f"{n}: live PCell geometry == qcc build", ok, why)
    n_hist = len(S.history)
    before = design_path.read_text(encoding="utf-8")
    for _ in range(6):
        S._tick()  # noqa: SLF001
        L.tick()
    check("no spurious design.json writes from the swap (native-move sync sees no change)",
          len(S.history) == n_hist and design_path.read_text(encoding="utf-8") == before)
    check("sidecar overlays still there (ports)", "Q1.claw_n" in (S.data or {}).get("ports", {}))
    say(f"INFO the view's layout counts as modified after the swap: {S.find_view()[0].is_dirty()}")

    # ---- KLayout's own Instance tool places a Quantcore Xmon ------------------------------------------------------
    view, _ = S.find_view()
    view.zoom_box(pya.DBox(0, 0, 7500, 7500))
    app.process_events()
    mw.set_config("edit-inst-lib-name", pcells.LIB_NAME)
    mw.set_config("edit-inst-cell-name", "Xmon")
    mw.set_config("edit-inst-pcell-parameters", "!junction_type:'Quantcore Squid';cross_length:##250;")
    mw.set_config("edit-inst-angle", "90")
    view.switch_mode("instance")
    app.process_events()
    target = pya.DPoint(5200, 5600)

    def pixel():
        """``target`` in the view's pixels, computed afresh once the canvas size has settled (the window and the
        Editor Options dock can still be resizing it)."""
        sizes, end = [], time.time() + 10
        while time.time() < end and (len(sizes) < 3 or len(set(sizes[-3:])) > 1):
            pump(0.2)
            sizes.append((view.viewport_width(), view.viewport_height()))
        view.zoom_box(pya.DBox(0, 0, 7500, 7500))
        app.process_events()
        px = view.viewport_trans() * target
        return pya.DPoint(px.x, view.viewport_height() - px.y)

    pix = pixel()
    produced = L.provider.produced
    t0 = time.time()
    view.send_mouse_move_event(pix, 0)
    app.process_events()
    timing("Instance tool preview of an unbuilt parameter set (UI thread)", time.time() - t0)
    check("the Instance tool asked our PCell for a preview", L.provider.produced > produced,
          f"produce calls {L.provider.produced - produced}")
    key = pcells.params_key("Xmon", {"junction_type": "Quantcore Squid", "cross_length": 250})
    check("the unbuilt parameter set is previewed and queued for a background fetch",
          key in L.provider.fallback and (key in L.provider.queue or (L.provider.running or ("",))[0] == key))
    t0 = time.time()
    while L.provider.busy() and time.time() - t0 < 60:
        L.tick()
        pump(0.05)
    timing("background qcc components --oas fetch (UI stays responsive)", time.time() - t0)
    fetched = L.provider.cache.get(key)
    check("the fetch cached the geometry for these parameters", fetched is not None, str(L.provider.failed))
    fetched_regions = regions(fetched) if fetched is not None else {}
    check("the Instance tool is still on after the library refresh", view.mode_name() == "instance", view.mode_name())
    pix = pixel()
    view.send_mouse_move_event(pix, 0)  # the refresh restarted the tool: the preview comes back with the mouse
    app.process_events()
    n_hist = len(S.history)
    def n_live():
        return sum(1 for i in chip().each_inst() if pcells.library_cell_name(i, chip().layout()))

    known = n_live()
    view.send_mouse_press_event(pix, pya.ButtonState.LeftButton)
    view.send_mouse_release_event(pix, pya.ButtonState.LeftButton)
    say(f"  instances right after the click: {sorted(str(i.property('id') or '-') for i in chip().each_inst())}")
    app.process_events()
    say(f"  ... after processing events: {sorted(str(i.property('id') or '-') for i in chip().each_inst())}")
    check("the Instance tool click inserted one Quantcore library PCell in the chip cell", n_live() == known + 1,
          f"{known} -> {n_live()}")
    view.switch_mode("select")
    t0 = time.time()
    S._tick()  # noqa: SLF001  the session timer picks it up (it may already have, while events were processed)
    timing("sync of the new instance to design.json (tick)", time.time() - t0)
    des = design_now()
    added = [n for n in des["instances"] if n not in names]
    entry = des["instances"][added[0]] if added else {}
    px_um = 1.0 / view.viewport_trans().mag  # one screen pixel in µm (the click position is a pixel)
    at = entry.get("place", {}).get("at", [0, 0])
    check("design.json got the instance: cell, params, rotation", len(added) == 1
          and entry.get("cell") == "Xmon" and entry.get("params") == {"junction_type": "Quantcore Squid",
                                                                       "cross_length": 250}
          and entry.get("place", {}).get("rot") == 90.0, json.dumps(entry))
    check("... at the clicked point (within a pixel, on the editor grid)", abs(at[0] - target.x) <= 1.5 * px_um
          and abs(at[1] - target.y) <= 1.5 * px_um, f"{at} vs {target}, pixel {px_um:.1f} um")
    check("one Quantcore undo step", len(S.history) == n_hist + 1, f"{n_hist} -> {len(S.history)}")
    xname = added[0] if added else "?"
    check("the placed instance carries its id", inst_by_id(xname) is not None)
    t0 = time.time()
    settle()
    timing("rebuild + reload + liven after the placement", time.time() - t0)
    check("after the rebuild it is a live PCell again", S.last_error is None and is_live(xname), str(S.last_error))
    ok, why = live_geometry_ok(xname)
    check("its geometry == the qcc build", ok, why)
    ok, why = same_geometry(fetched_regions, built_regions(xname))
    check("the background fetch (--oas --design) gave exactly the build's geometry", ok, why)

    # ---- a parameter changed through the PCell API (what KLayout's PCell dialog does) -------------------------------
    q1 = inst_by_id("Q1")
    old_params = dict(design_now()["instances"]["Q1"]["params"])
    t0 = time.time()
    q1.change_pcell_parameter("cross_length", 340.0)
    dt = time.time() - t0
    timing("PCell parameter change in KLayout (produce with a preview, UI thread)", dt)
    check("the change keeps the id property", inst_by_id("Q1") is not None)
    n_hist = len(S.history)
    S._tick()  # noqa: SLF001
    p = design_now()["instances"]["Q1"]["params"]
    check("design.json Q1.params.cross_length = 340 (other params kept)", p.get("cross_length") == 340
          and {k: v for k, v in p.items() if k != "cross_length"} == {k: v for k, v in old_params.items()
                                                                       if k != "cross_length"}, json.dumps(p))
    check("one Quantcore undo step for the dialog edit", len(S.history) == n_hist + 1)
    settle()
    check("Q1 is live after the rebuild, with cross_length 340", S.last_error is None and is_live("Q1")
          and inst_by_id("Q1").pcell_parameters_by_name().get("cross_length") == 340)
    ok, why = live_geometry_ok("Q1")
    check("Q1 geometry == the qcc build after the edit", ok, why)

    # ---- undo / redo ----------------------------------------------------------------------------------------------
    S.undo()
    settle()
    check("Undo restores Q1's parameters in design.json", design_now()["instances"]["Q1"]["params"] == old_params)
    check("... and in the live PCell", inst_by_id("Q1").pcell_parameters_by_name().get("cross_length") == 300)
    ok, why = live_geometry_ok("Q1")
    check("Q1 geometry == the qcc build after undo", ok, why)
    S.undo()
    settle()
    check("a second Undo removes the Instance-tool placement", xname not in design_now()["instances"]
          and inst_by_id(xname) is None)
    S.redo()
    settle()
    check("Redo puts it back (live, same id)", xname in design_now()["instances"] and is_live(xname))
    S.undo()
    settle()

    # ---- native move of a live PCell still syncs -------------------------------------------------------------------
    pad = inst_by_id("PAD_E")  # (the readout hanger sits at s = 2000 µm from FL's start: move the far pad)
    pad.transform(pya.DTrans(pya.DVector(-100, 0)))
    S._tick()  # noqa: SLF001
    check("native move of a live PCell → design.json", design_now()["instances"]["PAD_E"]["place"]["at"]
          == [6275.0, 3750.0], json.dumps(design_now()["instances"]["PAD_E"]["place"]))
    settle()
    check("the move rebuilds and the pad is live again", S.last_error is None and is_live("PAD_E"), str(S.last_error))
    S.undo()
    settle()

    # ---- the palette placement is unchanged --------------------------------------------------------------------------
    tools.arm_place("BondPad", {}, 0.0)
    snap = tools.ACTIVE[0] if tools.ACTIVE else None
    snap.mouse_click_event(pya.DPoint(4000, 6500), tools.LEFT, True)
    des = design_now()
    padded = [n for n in des["instances"] if n not in names]
    check("palette placement still writes design.json", len(padded) == 1 and des["instances"][padded[0]]["cell"]
          == "BondPad", json.dumps(padded))
    settle()
    check("... and the palette-placed pad becomes live too", bool(padded) and is_live(padded[0]))
    S.undo()
    settle()

    # ---- off again ------------------------------------------------------------------------------------------------
    actions.set_live_pcells(False)
    actions.rebuild()
    settle()
    check("Settings off: the next build shows static cells again", not any(is_live(n) for n in names))
    say(f"log: produce calls {L.provider.produced}, fetch failures {L.provider.failed}")
    say("DONE")
except Exception:  # noqa: BLE001
    say("EXCEPTION\n" + traceback.format_exc())
finally:
    try:
        say("log tail:\n" + "\n".join(session.LOG.read_text(encoding="utf-8").splitlines()[-12:]))
    except Exception:  # noqa: BLE001
        pass
    try:
        session.set_config("qcc-kplugin-live-pcells", "false")
    except Exception:  # noqa: BLE001
        pass
    pya.Application.instance().exit(0)
