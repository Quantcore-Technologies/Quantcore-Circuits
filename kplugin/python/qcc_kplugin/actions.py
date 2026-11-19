"""qcc menu actions (GUI only; geometry/JSON logic lives in ``design_io`` / ``geometry``, building in ``qcc``)."""

from __future__ import annotations

import json
from pathlib import Path

import pya  # type: ignore

from qcc_kplugin import design_io, tools
from qcc_kplugin.session import (
    CFG_CAPTURE,
    CFG_DESIGN,
    CFG_DIALOG_COLUMNS,
    CFG_GRID,
    CFG_LABEL_HEIGHT,
    CFG_LOM_LIMIT,
    CFG_QCC,
    SESSION,
    config,
    label_height,
    message,
    ok_cancel,
    set_config,
)

LABEL_TEXT = "Instance name labels in the layout: height µm (0 = none)"
COLUMNS_TEXT = "Long dialogs in two columns (every dialog scrolls and fits the screen)"


def configure():
    dialog = pya.QDialog(pya.Application.instance().main_window())
    dialog.windowTitle = "quantcore-circuits settings"
    from qcc_kplugin import dialogs  # pylint: disable=import-outside-toplevel

    form = dialogs.Rows(dialog)
    e_qcc = pya.QLineEdit(config(CFG_QCC, "qcc"), dialog)
    e_grid = pya.QLineEdit(config(CFG_GRID, "1.0"), dialog)
    e_cap = pya.QLineEdit(config(CFG_CAPTURE, "12"), dialog)
    form.addRow("qcc executable (conda env Scripts\\qcc.exe)", e_qcc)
    form.addRow("Placement / waypoint grid µm", e_grid)
    form.addRow("Capture radius (pixels)", e_cap)
    e_lom = pya.QLineEdit(config(CFG_LOM_LIMIT, "30"), dialog)
    e_lom.toolTip = "Run LOM stops by itself after this long (QuCat on 5+ qubits can take 10 min or more)"
    form.addRow("Run LOM time limit (minutes)", e_lom)
    e_label = pya.QLineEdit(f"{label_height():g}", dialog)
    e_label.toolTip = ("Height of the component names (TCT1, R1, ...) the build writes on the instance_names layer, in "
                       "µm (capital letters). KQC draws 280 µm; the command-line build keeps that. An annotation "
                       "layer: the fab mask, the simulations and the design do not change. A new value rebuilds.")
    form.addRow(LABEL_TEXT, e_label)
    e_cols = pya.QCheckBox(COLUMNS_TEXT, dialog)
    e_cols.checked = config(CFG_DIALOG_COLUMNS, "2").strip() != "1"
    e_cols.toolTip = ("The route, component and hanger dialogs put their rows in two columns when one column would be "
                      "taller than the screen. Off: one column, scrolled.")
    form.addRow(e_cols)
    from qcc_kplugin import pcells  # pylint: disable=import-outside-toplevel

    e_live = pya.QCheckBox("Live PCells: Quantcore cells in KLayout's Instance tool and PCell dialog (experimental)",
                           dialog)
    e_live.checked = pcells.LIVE.enabled()
    e_live.toolTip = ("Registers the 'Quantcore' library; components become library PCells after each build. "
                      "Every edit still goes to design.json and is rebuilt by qcc.")
    form.addRow(e_live)
    dialogs.fit(dialog, form.build(columns=1), ok_cancel(dialog))
    dialog.qcc_settings = {"label": e_label, "columns": e_cols}  # tests
    if dialog.exec_():
        set_config(CFG_QCC, e_qcc.text.strip())
        set_config(CFG_GRID, float(e_grid.text))
        set_config(CFG_CAPTURE, float(e_cap.text))
        set_config(CFG_LOM_LIMIT, float(e_lom.text))
        set_config(CFG_DIALOG_COLUMNS, "2" if e_cols.checked else "1")
        before = label_height()
        try:
            new = float(e_label.text)
        except ValueError:
            new = -1.0
        if new < 0:
            message(f"Settings: the label height must be a number >= 0 (kept {before:g} µm)", 10)
        else:
            set_config(CFG_LABEL_HEIGHT, f"{new:g}")
            if abs(new - before) > 1e-9 and SESSION.design_path is not None:
                rebuild()  # the labels are drawn by the build
        set_live_pcells(bool(e_live.checked))


def set_live_pcells(on: bool) -> None:
    """Settings > live PCells on / off (on: the library loads in the background; off: the next build is static)."""
    from qcc_kplugin import pcells  # pylint: disable=import-outside-toplevel

    set_config(pcells.CFG_LIVE, "true" if on else "false")
    if on:
        pcells.LIVE.start()
    else:
        pcells.LIVE.stop()


def new_design():
    """A blank PDK die as a new design.json, opened and built: then place components from the Quantcore panel."""
    path = pya.QFileDialog.getSaveFileName(None, "New design.json", config(CFG_DESIGN), "Design (*.json)")
    if not path:
        return None
    path = Path(path if path.lower().endswith(".json") else path + ".json")
    from qcc_kplugin import edits  # pylint: disable=import-outside-toplevel  (edits imports this module)

    dialog = pya.QDialog(pya.Application.instance().main_window())
    dialog.windowTitle = "New design"
    form = pya.QFormLayout(dialog)
    size_of = edits.die_size_rows(dialog, form, 7500.0, 7500.0)
    form.addRow(ok_cancel(dialog))
    if not dialog.exec_():
        return None
    try:
        w, h = size_of()
    except ValueError as e:
        return message(f"New design: {e}", 8)
    path.write_text(json.dumps(design_io.new_design(path.stem, (0.0, 0.0, w, h)), indent=2), encoding="utf-8")
    set_config(CFG_DESIGN, str(path))
    SESSION.open(str(path))
    rebuild()
    return message(f"new design {path.name}: Quantcore panel (Ctrl+Shift+P) → double-click a component, click to drop")


def open_design():
    path = pya.QFileDialog.getOpenFileName(None, "Open design.json", config(CFG_DESIGN), "Design (*.json *.py)")
    if path:
        SESSION.open(path)
        rebuild()


def rebuild():
    if SESSION.design_path is None:
        return message("no design open (Quantcore > Open design...)")
    SESSION._reload_after = 0.0  # pylint: disable=protected-access  (reload as soon as the new layout lands)
    SESSION._build()  # pylint: disable=protected-access
    return message(f"rebuilding {SESSION.design_path.name}…")


def undo():
    SESSION.undo()


def redo():
    SESSION.redo()


def toggle_live():
    if SESSION.watching():
        SESSION.stop_watch()
        return message("live rebuild stopped")
    if SESSION.design_path is None and not SESSION.attach_view():
        return message("no design open (Quantcore > Open design...)")
    return SESSION.start_watch()


def _current_top():
    cv = pya.CellView.active()
    if cv is None or cv.cell is None:
        raise RuntimeError("no layout open")
    return SESSION.chip_cell() or cv.cell  # not layout.top_cell(): a deleted component leaves an extra top cell


def sync_placements():
    """Instances moved with KLayout's own move tool → ``place.at`` (snap-placed ones become absolute)."""
    design = SESSION.design()
    top = _current_top()
    chip = design_io.find_chip_cell(top)
    design, report = design_io.sync_placements(design, chip)
    design, added = design_io.new_pcell_instances(design, top)
    report += added
    if not report:
        return message("design.json already matches the layout")
    return SESSION.commit(design, "; ".join(report))


def path_to_route():
    """Selected path(s) → routes: ends snap to ports, corners become waypoints bent to the route radius."""
    view = pya.LayoutView.current()
    if view is None or SESSION.data is None and not SESSION.attach_view(view):
        return message("open a qcc-built layout first")
    design = SESSION.design()
    capture = SESSION.capture_px / view.viewport_trans().mag
    made, shapes = [], []
    for obj in view.each_object_selected():
        if obj.is_cell_inst() or not obj.shape.is_path():
            continue
        dbu = obj.layout().dbu
        path = obj.shape.path.transformed(obj.trans()).to_dtype(dbu)
        pts = [(p.x, p.y) for p in path.each_point()]
        try:
            src, dst, nodes = design_io.route_from_path(pts, SESSION.data["ports"], capture * 3)
        except ValueError as e:
            message(str(e))
            continue
        opts = tools.route_dialog(design_io.unique_name(design, "R"), "cpw", None, None, "qcc: path → route")
        if opts is None:
            continue
        name = opts["name"]
        design_io.add_route(design, name, src, dst, opts["kind"], opts["length"], nodes, opts["r"])
        made.append(f"{name}: {src} → {dst} ({len(nodes)} waypoints)")
        shapes.append(obj.shape)
    if not made:
        return message("select drawn path(s) whose ends touch two ports")
    for shape in shapes:
        shape.delete()  # the drawing was only a sketch; the route comes from design.json
    return SESSION.commit(design, "; ".join(made))


def place_component():
    """Place the component selected in the Quantcore panel (with the parameters shown there); without a selection,
    open the panel to pick one."""
    from qcc_kplugin import dock  # pylint: disable=import-outside-toplevel

    dock.show_dock()
    panel = dock.DOCK[0]
    panel.tabs.setCurrentIndex(0)
    cell = panel.selected()
    if cell is None:
        return message("Quantcore panel: click a component (its parameters show), then Place component again")
    panel._place(panel.components.currentItem)  # pylint: disable=protected-access
    return None


def selected_component() -> str | None:
    """The component selected with KLayout's own select tool, else the one under the *Move/Snap* cursor."""
    view = pya.LayoutView.current()
    design = SESSION.data or {}
    if view is not None:
        for obj in view.each_object_selected():
            if obj.is_cell_inst():
                pid = obj.inst().property("id")
                if pid and str(pid) in design.get("instances", {}):
                    return str(pid)
    tool = tools.ACTIVE[0] if tools.ACTIVE else None
    if isinstance(tool, tools.SnapTool) and tool.active:
        return tool.instance_at(tool.mouse)
    return None


def selected_route() -> str | None:
    """The route selected with KLayout's own select tool (a route cell carries its design name in ``id``)."""
    view = pya.LayoutView.current()
    routes = (SESSION.data or {}).get("routes", {})
    if view is not None:
        for obj in view.each_object_selected():
            if obj.is_cell_inst():
                pid = obj.inst().property("id")
                if pid and str(pid) in routes:
                    return str(pid)
    return None


def duplicate_selected():
    """A copy of the selected component (same cell, parameters, rotation, mirror, junction) follows the mouse in
    *Move/Snap*; a click drops it."""
    name = selected_component()
    if name is None:
        return message("select a component first (KLayout's select tool, or point at it in Move/Snap), then Duplicate")
    spec = design_io.duplicate_spec(SESSION.design(), name)
    tools.arm_place(spec["cell"], spec["params"], spec["rot"], spec["mirror"], spec["extra"])
    return message(f"copy of {name}: click to drop it, [ ] rotate, right-click cancels")


def mirror_selected():
    """Mirror the selected component (about its own x axis, before its rotation or snap)."""
    name = selected_component()
    if name is None:
        return message("select a component first (KLayout's select tool, or point at it in Move/Snap), then Mirror")
    design = SESSION.design()
    state = design_io.mirror_instance(design, name)
    return SESSION.commit(design, f"{name}: mirror {'on' if state else 'off'}")


def edit_selected():
    """PCell parameters + rotation of the component selected with KLayout's own select tool (or under the
    Move/Snap cursor): the same dialog as double-clicking it in *Move/Snap*."""
    name = selected_component()
    if name is None:
        route = selected_route()
        if route is not None:  # a route selected with KLayout's select tool: its dialog (type, length, hanger, ...)
            return tools.edit_route_options(route)
        return message("select a component or a route first (KLayout's select tool, a click on it), then Edit")
    design = SESSION.design()
    out = tools.edit_instance_dialog(name, design["instances"][name], design.get("targets", {}).get(name, {}))
    if out is None:
        return None
    return SESSION.commit(design, tools.apply_instance_edit(design, name, out))


def delete_instance():
    if SESSION.data is None and not SESSION.attach_view():
        return message("open a qcc-built layout first")
    names = sorted(SESSION.data.get("instances", {}))
    name = pya.InputDialog.ask_item("Delete instance", "Instance (its routes are removed too)", names, 0)
    if not name:
        return None
    design, gone = design_io.delete_instance(SESSION.design(), name)
    return SESSION.commit(design, f"deleted {name}" + (f" and routes {', '.join(gone)}" if gone else ""))


def delete_route():
    """Quantcore > Edit > Delete route...: a route chosen from the list, failed ones first (they have no cell to select
    and delete with KLayout's own Delete)."""
    if SESSION.data is None and not SESSION.attach_view():
        return message("open a qcc-built layout first")
    failed = sorted((SESSION.data or {}).get("failed_routes") or {})
    names = failed + [n for n in sorted(SESSION.data.get("routes", {})) if n not in failed]
    if not names:
        return message("this design has no routes")
    labels = [f"{n}  (failed)" if n in failed else n for n in names]
    pick = pya.InputDialog.ask_item("Delete route", "Route (a route hanging on it is removed too)", labels, 0)
    if not pick:
        return None
    tools.delete_route(names[labels.index(pick)])
    return None


def screenshot():
    path = pya.QFileDialog.getSaveFileName(None, "Save view as PNG", "", "PNG (*.png)")
    if path:
        pya.LayoutView.current().save_image_with_options(path, 1600, 1200, 0, 2, 0, pya.DBox(), False)
        message(f"saved {Path(path).name}")


def show_dock():
    from qcc_kplugin import dock  # pylint: disable=import-outside-toplevel

    if SESSION.data is None:
        SESSION.attach_view()
    dock.show_dock()


def _panel():
    from qcc_kplugin import dock  # pylint: disable=import-outside-toplevel

    show_dock()
    return dock.DOCK[0]


def check_design():
    """Quantcore > Check and LOM > Check design: the DRC tab plus the full check (netlist) in the background."""
    return _panel().check()


def run_lom():
    """Quantcore > Check and LOM > Run LOM: export the circuit and simulate it in a background process; the LOM tab
    of the panel shows modes, parameters against targets, netlist values and the circuit drawing."""
    return _panel().run_lom()


def stop_lom():
    """Quantcore > Check and LOM > Stop LOM simulation: stop the running LOM (the process this panel started), drop its
    partial output and show the state from before the run."""
    return _panel().stop_lom()
