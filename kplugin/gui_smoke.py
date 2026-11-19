"""Run: set KLAYOUT_HOME to an empty folder, then  klayout_app.exe -e -rm kplugin/load_dev.py -r kplugin/gui_smoke.py
(set QCC_REPO to the repo root and QCC_EXE / QCC_PYTHON to the qcc executable / Python; results in <temp>/qcc_gui_smoke_*/smoke.txt; every checked step prints PASS / FAIL).

GUI smoke test of the Quantcore KLayout plugin, run in a real KLayout window (scratch designs, own KLAYOUT_HOME):
place with rotation, the [ / ] menu actions, Connect pad → pad (route dialog), Connect claw → feedline (hanger
dialog), double-click edit of an instance, native moves / rotates / deletes, the panel's parameter table, Settings.
Then a second design drawn like Q1 + R1 by hand: KLayout's editor grid, port → port, port → line (hanger),
canvas → line (a bare λ/4 from a free open end), a Shift-aligned flux line, port → free end, right-click undo in
Connect; in Route handles node select / Shift move, undo / redo, the curvature (radius) handle, node dialog, insert
and delete (menu and right-click), meander segment (menu and double-click); duplicate and mirror a component; a
native route delete; shortcut clashes with KLayout. Then the menu structure (six submenus, old actions and
shortcuts, flow.ACTIONS contract), the Flow strip, targets in the edit dialog, Check and the LOM run (background
job, LOM tab, circuit PNG). Dialogs are auto-accepted. Writes smoke.txt, then quits."""
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

import pya

HERE = Path(__import__("tempfile").mkdtemp(prefix="qcc_gui_smoke_"))
OUT = HERE / "smoke.txt"
lines = []


def say(s):
    lines.append(str(s))
    OUT.write_text("\n".join(lines), encoding="utf-8")


try:
    sys.path.insert(0, str(Path(os.environ.get("QCC_REPO", ".")) / "kplugin" / "python"))
    from qcc_kplugin import actions, design_io, dock, session, tools  # noqa: E402

    # auto-accept every dialog (exec_ returns 1) so the code after it runs
    pya.QDialog.exec_ = lambda self: 1
    QCC = os.environ.get("QCC_EXE", "qcc")
    session.set_config(session.CFG_QCC, QCC)

    design_path = HERE / "smoke_design.json"
    d = design_io.new_design("smoke")
    design_path.write_text(json.dumps(d), encoding="utf-8")
    layout = HERE / "build" / "smoke_design.oas"

    def build():
        r = subprocess.run([QCC, "build", str(design_path), "-o", str(layout)], capture_output=True, text=True,
                           env=session.clean_env(), check=False, encoding="utf-8", errors="replace")
        return r.returncode if r.returncode == 0 else f"{r.returncode}: {(r.stderr or r.stdout)[-600:]}"

    say(f"build blank: {build()}")
    mw = pya.MainWindow.instance()
    mw.load_layout(str(layout), 0)
    S = session.SESSION
    S.open(str(design_path))
    say(f"session design {S.design_path.name}, data {S.data is not None}")

    # menu: rotate actions with [ ] shortcuts
    menu = mw.menu()
    for a in ("qcc_menu.qcc_edit_menu.qcc_rot_ccw", "qcc_menu.qcc_edit_menu.qcc_rot_cw", "qcc_menu.qcc_design_menu.qcc_chip", "qcc_menu.qcc_design_menu.qcc_new"):
        say(f"menu {a}: valid={menu.is_valid(a)} shortcut={menu.action(a).shortcut if menu.is_valid(a) else None}")

    # panel: parameter table
    dock.show_dock()
    panel = dock.DOCK[0]
    panel.load_components()
    from qcc_kplugin import qcache  # noqa: E402
    qcache.wait()  # the list loads in the background now
    items = [panel.components.item(i) for i in range(panel.components.count)]
    bp = next(i for i in items if i.text == "BondPad")
    panel.components.setCurrentItem(bp)
    panel._select(bp)
    qcache.wait()  # the parameters load in the background
    say(f"panel BondPad rows={panel.table.rowCount} first={panel.table.item(0, 0).text}={panel.table.item(0, 1).text}")

    # place two pads: west pad rotated 270 via the [ action (3 × +90), east pad −90 via ]
    panel._place(bp)
    qcache.wait()  # placement arms once the outline is loaded (background)
    snap = tools.ACTIVE[0] if tools.ACTIVE else None
    say(f"armed: pending={tools.PENDING_PLACE.get('cell')} tool={type(snap).__name__} ghost={bool(tools.PENDING_PLACE.get('ghost'))}")
    for _ in range(3):
        mw.menu().action("qcc_menu.qcc_edit_menu.qcc_rot_ccw").trigger()
    say(f"rot after 3x [: {tools.PENDING_PLACE.get('rot')}")
    snap.mouse_click_event(pya.DPoint(1125, 3750), tools.LEFT, True)
    panel._place(bp)
    qcache.wait()
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_rot_cw").trigger()
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_rot_cw").trigger()
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_rot_cw").trigger()
    snap.mouse_click_event(pya.DPoint(6375, 3750), tools.LEFT, True)
    xm = next(i for i in items if i.text == "Xmon")
    panel.components.setCurrentItem(xm)
    panel._select(xm)
    qcache.wait()
    panel._place(xm)
    qcache.wait()
    snap.mouse_click_event(pya.DPoint(3000, 2200), tools.LEFT, True)
    des = json.loads(design_path.read_text(encoding="utf-8"))
    say("instances: " + json.dumps({k: v["place"] for k, v in des["instances"].items()}))

    # rebuild so the sidecar has ports
    if S.builder is not None:
        S.builder.wait()
    say(f"rebuild: {build()}")
    S.reload_sidecar(force=True)
    ports = S.data.get("ports", {})
    say(f"ports: {sorted(ports)}")

    # Connect pad → pad (route dialog auto-accepted: name R1, cpw)
    mw.menu().action("@toolbar.qcc_connect").trigger()
    con = tools.ACTIVE[0]
    pw, pe = ports["BP1.a"]["pos"], ports["BP2.a"]["pos"]
    con.mouse_click_event(pya.DPoint(*pw), tools.LEFT, True)
    con.mouse_click_event(pya.DPoint(*pe), tools.LEFT, True)
    des = json.loads(design_path.read_text(encoding="utf-8"))
    say("routes after pad→pad: " + json.dumps(des.get("routes")))
    if S.builder is not None:
        S.builder.wait()
    say(f"rebuild: {build()}")
    S.reload_sidecar(force=True)
    claw = S.data["ports"]["X1.claw_n"]["pos"] if "X1.claw_n" in S.data["ports"] else None
    say(f"claw {claw}; routes in sidecar {list(S.data.get('routes', {}))}")
    # Connect claw → feedline (hanger dialog: auto-accepted defaults → meander 4200, coupler 300)
    con.mouse_click_event(pya.DPoint(*claw), tools.LEFT, True)
    con.mouse_click_event(pya.DPoint(3150, 3750), tools.LEFT, True)
    des = json.loads(design_path.read_text(encoding="utf-8"))
    say("routes after claw→line: " + json.dumps(des.get("routes")))
    if S.builder is not None:
        S.builder.wait()
    say(f"rebuild with hanger: {build()}")

    # double-click edit of X1 (auto-accepted: values unchanged → params as before, rotation kept)
    mw.menu().action("@toolbar.qcc_snap").trigger()
    snap = tools.ACTIVE[0]
    S.reload_sidecar(force=True)
    out = tools.edit_instance_dialog("X1", des["instances"]["X1"])
    say(f"edit dialog returns {out}")
    snap.mouse_double_click_event(pya.DPoint(3000, 2200), tools.LEFT, True)
    say("X1 after double-click OK: " + json.dumps(json.loads(design_path.read_text(encoding='utf-8'))["instances"]["X1"]))

    def settle():
        """Wait for the plugin's own rebuild, then run its timer step (reload the view, focus the chip, sync)."""
        while True:
            if S.builder is not None:
                S.builder.wait()
            S._tick()  # noqa: SLF001  (may start a build queued during the last one)
            if S.builder is None:
                break
        S._reload_after = 0.0  # noqa: SLF001
        S._tick()  # noqa: SLF001
        S._tick()  # noqa: SLF001
        S._reload_after = None  # noqa: SLF001  (view is current: native edits sync again)
        S.focus_chip()

    settle()
    view, j = S.find_view()
    chip = S.chip_cell()
    say(f"view cell = chip cell: {view.cellview(j).cell_index == chip.cell_index()} ({chip.name}); built {sorted(S.built)}")

    # KLayout's own move/rotate of a component (as its move tool / Edit > Rotate would) → design.json
    inst = next(i for i in chip.each_inst() if i.property("id") == "X1")
    inst.dcplx_trans = pya.DCplxTrans(1.0, 0.0, False, pya.DVector(3100.0, 2150.0))
    S.sync_native_moves()
    say("native move → X1 place: " + json.dumps(json.loads(design_path.read_text(encoding="utf-8"))["instances"]["X1"]["place"]))
    settle()
    say(f"rebuilt after native move: error={S.last_error}; sidecar X1 at {S.data['instances']['X1']['trans']}")

    # an unconnected component to rotate (rotating X1 would turn its claw away from its readout)
    mw.menu().action("@toolbar.qcc_snap").trigger()
    snap = tools.ACTIVE[0]
    tools.arm_place("Xmon", {})
    snap.mouse_click_event(pya.DPoint(5000, 1500), tools.LEFT, True)
    settle()
    inst2 = next(i for i in S.chip_cell().each_inst() if i.property("id") == "X2")
    inst2.dcplx_trans = pya.DCplxTrans(1.0, 90.0, False, inst2.dcplx_trans.disp)  # KLayout's Edit > Rotate
    S.sync_native_moves()
    say("native rotate → X2 place: " + json.dumps(json.loads(design_path.read_text(encoding="utf-8"))["instances"]["X2"]["place"]))
    settle()

    # Move/Snap: click to pick X1, ] to rotate, click to drop
    mw.menu().action("@toolbar.qcc_snap").trigger()
    snap = tools.ACTIVE[0]
    S.reload_sidecar(force=True)
    at = S.data["instances"]["X2"]["trans"]["at"]
    snap.mouse_click_event(pya.DPoint(*at), tools.LEFT, True)
    say(f"picked: {snap.drag and snap.drag['inst']} (rot {snap.drag and snap.drag['rot']})")
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_rot_cw").trigger()
    snap.mouse_moved_event(pya.DPoint(at[0] + 300, at[1]), 0, True)
    snap.mouse_click_event(pya.DPoint(at[0] + 300, at[1]), tools.LEFT, True)
    say("click-drop → X2 place: " + json.dumps(json.loads(design_path.read_text(encoding="utf-8"))["instances"]["X2"]["place"]))
    settle()
    say(f"rebuilt: error={S.last_error}")

    # Route handles: click an insert handle of the feedline, click to drop it 300 µm higher → a bent route
    mw.menu().action("@toolbar.qcc_route_edit").trigger()
    edit = tools.ACTIVE[0]
    S.reload_sidecar(force=True)
    hs = [h for h in edit.handles() if h[0] == "R1" and h[1] == "insert"]
    say(f"R1 insert handles: {len(hs)}")
    if hs:
        hx, hy = hs[0][3]
        edit.mouse_click_event(pya.DPoint(hx, hy), tools.LEFT, True)
        edit.mouse_moved_event(pya.DPoint(hx, hy + 300), 0, True)
        edit.mouse_click_event(pya.DPoint(hx, hy + 300), tools.LEFT, True)
        say("R1 after bend: " + json.dumps(json.loads(design_path.read_text(encoding="utf-8"))["routes"]["R1"]))
        settle()
        say(f"bent R1 built: error={S.last_error}; polyline points {len(S.data['routes']['R1']['polyline'])}")
        # an oblique bend under R2's hanger coupler cannot route R2: undo it, so the rest runs on a valid design
        mw.menu().action("qcc_menu.qcc_edit_menu.qcc_undo").trigger()
        settle()
        say(f"undo the bend: error={S.last_error}")

    # Edit selected (KLayout selection of X1 → parameter dialog, auto-accepted)
    chip = S.chip_cell()
    inst = next(i for i in chip.each_inst() if i.property("id") == "X2")
    sel = pya.ObjectInstPath()
    sel.top = chip.cell_index()
    sel.append_path(pya.InstElement.new(inst))
    view.object_selection = [sel]
    actions.edit_selected()
    say("edit selected ran; log: " + session.LOG.read_text(encoding="utf-8").splitlines()[-1])

    # KLayout's own Delete on a component (leaves its cell as an extra top cell) → removed from design.json
    settle()
    chip = S.chip_cell()
    next(i for i in chip.each_inst() if i.property("id") == "X2").delete()
    tops = len(list(chip.layout().top_cells()))
    S._tick()  # noqa: SLF001
    gone = 'X2' not in json.loads(design_path.read_text(encoding='utf-8'))['instances']
    say(f"{'PASS' if gone else 'FAIL'} native delete of X2: top cells now {tops}; X2 removed from design: {gone}")
    settle()
    say(f"after delete rebuild: error={S.last_error}")

    # ==== pen tool, grid, Shift, node editing, per-corner radius (a fresh Q1 + R1 design drawn by hand) =========
    from qcc_kplugin import geometry  # noqa: E402

    def check(label, ok, extra=""):
        say(f"{'PASS' if ok else 'FAIL'} {label}" + (f": {extra}" if extra else ""))

    def design_now():
        return json.loads(pen_path.read_text(encoding="utf-8"))

    def built(label):
        settle()
        check(f"{label} builds", S.last_error is None, S.last_error or "")
        t = tools.ACTIVE[0] if tools.ACTIVE else None
        if not (t is not None and t.active):
            say(f"   FAIL the tool was switched off by the rebuild ({label})")

    pen_path = HERE / "pen_design.json"
    pd = design_io.new_design("pen")
    design_io.add_instance(pd, "PAD_W", "BondPad", (1125, 3750), 270)
    design_io.add_instance(pd, "PAD_E", "BondPad", (6375, 3750), 90)
    design_io.add_instance(pd, "PAD_F", "BondPad", (2964.5, 750), 0,
                           {"a": 4, "b": 6, "pad_width": 300, "pad_height": 300, "pad_gap": 150, "taper_length": 300})
    design_io.add_instance(pd, "PAD_N", "BondPad", (3750, 6375), 180)
    design_io.add_instance(pd, "Q1", "Xmon", (2975, 2200), 0,
                           {"cross_length": 300, "arm_width": 25, "gap": 25, "claws": ["n"], "flux_port": True,
                            "junction_type": "Trilayer Squid"})
    pen_path.write_text(json.dumps(pd), encoding="utf-8")
    pen_oas = HERE / "build" / "pen_design.oas"
    r = subprocess.run([QCC, "build", str(pen_path), "-o", str(pen_oas)], capture_output=True, text=True,
                       env=session.clean_env(), check=False, encoding="utf-8", errors="replace")
    say(f"pen design build: {r.returncode}")
    mw.load_layout(str(pen_oas), 0)
    S.open(str(pen_path))
    settle()
    view = pya.LayoutView.current()
    mw.resize(1600, 1200)  # a realistic window, so the 12 px capture radius is ~100 µm, not ~350 µm
    pya.Application.instance().process_events()
    view.zoom_box(pya.DBox(1500, 1000, 6000, 4500))
    pya.Application.instance().process_events()
    app = pya.Application.instance()
    old_grid = app.get_config("edit-grid")
    app.set_config("edit-grid", "5")
    check("grid follows KLayout's edit-grid", abs(S.grid - 5.0) < 1e-9, f"grid {S.grid}")

    mw.menu().action("@toolbar.qcc_connect").trigger()
    con = tools.ACTIVE[0]
    say(f"capture radius {con.capture():.1f} µm")
    P = S.data["ports"]
    SH = tools.LEFT | pya.ButtonState.ShiftKey

    def click(tool, x, y, buttons=tools.LEFT):
        tool.mouse_moved_event(pya.DPoint(x, y), buttons & ~tools.LEFT & ~tools.RIGHT, True)
        tool.mouse_click_event(pya.DPoint(x, y), buttons, True)

    # (a) port → port (feedline), exactly as before: click a port, click a port
    click(con, *P["PAD_W.a"]["pos"])
    click(con, *P["PAD_E.a"]["pos"])
    fl = design_now()["routes"].get("R1")
    check("port→port feedline", fl == {"from": "PAD_W.a", "to": "PAD_E.a", "type": "cpw"},  # no r: the PDK turn radius is not written
          json.dumps(fl))
    built("feedline")
    # (b) port → line: Q1's claw to the feedline (hanger dialog: meander 4200, coupler 300, short)
    click(con, *S.data["ports"]["Q1.claw_n"]["pos"])
    click(con, 3125, 3752)
    r2 = design_now()["routes"].get("R2", {})
    check("port→line hanger readout", isinstance(r2.get("to"), dict) and r2["to"].get("hanger") == "R1"
          and r2.get("from") == "Q1.claw_n" and r2.get("type") == "meander", json.dumps(r2))
    built("claw→line readout")
    # (c) canvas → line: a bare λ/4 (free open end, two nodes with grid + Shift, hanger on the feedline)
    con.mouse_moved_event(pya.DPoint(4512.3, 2001.7), 0, True)
    check("snapped cursor point", con.node_point(con.mouse) == (4510.0, 2000.0), str(con.node_point(con.mouse)))
    click(con, 4512.3, 2001.7)
    check("free start on the grid", con.start_free == (4510.0, 2000.0), str(con.start_free))
    click(con, 4513.0, 3000.2, SH)  # Shift: vertical from the free start
    click(con, 4800.4, 3004.0, SH)  # Shift: horizontal from the last node
    check("Shift + grid nodes", con.waypoints == [(4510.0, 3000.0), (4800.0, 3000.0)], str(con.waypoints))
    click(con, 4950, 3751)
    r3 = design_now()["routes"].get("R3", {})
    check("canvas→line bare λ/4", r3.get("from") == {"at": [4510.0, 2000.0], "term": 6.0}
          and r3.get("nodes") == [[4510.0, 3000.0], [4800.0, 3000.0]] and r3.get("to", {}).get("hanger") == "R1"
          and r3["to"].get("end") == "short" and r3.get("type") == "meander", json.dumps(r3))
    built("bare λ/4 from canvas")
    say(f"R3 built length {S.data['routes']['R3']['length']}")
    # (d) port → port with a Shift node: the flux line PAD_F → Q1.flux (Shift keeps x on the port axis, off-grid)
    click(con, *S.data["ports"]["PAD_F.a"]["pos"])
    click(con, 2966.0, 1500.0, SH)
    click(con, *S.data["ports"]["Q1.flux"]["pos"])
    r4 = design_now()["routes"].get("R4", {})
    check("flux line, Shift aligns to the port axis", r4.get("nodes") == [[2964.5, 1500.0]] and r4.get("to") == "Q1.flux",
          json.dumps(r4))
    built("flux line")
    # (e) port → free end: click the last node again. A click without Shift commits the square corner the preview
    # showed (the user saw an L and got an oblique line before 2026-11-15)
    pn = S.data["ports"]["PAD_N.a"]
    click(con, *pn["pos"])
    stub_end = geometry.add(tuple(pn["pos"]), geometry.mul(tuple(pn["dir"]), con.stub()))
    d = tuple(pn["dir"])
    off = geometry.add(stub_end, geometry.add(geometry.mul(d, 400.0), (-d[1] * 300.0, d[0] * 300.0)))
    con.mouse_moved_event(pya.DPoint(*off), 0, True)
    shown = con.segment_to(con.node_point(con.mouse))
    click(con, *off)
    got = list(con.waypoints)
    square = all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6 for a, b in zip([stub_end] + got, got))
    check("off-axis click commits the previewed L corner", len(got) == 2 and got == shown and square,
          f"preview {shown} committed {got}")
    click(con, 0, 0, tools.RIGHT)
    check("right-click removes the corner with its node", con.waypoints == [] and con.start == "PAD_N.a",
          str(con.waypoints))
    corner = geometry.elbow(stub_end, tuple(pn["dir"]), (3750.0, 5000.0))
    con.mouse_moved_event(pya.DPoint(3750, 5000), 0, True)
    preview_nodes = con.segment_to(con.node_point(con.mouse))
    click(con, 3750, 5000)
    check("click commits the previewed corner", con.waypoints == preview_nodes == corner + [(3750.0, 5000.0)],
          f"preview {preview_nodes} committed {con.waypoints}")
    click(con, 4500, 5002, SH)
    click(con, 4500, 5000)  # the last node again → free end there, pointing back along the last segment
    r5 = design_now()["routes"].get("R5", {})
    check("port→free end", r5.get("to") == {"at": [4500.0, 5000.0], "term": 6.0, "dir": 180.0}
          and r5.get("nodes") == [list(c) for c in corner] + [[3750.0, 5000.0]], json.dumps(r5))
    # Shift draws 45° slants too
    click(con, 1000, 1000)
    click(con, 1302, 1297, SH)
    check("Shift: 45° segment", con.waypoints == [(1300.0, 1300.0)], str(con.waypoints))
    click(con, 0, 0, tools.RIGHT)
    click(con, 0, 0, tools.RIGHT)
    built("route ending in a free end")
    # right-click removes the last node, then cancels
    click(con, 1000, 1000)
    click(con, 1500, 1000)
    click(con, 0, 0, tools.RIGHT)
    n_after_right = len(con.waypoints)
    click(con, 0, 0, tools.RIGHT)
    click(con, 0, 0, tools.RIGHT)
    check("right-click: last node off, then cancel", n_after_right == 0 and not con.started)

    # ---- Route handles
    mw.menu().action("@toolbar.qcc_route_edit").trigger()
    ed = tools.ACTIVE[0]
    S.reload_sidecar(force=True)
    # (f) move a node with Shift: stays vertical under its previous neighbour, on the grid
    click(ed, 4510, 3000)
    check("click selects a node", ed.selected == ("R3", 0), str(ed.selected))
    click(ed, 4515, 2603, SH)
    check("Shift move aligned to neighbour", design_now()["routes"]["R3"]["nodes"][0] == [4510.0, 2605.0],
          json.dumps(design_now()["routes"]["R3"]["nodes"]))
    built("moved node")
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_undo").trigger()
    undone = design_now()["routes"]["R3"]["nodes"][0]
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_redo").trigger()
    redone = design_now()["routes"]["R3"]["nodes"][0]
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_undo").trigger()
    check("undo / redo", undone == [4510.0, 3000.0] and redone == [4510.0, 2605.0], f"{undone} {redone}")
    built("after undo/redo")
    # (g) curvature handle: select the corner (4800, 3000), pick its radius handle, drop it at r = 150
    click(ed, 4800, 3000)
    click(ed, 4800, 3000)  # drop in place: selection only, no edit
    c = ed.corner("R3", 1)
    h = ed.radius_handle()
    check("selected corner shows a radius handle", ed.selected == ("R3", 1) and h is not None, f"{ed.selected} {h}")
    click(ed, *h)
    target = geometry.radius_handle(c[0], c[1], c[2], 151.2)
    click(ed, *target)
    n1 = design_now()["routes"]["R3"]["nodes"][1]
    check("radius handle sets the corner radius (grid)", n1 == {"at": [4800.0, 3000.0], "r": 150.0}, json.dumps(n1))
    built("per-corner radius")
    cells = sorted({S.chip_cell().layout().cell(i.cell_index).name for i in S.chip_cell().each_inst()
                    if i.property("id") == "R3"})
    check("sidecar waypoint_r + corner waveguide", S.data["routes"]["R3"].get("waypoint_r") == [None, 150.0], f"{cells}")
    # (h) node dialog from the menu (auto-accepted: same values)
    ed.selected = ("R3", 1)
    before = design_now()["routes"]["R3"]
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_node_props").trigger()
    check("node properties dialog", design_now()["routes"]["R3"] == before)
    # (i) insert a node on the short straight (the meander keeps the long one), delete it from the menu; insert
    # again, delete it with a right-click
    S.reload_sidecar(force=True)
    ins = [hh for hh in ed.handles() if hh[0] == "R3" and hh[1] == "insert" and hh[2] == 2]
    click(ed, *ins[0][3])
    click(ed, 4652, 3012, SH)  # Shift: stays on the straight between its neighbours
    nodes_ins = design_now()["routes"]["R3"]["nodes"]
    built("inserted node")
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_node_delete").trigger()
    nodes_del = design_now()["routes"]["R3"]["nodes"]
    check("insert (Shift) + delete from the menu", nodes_ins[1] == [4650.0, 3000.0] and len(nodes_ins) == 3
          and len(nodes_del) == 2, f"{nodes_ins} → {nodes_del}")
    built("deleted node")
    ins = [hh for hh in ed.handles() if hh[0] == "R3" and hh[1] == "insert" and hh[2] == 2]
    click(ed, *ins[0][3])
    click(ed, 4630, 3000)
    built("inserted node 2")
    click(ed, 4630, 3000, tools.RIGHT)
    check("right-click deletes a node", len(design_now()["routes"]["R3"]["nodes"]) == 2,
          json.dumps(design_now()["routes"]["R3"]["nodes"]))
    built("right-click delete")
    # (j) meander on the segment under the cursor (menu action), and via a double-click on the route
    ed.mouse_moved_event(pya.DPoint(4510, 2300), 0, True)
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_meander_here").trigger()
    check("meander here (menu)", design_now()["routes"]["R3"].get("meander_segment") == 1,
          str(design_now()["routes"]["R3"].get("meander_segment")))
    built("meander segment")
    ed.mouse_double_click_event(pya.DPoint(4510, 2300), tools.LEFT, True)
    check("double-click on a route: route dialog", design_now()["routes"]["R3"].get("meander_segment") == 1)
    ed.mouse_double_click_event(pya.DPoint(4800, 3000), tools.LEFT, True)
    check("double-click on a node: node dialog", ed.selected == ("R3", 1)
          and design_now()["routes"]["R3"]["nodes"][1] == {"at": [4800.0, 3000.0], "r": 150.0},
          json.dumps(design_now()["routes"]["R3"]["nodes"]))

    # ---- duplicate + mirror a component (Move/Snap, KLayout selection)
    mw.menu().action("@toolbar.qcc_snap").trigger()
    snap = tools.ACTIVE[0]
    S.reload_sidecar(force=True)
    chip = S.chip_cell()
    q1 = next(i for i in chip.each_inst() if i.property("id") == "Q1")
    sel = pya.ObjectInstPath()
    sel.top = chip.cell_index()
    sel.append_path(pya.InstElement.new(q1))
    view.object_selection = [sel]
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_duplicate").trigger()
    snap.mouse_click_event(pya.DPoint(5800, 1500), tools.LEFT, True)
    dup = design_now()["instances"].get("X1", {})
    check("duplicate selected component", dup.get("cell") == "Xmon"
          and dup.get("params") == design_now()["instances"]["Q1"]["params"], json.dumps(dup))
    built("duplicate")
    chip = S.chip_cell()
    x1 = next(i for i in chip.each_inst() if i.property("id") == "X1")
    sel = pya.ObjectInstPath()
    sel.top = chip.cell_index()
    sel.append_path(pya.InstElement.new(x1))
    view.object_selection = [sel]
    mw.menu().action("qcc_menu.qcc_edit_menu.qcc_mirror").trigger()
    check("mirror selected component", design_now()["instances"]["X1"]["place"].get("mirror") is True,
          json.dumps(design_now()["instances"]["X1"]["place"]))
    built("mirror")
    view.object_selection = []

    # ---- KLayout's own Delete on a route instance → removed from design.json
    chip = S.chip_cell()
    next(i for i in chip.each_inst() if i.property("id") == "R5").delete()
    S._tick()  # noqa: SLF001
    check("native delete of a route", "R5" not in design_now()["routes"])
    built("after route delete")

    # ---- shortcuts: ours vs KLayout's own
    ours, theirs = {}, {}

    def walk(path):
        for item in menu.items(path):
            a = menu.action(item)
            sc = a.shortcut or a.default_shortcut
            if sc:
                (ours if item.startswith("qcc_menu") else theirs).setdefault(sc, []).append(item)
            if menu.is_menu(item):
                walk(item)

    walk("")
    clash = {k: (ours[k], theirs[k]) for k in ours if k in theirs}
    check("no shortcut clashes with KLayout", not clash, json.dumps(clash))
    say("edit menu: " + ", ".join(f"{i.split('.')[-1]}={menu.action(i).shortcut}" for i in menu.items("qcc_menu.qcc_edit_menu")))
    app.set_config("edit-grid", old_grid or "")
    final = design_now()
    say("pen design routes: " + json.dumps(final["routes"]))

    # ==== G2: menu structure, Flow strip =======================================================================
    from qcc_kplugin import jobs as jobs_mod  # noqa: E402
    from qcc_kplugin import menu as qmenu  # noqa: E402

    def walk_menu(path):
        out = {}
        for item in menu.items(path):
            out[item.split(".")[-1]] = item
            if menu.is_menu(item):
                out.update(walk_menu(item))
        return out

    allq = walk_menu("qcc_menu")
    tops = [i.split(".")[-1] for i in menu.items("qcc_menu")]
    subs = [t for t in tops if menu.is_menu(f"qcc_menu.{t}")]
    check("menu has 6 submenus: Design, Edit, Check and LOM, Simulate, Results, Fab",
          [menu.action(f"qcc_menu.{t}").title for t in subs] == ["Design", "Edit", "Check and LOM", "Simulate", "Results", "Fab"],
          str([menu.action(f"qcc_menu.{t}").title for t in subs]))
    check("panel and Settings stay at the top level", "qcc_dock" in tops and "qcc_config" in tops, str(tops))
    old = {"qcc_new": "", "qcc_open": "", "qcc_rebuild": "Ctrl+Shift+B",
           "qcc_undo": "Ctrl+Shift+Z", "qcc_redo": "Ctrl+Shift+Y", "qcc_rot_ccw": "[",
           "qcc_rot_cw": "]", "qcc_duplicate": "Ctrl+Shift+U", "qcc_mirror": "Ctrl+Shift+F",
           "qcc_node_delete": "Ctrl+Shift+X", "qcc_node_props": "Ctrl+Shift+N", "qcc_meander_here": "Ctrl+Shift+M",
           "qcc_edit": "Ctrl+Shift+Q", "qcc_dock": "Ctrl+Shift+P", "qcc_drc": "Ctrl+Shift+D",
           "qcc_config": ""}
    missing = [n for n in old if n not in allq]
    check("every kept menu action is still reachable", not missing, str(missing))
    gone = ["qcc_place", "qcc_path_route", "qcc_live", "qcc_sync", "qcc_shot", "qcc_junction", "qcc_delete",
            "qcc_stop_lom", "qcc_export_job", "qcc_open_results"]
    check("the redundant items removed by the audit are gone", not [n for n in gone if n in allq],
          str([n for n in gone if n in allq]))
    changed = {n: menu.action(allq[n]).shortcut for n, sc in old.items() if n in allq and (menu.action(allq[n]).shortcut or "") != sc}
    check("every old shortcut is unchanged", not changed, str(changed))
    check("new LOM action has a shortcut", (menu.action(allq["qcc_run_lom"]).shortcut or "") == "Ctrl+Shift+O")
    check("no duplicate circuit export (Run LOM writes circuit.json; Fab export bundles it)", "qcc_lom" not in allq)
    if qmenu.FILLED:
        check("Save as Python script sits in the Design submenu (one item, not also in Fab)",
              allq.get("qcc_save_python", "").startswith("qcc_menu.qcc_design_menu."), allq.get("qcc_save_python"))
    soon = [n for n in allq if n.endswith("_soon")]
    if qmenu.FILLED:  # flow.ACTIONS existed when the menu was built at startup
        names = set(qmenu.FILLED)
        check("Simulate / Results / Fab are filled from flow.ACTIONS", names <= set(allq), str(names - set(allq)))
    else:
        check("without flow.ACTIONS the three flow submenus show '(coming soon)' disabled",
              len(soon) == 3 and all(not menu.action(allq[n]).enabled for n in soon), str(soon))
    # the flow contract with a fake ACTIONS list, on a throw-away menu root
    hits = []
    real_actions, real_root = qmenu.flow_actions, qmenu.ROOT
    qmenu.flow_actions = lambda: [("simulate", "t_sim", "Fake simulate", lambda: hits.append("sim"), "Ctrl+Alt+F9"),
                                  ("fab", "t_fab", "Fake fab", lambda: hits.append("fab"), "")]
    qmenu.ROOT = "qcc_test_menu"
    try:
        qmenu.build(menu)
        tm = walk_menu("qcc_test_menu")
        menu.action(tm["t_sim"]).trigger()
        menu.action(tm["t_fab"]).trigger()
        parts = {"triggered": hits == ["sim", "fab"], "shortcut": menu.action(tm["t_sim"]).shortcut,
                 "results placeholder disabled": not menu.action(tm["qcc_results_menu_soon"]).enabled,
                 "simulate has no placeholder": "qcc_simulate_menu_soon" not in tm}
        check("flow.ACTIONS tuples become menu items (shortcut kept, empty submenus get a placeholder)",
              parts["triggered"] and parts["shortcut"] == "Ctrl+Alt+F9" and parts["results placeholder disabled"]
              and parts["simulate has no placeholder"], str(parts))
    finally:
        qmenu.flow_actions, qmenu.ROOT = real_actions, real_root
        menu.delete_item("qcc_test_menu")
    check("throw-away menu removed", not menu.is_valid("qcc_test_menu"))

    dock.show_dock()
    panel = dock.DOCK[0]
    keys = list(panel.flow_buttons)
    check("Flow strip has Design, Check, LOM, Simulate, Results, Fab", keys == ["design", "check", "lom", "simulate", "results", "fab"], str(keys))
    check("Flow buttons carry a status mark and a tooltip",
          all(b.text[-1] in "✓⚠–" and len(b.toolTip) > 30 for b in panel.flow_buttons.values()),
          json.dumps({k: b.text for k, b in panel.flow_buttons.items()}, ensure_ascii=False))
    panel.show_tab("DRC")
    panel.flow_buttons["design"].click()
    check("Flow Design shows the Components tab", panel.tabs.tabText(panel.tabs.currentIndex) == "Components")
    st_before = panel.flow_state()
    check("Flow status: Design done, Check not yet, Fab not yet",
          st_before["design"] == "done" and st_before["check"] == "todo" and st_before["fab"] == "todo", str(st_before))
    has_flow = True
    try:
        from qcc_kplugin import flow as _flow  # noqa: F401
    except Exception:  # noqa: BLE001
        has_flow = False
    if not has_flow:
        panel.flow_buttons["simulate"].click()
        check("Flow Simulate without the flow module says 'not available yet'",
              "not available yet" in session.LOG.read_text(encoding="utf-8").splitlines()[-1],
              session.LOG.read_text(encoding="utf-8").splitlines()[-1])

    # ==== G3: targets in the edit dialog, Check, LOM tab ========================================================
    lom_design = HERE / "lom_design.json"
    lom_design.write_text((Path(os.environ.get("QCC_REPO", ".")) / "examples" / "q1_r1_feedline.json").read_text(encoding="utf-8"), encoding="utf-8")
    ld = json.loads(lom_design.read_text(encoding="utf-8"))
    ld["name"] = "lom_design"
    ld["targets"] = {"Q1": {"f_q_GHz": 5.2, "alpha_MHz": -320.0}, "R1": {"f_GHz": 6.65, "kappa_MHz": 0.5}}
    lom_design.write_text(json.dumps(ld), encoding="utf-8")
    r = subprocess.run([QCC, "build", str(lom_design), "-o", str(HERE / "build" / "lom_design.oas")], capture_output=True,
                       text=True, env=session.clean_env(), check=False, encoding="utf-8", errors="replace")
    check("LOM design builds", r.returncode == 0, (r.stderr or r.stdout)[-300:])
    S.open(str(lom_design))
    settle()

    # targets rows in the instance edit dialog (qubit) with typed values
    typed = {}
    real_exec = pya.QDialog.exec_

    def fill_then_accept(self):
        ed = getattr(self, "targets_editor", None)
        if ed is not None:
            typed["keys"] = list(ed.edits)
            typed["shown"] = {k: e.text for k, e in ed.edits.items()}
            for k, txt in typed.get("set", {}).items():
                ed.edits[k].text = txt
        return 1

    pya.QDialog.exec_ = fill_then_accept
    typed["set"] = {"f_q_GHz": "5.35", "alpha_MHz": "-300"}
    des_l = design_io.read_design(lom_design)
    out = tools.edit_instance_dialog("Q1", des_l["instances"]["Q1"], des_l["targets"].get("Q1", {}))
    check("edit dialog shows the qubit target rows with the current values",
          typed.get("keys") == ["f_q_GHz", "alpha_MHz"] and typed["shown"]["f_q_GHz"] == "5.2", json.dumps(typed))
    check("edit dialog returns the typed targets", out is not None and out[2] == {"f_q_GHz": 5.35, "alpha_MHz": -300.0}, str(out))
    what = tools.apply_instance_edit(des_l, "Q1", out)
    design_io.write_design(lom_design, des_l)
    check("targets written to design.json (additive, schema's targets key)",
          design_io.read_design(lom_design)["targets"]["Q1"] == {"f_q_GHz": 5.35, "alpha_MHz": -300.0}
          and design_io.read_design(lom_design)["targets"]["R1"] == {"f_GHz": 6.65, "kappa_MHz": 0.5}, what)
    typed["set"] = {"f_q_GHz": "", "alpha_MHz": ""}
    out = tools.edit_instance_dialog("Q1", des_l["instances"]["Q1"], des_l["targets"]["Q1"])
    tools.apply_instance_edit(des_l, "Q1", out)
    check("emptied target fields remove the entry", "Q1" not in des_l.get("targets", {}), str(des_l.get("targets")))
    typed["set"] = {"f_q_GHz": "5.2", "alpha_MHz": "-320"}
    out = tools.edit_instance_dialog("Q1", {**des_l["instances"]["Q1"]}, {})
    tools.apply_instance_edit(des_l, "Q1", out)
    design_io.write_design(lom_design, des_l)
    pya.QDialog.exec_ = real_exec

    # Check: full DRC + netlist check in a background process, DRC tab
    panel.flow_buttons["check"].click()
    check("Flow Check shows the DRC tab", panel.tabs.tabText(panel.tabs.currentIndex) == "DRC")
    job = jobs_mod.RUNNING[-1] if jobs_mod.RUNNING else None
    check("Check runs in a background job (UI not blocked)", job is not None and not job.finished)
    if job is not None:
        job.wait(300)
    check("Check result listed in the DRC tab", panel.full_check is not None and
          any("full check" in panel.drc.item(i).text for i in range(panel.drc.count)),
          str([panel.drc.item(i).text for i in range(panel.drc.count)][:6]))
    check("Flow status: Check done after running it", panel.flow_state()["check"] in ("done", "warn"), str(panel.flow_state()))

    # LOM: export + simulate in the background, LOM tab, circuit picture
    S.reload_sidecar(force=True)
    panel.flow_buttons["lom"].click()
    check("Flow LOM shows the LOM tab", panel.tabs.tabText(panel.tabs.currentIndex) == "LOM")
    job = jobs_mod.RUNNING[-1] if jobs_mod.RUNNING else None
    check("LOM runs in a background job and the Run button is disabled meanwhile",
          job is not None and not job.finished and not panel.lom_run.enabled)
    t0 = __import__("time").time()
    if job is not None:
        job.wait(600)
    say(f"LOM job took {__import__('time').time() - t0:.1f} s, ok={job.ok if job else None}")
    check("LOM job succeeded", job is not None and job.ok, (job.output[-500:] if job else ""))
    lom_json = HERE / "build" / "lom_design" / "lom.json"
    lom_png = HERE / "build" / "lom_design" / "lom.png"
    circ = HERE / "build" / "lom_design.circuit.json"
    check("circuit.json, lom.json and lom.png were written", circ.exists() and lom_json.exists() and lom_png.exists())
    panel.load_lom()
    labels = [panel.lom_modes.item(i, 1).text for i in range(panel.lom_modes.rowCount)]
    check("LOM tab lists the modes (qubit and resonator)", "Q1" in labels and "R1" in labels, str(labels))
    params = {panel.lom_params.item(i, 0).text: (panel.lom_params.item(i, 1).text, panel.lom_params.item(i, 2).text,
                                                  panel.lom_params.item(i, 3).text)
              for i in range(panel.lom_params.rowCount)}
    check("LOM tab shows derived parameters with their targets and a status",
          all(k in params for k in ("Q1.f_q_GHz", "Q1.alpha_MHz", "R1.f_GHz", "R1.chi_MHz", "R1.kappa_MHz"))
          and params["Q1.f_q_GHz"][1].startswith("5.2") and params["Q1.f_q_GHz"][2] in ("within tolerance", "off")
          and params["R1.chi_MHz"][1] == "", json.dumps(params))
    nets = [panel.lom_net.item(i, 0).text for i in range(panel.lom_net.rowCount)]
    check("LOM tab lists the netlist values (C, L / Lj, ...)", "C_Q1" in nets and "J_Q1" in nets, str(nets))
    vals = [panel.lom_net.item(i, 3).text for i in range(panel.lom_net.rowCount)]
    pair = next((v for v in vals if "‖" in v), "")
    check("a C ‖ L value carries one unit per value (e.g. 302 fF ‖ 1.49 nH)",
          not pair or (pair.count("fF") == 1 and pair.split("‖")[0].strip().endswith("fF")
                       and pair.strip().endswith("nH")), pair)
    pix = pya.QPixmap(str(lom_png))
    check("circuit picture is a PNG and shown in the tab", lom_png.stat().st_size > 5000 and not pix.isNull()
          and panel.lom_open.enabled and panel.lom_png == lom_png, f"{lom_png.stat().st_size} bytes {pix.width()}x{pix.height()}")
    panel.open_png()
    check("full-size picture opens in a non-modal window", len(panel.viewers) == 1 and panel.viewers[0].isVisible())
    panel.viewers[0].close()
    check("Flow status: LOM done after the run", panel.flow_state()["lom"] == "done", str(panel.flow_state()))
    menu.action(allq["qcc_run_lom"]).trigger()
    j2 = jobs_mod.RUNNING[-1] if jobs_mod.RUNNING else None
    check("LOM menu action starts the same background job", j2 is not None and not j2.finished)
    if j2 is not None:
        j2.wait(600)

    try:  # a picture of the panel for the report (optional)
        panel.show_tab("LOM")
        panel.dock.resize(420, 900)
        pya.Application.instance().process_events()
        shot = HERE / "panel_lom.png"
        panel.dock.grab().save(str(shot))
        say(f"panel picture: {shot}")
    except Exception as e:  # noqa: BLE001
        say(f"panel picture skipped: {e!r}")

    # settings dialog builds (auto-accepted; writes the same values back)
    actions.configure()
    say("settings dialog ok")
    say("DONE")
except Exception:  # noqa: BLE001
    say("EXCEPTION\n" + traceback.format_exc())
finally:
    say("log tail:\n" + "\n".join(session.LOG.read_text(encoding="utf-8").splitlines()[-12:]) if "session" in dir() else "")
    pya.Application.instance().exit(0)
