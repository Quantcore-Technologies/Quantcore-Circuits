"""The Values tab and the layout annotations of :mod:`qcc_kplugin.instance_values`.

Tick *Show values in the layout* and every qubit and resonator with a value gets its f_q / α (or f_r / κ / χ) written
beside it, green / amber / red by |value − target| / tolerance. Selecting an instance (KLayout's select tool) shows its
values in the tab; clicking a row selects the instance. Markers only: the layout and design.json are not touched. The
values refresh after every rebuild, Run LOM and Import results.
"""

from __future__ import annotations

import pya  # type: ignore

from qcc_kplugin import instance_values as iv
from qcc_kplugin import tools
from qcc_kplugin.session import SESSION, log

STATE = {"on": False, "overlay": None, "values": {}, "tab": None, "view": None}
_BRUSH = {"ok": "#bfe8c3", "near": "#f5e3a8", "off": "#f4b6b6", "none": "#e4e4e4"}


def values() -> dict:
    """The collected values of the open design (``{element: rows}``); empty without a design."""
    if SESSION.design_path is None:
        return {}
    return iv.collect(iv.sources(SESSION.design_path, SESSION.data))


def _anchor(name: str):
    """(bbox) of an instance or of a route's polyline in the sidecar, or None."""
    data = SESSION.data or {}
    bb = (data.get("instances", {}).get(name) or {}).get("bbox")
    if bb:
        return bb
    line = (data.get("routes", {}).get(name) or {}).get("polyline")
    if line and len(line) > 1:
        xs, ys = [p[0] for p in line], [p[1] for p in line]
        return [min(xs), min(ys), max(xs), max(ys)]
    return None


def _overlay():
    view, _ = SESSION.find_view()
    if view is None:
        view = pya.LayoutView.current()
    old = STATE["overlay"]
    if old is not None and (view is None or old.view is not view):
        old.clear()
        STATE["overlay"] = old = None
    if view is None:
        return None
    if old is None:
        old = STATE["overlay"] = tools._Overlay(view)  # pylint: disable=protected-access
    return old


def draw(vals: dict | None = None) -> int:
    """(Re)draw the annotations; returns the number of markers. Nothing is drawn while the toggle is off."""
    o = _overlay()
    if o is None:
        return 0
    o.clear()
    if not STATE["on"]:
        return 0
    vals = values() if vals is None else vals
    for name, rows in vals.items():
        bb = _anchor(name)
        if not bb:
            continue
        o.rect(bb, iv.COLOURS[iv.worst(rows)], style=0, width=2)
        x, y = bb[2] + o.px(10), bb[3]
        for r in rows:
            if r["value"] is None:
                continue
            o.text((x, y), iv.line(r), iv.COLOURS[r["grade"]])
            y -= o.px(18)
    return len(o.markers)


def select(name: str) -> bool:
    """Select instance or route ``name`` with KLayout's select tool and zoom to it."""
    view, _ = SESSION.find_view()
    chip = SESSION.chip_cell()
    if view is None or chip is None:
        return False
    inst = next((i for i in chip.each_inst() if i.property("id") == name), None)
    if inst is None:
        return False
    path = pya.ObjectInstPath()
    path.top = chip.cell_index()
    path.append_path(pya.InstElement.new(inst))
    view.object_selection = [path]
    bb = _anchor(name)
    if bb:
        pad = 0.25 * max(bb[2] - bb[0], bb[3] - bb[1], 400.0)
        view.zoom_box(pya.DBox(bb[0] - pad, bb[1] - pad, bb[2] + 3 * pad, bb[3] + pad))
    return True


def selected() -> list[str]:
    from qcc_kplugin import flow  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    return flow.selected_names()


class ValuesTab:
    def __init__(self, tabs):
        page = pya.QWidget(tabs)
        lay = pya.QVBoxLayout(page)
        self.toggle = pya.QCheckBox("Show values in the layout", page)
        self.toggle.toolTip = ("Write f_q, α (qubits) or f_r, κ, χ (resonators) beside each instance, green / amber / "
                               "red by |value − target| / tolerance. Display only: design.json is not changed.")
        self.toggle.clicked(lambda _c=False: self.set_on(self.toggle.isChecked()))
        lay.addWidget(self.toggle)
        self.readout = pya.QLabel("Select an instance to see its values", page)
        self.readout.wordWrap = True
        lay.addWidget(self.readout)
        self.tree = pya.QTreeWidget(page)
        self.tree.setHeaderLabels(["instance", "LOM", "FEM", "consensus", "target ± tol", "status"])
        self.tree.toolTip = ("value per instance: the layout colour judges the FEM value, else the LOM value, else "
                             "the consensus. Click a row to select the instance.")
        self.tree.itemClicked(self._click)
        lay.addWidget(self.tree)
        tabs.addTab(page, "Values")
        self.items = {}  # element → its top-level tree item
        self.vals = {}
        STATE["tab"] = self
        SESSION.listeners.append(self.refresh)
        self.refresh()  # the panel can open after the design

    def set_on(self, on: bool):
        STATE["on"] = bool(on)
        self.toggle.setChecked(bool(on))
        self.refresh()

    def _hook(self):
        """Follow KLayout's selection (re-hooked when the view changes)."""
        view, _ = SESSION.find_view()
        if view is None or STATE["view"] is view:
            return
        STATE["view"] = view
        try:
            view.on_selection_changed += self.on_selection
        except Exception as e:  # noqa: BLE001
            log(f"values: selection hook failed ({e!r})")

    def refresh(self):
        """After a rebuild, Run LOM or Import results: collect again, refill, redraw."""
        try:
            self._hook()
            self.vals = values()
            self.tree.clear()
            self.items = {}
            for name, rows in self.vals.items():
                top = pya.QTreeWidgetItem(self.tree, [name, "", "", "", "", iv.worst(rows)])
                self.items[name] = top
                for r in rows:
                    lom, fem, cons, tgt, grade = iv.detail(r)
                    child = pya.QTreeWidgetItem(top, [f"{r['label']} ({r['unit']})", lom, fem, cons, tgt, grade])
                    child.setBackground(5, pya.QBrush(pya.QColor(_BRUSH[grade])))
                top.setBackground(5, pya.QBrush(pya.QColor(_BRUSH[iv.worst(rows)])))
            if not self.vals:
                pya.QTreeWidgetItem(self.tree, ["no values yet", "Run LOM, or set targets and import results", "", "",
                                                "", ""])
            self.tree.expandAll()
            for col in range(6):
                self.tree.resizeColumnToContents(col)
            draw(self.vals)
            self.on_selection()
        except Exception as e:  # noqa: BLE001
            log(f"values: refresh failed ({e!r})")

    def on_selection(self):
        try:
            names = [n for n in selected() if n in self.vals]
        except Exception:  # noqa: BLE001
            names = []
        self.readout.text = ("\n".join(iv.readout(n, self.vals[n]) for n in names) if names
                             else "Select an instance to see its values")

    def _click(self, item, _col=0):
        parent = item.parent()
        name = (parent if parent is not None else item).text(0)
        if name in self.vals:
            select(name)


def build_tab(tabs) -> ValuesTab:
    return ValuesTab(tabs)
