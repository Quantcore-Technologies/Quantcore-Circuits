"""The Quantcore menu: six submenus that follow the flow, plus the panel and Settings::

    Quantcore
      Design           New / open, chip settings, rebuild, save as Python
      Edit             undo / redo, edit / rename component, add coupling, delete route, rotate, duplicate, mirror,
                       route-node tools (the keyboard-only actions live here: KLayout needs a menu entry for a
                       shortcut)
      Check and LOM    DRC, run the LOM simulation (it also writes the circuit, build/<name>.circuit.json)
      Simulate         from ``qcc_kplugin.flow.ACTIONS`` (submenu "simulate": Simulate, Open simulation layout, Import
                       results), else "(coming soon)"
      Results          from ``qcc_kplugin.flow.ACTIONS`` (submenu "results")
      Fab              from ``qcc_kplugin.flow.ACTIONS`` (submenu "fab")
      Quantcore panel (Ctrl+Shift+P)
      Settings…

Not in the menu on purpose (the audit of 2026-11-16: each is done by the panel, a dialog or KLayout itself): place a
component (double-click it in the panel), selected path → route (the Connect tool), live rebuild (every edit already
rebuilds with ``qcc build --keep-going``), write moved instances (moves and deletes with KLayout's own tools are
written to design.json by themselves), save view as PNG (KLayout's File > Screenshot), junction values (the component
dialog has the L_J / I_c / R_n / C_J rows), delete instance (KLayout's Delete), stop LOM (the panel's Stop button),
export sim job (the Simulate dialog's "Export the job only") and open results file (Import results takes a file).
The menu has 30 items (29 before Simulate ▸ Open simulation layout, which shows the geometry HFSS imports in a new tab).

``flow.ACTIONS`` is a list of ``(submenu, name, title, func, shortcut)`` tuples, ``submenu`` one of ``design``,
``simulate``, ``results``, ``fab`` (``design`` items go to the end of the Design submenu); the module and the
attribute are optional.
"""

from __future__ import annotations

import pya  # type: ignore

from qcc_kplugin import actions, edits, tools
from qcc_kplugin.session import log, report_error

ROOT = "qcc_menu"
SUBMENUS = (  # (menu name, title) in menu order
    ("qcc_design_menu", "Design"),
    ("qcc_edit_menu", "Edit"),
    ("qcc_check_menu", "Check and LOM"),
    ("qcc_simulate_menu", "Simulate"),
    ("qcc_results_menu", "Results"),
    ("qcc_fab_menu", "Fab"),
)
FILLED: list[str] = []  # names of the flow.ACTIONS items the last build() added (for tests)
FLOW_SUBMENUS = {"design": "qcc_design_menu", "simulate": "qcc_simulate_menu", "results": "qcc_results_menu",
                 "fab": "qcc_fab_menu"}
PLACEHOLDER_SUBMENUS = ("qcc_simulate_menu", "qcc_results_menu", "qcc_fab_menu")  # "(coming soon)" when empty


def _items():
    """(submenu or None, name, title, func, shortcut) for the fixed part of the menu."""
    D, E, C = "qcc_design_menu", "qcc_edit_menu", "qcc_check_menu"
    return [
        (D, "qcc_new", "New design…", actions.new_design, ""),
        (D, "qcc_open", "Open design…", actions.open_design, ""),
        (D, "qcc_chip", "Chip settings (label, die size)…", edits.chip_settings, ""),
        (D, "qcc_rebuild", "Rebuild", actions.rebuild, "Ctrl+Shift+B"),
        (E, "qcc_undo", "Undo last design edit", actions.undo, "Ctrl+Shift+Z"),
        (E, "qcc_redo", "Redo design edit", actions.redo, "Ctrl+Shift+Y"),
        (E, "qcc_edit", "Edit selected component (position, rotation, parameters, targets)…", actions.edit_selected,
         "Ctrl+Shift+Q"),
        (E, "qcc_rename", "Rename selected component…", edits.rename_instance, ""),
        (E, "qcc_coupling", "Add coupling between components…", edits.add_coupling, ""),
        (E, "qcc_delete_route", "Delete route… (a failed route too)", actions.delete_route, ""),
        (E, "qcc_rot_ccw", "Rotate the component being placed or moved +90°", lambda: tools.rotate(90.0), "["),
        (E, "qcc_rot_cw", "Rotate the component being placed or moved −90°", lambda: tools.rotate(-90.0), "]"),
        (E, "qcc_duplicate", "Duplicate selected component", actions.duplicate_selected, "Ctrl+Shift+U"),
        (E, "qcc_mirror", "Mirror selected component", actions.mirror_selected, "Ctrl+Shift+F"),
        (E, "qcc_node_delete", "Delete selected route node", tools.delete_selected_node, "Ctrl+Shift+X"),
        (E, "qcc_node_props", "Route node properties (x, y, corner radius, airbridge, taper)…", tools.node_properties,
         "Ctrl+Shift+N"),
        (E, "qcc_meander_here", "Meander on the segment under the cursor", tools.meander_here, "Ctrl+Shift+M"),
        (E, "qcc_join_mode", "Connect on a line: hang beside it / merge into it (T-junction)", tools.toggle_join, "Ctrl+Shift+J"),
        (C, "qcc_drc", "Check design (DRC and netlist)", actions.check_design, "Ctrl+Shift+D"),
        (C, "qcc_pad_edge", "Fix pad edge warnings (PDK 100 µm rule)", edits.fix_pad_edges, ""),
        (C, "qcc_run_lom", "Run LOM simulation (circuit → modes, f_q, α, f_r, χ, κ)", actions.run_lom, "Ctrl+Shift+O"),
        # no separate "Export LOM circuit": Run LOM writes build/<name>.circuit.json, and Fab export bundles it
    ]


def flow_actions() -> list[tuple]:
    """``flow.ACTIONS`` when the module and the attribute exist, else ``[]``. Never raises."""
    try:
        from qcc_kplugin import flow  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
    except Exception as e:  # noqa: BLE001  (not written yet, or broken: the menu must still come up)
        if not isinstance(e, ImportError):
            log(f"menu: importing qcc_kplugin.flow failed: {e!r}")
        return []
    try:
        return [tuple(a) for a in getattr(flow, "ACTIONS", [])]
    except Exception as e:  # noqa: BLE001
        log(f"menu: flow.ACTIONS unusable: {e!r}")
        return []


def _safe(func, title):
    """A menu action that raises must not end in KLayout's "Script Error" box: report it (log + one dialog)."""

    def run():
        try:
            return func()
        except Exception:  # noqa: BLE001
            report_error(title)
            return None

    return run


def build(menu=None):
    """(Re)build the Quantcore menu in the main window (idempotent: an existing menu is left alone)."""
    menu = menu or pya.Application.instance().main_window().menu()
    if menu.is_valid(ROOT):
        return menu

    def add(name, title, func, shortcut="", where=ROOT, enabled=True):
        action = pya.Action()
        action.title = title
        if shortcut:
            action.shortcut = shortcut
        if tools.icon(name):
            action.icon = tools.icon(name)
        if func is not None:
            action.on_triggered(_safe(func, title))
        menu.insert_item(where + ".end", name, action)
        if not enabled:  # after the insert: KLayout keeps the menu's own copy of the state
            menu.action(f"{where}.{name}").enabled = False
        return action

    menu.insert_menu("help_menu", ROOT, "Quantcore")
    for name, title in SUBMENUS:
        menu.insert_menu(ROOT + ".end", name, title)
    for sub, name, title, func, shortcut in _items():
        add(name, title, func, shortcut, f"{ROOT}.{sub}")
    filled = set()
    FILLED.clear()
    for entry in flow_actions():
        try:
            sub, name, title, func, shortcut = entry
            where = FLOW_SUBMENUS[sub]
            add(name, title, func, shortcut or "", f"{ROOT}.{where}")
            filled.add(where)
            FILLED.append(name)
        except Exception as e:  # noqa: BLE001
            log(f"menu: skipped flow action {entry!r}: {e!r}")
    for where in PLACEHOLDER_SUBMENUS:
        if where not in filled:
            add(f"{where}_soon", "(coming soon)", None, "", f"{ROOT}.{where}", enabled=False)
    menu.insert_separator(ROOT + ".end", "qcc_sep_panel")
    add("qcc_dock", "Quantcore panel (flow · components · LOM · DRC)", actions.show_dock, "Ctrl+Shift+P")
    add("qcc_config", "Settings…", actions.configure)
    return menu
