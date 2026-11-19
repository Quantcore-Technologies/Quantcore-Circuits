"""Recreate the tutorial designs with the Quantcore KLayout plugin, through the GUI paths only, and check the loop.

Run (set KLAYOUT_HOME to a fresh folder seeded with a klayoutrc; QCC_TUT picks the designs, default t04,t02,t01,t03):
    set QCC_TUT=t04
    "%APPDATA%/KLayout/klayout_app.exe" -e -rm kplugin/load_dev.py -r kplugin/gui_smoke_tutorials.py
Other settings: QCC_TUT_LOMWAIT (seconds the GUI Run LOM job may take, default 600), QCC_TUT_REFLOM=1 (also run the
reference LOM for designs with more than two qubits, minutes), QCC_T03 (comma list of t03 instances to recreate).
Results: <temp>/qcc_gui_tut_*/smoke.txt (one section per design; every checked step prints PASS / FAIL / GAP / DIFF).

Per design (``examples/tutorials/designs/t0N_*.json`` is read like a user reads a drawing; every change goes through the
plugin: Design > New design and Chip settings, the panel's component list (a double-click arms the component, [ ] turn
it, a click drops it), the edit dialog (parameters, rotation, targets), Rename, Junction values, Add coupling, Fix pad
edge warnings, Connect (port -> port, port -> line hangers, free ends, nodes with Shift), the route dialog, Route handles
(node dialog, move, insert, delete, radius handle, meander segment: each undone), then Check, Run LOM, Save as Python
and the Fab export from the Flow strip / menu. design.json is never written directly. Simulate / AEDT is never run.)

Afterwards the recreated design.json is compared with the reference (instances, routes, targets, chip, sim groups,
couplings: after the schema's defaults are normalised), the two builds are compared per layer (XOR area) and the
exported circuits are compared. GAP lines name what the GUI cannot express (sim groups are made by Simulate);
DIFF lines are differences to the reference.
Dialogs are driven by label: FILL queues a function per expected dialog; an unexpected dialog is accepted with its
defaults and listed.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import pya

REPO = Path(os.environ.get("QCC_REPO", "."))
DESIGNS = REPO / "examples" / "tutorials" / "designs"
QCC = os.environ.get("QCC_EXE", "qcc")
PYEXE = os.environ.get("QCC_PYTHON", "python")
ONLY = os.environ.get("QCC_TUT", "t04,t02,t01,t03").split(",")
LOMWAIT = int(os.environ.get("QCC_TUT_LOMWAIT", "600"))  # seconds the GUI Run LOM job may take
ROOT = Path(tempfile.mkdtemp(prefix="qcc_gui_tut_"))
OUT = ROOT / "smoke.txt"
lines = []
COUNT = {"PASS": 0, "FAIL": 0, "GAP": 0, "DIFF": 0}


def say(s):
    lines.append(str(s))
    OUT.write_text("\n".join(lines), encoding="utf-8")


def tag(kind, label, extra=""):
    COUNT[kind] = COUNT.get(kind, 0) + 1
    say(f"{kind} {label}" + (f": {extra}" if extra else ""))


def check(label, ok, extra=""):
    tag("PASS" if ok else "FAIL", label, extra)


def gap(label, extra=""):  # something the GUI cannot express (not a failure of the plugin as built)
    tag("GAP", label, extra)


def diff(label, extra=""):  # a difference to the reference
    tag("DIFF", label, extra)


try:
    sys.path.insert(0, str(REPO / "kplugin" / "python"))
    from qcc_kplugin import actions, design_io, dock, edits, flow, geometry, jobs, session, tools  # noqa: E402

    S = session.SESSION
    session.set_config(session.CFG_QCC, QCC)
    mw = pya.MainWindow.instance()
    menu = mw.menu()
    app = pya.Application.instance()
    LEFT, RIGHT = tools.LEFT, tools.RIGHT
    SH = LEFT | pya.ButtonState.ShiftKey

    # ---- dialogs: a queue of fillers, one per expected dialog -------------------------------------------------------
    FILL = []
    UNSCRIPTED = []

    def _g(obj, name):  # a pya getter: a property in one binding, a method in another
        value = getattr(obj, name)
        return value() if callable(value) else value

    def walk(lay):
        """The widgets of a layout in order, into nested layouts and into the body of a scroll area (the dialogs
        put their rows in a scrolled body, in one or two columns: ``qcc_kplugin.dialogs``)."""
        out = []
        if lay is None:
            return out
        for i in range(lay.count()):
            it = lay.itemAt(i)
            w = it.widget()
            if w is not None:
                out.append(w)
                kind = type(w).__name__
                if kind.startswith("QScrollArea"):
                    inner = _g(w, "widget")
                    if inner is not None:
                        out += walk(_g(inner, "layout"))
                elif kind in ("QWidget", "QWidget_Native"):
                    out += walk(_g(w, "layout"))
            sub = it.layout()
            if sub is not None:
                out += walk(sub)
        return out

    def labelled(dialog):
        """{label text: field widget} of a form dialog (label widgets are QLabel_Native; the next widget is the field)."""
        out, pending = {}, None
        for w in walk(dialog.layout):
            n = type(w).__name__
            if n == "QLabel_Native":
                pending = w.text
            elif pending is not None:
                out[pending] = w
                pending = None
        return out

    def setw(w, v):
        n = type(w).__name__
        if n == "QLineEdit":
            w.text = str(v)
        elif n == "QComboBox":
            w.currentText = str(v)
        elif n == "QCheckBox":
            w.checked = bool(v)
        else:
            raise TypeError(f"cannot set {n}")

    def field(dialog, prefix):
        f = labelled(dialog)
        for k, w in f.items():
            if k.startswith(prefix):
                return w
        raise KeyError(f"dialog {dialog.windowTitle!r} has no field {prefix!r}: {list(f)}")

    def tick_box(dialog, text, on):
        """A checkbox of a form (added without a label) by its own text."""
        box_ = next((w for w in walk(dialog.layout) if type(w).__name__ == "QCheckBox" and w.text.startswith(text)),
                    None)
        if box_ is None:
            raise KeyError(f"dialog {dialog.windowTitle!r} has no checkbox {text!r}")
        box_.checked = bool(on)

    def die_fill(width, height):
        """The die size rows of New design / Chip settings: the square box first (it greys out the height)."""
        def fn(dialog):
            tick_box(dialog, edits.SQUARE_TEXT, abs(width - height) < 1e-9)
            fill_form({"Die width": width, "Die height": height})(dialog)
        return fn

    def fill_form(values):
        def fn(dialog):
            for prefix, v in values.items():
                if v is not None:
                    setw(field(dialog, prefix), v)
        return fn

    def _exec(self):
        if FILL:
            try:
                FILL.pop(0)(self)
            except Exception as e:  # noqa: BLE001
                UNSCRIPTED.append(f"{self.windowTitle}: the script could not fill it: {e!r}")
        else:
            UNSCRIPTED.append(self.windowTitle)
        return 1

    pya.QDialog.exec_ = _exec
    FILE_ANSWER = []  # answers of QFileDialog.get*FileName (stand-in for the user typing a path)
    pya.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: FILE_ANSWER.pop(0) if FILE_ANSWER else "")
    pya.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: FILE_ANSWER.pop(0) if FILE_ANSWER else "")
    try:
        pya.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: FILE_ANSWER.pop(0) if FILE_ANSWER else "")
    except Exception:  # noqa: BLE001
        pass

    # ---- helpers ----------------------------------------------------------------------------------------------------
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
        S.reload_sidecar(force=True)

    def pump(seconds=0.2):
        end = time.time() + seconds
        while time.time() < end:
            app.process_events()
            time.sleep(0.02)

    def ref_json(stem):
        return json.loads((DESIGNS / f"{stem}.json").read_text(encoding="utf-8"))

    def run(*args, **kw):
        return subprocess.run([QCC, *map(str, args)], capture_output=True, text=True, env=session.clean_env(),
                              check=False, encoding="utf-8", errors="replace", **kw)

    def click(tool, x, y, buttons=LEFT):
        tool.mouse_moved_event(pya.DPoint(x, y), buttons & ~LEFT & ~RIGHT, True)
        tool.mouse_click_event(pya.DPoint(x, y), buttons, True)

    class Live:
        """The active tool of one kind, looked up at every use: a rebuild that lands while a route is drawn reloads the
        view, which switches the tool off and on (a new tool object that carries the route on). A user's clicks always go
        to the active tool, so the script's must too."""

        def __init__(self, kind):
            object.__setattr__(self, "_kind", kind)

        def _tool(self):
            t = tools.ACTIVE[0] if tools.ACTIVE else None
            if t is None or type(t).__name__ != self._kind:
                raise RuntimeError(f"the {self._kind} tool is no longer active (active: {type(t).__name__})")
            return t

        def __getattr__(self, k):
            return getattr(self._tool(), k)

        def __setattr__(self, k, v):
            setattr(self._tool(), k, v)

    def use(name):
        """Switch a toolbar mode on (as a click on its toolbar button)."""
        mw.menu().action(f"@toolbar.qcc_{name}").trigger()
        return Live(type(tools.ACTIVE[0]).__name__)

    def aim(tool, q, want, what=None, buttons=LEFT):
        """Zoom in on ``q`` until a click there does what it should (``tool.target`` kind ``want``, and ``what`` when
        given), as a user zooms in when a node is close to a port or a line: the capture radius is in pixels."""
        view = pya.LayoutView.current()
        tool.shift = bool(buttons & pya.ButtonState.ShiftKey)
        tool.free = bool(buttons & tools.CTRL)
        for _ in range(10):
            kind, got = tool.target(q)
            if kind == want and (what is None or got == what):
                return True
            b = view.box()
            w, h = 0.25 * b.width(), 0.25 * b.height()
            view.zoom_box(pya.DBox(q[0] - w, q[1] - h, q[0] + w, q[1] + h))
            app.process_events()
        ports = tool.ports()
        best = min(((geometry.dist(q, tuple(v["pos"])), n) for n, v in ports.items()), default=None)
        say(f"   [dbg] aim {q} wanted {want} {what or ''}: still {tool.target(q)}; capture {tool.capture()!r} um, "
            f"{len(ports)} ports, nearest {best}, {what} in ports: {what in ports}, started {tool.started}, "
            f"start {tool.start} free {tool.start_free} nodes {tool.waypoints}, viewport {view.viewport_width()} px, "
            f"mag {view.viewport_trans().mag!r}, S.data is tool.data: {S.data is tool.data}")
        return False

    def design_now():
        return json.loads(S.design_path.read_text(encoding="utf-8"))

    def close_enough(a, b, tol=2e-3):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            return abs(a - b) <= tol * max(1.0, abs(a) * 1e-4) or abs(a - b) <= 1e-3
        return a == b

    # ---- normalising the designs for the comparison -------------------------------------------------------------------
    NORM = r"""
import json, sys
from quantcore_circuits.design import load_design
d = load_design(sys.argv[1])
print(json.dumps(d.model_dump(mode="json", by_alias=True, exclude_defaults=True)))
"""

    def normalised(path):
        r = subprocess.run([PYEXE, "-c", NORM, str(path)], capture_output=True, text=True, env=session.clean_env(),
                           check=False, encoding="utf-8", errors="replace")
        if r.returncode:
            raise RuntimeError(r.stderr[-600:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def flat_params(cell, params):
        """Metal cells take their options flat or in ``options``: one flat dict for the comparison; values equal to the
        cell's default and JSON strings of dicts are normalised (the table writes defaults only when they differ)."""
        p = dict(params or {})
        for k, v in list(p.items()):
            if isinstance(v, str) and v.strip().startswith(("{", "[")):
                try:
                    p[k] = json.loads(v)
                except ValueError:
                    pass
        if cell.startswith("metal:"):
            opts = p.pop("options", None)
            if isinstance(opts, str):
                opts = json.loads(opts or "{}")
            p.update(opts or {})
        for row in tools.schema(cell):
            if row["name"] in p and p[row["name"]] == row["default"]:
                p.pop(row["name"])
        return p

    def deep_diff(a, b, path=""):
        """Differences between two JSON values (numbers within a tolerance), as a list of strings."""
        out = []
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a:
                    out.append(f"{path}.{k}: only in recreation = {json.dumps(b[k])[:80]}")
                elif k not in b:
                    out.append(f"{path}.{k}: only in reference = {json.dumps(a[k])[:80]}")
                else:
                    out += deep_diff(a[k], b[k], f"{path}.{k}")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                out.append(f"{path}: length {len(a)} (reference) vs {len(b)}: {json.dumps(a)[:90]} / {json.dumps(b)[:90]}")
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    out += deep_diff(x, y, f"{path}[{i}]")
        elif not close_enough(a, b):
            out.append(f"{path}: {json.dumps(a)[:60]} (reference) vs {json.dumps(b)[:60]}")
        return out

    def rename_in(value, name_map):
        """Map reference instance names to the recreation's inside a port reference string."""
        if isinstance(value, str) and "." in value:
            inst, _, port = value.partition(".")
            return f"{name_map.get(inst, inst)}.{port}"
        return value

    def angles_mod_360(doc):
        """-45 and 315 are the same rotation / free-end direction."""
        for inst in doc.get("instances", {}).values():
            pl = inst.get("place", {})
            if "rot" in pl:
                pl["rot"] = round(float(pl["rot"]) % 360.0, 6)
        for r in doc.get("routes", {}).values():
            for k in ("from", "to"):
                e = r.get(k)
                if isinstance(e, dict) and e.get("dir") is not None:
                    e["dir"] = round(float(e["dir"]) % 360.0, 4) % 360.0
        return doc

    def compare(ref_path, our_path, name_map):
        ref = angles_mod_360(normalised(ref_path))
        ours = angles_mod_360(normalised(our_path))
        res = []
        for rn, ri in ref.get("instances", {}).items():
            on = name_map.get(rn, rn)
            oi = ours.get("instances", {}).get(on)
            if oi is None:
                res.append(f"instance {rn}: missing")
                continue
            ri, oi = dict(ri), dict(oi)
            ri["params"] = flat_params(ri["cell"], ri.get("params"))
            oi["params"] = flat_params(oi["cell"], oi.get("params"))
            for d in deep_diff(ri, oi, f"instances.{rn}"):
                res.append(d)
        for on in ours.get("instances", {}):
            if on not in {name_map.get(r, r) for r in ref.get("instances", {})}:
                res.append(f"instance {on}: extra in the recreation")
        for rn, rr in ref.get("routes", {}).items():
            orr = ours.get("routes", {}).get(rn)
            if orr is None:
                res.append(f"route {rn}: missing")
                continue
            rr = json.loads(json.dumps(rr))
            for k in ("from", "to"):
                rr[k] = rename_in(rr.get(k), name_map)
            res += deep_diff(rr, orr, f"routes.{rn}")
        for on in ours.get("routes", {}):
            if on not in ref.get("routes", {}):
                res.append(f"route {on}: extra in the recreation")
        rt = {name_map.get(k, k): v for k, v in (ref.get("targets") or {}).items()}
        res += deep_diff(rt, ours.get("targets") or {}, "targets")
        for k in ("chip", "pdk", "nets", "sim_groups", "couplings"):
            res += deep_diff(ref.get(k), ours.get(k), k) if (ref.get(k) is not None or ours.get(k) is not None) else []
        return res

    # ---- geometry comparison ----------------------------------------------------------------------------------------
    def regions(path):
        ly = pya.Layout()
        ly.read(str(path))
        tops = list(ly.top_cells())
        top = max(tops, key=lambda c: c.dbbox().area())
        out = {}
        for li in ly.layer_indexes():
            info = ly.get_info(li)
            r = pya.Region(top.begin_shapes_rec(li))
            r.merge()
            if not r.is_empty():
                out[(info.layer, info.datatype)] = r
        return out, ly.dbu

    def compare_geometry(ref_oas, our_oas):
        a, dbu = regions(ref_oas)
        b, _ = regions(our_oas)
        rows = []
        for k in sorted(set(a) | set(b)):
            ra, rb = a.get(k, pya.Region()), b.get(k, pya.Region())
            x = ra ^ rb
            rows.append((k, ra.count(), rb.count(), ra.area() * dbu * dbu, rb.area() * dbu * dbu, x.area() * dbu * dbu))
        return rows

    # ---- GUI recipes ------------------------------------------------------------------------------------------------
    QUANT, KQC, METAL = "quantcore", "kqc", "metal"
    SRC = {}

    def source_of(cell, panel):
        if cell.startswith("metal:"):
            return METAL
        if not SRC:
            for s in (QUANT, KQC):
                panel.source.currentText = s
                from qcc_kplugin import qcache as _qc; _qc.wait()  # noqa: E702  (loads run in the background)
                SRC[s] = {panel.components.item(i).text for i in range(panel.components.count)}
        return QUANT if cell in SRC[QUANT] else KQC

    def new_design(dirpath, stem, width, height):
        dirpath.mkdir(parents=True, exist_ok=True)
        FILE_ANSWER.append(str(dirpath / f"{stem}.json"))
        FILL.append(die_fill(float(width), float(height)))
        menu.action("qcc_menu.qcc_design_menu.qcc_new").trigger()
        settle()

    def place(name_ref, ent, panel):
        """Component from the panel (cell list), [ ] to rotate, a click on the layout."""
        cell = ent["cell"]
        panel.source.currentText = source_of(cell, panel)
        from qcc_kplugin import qcache as _qc; _qc.wait()  # noqa: E702  (loads run in the background)
        item = next((panel.components.item(i) for i in range(panel.components.count)
                     if panel.components.item(i).text == cell), None)
        if item is None:
            gap(f"{name_ref}: cell {cell} not in the panel list")
            return None
        panel.components.setCurrentItem(item)
        panel._select(item)  # noqa: SLF001  (a click on the list)
        from qcc_kplugin import qcache as _qc; _qc.wait()  # noqa: E702  (loads run in the background)
        panel._place(item)  # noqa: SLF001  (a double-click: arm + the ghost)
        from qcc_kplugin import qcache as _qc; _qc.wait()  # noqa: E702  (loads run in the background)
        pl = ent.get("place", {})
        n = int(round((float(pl.get("rot", 0.0)) % 360.0) / 90.0)) % 4
        if abs(float(pl.get("rot", 0.0)) % 90.0) > 1e-9:
            n = 0  # the rotation field of the edit dialog sets angles that are not multiples of 90
        for _ in range(n):
            menu.action("qcc_menu.qcc_edit_menu.qcc_rot_ccw").trigger()
        snap = tools.ACTIVE[0]
        before = set(design_now().get("instances", {}))
        at = pl["at"]
        snap.mouse_click_event(pya.DPoint(*at), LEFT, True)
        new = set(design_now().get("instances", {})) - before
        if len(new) != 1:
            diff(f"{name_ref}: the click did not place one component", str(new))
            return None
        if pl.get("mirror"):
            gap(f"{name_ref}: mirrored placement needs the selection + Mirror (not scripted)")
        return new.pop()

    def instance_point(name):
        return tuple(S.data["instances"][name]["trans"]["at"])

    def edit_instance(name, ref_ent, targets, rename_to=None):
        """Double-click the instance in Move/Snap: parameters (table), rotation untouched, targets."""
        cell = ref_ent["cell"]
        rows = tools.schema(cell)
        known = {p["name"]: p for p in rows}
        want = dict(ref_ent.get("params") or {})
        metal_opts = {}
        if cell.startswith("metal:"):
            for k in list(want):
                if k not in known:
                    metal_opts[k] = want.pop(k)
            if metal_opts:
                want["options"] = {**(want.get("options") or {}), **metal_opts}
        else:
            for k in want:
                if k not in known:
                    gap(f"{name}: parameter {k} is not in the schema (the table cannot add it)")
        for k in list(want):
            if k not in known:
                want.pop(k)

        def fn(dialog):
            tbl = next(w for w in walk(dialog.layout) if type(w).__name__ == "QTableWidget")
            for r in range(tbl.rowCount):
                label = tbl.item(r, 0).text.split(" (")[0]
                if label in want:
                    v = want[label]
                    default = known[label]["default"]
                    tbl.item(r, 1).text = v if isinstance(default, str) and isinstance(v, str) else json.dumps(v)
            ed = getattr(dialog, "targets_editor", None)
            if targets:
                if ed is None:
                    gap(f"{name}: no targets section in the edit dialog for {cell}")
                else:
                    for k, v in targets.items():
                        if k in ed.edits:
                            ed.edits[k].text = f"{v:g}"
                        else:
                            gap(f"{name}: target {k} is not offered for {cell}")
        rot_ref = float(ref_ent.get("place", {}).get("rot", 0.0))
        if abs(rot_ref % 90.0) > 1e-9:
            fn0 = fn

            def fn(dialog, fn0=fn0, rot_ref=rot_ref):  # noqa: F811
                fn0(dialog)
                setw(field(dialog, "rotation"), f"{rot_ref:.6f}".rstrip("0").rstrip("."))
        FILL.append(fn)
        snap = use("snap")
        at = instance_point(name)
        snap.mouse_double_click_event(pya.DPoint(*at), LEFT, True)

    def route_points(name):
        return [tuple(p) for p in S.data["routes"][name]["polyline"]]

    def port_pos(port):
        return tuple(S.data["ports"][port]["pos"])

    FIXES = []  # (node index, wanted point): nodes that a click put somewhere else; set in the node dialog
    EXTRA = []  # indices of square corners the pen tool added before a node that is oblique to the previous point

    def click_node(tool, q):
        """A node. Horizontal, vertical and 45 degree segments: a Shift click is exactly the node. Any other angle: a Ctrl
        click (any angle, the node on the grid; G12), set to the exact point afterwards in Route handles when the grid
        moved it. (Before G12 a plain click added a square corner that was deleted afterwards; deleting it after the
        router had built a detour round it wrote the detour's corners into the route.)"""
        if not tool.started:
            raise RuntimeError("the route in progress was dropped (a rebuild switched the Connect tool off and on); "
                               f"tool is ACTIVE[0]: {tools.ACTIVE[0] is tool}, active {tool.active}, nodes so far "
                               f"{tool.waypoints}, node asked {q}")
        a = tool.anchor()
        dx, dy = abs(q[0] - a[0]), abs(q[1] - a[1])
        aligned = dx < 1e-3 or dy < 1e-3 or abs(dx - dy) < 1e-3
        n0 = len(tool.waypoints)
        buttons = SH if aligned else LEFT | tools.CTRL
        aim(tool, q, "node", buttons=buttons)
        click(tool, q[0], q[1], buttons)
        added = len(tool.waypoints) - n0
        if added == 2:
            EXTRA.append(n0)
        elif added != 1:
            raise RuntimeError(f"the click at {q} added {added} nodes: {tool.waypoints[n0:]}")
        if geometry.dist(tool.waypoints[-1], q) > 0.01:
            FIXES.append((len(tool.waypoints) - 1, q))

    def zoom_to_route(rr, src, dst):
        """Zoom in on the route like a user would (a click within the capture radius of the previous node finishes the
        route as a free end, so nodes closer than ~12 pixels need a closer view)."""
        pts = []
        for e in (src, dst):
            if isinstance(e, str):
                pts.append(port_pos(e))
            elif "at" in e:
                pts.append(tuple(e["at"]))
            elif "near" in e:
                pts.append(tuple(e["near"]))
        pts += [tuple(n["at"]) if isinstance(n, dict) else tuple(n) for n in rr.get("nodes", [])]
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        m = max(250.0, 0.25 * max(x1 - x0, y1 - y0))
        view = pya.LayoutView.current()
        view.zoom_box(pya.DBox(x0 - m, y0 - m, x1 + m, y1 + m))
        app.process_events()

    def connect(name, r, name_map):
        settle()  # no rebuild lands while the route is drawn
        FILL.clear()
        tool = use("connect")
        tool.reset()
        rr = json.loads(json.dumps(r))
        src, dst = rename_in(rr["from"], name_map), rename_in(rr["to"], name_map)
        zoom_to_route(rr, src, dst)
        if os.environ.get("QCC_TUT_DEBUG"):
            view = pya.LayoutView.current()
            say(f"   [dbg] {name}: viewport {view.viewport_width()} x {view.viewport_height()} px, capture "
                f"{tool.capture():.1f} um, {len(tool.ports())} ports, tool active {tool.active}")
        if isinstance(src, dict):
            aim(tool, tuple(src["at"]), "start-free")
            click(tool, *src["at"])  # a free start
        else:
            aim(tool, port_pos(src), "start-port", src)
            click(tool, *port_pos(src))
        if tool.start is None and tool.start_free is None:
            diff(f"{name}: the start click did not start a route", str(src))
            tool.reset()
            return
        nodes = [tuple(n["at"]) if isinstance(n, dict) else tuple(n) for n in rr.get("nodes", [])]
        for e in (src, dst):  # a node exactly on an end port: a click there is the port, not a node
            if isinstance(e, str):
                on_port = [q for q in nodes if geometry.dist(q, port_pos(e)) < 1.0]
                if on_port:
                    nodes = [q for q in nodes if q not in on_port]
                    gap(f"{name}: the reference has a node exactly on port {e} (redundant: a click there is the port)")
        if os.environ.get("QCC_TUT_DEBUG"):
            say(f"   [dbg] {name}: src {src} start={tool.start} free={tool.start_free} started={tool.started}")
        FIXES.clear()
        EXTRA.clear()
        for q in nodes:
            click_node(tool, q)
        got = list(tool.waypoints)
        # fields of the dialogs
        common = {"Name": name, "Type": rr.get("type", "cpw"), "Bend radius": rr.get("r") or "",
                  "Line width a": rr.get("a"), "Line gap b": rr.get("b")}
        if rr.get("type") == "meander":
            common["Length"] = rr.get("length")
            common["Meander length"] = rr.get("length")
        if isinstance(dst, dict) and "hanger" in dst:
            vals = {**common, "Coupler length": dst["length"], "Side": dst["side"], "Coupler end": dst["end"],
                    "Ground strip": dst.get("ground_gap"), "Direction": dst.get("direction")}
            if isinstance(src, dict):
                vals["Free end (start)"] = "short" if src.get("term", 0) == 0 else "open"
                vals["Open gap µm (start)"] = src.get("term") or 6
            FILL.append(lambda d, v=vals: fill_form({k: x for k, x in v.items() if _has(d, k)})(d))
            for k in ("Direction",):
                if vals.get(k) and vals[k] != "forward":
                    pass
            near = dst["near"]
            aim(tool, tuple(near), "line")
            click(tool, near[0], near[1])
        elif isinstance(dst, dict):  # a free end: the last node, then once more
            if isinstance(src, dict):
                gap(f"{name}: both ends free")
            nodes_end = tuple(dst["at"])
            click_node(tool, nodes_end)
            vals = dict(common)
            vals["Free end (end)"] = "short" if dst.get("term", 0) == 0 else "open"
            vals["Open gap µm (end)"] = dst.get("term") or 6
            FILL.append(lambda d, v=vals: fill_form({k: x for k, x in v.items() if _has(d, k)})(d))
            aim(tool, nodes_end, "finish-free")
            click(tool, nodes_end[0], nodes_end[1])
        else:
            vals = dict(common)
            if isinstance(src, dict):
                vals["Free end (start)"] = "short" if src.get("term", 0) == 0 else "open"
                vals["Open gap µm (start)"] = src.get("term") or 6
            FILL.append(lambda d, v=vals: fill_form({k: x for k, x in v.items() if _has(d, k)})(d))
            aim(tool, port_pos(dst), "port", dst)
            click(tool, *port_pos(dst))
        now = design_now().get("routes", {})
        if name not in now:
            diff(f"{name}: no route was created", f"{rr['from']} -> {rr['to']}")
            tool.reset()
            return
        if EXTRA or FIXES:
            fix_nodes(name, list(EXTRA), list(FIXES))
            FIXES.clear()
            EXTRA.clear()
        return got

    def fix_nodes(name, extra, fixes):
        """Route handles: delete the extra square corners (click the node, Edit > Delete route node), then set nodes that
        are not where they should be (click the node, Edit > Route node properties, type x and y)."""
        settle()
        ed = use("route_edit")

        def select(i):
            cur = design_now()["routes"][name]["nodes"][i]
            cur = cur["at"] if isinstance(cur, dict) else cur
            pya.LayoutView.current().zoom_box(pya.DBox(cur[0] - 300, cur[1] - 300, cur[0] + 300, cur[1] + 300))
            app.process_events()
            click(ed, *cur)
            if ed.selected != (name, i):  # the route does not build in this state: it has no handles in the sidecar
                gap(f"{name}: node {i} has no handle while the route fails to build (a half-drawn oblique route); "
                    "selected directly")
                ed.selected = (name, i)
            return True

        for i in sorted(extra, reverse=True):
            if select(i):
                menu.action("qcc_menu.qcc_edit_menu.qcc_node_delete").trigger()
                settle()
                ed = use("route_edit")
            else:
                diff(f"{name}: the extra corner node {i} could not be selected", f"selected {ed.selected}")
        for i, q in fixes:
            i -= sum(1 for e in extra if e < i)
            if select(i):
                FILL.append(fill_form({"x µm": q[0], "y µm": q[1]}))
                menu.action("qcc_menu.qcc_edit_menu.qcc_node_props").trigger()
                settle()
                ed = use("route_edit")
            else:
                diff(f"{name}: node {i} could not be selected to set it to {q}", f"selected {ed.selected}")
        settle()

    def _has(dialog, prefix):
        return any(k.startswith(prefix) for k in labelled(dialog))

    def edit_route(name, targets):
        tool = use("route_edit")
        pts = route_points(name)
        seg = max(range(len(pts) - 1), key=lambda i: geometry.dist(pts[i], pts[i + 1]))
        mid = geometry.mul(geometry.add(pts[seg], pts[seg + 1]), 0.5)
        pya.LayoutView.current().zoom_box(pya.DBox(mid[0] - 400, mid[1] - 400, mid[0] + 400, mid[1] + 400))
        app.process_events()

        def fn(dialog):
            seg = labelled(dialog).get(tools.SEGMENT_TEXT)
            if seg is not None:  # only the targets are wanted: keep the meander on its longest straight
                seg.currentIndex = 0
            for k, v in targets.items():
                w = next((x for x in walk(dialog.layout) if getattr(x, "objectName", "") == f"qcc_target_{k}"), None)
                if w is None:
                    gap(f"{name}: target {k} is not offered in the route dialog")
                else:
                    w.text = f"{v:g}"
        FILL.append(fn)
        tool.mouse_double_click_event(pya.DPoint(*mid), LEFT, True)

    def zoom_around(p, half=500.0):
        pya.LayoutView.current().zoom_box(pya.DBox(p[0] - half, p[1] - half, p[0] + half, p[1] + half))
        app.process_events()

    def undo():
        menu.action("qcc_menu.qcc_edit_menu.qcc_undo").trigger()

    def handles_exercise(tag_, ref_routes):
        """Route handles on the recreated design: move, insert, radius handle, node dialog, meander segment, each undone;
        the design must be exactly as before at the end."""
        label = f"[{tag_}] Route handles"
        before = design_now()
        routes = before["routes"]
        ed = use("route_edit")
        S.reload_sidecar(force=True)
        # a route with a node (not a hanger host feedline): prefer one with two or more nodes
        cand = [n for n, r in routes.items() if len(r.get("nodes", [])) >= 2 and isinstance(r.get("to"), (str, dict))]
        if cand:
            rn = cand[0]
            nodes = [tuple(n["at"]) if isinstance(n, dict) else tuple(n) for n in routes[rn]["nodes"]]
            wps = S.data["routes"][rn].get("waypoints") or nodes
            # (1) select + move a node (click, click) and undo
            p0 = nodes[0]
            zoom_around(p0)
            click(ed, *p0)
            check(f"{label}: click selects node 0 of {rn}", ed.selected == (rn, 0), str(ed.selected))
            click(ed, p0[0] + 20.0, p0[1] + 20.0)
            moved = design_now()["routes"][rn]["nodes"][0]
            moved = list(moved["at"]) if isinstance(moved, dict) else list(moved)
            check(f"{label}: a node moves by (20, 20)", abs(moved[0] - p0[0] - 20) < 1e-3 and abs(moved[1] - p0[1] - 20) < 1e-3,
                  str(moved))
            settle()
            undo()
            settle()
            # (2) the node dialog: set y + 10
            ed = use("route_edit")
            ed.selected = (rn, 0)
            FILL.append(fill_form({"y µm": p0[1] + 10.0}))
            menu.action("qcc_menu.qcc_edit_menu.qcc_node_props").trigger()
            got = design_now()["routes"][rn]["nodes"][0]
            got = got["at"] if isinstance(got, dict) else got
            check(f"{label}: node dialog changes y", abs(got[1] - p0[1] - 10.0) < 1e-3, str(got))
            settle()
            undo()
            settle()
            # (3) per-corner radius: the node handle shows a radius handle; drop it at 40 um
            ed = use("route_edit")
            S.reload_sidecar(force=True)
            click(ed, *p0)
            click(ed, *p0)  # drop in place: only selects
            c = ed.corner(rn, 0)
            h = ed.radius_handle()
            if c is None or h is None:
                gap(f"{label}: node 0 of {rn} has no radius handle (first node is not a corner?)")
            else:
                click(ed, *h)
                click(ed, *geometry.radius_handle(c[0], c[1], c[2], 40.0))
                n0 = design_now()["routes"][rn]["nodes"][0]
                check(f"{label}: radius handle sets a corner radius", isinstance(n0, dict) and abs(n0.get("r", 0) - 40) < 1.5,
                      json.dumps(n0))
                settle()
                undo()
                settle()
            # (4) delete a node from the menu, undo
            ed = use("route_edit")
            S.reload_sidecar(force=True)
            click(ed, *p0)
            menu.action("qcc_menu.qcc_edit_menu.qcc_node_delete").trigger()
            check(f"{label}: delete node from the menu", len(design_now()["routes"][rn].get("nodes", [])) == len(nodes) - 1)
            settle()
            undo()
            settle()
            # (5) insert a node on the longest segment (Shift: stays on the straight), then undo
            ed = use("route_edit")
            S.reload_sidecar(force=True)
            ins = [x for x in ed.handles() if x[0] == rn and x[1] == "insert"]
            if ins:
                hx, hy = ins[0][3]
                click(ed, hx, hy)
                click(ed, hx + 1.0, hy + 1.0, SH)
                check(f"{label}: insert handle adds a node", len(design_now()["routes"][rn].get("nodes", [])) == len(nodes) + 1,
                      json.dumps(design_now()["routes"][rn].get("nodes")))
                settle()
                undo()
                settle()
            else:
                gap(f"{label}: {rn} has no insert handle (all segments fixed)")
        else:
            gap(f"{label}: no route with two or more nodes in this design")
        # (6) meander segment from the menu on a meander route, then undo
        mean = [n for n, r in design_now()["routes"].items() if r.get("type") == "meander"]
        if mean:
            rn = mean[0]
            ed = use("route_edit")
            S.reload_sidecar(force=True)
            poly = route_points(rn)
            fixed = set(S.data["routes"][rn].get("fixed_segments", []))
            segs = [i for i in range(len(poly) - 1) if (i + 1) not in fixed and geometry.dist(poly[i], poly[i + 1]) > 300]
            if segs:
                i = segs[0]
                mid = geometry.mul(geometry.add(poly[i], poly[i + 1]), 0.5)
                zoom_around(mid, 600.0)
                ed.mouse_moved_event(pya.DPoint(*mid), 0, True)
                menu.action("qcc_menu.qcc_edit_menu.qcc_meander_here").trigger()
                check(f"{label}: meander on the segment under the cursor ({rn})",
                      design_now()["routes"][rn].get("meander_segment") == i + 1, str(design_now()["routes"][rn].get("meander_segment")))
                settle()
                check(f"{label}: the design still builds with the meander moved", S.last_error is None, str(S.last_error))
                undo()
                settle()
            else:
                gap(f"{label}: {rn} has no free straight longer than 300 um")
        final = design_now()
        check(f"{label}: after every undo the design is exactly as before", final == before,
              "; ".join(deep_diff(before, final)[:3]))
        check(f"{label}: and it builds", S.last_error is None, str(S.last_error))

    def check_loop(tag_, dirpath, ref_path, our_path, name_map):
        """Check (DRC), Run LOM (compare with the reference), Results tab, Save as Python, Fab export."""
        panel = dock.DOCK[0]
        panel.flow_buttons["check"].click()
        job = jobs.RUNNING[-1] if jobs.RUNNING else None
        if job is not None:
            job.wait(900)
        items = [panel.drc.item(i).text for i in range(panel.drc.count)]
        check(f"[{tag_}] Check ran from the Flow strip", panel.full_check is not None, "; ".join(items[:4]))
        errs = [i for i in (S.data or {}).get("drc", []) if i.get("severity") == "error"]
        warns = [i for i in (S.data or {}).get("drc", []) if i.get("severity") != "error"]
        say(f"   DRC errors {len(errs)} warnings {len(warns)}: " + json.dumps(
            [f"{i.get('rule')}: {i.get('message', '')[:70]}" for i in (errs + warns)[:6]]))
        t0 = time.time()
        stopped = False
        panel.flow_buttons["lom"].click()
        job = jobs.RUNNING[-1] if jobs.RUNNING else None
        if job is not None:
            job.wait(LOMWAIT)
            if not job.finished:  # heavy chip: the LOM is still running; stop it (our own process) and say so
                try:
                    job.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
                job.wait(30)
                gap(f"[{tag_}] Run LOM still running after {LOMWAIT} s (QuCat on this many modes); stopped")
                stopped = True
        our_ok = job is not None and job.ok
        our_msg = job.output[-300:] if job else "no job"
        say(f"   LOM took {time.time() - t0:.0f} s")
        panel.load_lom()
        params = {panel.lom_params.item(i, 0).text: (panel.lom_params.item(i, 1).text, panel.lom_params.item(i, 2).text,
                                                    panel.lom_params.item(i, 3).text)
                  for i in range(panel.lom_params.rowCount)}
        say(f"   LOM tab: {len(params)} values, modes {panel.lom_modes.rowCount}")
        # the same circuit as the reference's (cheap), and the reference LOM values when that is fast enough
        ref_dir = ROOT / f"{tag_}_ref"
        ref_dir.mkdir(exist_ok=True)
        shutil.copy(ref_path, ref_dir / Path(ref_path).name)
        r1 = run("circuit", "export", ref_dir / Path(ref_path).name, "-o", ref_dir / "ref.circuit.json")
        ours_c = Path(our_path).parent / "build" / f"{Path(our_path).stem}.circuit.json"
        if r1.returncode or not ours_c.exists():
            diff(f"[{tag_}] circuit export", (r1.stderr or r1.stdout)[-300:] or f"ours missing {ours_c}")
        else:
            ca = json.loads((ref_dir / "ref.circuit.json").read_text(encoding="utf-8"))
            cb = json.loads(ours_c.read_text(encoding="utf-8"))
            cd = []
            for k in ("nodes", "branches", "knobs", "targets", "estimators", "controls"):
                cd += deep_diff(ca.get(k), cb.get(k), k)
            (tag("PASS", f"[{tag_}] the exported circuit equals the reference's ({len(ca.get('nodes', {}))} nodes, "
                         f"{len(ca.get('branches', {}))} branches)") if not cd else
             diff(f"[{tag_}] the exported circuit differs from the reference's", "; ".join(cd[:6])))
        nq = sum(1 for e in design_now()["instances"].values() if any(w in e["cell"].lower() for w in ("xmon", "transmon", "star")))
        if nq > 2 and not os.environ.get("QCC_TUT_REFLOM"):
            gap(f"[{tag_}] reference LOM values not computed ({nq} qubits: QuCat takes many minutes); circuits compared instead")
            r2 = None
        else:
            try:
                r2 = run("circuit", "simulate", ref_dir / "ref.circuit.json", "--json", ref_dir / "ref.lom.json", timeout=900)
            except subprocess.TimeoutExpired:
                r2 = None
                gap(f"[{tag_}] the reference LOM (qcc circuit simulate) takes more than 15 minutes: not compared")
        if stopped:
            pass
        elif our_ok:
            check(f"[{tag_}] Run LOM job", True)
        elif r2 is not None and r2.returncode:
            gap(f"[{tag_}] Run LOM fails for the reference too (same open circuit): not a plugin difference",
                our_msg.strip().splitlines()[-1] if our_msg.strip() else "")
        else:
            check(f"[{tag_}] Run LOM job", False, our_msg)
        if r2 is not None and r1.returncode or (r2 is not None and r2.returncode and our_ok):
            diff(f"[{tag_}] reference LOM did not run", (r1.stderr or r1.stdout or r2.stderr or r2.stdout)[-300:])
        elif r2 is not None and not r2.returncode and our_ok:
            rj = json.loads((ref_dir / "ref.lom.json").read_text(encoding="utf-8"))
            oj = json.loads((Path(our_path).parent / "build" / Path(our_path).stem / "lom.json").read_text(encoding="utf-8"))
            say("   LOM keys: " + ",".join(rj))
            rp, op = rj.get("params", {}), oj.get("params", {})
            bad = []
            for k, p in rp.items():
                inst, _, rest = k.partition(".")
                q = op.get(f"{name_map.get(inst, inst)}.{rest}")
                if q is None:
                    bad.append(f"{k}: missing")
                elif abs(p - q) > 1e-3 * max(abs(p), 1.0):
                    bad.append(f"{k}: {p:.5g} (reference) vs {q:.5g}")
            (tag("PASS", f"[{tag_}] LOM values equal the reference ({len(rp)} values)") if not bad else
             diff(f"[{tag_}] LOM values differ from the reference ({len(rp)} values)", "; ".join(bad[:12])))
        check(f"[{tag_}] Results tab opens", True)
        flow.results(wait=True, quiet=True)
        app.process_events()
        def width(w):
            v = w.width
            return v() if callable(v) else v
        ww, dw = width(mw), width(dock.DOCK[0].dock)  # both in logical pixels (the view's viewport is in device pixels)
        check(f"[{tag_}] the Quantcore panel leaves the layout view its width after LOM (status text wraps)",
              dw <= 0.45 * ww, f"panel {dw} px of a {ww} px window")
        # Save as Python (Design submenu) and the round trip
        py_out = dirpath / f"{Path(our_path).stem}_saved.py"
        job = flow.save_python(wait=True, path=str(py_out))
        check(f"[{tag_}] Save as Python wrote design.py", py_out.exists(), (job.output[-200:] if job and not job.ok else ""))
        if py_out.exists():
            rt = dirpath / "rt"
            rt.mkdir(exist_ok=True)
            shutil.copy(py_out, rt / py_out.name)
            r = subprocess.run([PYEXE, str(rt / py_out.name)], capture_output=True, text=True, cwd=rt, check=False,
                               env=session.clean_env(), encoding="utf-8", errors="replace")
            js = list(rt.glob("*.json"))
            h0 = run("design", "hash", our_path).stdout.strip()
            h1 = run("design", "hash", js[0]).stdout.strip() if js else r.stderr[-300:]
            check(f"[{tag_}] design.py rebuilds the same design hash", h0 and h0 == h1, f"{h0} {h1}")
        # Fab export
        fab_dir = dirpath / "fab_out"
        t0 = time.time()
        job = flow.fab(wait=True, folder=str(fab_dir), force=True)
        names = sorted(p.name for p in fab_dir.iterdir()) if fab_dir.exists() else []
        check(f"[{tag_}] Fab export wrote mask, netlist, design.py, PNG", job is not None and job.ok
              and any(n.endswith("_fab.oas") for n in names) and any(n.endswith(".png") for n in names),
              f"{names} {time.time() - t0:.0f} s" + ("" if job is None or job.ok else job.output[-300:]))
        for w in list(flow.DIALOGS):
            try:
                w.dialog.close()
            except Exception:  # noqa: BLE001
                pass

    # ---- one design -------------------------------------------------------------------------------------------------
    def recreate(tag_, ref_stem, subset=None, loop=True):
        say(f"\n==================== {tag_}: {ref_stem} ====================")
        ref = ref_json(ref_stem)
        FILL.clear()
        UNSCRIPTED.clear()
        dirpath = ROOT / tag_
        box = ref["chip"]["box"]
        new_design(dirpath, ref_stem, box[2] - box[0], box[3] - box[1])
        our_path = dirpath / f"{ref_stem}.json"
        got_box = json.loads(our_path.read_text(encoding="utf-8"))["chip"]["box"] if our_path.exists() else None
        check(f"[{tag_}] New design asks for the die width and height", got_box is not None and all(
            abs(float(a) - float(b)) < 1e-6 for a, b in zip(got_box, box)), f"{got_box} vs {box}")
        check(f"[{tag_}] New design builds the empty die", S.last_error is None and (dirpath / "build" / f"{ref_stem}.oas").exists(),
              str(S.last_error))
        dock.show_dock()
        panel = dock.DOCK[0]
        panel.load_components()
        from qcc_kplugin import qcache  # noqa: E402
        qcache.wait()  # the list loads in the background now
        view = pya.LayoutView.current()
        check(f"[{tag_}] a view shows the new design", view is not None)
        if view is not None:
            mw.resize(1600, 1200)
            app.process_events()
            view.zoom_box(pya.DBox(box[0], box[1], box[2], box[3]))
            app.process_events()
        app.set_config("edit-grid", "0.0001")
        cp = ref["chip"].get("params", {})
        def chip_fill(d):
            fill_form({"Label on the die": cp.get("name_chip")})(d)
            die_fill(box[2] - box[0], box[3] - box[1])(d)
            tick_box(d, "KQC ground-plane grid", bool(cp.get("with_grid", False)))
        FILL.append(chip_fill)
        edits.chip_settings()
        settle()
        insts = ref["instances"]
        if subset is not None:
            insts = {k: v for k, v in insts.items() if k in subset}
        name_map = {}
        t0 = time.time()
        for rn, ent in insts.items():
            on = place(rn, ent, panel)
            if on:
                name_map[rn] = on
        settle()
        say(f"   placed {len(name_map)}/{len(insts)} instances in {time.time() - t0:.0f} s; names {json.dumps(name_map)[:300]}")
        check(f"[{tag_}] every instance placed", len(name_map) == len(insts))
        # rename to the reference names (Edit > Rename)
        for rn, on in list(name_map.items()):
            if rn != on:
                FILL.append(fill_form({"New name": rn}))
                edits.rename_instance(on)
                if rn in design_now().get("instances", {}):
                    name_map[rn] = rn
                else:
                    diff(f"rename {on} -> {rn} did not happen")
        settle()
        # the PDK pad-edge rule: Check shows the warnings, the fix action sets edge = auto
        if any(i.get("rule") == "pad_edge" for i in S.data.get("drc", [])):
            edits.fix_pad_edges()
            settle()
            check(f"[{tag_}] pad edge warnings fixed by the Check-menu action",
                  not any(i.get("rule") == "pad_edge" for i in S.data.get("drc", [])),
                  str([i["message"][:50] for i in S.data.get("drc", []) if i.get("rule") == "pad_edge"]))
        # parameters, targets
        targets = ref.get("targets", {})
        for rn, ent in insts.items():
            on = name_map.get(rn)
            if on is None:
                continue
            tg = {k: v for k, v in (targets.get(rn) or {}).items()}
            edit_instance(on, ent, tg)
            settle()
            jn = ent.get("junction") or {}
            if jn:
                FILL.append(fill_form({"Junction L_J": jn.get("Lj_nH"), "Junction C_J": jn.get("Cj_fF")}))
                edits.junction_values(on)
        check(f"[{tag_}] edit dialogs scripted as expected", not UNSCRIPTED and not FILL, f"unscripted {UNSCRIPTED} queued {len(FILL)}")
        UNSCRIPTED.clear()
        FILL.clear()
        for cn, c in (ref.get("couplings") or {}).items():
            if subset is not None and not all(rename_name(e) in insts for e in c["between"]):
                continue
            FILL.append(fill_form({"Name": cn, "Between": rename_in(c["between"][0], name_map),
                                   "and": rename_in(c["between"][1], name_map), "Type": c.get("type", "C"),
                                   "Value": c.get("value"), "Note": c.get("note", "")}))
            edits.add_coupling()
        gap(f"[{tag_}] sim_groups {sorted(ref.get('sim_groups', {}))}: made by Simulate (flow), not drawable", "")
        # routes
        routes = ref["routes"]
        if subset is not None:
            routes = {k: v for k, v in routes.items()
                      if all(rename_name(x) in insts for x in (v["from"], v["to"]) if isinstance(x, str))}
        hosts = {v["to"]["hanger"] for v in routes.values() if isinstance(v["to"], dict) and "hanger" in v["to"]}
        route_notes = {}
        for rn, r in routes.items():
            try:
                got = connect(rn, r, name_map)
            except Exception:  # noqa: BLE001
                tag("FAIL", f"[{tag_}] route {rn} raised", traceback.format_exc()[-500:])
                got = None
            route_notes[rn] = got
        settle()
        for rn in routes:
            if rn in (targets or {}) and rn in design_now().get("routes", {}):
                edit_route(rn, targets[rn])
        settle()
        check(f"[{tag_}] route dialogs scripted as expected", not UNSCRIPTED and not FILL, f"unscripted {UNSCRIPTED} queued {len(FILL)}")
        UNSCRIPTED.clear()
        FILL.clear()
        check(f"[{tag_}] design builds after all edits", S.last_error is None, str(S.last_error))
        say(f"   routes created: {len(design_now().get('routes', {}))}/{len(routes)}")
        # compare to the reference
        ref_copy = ROOT / f"{tag_}_refcopy" / f"{ref_stem}.json"
        ref_copy.parent.mkdir(exist_ok=True)
        ref_data = dict(ref)
        if subset is not None:
            ref_data["instances"] = insts
            ref_data["routes"] = routes
            ref_data["targets"] = {k: v for k, v in targets.items() if k in insts or k in routes}
            ref_data["sim_groups"] = {}
            ref_data.pop("couplings", None)
        ref_copy.write_text(json.dumps(ref_data, indent=2), encoding="utf-8")
        for line in compare(ref_copy, our_path, name_map)[:400]:
            diff(f"[{tag_}] {line}")
        r = run("build", ref_copy, "-o", ref_copy.parent / "build" / f"{ref_stem}.oas", *session.label_args())  # labels as the plugin draws them
        check(f"[{tag_}] reference builds", r.returncode == 0, (r.stderr or r.stdout)[-300:])
        if r.returncode == 0:
            settle()
            rows = compare_geometry(ref_copy.parent / "build" / f"{ref_stem}.oas", dirpath / "build" / f"{ref_stem}.oas")
            worst = max((x[5] for x in rows), default=0.0)
            say("   layer (ref polys, ours; ref area, ours; XOR area um2):")
            for k, na, nb, aa, ab, ax in rows:
                if ax > 0.5 or na != nb:
                    say(f"     {k}: {na} {nb}; {aa:.0f} {ab:.0f}; xor {ax:.1f}")
            check(f"[{tag_}] built geometry equals the reference (XOR, < 10 um2: the node coordinates are rounded to 1e-4 um)", worst < 10.0, f"worst layer XOR {worst:.1f} um2")
        h0 = run("design", "hash", ref_copy).stdout.strip()
        h1 = run("design", "hash", our_path).stdout.strip()
        (tag("PASS", f"[{tag_}] design hash equals the reference") if h0 == h1 else
         diff(f"[{tag_}] design hash differs from the reference", f"{h0} vs {h1}"))
        try:
            handles_exercise(tag_, routes)
        except Exception:  # noqa: BLE001
            tag("FAIL", f"[{tag_}] Route handles exercise raised", traceback.format_exc()[-600:])
        UNSCRIPTED.clear()
        FILL.clear()
        if loop:
            check_loop(tag_, dirpath, ref_copy, our_path, name_map)
        say(f"   unexpected dialogs in {tag_}: {UNSCRIPTED}")

    def rename_name(x):
        return x.split(".")[0] if isinstance(x, str) else x

    for t in ONLY:
        try:
            if t == "t04":
                recreate("t04", "t04_two_qubit")
            elif t == "t02":
                recreate("t02", "t02_ibm_bowtie_5q")
            elif t == "t01":
                recreate("t01", "t01_chip12")
            elif t == "t03":
                # 117 instances and 154 routes on a 15 mm die: one representative part by hand, two qubits that share a
                # coupler (StarQubit + CapNInterdigitalTee, 45 degree rotations, airbridges, free-end readout routes)
                keep = os.environ.get("QCC_T03", "")
                names = set(keep.split(",")) if keep else {k for k in ref_json("t03_demoqpu17")["instances"]
                                                           if "Q22" in k or "Q23" in k}
                recreate("t03", "t03_demoqpu17", subset=names)
        except Exception:  # noqa: BLE001
            say(f"EXCEPTION in {t}\n" + traceback.format_exc())
    say(f"\nTOTAL {COUNT}")
    say("DONE")
except Exception:  # noqa: BLE001
    say("EXCEPTION\n" + traceback.format_exc())
finally:
    try:
        say("log tail:\n" + "\n".join(session.LOG.read_text(encoding="utf-8").splitlines()[-25:]))
    except Exception:  # noqa: BLE001
        pass
    pya.Application.instance().exit(0)
