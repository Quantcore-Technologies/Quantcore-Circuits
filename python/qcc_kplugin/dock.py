"""Quantcore dock panel: the Flow strip on top, then components, LOM, DRC and results.

* **Flow strip** — Design → Check → LOM → Simulate → Results → Fab, one button per step with a status mark (done /
  needs attention / not yet). Simulate, Results and Fab call ``qcc_kplugin.flow`` when it exists.
* **Components** — double-click a cell to arm *Move/Snap* in place mode; the next click drops it (parameters can be
  given as JSON). Ports of the new instance are then connected with *Connect* or *Route handles*.
* **LOM** — *Run LOM* exports the circuit and simulates it (QuCat / QuTiP) in a background process: modes, the derived
  parameters (f_q, alpha, f_r, chi, kappa) against the targets in design.json, the netlist values and the circuit
  drawing. Below: the circuit nodes / branches of the layout, as ``qcc`` derives them (updates on every rebuild).
* **DRC** — dangling ports, overlaps, crossings, components without a LOM model; click an issue to zoom to it.
  *Check* also runs the netlist check (opens / shorts) in the background and lists its result below.

Everything comes from the sidecar written by each build; nothing here imports quantcore_circuits.
"""

from __future__ import annotations

import json

import pya  # type: ignore

from qcc_kplugin import design_io, jobs, qcache, tools
from qcc_kplugin import session as _session
from qcc_kplugin.session import SESSION, config, log, message, report_error

# looked up with a default: a KLayout that loaded an older session.py before this module was updated still opens the panel
CFG_LOM_LIMIT = getattr(_session, "CFG_LOM_LIMIT", "qcc-kplugin-lom-limit-min")
ALL_CATEGORIES = "all classes"
LEGACY = "legacy (kept for old designs)"


def _fresh_jobs():
    """A KLayout that loaded ``jobs.py`` before an update keeps the old ``jobs.run`` (no ``timeout``): this panel is
    imported later, so load the new one (only while no job runs; its module state is only that list)."""
    import importlib  # pylint: disable=import-outside-toplevel
    import inspect  # pylint: disable=import-outside-toplevel

    try:
        if "timeout" not in inspect.signature(jobs.run).parameters and not getattr(jobs, "RUNNING", None):
            importlib.reload(jobs)
            log("the plugin was updated while KLayout ran: jobs.py reloaded (restart KLayout to load the rest)")
    except Exception:  # noqa: BLE001
        pass


_fresh_jobs()

_NO_WINDOW = 0x08000000

FLOW_STEPS = (
    ("design", "Design", "Draw the chip: pick components in the Components tab and place them, then connect ports.\n"
                         "Next: Check."),
    ("check", "Check", "Run the design checks (dangling ports, overlaps, crossings, opens / shorts) and show the DRC "
                       "tab.\nNext: LOM."),
    ("lom", "LOM", "Make the lumped circuit of the drawn chip and simulate it (QuCat / QuTiP): f_q, anharmonicity, "
                   "f_r, chi, kappa against your targets, in the LOM tab. Runs in the background.\n"
                   "Next: Simulate."),
    ("simulate", "Simulate", "Run the full-wave / FEM simulation of the chip or of the selected components.\n"
                             "Next: Results."),
    ("results", "Results", "Read the simulation back, compare it with the LOM and the targets, and tune the design."
                           "\nNext: Fab."),
    ("fab", "Fab", "Write the fab mask (PDK rules, cheese, layer table) and the other exports."),
)
_MARK = {"done": "✓", "warn": "⚠", "todo": "–"}
_WARN = {  # what a ⚠ means, per step (shown in the hint line when that step is the next one)
    "check": "issues found: see the DRC tab",
    "lom": "the design changed since: run LOM again",
    "simulate": "the results are from another revision: simulate again",
    "results": "a target is not met: Results > Propose next revision",
    "fab": "the mask is older than the design: export again",
}
_PNG_WIDTH = 330


def _get(obj, name):
    """A Qt getter through pya, which exposes some as properties and some as methods."""
    value = getattr(obj, name)
    return value() if callable(value) else value


# Run LOM stages, as the progress bar shows them: step 1 is ``qcc circuit export``; ``qcc circuit simulate`` prints a
# "[lom] <key>" line (stderr) as it enters each of the others
LOM_STAGES = (("", "exporting the circuit"), ("[lom] reading", "reading the circuit"),
              ("[lom] solving", "QuCat normal modes + QuTiP spectrum"), ("[lom] writing", "writing the result"),
              ("[lom] drawing", "drawing the circuit"))


def lom_warnings(output: str) -> list[str]:
    """The ``WARNING: route R2 failed to build (...); using its last good route`` lines of a LOM run's output (the
    circuit export prints each as a note and as a Python warning), once each, without the ``note:`` / file prefix."""
    out = []
    for line in output.splitlines():
        at = line.find("WARNING: route ")
        if at < 0:
            continue
        text = line[at:].strip()
        if text not in out:
            out.append(text)
    return out


def lom_stage(step_index: int, text: str) -> int:
    """1-based Run LOM stage from the running step and its output so far."""
    if step_index <= 0:
        return 1
    stage = 2
    for i, (key, _title) in enumerate(LOM_STAGES[1:], start=2):
        if key in text:
            stage = i
    return stage


def _wrap(label):
    """A label whose text wraps and never widens the dock: an unwrapped status line (e.g. a failed LOM's error) sets the
    dock's minimum width to its length and squeezes the layout view (the capture radius in µm grows with it)."""
    try:
        label.setWordWrap(True)
        label.setSizePolicy(pya.QSizePolicy.Ignored, pya.QSizePolicy.Preferred)
    except Exception as e:  # noqa: BLE001  (layout nicety)
        log(f"dock: label wrap not set ({e!r})")
    return label


class QuantcoreDock:
    def __init__(self):
        mw = pya.Application.instance().main_window()
        self.dock = pya.QDockWidget("Quantcore", mw)
        self.dock.objectName = "quantcore_dock"
        root = pya.QWidget(self.dock)
        root_lay = pya.QVBoxLayout(root)
        root_lay.setContentsMargins(4, 4, 4, 4)
        root_lay.setSpacing(4)
        strip = pya.QHBoxLayout()
        strip.setSpacing(2)
        self.flow_buttons = {}
        for i, (key, title, tip) in enumerate(FLOW_STEPS):
            if i:
                arrow = pya.QLabel("→", root)
                strip.addWidget(arrow)
            b = pya.QPushButton(title, root)
            b.toolTip = tip
            b.objectName = f"qcc_flow_{key}"
            b.setStyleSheet("QPushButton { padding: 3px 4px; }")
            b.clicked(lambda _c=False, k=key: self.flow_click(k))
            strip.addWidget(b)
            self.flow_buttons[key] = b
        root_lay.addLayout(strip)
        self.flow_hint = pya.QLabel("", root)
        _wrap(self.flow_hint)
        root_lay.addWidget(self.flow_hint)
        tabs = pya.QTabWidget(root)
        root_lay.addWidget(tabs)
        self.dock.setWidget(root)
        self.full_check = None  # {"ok", "lines", "mtime"} of the last Check
        self.lom_result = None
        self.viewers = []

        comp = pya.QWidget(tabs)
        lay = pya.QVBoxLayout(comp)
        self.source = pya.QComboBox(comp)
        self.source.addItems(["quantcore", "kqc", "metal", "all"])
        self.source.toolTip = "Component library shown below (quantcore = the Quantcore PDK cells)"
        self.category = pya.QComboBox(comp)
        self.category.addItem(ALL_CATEGORIES)
        self.category.toolTip = ("Component class: every qubit gets qubit targets (f_q, α) and junction values, every "
                                 "resonator resonator targets, …")
        self.records = {}  # component ref → catalog record (name, category, description, note)
        self.components = pya.QListWidget(comp)
        self.table = pya.QTableWidget(0, 2, comp)
        self.table.setHorizontalHeaderLabels(["parameter", "value"])
        self.table.toolTip = "Parameters of the next placed component: double-click a value to edit it"
        self.schema = []
        self.cell = None  # the component whose parameters the table shows
        self.loading_list = False
        self.loading_schema = None  # the cell whose parameters are being loaded
        self._place_wanted = None
        self._place_token = 0
        refresh = pya.QPushButton("Refresh list", comp)
        pick = pya.QHBoxLayout()
        pick.addWidget(self.source)
        pick.addWidget(self.category)
        lay.addLayout(pick)
        lay.addWidget(_wrap(pya.QLabel("Click: parameters below · double-click: place ([ ] rotate, right-click cancels)",
                                       comp)))
        lay.addWidget(self.components)
        lay.addWidget(self.table)
        lay.addWidget(refresh)
        tabs.addTab(comp, "Components")
        self.tabs = tabs
        self.components.itemClicked(self._select)
        self.components.itemDoubleClicked(self._place)
        refresh.clicked(self.refresh_list)
        self.source.currentIndexChanged(lambda _i: self.load_components())
        self.category.currentIndexChanged(lambda _i: self.show_components())

        self._build_lom_tab(tabs)

        self.drc = pya.QListWidget(tabs)
        self.drc.itemClicked(self._zoom_drc)
        tabs.addTab(self.drc, "DRC")
        self.drc_items = []

        self.results = pya.QTreeWidget(tabs)
        self.results.setHeaderLabels(["element", "parameter", "value", "target · status"])
        self.results.toolTip = "Latest loop results per instance (build/<design>/state.json, via the sidecar)"
        tabs.addTab(self.results, "Results")

        groups = pya.QWidget(tabs)
        g_lay = pya.QVBoxLayout(groups)
        g_lay.addWidget(_wrap(pya.QLabel("Saved sim groups (design.json). Click one to draw its box, components and ports "
                                         "in the layout; they are for simulation only and are not part of the "
                                         "chip or any export.", groups)))
        self.sim_groups = pya.QListWidget(groups)
        self.sim_analysis = pya.QComboBox(groups)
        self.sim_analysis.toolTip = "The analysis the group is drawn for (its box and ports depend on it)"
        self.sim_hide = pya.QPushButton("Hide", groups)
        self.sim_info = _wrap(pya.QLabel("", groups))
        g_lay.addWidget(self.sim_groups)
        g_lay.addWidget(self.sim_analysis)
        g_lay.addWidget(self.sim_hide)
        g_lay.addWidget(self.sim_info)
        tabs.addTab(groups, "Sim groups")
        self._sim_specs = {}
        self._sim_filling = False
        self.sim_groups.itemClicked(self._pick_sim_group)
        self.sim_analysis.currentIndexChanged(lambda _i: self._show_sim_group())
        self.sim_hide.clicked(lambda _c=False: self._hide_sim_group())

        from qcc_kplugin import valuesview  # pylint: disable=import-outside-toplevel

        self.values = valuesview.build_tab(tabs)  # per-instance values: tab + layout annotations

        mw.addDockWidget(pya.Qt.RightDockWidgetArea, self.dock)
        SESSION.listeners.append(self.refresh)
        self._loaded = False
        self.update_flow()

    def load_components(self, force: bool = False):
        """The library's components with their class (``qcc components --json --details``), then the list.
        Cached (see :mod:`qcache`); on a miss ``qcc`` runs in the background and the list shows "loading…"."""
        src = self.source.currentText
        if force is True:
            qcache.clear()
            tools._SCHEMAS.clear()  # noqa: SLF001
            tools._GHOSTS.clear()  # noqa: SLF001
        name = f"list:{src}"
        cached = qcache.get(name)
        if cached is not None:
            return self._components_ready(src, cached)
        self.loading_list = True
        self.components.clear()
        self.components.addItem("loading components…")
        qcache.fetch(name, ["components", "--json", "--details"] + ([] if src == "all" else ["--source", src]),
                     lambda rows, src=src: self._components_ready(src, rows))
        return None

    def refresh_list(self):
        """The Refresh list button: forget the cache and ask ``qcc`` again."""
        self.load_components(force=True)

    def _components_ready(self, src, rows):
        if src != self.source.currentText:
            return  # the user switched the library meanwhile; the result is cached for later
        self.loading_list = False
        rows = rows or []
        if rows and isinstance(rows[0], str):  # an older qcc without --details
            rows = [{"ref": n, "name": n, "category": ""} for n in rows]
        if not rows:
            rows = [{"ref": "BondPad", "name": "BondPad", "category": "launcher"},
                    {"ref": "Xmon", "name": "Xmon", "category": "qubit"}]
        self.records = {r["ref"]: r for r in rows if r.get("cell", True)}
        for ref, r in self.records.items():
            tools.CATEGORY[ref] = r.get("category") or ""
        keep = self.category.currentText
        cats = sorted({r.get("category") or "other" for r in self.records.values()})
        if any(r.get("legacy") for r in self.records.values()):
            cats.append(LEGACY)  # the cells kept for old designs (still placeable; marked in their tooltip)
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(ALL_CATEGORIES)
        for c in cats:
            self.category.addItem(c)
        if keep in cats:
            self.category.currentText = keep
        self.category.blockSignals(False)
        self._loaded = True
        self.show_components()
        if qcache.get("schemas:quantcore") is not True:  # prefetch every Quantcore cell's parameters in one call
            qcache.fetch("schemas:quantcore", ["components", "--source", "quantcore", "--schemas"], bulk=True)

    def show_components(self):
        """The list: the components of the chosen class (all classes: every component), by name."""
        cat = self.category.currentText
        self.components.clear()
        for ref in sorted(self.records):
            r = self.records[ref]
            if cat == LEGACY:
                if not r.get("legacy"):
                    continue
            elif cat not in ("", ALL_CATEGORIES) and (r.get("category") or "other") != cat:
                continue
            self.components.addItem(ref)
            item = self.components.item(self.components.count - 1)
            item.toolTip = (f"{r.get('category') or 'other'}: {r.get('description') or ''}"
                            + (f"\n{r['note']}" if r.get("note") else "")
                            + (f"\nlegacy: {r['legacy']}" if r.get("legacy") else "")
                            + (f"\nsame circuit as {r['alias_of']} (drawn differently)" if r.get("alias_of") else ""))

    def _select(self, item):
        """Show the component's parameters (defaults) in the table (loaded in the background on a cache miss)."""
        try:
            if item is None or self.loading_list:
                return
            if item.text == self.cell:
                return  # keep the values the user edited
            cell = item.text
            self.cell = cell
            self.loading_schema = cell
            tools.schema_async(cell, lambda rows, cell=cell: self._schema_ready(cell, rows))
            if self.loading_schema == cell:  # not cached: say so until it arrives
                self.schema = []
                tools.fill_table(self.table, [], {})
                message(f"loading the parameters of {cell}…", 2)
        except Exception:  # noqa: BLE001
            report_error("reading the component parameters")

    def _schema_ready(self, cell, rows):
        if cell != self.cell:
            return  # another component was picked meanwhile
        self.loading_schema = None
        self.schema = rows
        tools.fill_table(self.table, self.schema, {}, cell)
        if self._place_wanted == cell:
            self._place_wanted = None
            self._place_go(cell)
        else:
            tools.ghost_async(cell, self.params())  # prefetch the outline a double-click will want

    def params(self) -> dict:
        return design_io.changed_params(self.schema, tools.table_values(self.table, self.schema))

    def selected(self) -> str | None:
        item = self.components.currentItem  # a property in pya
        return item.text if item is not None else None

    def _place(self, item):
        try:
            if item is None or self.loading_list:
                return message("select a component in the list first")
            self._select(item)
            if self.loading_schema == item.text:
                self._place_wanted = item.text  # armed as soon as the parameters are there
                return None
            self._place_go(item.text)
        except Exception:  # noqa: BLE001
            report_error("placing the component")
        return None

    def _place_go(self, cell):
        params = self.params()
        self._place_token += 1
        token = self._place_token

        def arm(_outline=None):
            if token != self._place_token:
                return  # another double-click came after this one
            try:
                tools.arm_place(cell, params)
            except Exception:  # noqa: BLE001
                report_error("placing the component")

        if tools.ghost_cached(cell, params):
            arm()
        else:
            message(f"loading the outline of {cell}…")
            tools.ghost_async(cell, params, arm)

    # ---- Sim groups tab -------------------------------------------------------------------------------------------
    def refresh_sim_groups(self):
        """The saved groups of design.json (the list keeps its selection while the names stay the same)."""
        specs = {}
        if SESSION.design_path is not None and SESSION.design_path.suffix == ".json":
            try:
                specs = design_io.read_design(SESSION.design_path).get("sim_groups") or {}
            except (OSError, ValueError):
                specs = {}
        if list(specs) == list(self._sim_specs) and specs == self._sim_specs:
            return
        keep = self.sim_groups.currentItem.text if self.sim_groups.currentItem is not None else None
        self._sim_specs = dict(specs)
        self.sim_groups.clear()
        for name, spec in specs.items():
            self.sim_groups.addItem(f"{name}")
            self.sim_groups.item(self.sim_groups.count - 1).toolTip = (
                f"{', '.join(spec.get('select', []))} · margin {spec.get('margin_um', 300):g} µm · "
                f"{', '.join(spec.get('analyses', []))}")
        for i in range(self.sim_groups.count):
            if self.sim_groups.item(i).text == keep:
                self.sim_groups.setCurrentRow(i)

    def _pick_sim_group(self, item):
        spec = self._sim_specs.get(item.text if item is not None else "", {})
        self._sim_filling = True
        self.sim_analysis.clear()
        self.sim_analysis.addItems(list(spec.get("analyses") or ["eigenmode_epr", "q3d_cmatrix"]))
        self._sim_filling = False
        self._show_sim_group()

    def _show_sim_group(self):
        from qcc_kplugin import simview  # pylint: disable=import-outside-toplevel

        item = self.sim_groups.currentItem
        if item is None or self._sim_filling:
            return
        name, analysis = item.text, self.sim_analysis.currentText

        def got(data, error):
            self.sim_info.text = (f"{name}: " + "; ".join(simview.summary(g) for g in data["groups"])
                                  if data else f"{name}: no preview ({error})")

        self.sim_info.text = f"{name}: working out the box and ports…"
        if not simview.request({"group": name, "analysis": analysis}, got):
            self.sim_info.text = "open a design.json first"

    def _hide_sim_group(self):
        from qcc_kplugin import simview  # pylint: disable=import-outside-toplevel

        simview.clear()
        self.sim_groups.clearSelection()
        self.sim_info.text = ""

    def refresh(self):
        data = SESSION.data or {}
        if not self._loaded and SESSION.design_path is not None:
            self.load_components()
        self.refresh_sim_groups()
        self.netlist.clear()
        lom = data.get("lom", {})
        nodes = pya.QTreeWidgetItem(self.netlist, ["nodes", "", str(len(lom.get("nodes", {})))])
        for n, layout in lom.get("nodes", {}).items():
            nets = ", ".join([layout.get("island", "")] + list(layout.get("aliases", []))) if layout else "ground"
            pya.QTreeWidgetItem(nodes, [n, "node", nets])
        branches = pya.QTreeWidgetItem(self.netlist, ["branches", "", str(len(lom.get("branches", {})))])
        for n, b in lom.get("branches", {}).items():
            pya.QTreeWidgetItem(branches, [n, b["type"], " – ".join(b["nodes"])])
        ports = pya.QTreeWidgetItem(self.netlist, ["ports → nodes", "", str(len(lom.get("port_nodes", {})))])
        for p, n in lom.get("port_nodes", {}).items():
            pya.QTreeWidgetItem(ports, [p, "port", n])
        for name, c in lom.get("controls", {}).items():
            pya.QTreeWidgetItem(self.netlist, [name, c.get("kind", "control"), c.get("target", "")])
        self.netlist.expandAll()
        self.refresh_drc()
        self.results.clear()
        groups = {}
        for element, label, value, extra in design_io.results_rows(data):
            if element not in groups:
                groups[element] = pya.QTreeWidgetItem(self.results, [element, "", "", ""])
            pya.QTreeWidgetItem(groups[element], ["", label, value, extra])
        if not groups:
            pya.QTreeWidgetItem(self.results, ["no results yet", "Flow: Simulate, or Simulate > Import results", "",
                                               ""])
        self.results.expandAll()
        for col in range(4):  # the dock is narrow: fit the columns instead of truncating values
            self.results.resizeColumnToContents(col)
        self.load_lom()
        self.update_flow()

    # ---- Flow strip ---------------------------------------------------------------------------------------------
    def flow_state(self) -> dict:
        """Done / warn / todo per step: file checks (:func:`design_io.flow_status`) plus this session's Check."""
        state = design_io.flow_status(SESSION.design_path, SESSION.data)
        state["check"] = "todo"
        if self.full_check is not None and SESSION.design_path is not None:
            # same design (sim groups and targets aside) as the one checked
            if design_io.design_fingerprint(SESSION.design_path) == self.full_check["fingerprint"]:
                state["check"] = "done" if self.full_check["ok"] else "warn"
        return state

    def update_flow(self):
        state = self.flow_state()
        for key, title, tip in FLOW_STEPS:
            b = self.flow_buttons[key]
            b.text = f"{title} {_MARK[state[key]]}"
            b.toolTip = tip + {
                "done": "\n[done]",
                "warn": "\n[done, but with issues or out of date]",
                "todo": "\n[not done yet]",
            }[state[key]]
        nxt = next(((k, t) for k, t, _ in FLOW_STEPS if state[k] != "done"), None)
        if nxt is None:
            self.flow_hint.text = "All steps done"
        else:
            self.flow_hint.text = f"Next: {nxt[1]}" + (f" ({_WARN[nxt[0]]})" if state[nxt[0]] == "warn" else "")

    def show_tab(self, name: str):
        for i in range(self.tabs.count):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i)
                return

    def flow_click(self, key: str):
        try:
            if key == "design":
                self.show_tab("Components")
            elif key == "check":
                self.check()
            elif key == "lom":
                self.run_lom()
            else:
                self._flow_call(key)
        except Exception:  # noqa: BLE001
            report_error(f"the {key} step")

    @staticmethod
    def _flow_call(name: str):
        flow = None
        try:
            from qcc_kplugin import flow  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        except Exception as e:  # noqa: BLE001  (missing module, or one that fails to import)
            if not isinstance(e, ImportError):
                log(f"importing qcc_kplugin.flow failed: {e!r}")
        fn = getattr(flow, name, None) if flow is not None else None
        if fn is None:
            return message(f"{name.capitalize()} is not available yet")
        return fn()

    # ---- Check -------------------------------------------------------------------------------------------------
    def check(self):
        """The DRC tab, plus the full check (netlist opens / shorts) in the background."""
        self.show_tab("DRC")
        if not SESSION.ensure_design():
            return message("open or create a design first (Quantcore > Design > New design...)")
        if jobs.busy("Check"):
            return message("the check is already running")
        design = SESSION.design_path
        self.full_check = None
        self.refresh_drc(running=True)
        fingerprint = design_io.design_fingerprint(design)  # the design as checked (it may change meanwhile)
        jobs.run([["design", "drc", design]], "Check", lambda ok, out: self._check_done(ok, out, fingerprint))
        return None

    def _check_done(self, ok, output, fingerprint=""):
        lines = [ln.rstrip() for ln in output.splitlines() if ln.strip()]
        self.full_check = {"ok": ok, "lines": lines, "fingerprint": fingerprint}
        self.refresh_drc()
        self.update_flow()

    def refresh_drc(self, running: bool = False):
        self.drc.clear()
        self.drc_items = list((SESSION.data or {}).get("drc", []))
        if not self.drc_items:
            self.drc.addItem("DRC clean")
        for issue in self.drc_items:
            self.drc.addItem(f"{issue['severity'].upper():7s} {issue['message']}")
        if running:
            self.drc.addItem("Full check running (netlist opens / shorts)…")
        elif self.full_check is not None:
            self.drc.addItem("— full check (with netlist): " + ("clean" if self.full_check["ok"] else "problems") + " —")
            for ln in self.full_check["lines"][-60:]:
                self.drc.addItem(ln)

    # ---- LOM tab ------------------------------------------------------------------------------------------------
    def _build_lom_tab(self, tabs):
        page = pya.QWidget(tabs)
        outer = pya.QVBoxLayout(page)
        outer.setContentsMargins(2, 2, 2, 2)
        top = pya.QHBoxLayout()
        self.lom_run = pya.QPushButton("Run LOM", page)
        self.lom_run.toolTip = ("Export the circuit of the design (build/<name>.circuit.json) and simulate it with "
                                "QuCat / QuTiP in a background process")
        self.lom_run.clicked(lambda _c=False: self.run_lom())
        self.lom_stop = pya.QPushButton("Stop", page)
        self.lom_stop.toolTip = ("Stop the running LOM simulation (only the process started here), discard its partial "
                                 "output and go back to the state before the run")
        self.lom_stop.enabled = False
        self.lom_stop.clicked(lambda _c=False: self.stop_lom())
        self.lom_status = _wrap(pya.QLabel("not run yet", page))
        top.addWidget(self.lom_run)
        top.addWidget(self.lom_stop)
        top.addWidget(self.lom_status)
        outer.addLayout(top)
        self.lom_bar = pya.QProgressBar(page)  # the stage of a running LOM, with the elapsed time
        self.lom_bar.setRange(0, len(LOM_STAGES))
        self.lom_bar.setValue(0)
        self.lom_bar.visible = False
        outer.addWidget(self.lom_bar)
        self.lom_log = pya.QPlainTextEdit(page)  # what qcc prints while the LOM runs (and why it failed)
        self.lom_log.setReadOnly(True)
        self.lom_log.setFixedHeight(120)
        self.lom_log.visible = False
        outer.addWidget(self.lom_log)
        self._lom_log_text = ""
        self._lom_warnings = []  # "WARNING: route R2 failed to build (...); using its last good route" of the last run
        self.lom_job = None
        self._lom_before = None
        scroll = pya.QScrollArea(page)
        scroll.setWidgetResizable(True)
        body = pya.QWidget(scroll)
        lay = pya.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)

        def head(text, tip=""):
            lab = pya.QLabel(f"<b>{text}</b>", body)
            lab.toolTip = tip
            lay.addWidget(lab)

        def table(headers):
            t = pya.QTableWidget(0, len(headers), body)
            t.setHorizontalHeaderLabels(headers)
            t.setEditTriggers(pya.QAbstractItemView.NoEditTriggers)
            lay.addWidget(t)
            return t

        head("Parameters vs targets", "Targets are set per component in its edit dialog (Ctrl+Shift+Q), stored in "
                                      "design.json under 'targets'. Tolerances (the same as qcc analyse): f_q 20 MHz, "
                                      "f_r 10 MHz, alpha 10 MHz, g 10 MHz, chi 0.1 MHz, kappa 0.2 MHz, else 1 %.")
        self.lom_params = table(["parameter", "value", "target", "status"])
        head("Modes")
        self.lom_modes = table(["#", "label", "kind", "f GHz", "κ MHz", "α MHz"])
        head("Netlist values", "C in fF, L / Lj in nH, ports in Ω")
        self.lom_net = table(["element", "type", "nodes", "value"])
        head("Circuit")
        self.lom_image = pya.QLabel("(run LOM to draw the circuit)", body)
        lay.addWidget(self.lom_image)
        self.lom_open = pya.QPushButton("Open the circuit picture full size", body)
        self.lom_open.clicked(lambda _c=False: self.open_png())
        self.lom_open.enabled = False
        lay.addWidget(self.lom_open)
        head("Connectivity of the layout", "Nodes with their FEM islands, branches, ports → nodes and controls, as "
                                           "qcc derives them from the layout (updates on every rebuild)")
        self.netlist = pya.QTreeWidget(body)
        self.netlist.setHeaderLabels(["item", "type", "nodes / nets"])
        self.netlist.setMinimumHeight(160)
        lay.addWidget(self.netlist)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        tabs.addTab(page, "LOM")
        self.lom_png = None

    def lom_files(self):
        """(circuit.json, lom.json, lom.png) for the open design."""
        d = SESSION.design_path
        build = d.parent / "build"
        return build / f"{d.stem}.circuit.json", build / d.stem / "lom.json", build / d.stem / "lom.png"

    def run_lom(self):
        """Export the circuit and simulate it in a background process; the LOM tab fills when it ends."""
        self.show_tab("LOM")
        if not SESSION.ensure_design():
            return message("open or create a design first (Quantcore > Design > New design...)")
        if jobs.busy("LOM"):
            return message("the LOM simulation is already running")
        circuit, result, png = self.lom_files()
        design = SESSION.design_path
        self._lom_before = self._lom_snapshot((circuit, result, png))  # what Stop goes back to
        self.lom_status.text = "running…"
        self.lom_run.enabled = False
        self.lom_stop.enabled = True
        try:
            limit_min = float(config(CFG_LOM_LIMIT, "30") or 30)
        except ValueError:
            limit_min = 30.0
        self.lom_bar.setValue(0)
        self.lom_bar.setFormat(f"1/{len(LOM_STAGES)} {LOM_STAGES[0][1]}")
        self.lom_bar.visible = True
        self._set_lom_log("")
        self._lom_warnings = []
        self.lom_log.visible = True
        fingerprint = design_io.design_fingerprint(design)  # the design as exported (it may change meanwhile)
        _fresh_jobs()
        self.lom_job = jobs.run(
            [["circuit", "export", design, "-o", circuit],
             ["circuit", "simulate", circuit, "--json", result, "--png", png]],
            "LOM", lambda ok, out: self._lom_done(ok, out, design, fingerprint),
            timeout=60.0 * limit_min, progress=self._lom_progress,
        )
        return None

    def _lom_snapshot(self, files) -> dict:
        """The state Stop restores: the three result files (bytes, or None when absent) and what the tab shows."""
        saved = {}
        for f in files:
            try:
                saved[f] = f.read_bytes() if f.exists() else None
            except OSError:
                saved[f] = None
        return {"files": saved, "status": self.lom_status.text, "bar": self.lom_bar.visible,
                "bar_value": self.lom_bar.value, "bar_format": self.lom_bar.format, "log": self.lom_log.visible,
                "log_text": self._lom_log_text}

    def stop_lom(self):
        """Stop the LOM run this panel started: kill its ``qcc`` process, drop the partial output, restore the tab."""
        job = self.lom_job
        if job is None or job.finished or not jobs.busy("LOM"):
            return message("no LOM simulation is running")
        job.cancel()  # calls _lom_done(False, "cancelled…"), which restores the state from before the run
        return None

    def _lom_restore(self):
        """After Stop: the result files as they were, the status line, bar and log as before the run."""
        before, self._lom_before = self._lom_before, None
        if not before:
            return
        for f, data in before["files"].items():
            try:
                if data is None:
                    f.unlink(missing_ok=True)  # written by the stopped run only
                elif not f.exists() or f.read_bytes() != data:
                    f.write_bytes(data)
            except OSError as e:
                log(f"LOM stop: could not restore {f}: {e!r}")
        self.lom_status.text = before["status"]
        self.lom_bar.visible = before["bar"]
        self.lom_bar.setValue(before["bar_value"])
        self.lom_bar.setFormat(before["bar_format"])
        self._set_lom_log(before["log_text"])
        self.lom_log.visible = before["log"]

    def _set_lom_log(self, text):
        lines = [ln for ln in text.splitlines() if ln.strip()][-200:]
        text = "\n".join(lines)
        if text == self._lom_log_text:
            return
        self._lom_log_text = text
        self.lom_log.setPlainText(text)
        try:  # follow the end of the log
            bar = _get(self.lom_log, "verticalScrollBar")
            bar.setValue(_get(bar, "maximum"))
        except Exception:  # noqa: BLE001  (a nicety)
            pass

    def _lom_progress(self, job):
        """Called by the job's timer while Run LOM runs: the stage bar and the live log."""
        text = job.live_text()
        stage = lom_stage(job.index, text)
        self.lom_bar.setValue(stage - 1)
        self.lom_bar.setFormat(f"{stage}/{len(LOM_STAGES)} {LOM_STAGES[stage - 1][1]} · {job.elapsed():.0f} s")
        self._set_lom_log(text)

    def _lom_done(self, ok, output, design=None, fingerprint=""):
        self.lom_run.enabled = True
        self.lom_stop.enabled = False
        job = self.lom_job
        if job is not None and job.cancelled:
            self._lom_restore()
            message("LOM: stopped, nothing was changed")
            return
        self._lom_before = None
        secs = f"{job.elapsed():.0f} s" if job is not None else ""
        self._set_lom_log(output)
        if ok:
            self.lom_bar.setValue(len(LOM_STAGES))
            self.lom_bar.setFormat(f"done in {secs}")
        else:
            self.lom_bar.setFormat(("stopped at the time limit" if job is not None and job.timed_out else "failed")
                                   + f" after {secs}")
        if not ok and job is not None and job.timed_out:
            self.lom_status.text = ("stopped: no result within the time limit (Quantcore > Settings); simulate a "
                                    "subset, or raise the limit")
            return
        if ok and design is not None:
            design_io.set_mark(design, "lom", fingerprint)
        if not ok and "at least one junction or inductor" in output:  # QuCat on a circuit without any qubit
            log(f"LOM: no qubit or inductor in the design:\n{output[-1500:]}")
            self.lom_status.text = "no qubit or inductor in the design: nothing to simulate yet"
            message("LOM: no qubit or inductor in the design: nothing to simulate yet (place a qubit first)")
            return
        if not ok:
            tail = [ln for ln in output.splitlines() if ln.strip()][-3:]
            log(f"LOM failed:\n{output[-3000:]}")
            self.lom_status.text = "LOM failed: " + " | ".join(tail)[-240:]
            if any(w in " ".join(tail).lower() for w in ("open", "short")):  # usually a qubit without its junction
                self.lom_status.text += ("\nHint: a qubit without junction values (Edit > Edit selected component, junction rows) or a port "
                                         "left open (Check) gives this.")
            return
        self._lom_warnings = lom_warnings(output)  # a failed route the LOM replaced by its last good one: say so
        if self._lom_warnings:
            message(self._lom_warnings[0] + (f" (+{len(self._lom_warnings) - 1} more, see the LOM tab)"
                                             if len(self._lom_warnings) > 1 else ""), 15)
        self.load_lom()
        self.values.refresh()
        self.update_flow()

    def load_lom(self):
        """Fill the LOM tab from build/<name>/lom.json (written by ``qcc circuit simulate --json``)."""
        if SESSION.design_path is None:
            return
        _, result, png = self.lom_files()
        if not result.exists():
            return
        try:
            res = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        try:
            targets = design_io.read_design(SESSION.design_path).get("targets", {})
        except (OSError, ValueError):
            targets = {}
        self.lom_result = res
        rows = design_io.compare_targets(res.get("params", {}), targets)
        self._fill(self.lom_params, [
            (r["key"], "–" if r["value"] is None else f"{r['value']:.5g}",
             "" if r["target"] is None else f"{r['target']:.5g} ± {r['tol']:.3g}", r["status"])
            for r in rows
        ], colour_col=3)
        self._fill(self.lom_modes, [
            (str(m["index"]), m["label"], m["kind"], f"{m['f_GHz']:.4f}", f"{m['kappa_MHz']:.4g}",
             f"{m['anharmonicity_MHz']:.1f}") for m in res.get("modes", [])
        ])
        self._fill(self.lom_net, design_io.netlist_rows(res))
        n_off = sum(1 for r in rows if r["status"] in ("off", "no value"))
        stale = design_io.flow_status(SESSION.design_path, SESSION.data)["lom"] == "warn"
        self.lom_status.text = (
            f"{len(res.get('modes', []))} modes, {n_off} off target" if any(r["target"] is not None for r in rows)
            else f"{len(res.get('modes', []))} modes (no targets set)"
        ) + ("  [out of date: design changed since, Run LOM]" if stale else "") + "".join(
            "\n" + w for w in self._lom_warnings)
        self.lom_png = png if png.exists() else None
        self.lom_open.enabled = self.lom_png is not None
        if self.lom_png is not None:
            pix = pya.QPixmap(str(self.lom_png))
            if not pix.isNull():
                self.lom_image.setPixmap(pix.scaledToWidth(_PNG_WIDTH, pya.Qt.SmoothTransformation))
                self.lom_image.toolTip = str(self.lom_png)

    @staticmethod
    def _fill(table, rows, colour_col=None):
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, text in enumerate(row):
                item = pya.QTableWidgetItem(str(text))
                if colour_col == j and text:
                    try:
                        item.setBackground(pya.QBrush(pya.QColor({"within tolerance": "#bfe8c3", "off": "#f4b6b6"}.get(
                            text, "#f5e3a8"))))
                    except Exception:  # noqa: BLE001  (colour is a nicety)
                        pass
                table.setItem(i, j, item)
        table.resizeColumnsToContents()
        try:  # the dock is narrow: no row numbers, and tall enough for every row (the tab scrolls, not the table)
            _get(table, "verticalHeader").setVisible(False)
            table.resizeRowsToContents()
            header = _get(_get(_get(table, "horizontalHeader"), "sizeHint"), "height")
            height = header + 2 * _get(table, "frameWidth") + 4 + sum(table.rowHeight(i) for i in range(len(rows)))
        except Exception as e:  # noqa: BLE001
            log(f"LOM tab: table height fallback ({e!r})")
            height = 30 + 24 * max(len(rows), 1)
        table.setFixedHeight(min(420, max(height, 48)))

    def open_png(self):
        """The circuit picture in its own (non-modal, resizable) window, never larger than the screen: it opens
        fitted to the window (Fit), and 100 % / − / + zoom it, with scroll bars when it is larger than the window."""
        if self.lom_png is None:
            return
        from qcc_kplugin import dialogs  # pylint: disable=import-outside-toplevel

        win = pya.QDialog(pya.Application.instance().main_window())
        win.windowTitle = f"Circuit: {self.lom_png.name}"
        lay = pya.QVBoxLayout(win)
        bar = pya.QHBoxLayout()
        area = pya.QScrollArea(win)
        area.setWidgetResizable(False)  # the picture keeps its zoomed size; the area scrolls over it
        lab = pya.QLabel(win)
        pix = pya.QPixmap(str(self.lom_png))
        pw, ph = max(1, int(_get(pix, "width"))), max(1, int(_get(pix, "height")))
        area.setWidget(lab)
        state = {"scale": 1.0}
        zoom_text = pya.QLabel("", win)

        def show(scale=None, first=False):
            if scale is None:  # Fit: the whole picture in the window, never enlarged
                if first:  # not shown yet: the viewport has no size; the window's size less the bar and margins
                    vw, vh = state["w"] - 40, state["h"] - 90
                else:
                    view = _get(area, "viewport")
                    vw, vh = int(_get(view, "width")), int(_get(view, "height"))
                scale = min(1.0, (vw - 24) / pw, (vh - 24) / ph)  # less the scroll bars: none appear
            scale = max(0.05, min(4.0, scale))
            state["scale"] = scale
            w = max(1, int(round(pw * scale)))
            try:
                lab.setPixmap(pix if abs(scale - 1.0) < 1e-6 else pix.scaledToWidth(w, pya.Qt.SmoothTransformation))
            except Exception:  # noqa: BLE001  (an older binding: no transformation mode)
                lab.setPixmap(pix.scaledToWidth(w))
            lab.adjustSize()
            zoom_text.text = f"{scale * 100:.0f} %"

        for text, fn in (("Fit", lambda: show(None)), ("100 %", lambda: show(1.0)),
                         ("−", lambda: show(state["scale"] / 1.25)), ("+", lambda: show(state["scale"] * 1.25))):
            b = pya.QPushButton(text, win)
            b.clicked(lambda _c=False, fn=fn: fn())
            bar.addWidget(b)
        bar.addWidget(zoom_text)
        bar.addStretch(1)
        lay.addLayout(bar)
        lay.addWidget(area, 1)
        try:
            win.setSizeGripEnabled(True)
        except Exception:  # noqa: BLE001
            pass
        dialogs.fit_window(win, pw + 40, ph + 90)
        state["w"], state["h"] = int(_get(win, "width")), int(_get(win, "height"))
        show(None, first=True)
        win.qcc_zoom = show  # tests
        win.qcc_state = state
        self.viewers.append(win)
        win.show()


    def _zoom_drc(self, item):
        row = self.drc.row(item)
        if row >= len(self.drc_items):
            return
        where = self.drc_items[row].get("where") or []
        view = pya.LayoutView.current()
        if where and view is not None:
            x, y = where[0]
            view.zoom_box(pya.DBox(x - 250, y - 250, x + 250, y + 250))


DOCK = []


def show_dock():
    if not DOCK:
        DOCK.append(QuantcoreDock())
    DOCK[0].dock.show()
    DOCK[0].refresh()
