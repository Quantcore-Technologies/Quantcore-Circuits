"""Simulate, Results and Fab: the last three steps of the Quantcore Flow strip (G4 – G6).

``ACTIONS`` fills the menu's Simulate / Results / Fab submenus; ``simulate`` / ``results`` / ``fab`` are what the
panel's Flow buttons call.

* **Simulate** (automatic): the components selected in KLayout are the subset (nothing selected: asks for the default
  subset or the whole chip). ``qcc sim auto`` runs in the background — subset, export, solve in a *new*
  non-graphical AEDT (never the one you have open), analyse — and the status bar shows its progress. KLayout stays
  usable; when it ends the layout is rebuilt so the Results tab shows the values.
* **Simulate** (manual): the Simulate dialog's *Export the job only* button (``export_job``) writes the job folder
  with a README (what to run, what to bring back); *Import results…* (a menu item) reads a
  solved job folder or a results.json back (format: ``qcc results template --format``).
* **Results** shows the latest values against the targets; *Propose next revision* previews old → new knob values
  (``loop.feedback``; 21 qubit classes with λ/4 or λ/2 readouts, through the generic surrogate in ``codesign.py``;
  what it cannot tune is listed as *Not tuned*), and *Apply* writes them to design.json through the session (undo
  works) and rebuilds.
* **Fab** writes the fab mask (``qcc mask``), the netlist (``circuit.json``), ``design.py`` (the drawn chip as a
  Designer script) and a PNG into one folder.

Everything slow runs as a ``qcc`` subprocess through :mod:`qcc_kplugin.jobs` (never in KLayout's UI thread, never a
modal dialog from a timer). The functions take ``wait=True`` for tests, which blocks until the job ended.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pya  # type: ignore

from qcc_kplugin import design_io, jobs, simrun, simsetup
from qcc_kplugin.session import SESSION, build_error, clean_env, config, log, message, report_error, set_config

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DIALOGS: list = []  # non-modal windows (kept alive here; tests read DIALOGS[-1])
CFG_AEDT_WINDOW = "qcc-kplugin-aedt-window"  # "1": simulate in a new AEDT window instead of a non-graphical one
CFG_SIM = "qcc-kplugin-sim-settings"  # JSON {analysis: {setting: value}}: the Simulate dialog's last values
AEDT_PATH_LIMIT = 250  # = quantcore_circuits.guiflow.AEDT_PATH_LIMIT (tests/test_kplugin_flow.py checks it)


def aedt_path_too_long(job_dir) -> bool:
    """AEDT fails on Windows when its ``*.aedtresults`` folders pass 260 characters; the job folder name is repeated
    in them (the same rule as ``quantcore_circuits.guiflow.aedt_path_too_long``)."""
    job_dir = Path(job_dir)
    return os.name == "nt" and len(str(job_dir.resolve())) + len(job_dir.name) + 75 > AEDT_PATH_LIMIT


# ---- small helpers -------------------------------------------------------------------------------------------------
def _main():
    return pya.Application.instance().main_window()


def _design_ready() -> bool:
    if not SESSION.ensure_design():
        message("open or create a design first (Quantcore > Design > New design...)")
        return False
    if SESSION.design_path.suffix != ".json":
        message("this step needs the design as a .json file (Quantcore > Design > Save as Python script writes a .py)")
        return False
    return True


def selected_names() -> list[str]:
    """Instances and routes selected with KLayout's own select tool (their ``id`` property is the design name)."""
    view = pya.LayoutView.current()
    data = SESSION.data or {}
    known = set(data.get("instances", {})) | set(data.get("routes", {}))
    names = []
    if view is not None:
        for obj in view.each_object_selected():
            if obj.is_cell_inst():
                pid = obj.inst().property("id")
                if pid and str(pid) in known and str(pid) not in names:
                    names.append(str(pid))
    return names


def choose(title: str, text: str, choices: list[str], checkbox: str | None = None):
    """A small modal question: one button per choice and Cancel. Returns ``(index, checked)`` or None. (An
    auto-accepted dialog returns the first choice, which is how the GUI smoke test drives it.)"""
    dialog = pya.QDialog(_main())
    dialog.windowTitle = title
    lay = pya.QVBoxLayout(dialog)
    label = pya.QLabel(text, dialog)
    label.wordWrap = True
    label.setMinimumWidth(460)
    lay.addWidget(label)
    box = pya.QCheckBox(checkbox, dialog) if checkbox else None
    if box is not None:
        box.checked = False
        lay.addWidget(box)
    picked = [None]

    def pick(i):
        picked[0] = i
        dialog.accept()

    for i, text_i in enumerate(choices):
        b = pya.QPushButton(text_i, dialog)
        b.clicked(lambda _c=False, i=i: pick(i))
        lay.addWidget(b)
    cancel = pya.QPushButton("Cancel", dialog)
    cancel.clicked(lambda _c=False: dialog.reject())
    lay.addWidget(cancel)
    accepted = dialog.exec_()
    if picked[0] is None:
        if not accepted:
            return None
        picked[0] = 0
    return picked[0], bool(box.checked) if box is not None else False


def ask_dir(title: str, start: str) -> str | None:
    path = pya.QFileDialog.getExistingDirectory(None, title, start)
    return str(path) if path else None


def ask_file(title: str, start: str, pattern: str = "JSON (*.json)") -> str | None:
    path = pya.QFileDialog.getOpenFileName(None, title, start, pattern)
    return str(path) if path else None


class _Window:
    """A non-modal window with a title, text and a Close button (results of background jobs: never modal from a timer)."""

    def __init__(self, title: str, width: int = 640, height: int = 420):
        self.dialog = pya.QDialog(_main())
        self.dialog.windowTitle = title
        from qcc_kplugin import dialogs  # pylint: disable=import-outside-toplevel

        dialogs.fit_window(self.dialog, width, height)  # never larger than the screen
        self.layout = pya.QVBoxLayout(self.dialog)
        self.buttons = {}
        self.row = None
        DIALOGS.append(self)
        del DIALOGS[:-8]

    def add_button(self, key: str, text: str, fn, tip: str = ""):
        if self.row is None:
            self.row = pya.QHBoxLayout()
            self.layout.addLayout(self.row)
        b = pya.QPushButton(text, self.dialog)
        if tip:
            b.toolTip = tip
        b.clicked(lambda _c=False: self._call(fn))
        self.row.addWidget(b)
        self.buttons[key] = b
        return b

    def _call(self, fn):
        try:
            fn()
        except Exception:  # noqa: BLE001
            report_error("this step")

    def finish(self, close_text: str = "Close"):
        self.add_button("close", close_text, self.dialog.close)
        self.dialog.show()
        self.dialog.raise_()
        return self


def info_window(title: str, text: str, buttons: dict | None = None) -> _Window:
    """Read-only text in a non-modal window, with optional extra buttons ``{key: (label, function)}``."""
    w = _Window(title)
    w.text = pya.QTextEdit(w.dialog)
    w.text.readOnly = True
    w.text.setPlainText(text)
    w.layout.addWidget(w.text)
    for key, (label, fn) in (buttons or {}).items():
        w.add_button(key, label, fn)
    return w.finish()


def open_folder(path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # noqa: S606  # pylint: disable=no-member
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
    except OSError as e:
        message(f"could not open {path}: {e}")


def _update_strip() -> None:
    """Refresh the panel's Flow strip marks (a step that writes files but no new sidecar, e.g. Fab)."""
    try:
        from qcc_kplugin import dock  # pylint: disable=import-outside-toplevel

        if dock.DOCK:
            dock.DOCK[0].update_flow()
    except Exception as e:  # noqa: BLE001  (the marks are a nicety; never fail the step for them)
        log(f"flow strip not updated: {e!r}")


def _rebuild() -> None:
    """Rebuild the layout (and its sidecar, which carries the results) like Quantcore > Design > Rebuild."""
    if SESSION.design_path is not None:
        SESSION._reload_after = 0.0  # pylint: disable=protected-access
        SESSION._build()  # pylint: disable=protected-access


def _flow_dir() -> Path:
    """``<layout folder>/<design name>.flow``: status files and exported proposals of the flow steps."""
    base = SESSION.layout_path.parent if SESSION.layout_path is not None else SESSION.design_path.parent / "build"
    d = base / f"{SESSION.design_path.stem}.flow"
    d.mkdir(parents=True, exist_ok=True)
    return d


class FlowJob(jobs.Job):
    """A :class:`jobs.Job` that shows its own progress (a status file the ``qcc`` command writes plus the AEDT progress
    line in its output) and can be stopped (only the process tree it started)."""

    def __init__(self, steps, label, done, cwd=None, status_file=None):
        super().__init__(steps, label, done, cwd)
        self.status_file = Path(status_file) if status_file else None
        self.cancelled = False
        self.last_step = ""

    def status(self) -> dict:
        try:
            return json.loads(self.status_file.read_text(encoding="utf-8")) if self.status_file else {}
        except (OSError, ValueError):
            return {}

    def progress_line(self) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace") if self.log_path else ""
        except OSError:
            return ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("[aedt")]
        return lines[-1] if lines else ""

    def poll(self) -> None:
        if not self.finished and self.proc is not None and self.proc.poll() is None:
            st = self.status()
            line = self.progress_line()
            bits = [f"{self.label}"]
            if st.get("step"):
                bits.append(f"step {st.get('n', '?')}/{st.get('of', '?')}: {st.get('message') or st['step']}")
                if st["step"] != self.last_step:
                    self.last_step = st["step"]
                    log(f"{self.label}: {st['step']} {st.get('message', '')}")
            if line:
                bits.append(line.split("] ", 1)[-1] if "] " in line else line)
            message(" · ".join(bits) + f" ({self.elapsed():.0f} s)", 2, log_it=False)
            return
        super().poll()

    def _finish(self, ok: bool) -> None:
        if self.cancelled:
            self.output, ok = "cancelled\n", False
        super()._finish(ok)

    def cancel(self) -> None:
        """Stop the job: the ``qcc`` process and the AEDT it started (taskkill /T), nothing else."""
        if self.finished or self.proc is None:
            return
        self.cancelled = True
        pid = self.proc.pid
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False,  # noqa: S603,S607
                           creationflags=_NO_WINDOW)
        else:
            self.proc.terminate()
        if self.status_file:
            st = self.status()
            st.update(state="cancelled", message="stopped by the user")
            try:
                self.status_file.write_text(json.dumps(st), encoding="utf-8")
            except OSError:
                pass
        log(f"{self.label}: stopped by the user (pid {pid})")


class SimJob(FlowJob):
    """``qcc sim auto``, started detached so it outlives KLayout (see :mod:`simrun`). Its output goes to
    ``<design>.flow/sim_run.log`` and the run record ``sim_run.json`` keeps its pid and outcome. With ``record`` (a
    run from an earlier KLayout session) nothing is started: the job watches that run's pid and ends when it does."""

    def __init__(self, steps, label, done, cwd=None, status_file=None, record=None):
        super().__init__(steps, label, done, cwd, status_file)
        self.flow_dir = Path(status_file).parent
        self.record = record
        if record is not None:
            self.index = 0
            self.proc = simrun.PidProc(record)
            self.log_path = Path(record["log"])
            self.started = float(record.get("started", time.time()))

    def _next(self) -> bool:
        self.index += 1
        if self.index >= 1 or self.record is not None:
            return False
        args = self.steps[0]
        self.log_path = self.flow_dir / simrun.LOG
        self.proc = simrun.launch([SESSION.qcc, *args], self.cwd, clean_env(), self.log_path)
        self.record = {"schema": "qcc-simrun/0.1", "pid": self.proc.pid, "started": self.started, "args": args,
                       "design": str(SESSION.design_path), "log": str(self.log_path), "status": str(self.status_file),
                       "state": "running", "handled": False}
        simrun.write_record(self.flow_dir, self.record)
        log(f"job {self.label} (detached, pid {self.proc.pid}): {' '.join(args)[:200]}")
        return True

    def _drop_log(self) -> None:
        pass  # the log stays next to the status file: what the run printed, also after KLayout was closed

    def _finish(self, ok: bool) -> None:
        if self.record is not None:
            state = "cancelled" if self.cancelled else ("done" if ok else "failed")
            self.record.update(state=state, handled=True, finished=time.time())
            try:
                simrun.write_record(self.flow_dir, self.record)
            except OSError as e:
                log(f"Simulate: could not update the run record: {e!r}")
        super()._finish(ok)


def _run(steps, label, done, status_file=None, cwd=None) -> FlowJob:
    if label == "Simulate" and status_file:
        job = SimJob(steps, label, done, cwd, status_file)
    else:
        job = FlowJob(steps, label, done, cwd, status_file)
    jobs.RUNNING.append(job)
    job._next()  # noqa: SLF001  pylint: disable=protected-access
    job.timer.start()
    return job


_RESUMED: set = set()  # designs whose earlier run was looked for in this KLayout session


def resume_runs(force: bool = False):
    """A ``qcc sim auto`` run of this design started in an earlier KLayout session: one that ended meanwhile is
    imported (its results are in the run state: the layout is rebuilt and the Results tab filled); one still going is
    watched and imported when it ends. Returns the watching job, or None. Called when a design is opened."""
    try:
        design = SESSION.design_path
        if design is None or (str(design) in _RESUMED and not force) or _running("Simulate") is not None:
            return None
        _RESUMED.add(str(design))
        build_dir = SESSION.layout_path.parent if SESSION.layout_path is not None else design.parent / "build"
        flow_dir = build_dir / f"{design.stem}.flow"
        rec = simrun.read_record(flow_dir)
        if not rec or rec.get("handled") or rec.get("state") != "running":
            return None
        if Path(rec.get("design", design)).resolve() != design.resolve():
            return None
        running = simrun.outcome(rec) == "running"
        job = SimJob([rec.get("args", [])], "Simulate", _simulate_done, design.parent, rec["status"], record=rec)
        jobs.RUNNING.append(job)
        job.timer.start()
        if running:
            message("Simulate: a run started earlier is still going; its results are imported when it ends", 10)
        else:  # it ended while KLayout was closed: the job's first poll imports it
            message("Simulate: a run started earlier has finished; importing its results", 10)
        return job
    except Exception:  # noqa: BLE001  (called from a listener: never raise)
        report_error("looking for a simulation that ran while KLayout was closed")
        return None


def _on_design(*_a) -> None:
    """Sidecar listener: the first time a design is shown, look for a run that outlived the last KLayout session."""
    if SESSION.design_path is not None and str(SESSION.design_path) not in _RESUMED:
        resume_runs()


if _on_design not in SESSION.listeners:
    SESSION.listeners.append(_on_design)


def _running(prefix: str = "") -> FlowJob | None:
    return next((j for j in jobs.RUNNING if isinstance(j, FlowJob) and not j.finished
                 and j.label.startswith(prefix)), None)


def _busy_check(what: str) -> bool:
    """True (and a message) when a flow job is running that this step must not overlap."""
    job = _running()
    if job is None:
        return False
    message(f"{job.label} is still running: wait for it, or use Simulate to stop it ({what} not started)")
    return True


def _finish(job_result: FlowJob, wait: bool):
    if wait:
        job_result.wait(3600)
    return job_result


# ---- Simulate: the dialog ---------------------------------------------------------------------------------------
def sim_settings_saved() -> dict:
    try:
        return json.loads(config(CFG_SIM, "") or "{}")
    except ValueError:
        return {}


def simulate_dialog(names: list[str]):
    """What to simulate and how → ``{"scope": selection|default|whole, "analysis", "settings", "window", "action":
    run|export|layout}`` or None (cancelled). The analysis (Q3D capacitance or HFSS eigenmode; driven runs are for scripts)
    is preset from the selection (:func:`simsetup.recommend`). The solver settings (passes, convergence, modes, mesh
    seeds) are filled with the fast values and can be changed; the last values are kept. The last run's convergence
    (``convergence.json``) is shown."""
    from qcc_kplugin import tools  # pylint: disable=import-outside-toplevel

    data = SESSION.data or {}
    rec, why = simsetup.recommend(names, data, tools.CATEGORY) if names else (simsetup.EIGEN, "")
    dialog = pya.QDialog(_main())
    dialog.windowTitle = "Simulate"
    lay = pya.QVBoxLayout()  # the body: it scrolls when the screen is small; the buttons stay below it

    def label(text):
        w = pya.QLabel(text, dialog)
        w.wordWrap = True
        w.setMinimumWidth(520)
        lay.addWidget(w)
        return w

    scope_box = None
    if names:
        label("Renders: " + ", ".join(names) + "  (plus, for eigenmode, the routes joining them and a line's end "
              "pads).")
    else:
        label("Nothing is selected (KLayout's select tool picks components and routes). Simulate:")
        scope_box = pya.QComboBox(dialog)
        scope_box.addItems(["the default subset: the first qubit with its readout (Q3D: the qubit, its readout cut to "
                            "a stub; eigenmode: with the resonator and feedline)",
                            "the whole chip (slow, needs a lot of memory)"])
        lay.addWidget(scope_box)
    r_q3d = pya.QRadioButton("Q3D capacitance: qubit islands and couplers as nets, resonators cut to a stub port "
                             "→ the C matrix for the LOM (minutes)", dialog)
    r_eig = pya.QRadioButton("HFSS eigenmode: everything selected (qubit, resonator, feedline, pads); junctions as "
                             "lumped L‖C, pads and cut lines 50 Ω → f, Q, κ, χ (slower, needs L_J)", dialog)
    lay.addWidget(r_q3d)
    lay.addWidget(r_eig)
    (r_eig if rec == simsetup.EIGEN else r_q3d).checked = True
    if why:
        label("Recommended: " + why)
    warn = label("")
    saved = sim_settings_saved()
    lay.addWidget(pya.QLabel("Solver settings (filled with the fast values: minutes, not converged; change them for "
                             "a finer run, or solve again in AEDT and use Import results):", dialog))
    forms, edits = {}, {}
    for analysis in simsetup.ANALYSES:
        holder = pya.QWidget(dialog)
        form = pya.QFormLayout(holder)
        edits[analysis] = {}
        for key, value in simsetup.settings_for(analysis, saved.get(analysis)).items():
            e = pya.QLineEdit("" if value is None else format(value, "g"), dialog)
            edits[analysis][key] = e
            form.addRow(simsetup.LABELS[key], e)
        forms[analysis] = holder
        lay.addWidget(holder)
    reset = pya.QPushButton("Reset to the fast values", dialog)
    lay.addWidget(reset)
    feedback_label = label("")
    preview_label = label("")  # what the layout overlay shows (kplugin/python/qcc_kplugin/simview.py)
    window = pya.QCheckBox("Show the AEDT window (slower to start, lets you watch the mesh)", dialog)
    window.checked = config(CFG_AEDT_WINDOW, "") == "1"
    lay.addWidget(window)
    picked = [None]

    def current():
        return simsetup.EIGEN if r_eig.checked else simsetup.Q3D

    def refresh(*_a):
        analysis = current()
        for a, holder in forms.items():
            holder.visible = a == analysis
        miss, why = [], {}
        if analysis == simsetup.EIGEN:
            if names:  # the selection: the build sidecar holds the library's resolved junction
                miss = simsetup.missing_junctions(names, data, tools.CATEGORY, SESSION.design())
            elif (scope_box is None or scope_box.currentIndex == 0) and SESSION.design_path is not None:
                from qcc_kplugin import jfetch  # pylint: disable=import-outside-toplevel

                why = jfetch.missing_default(SESSION.design_path)  # the default subset (qcc picks it)
                miss = list(why)
        warn.text = simsetup.missing_text(miss, data, why)
        fb = None
        if SESSION.design_path:
            fb = simsetup.last_feedback(SESSION.design_path,
                                        design_io.read_design(SESSION.design_path).get("name", ""), analysis)
        feedback_label.text = ("Last " + ("Q3D" if analysis == simsetup.Q3D else "eigenmode") + " run: "
                               + fb.get("message", "")) if fb else ""
        run_btn.enabled = not miss  # eigenmode needs L_J: no run, no job export with a missing value
        exp_btn.enabled = not miss
        preview()

    def preview(*_a):
        """The box, components and ports of this choice, drawn in the layout behind the dialog (temporary)."""
        from qcc_kplugin import simview  # pylint: disable=import-outside-toplevel

        which = ("default", "whole")[max(0, scope_box.currentIndex)] if scope_box is not None else "selection"
        spec = {"names": list(names) if names else None, "analysis": current(), "whole": which == "whole"}

        def got(data, error):
            preview_label.text = ("Drawn in the layout (purple box, ports): " + "; ".join(
                simview.summary(g) for g in data["groups"])) if data else f"No preview in the layout: {error}"

        preview_label.text = "Working out the box and ports…" if simview.request(spec, got, temp=True) else ""

    def go(action):
        picked[0] = action
        dialog.accept()

    row = pya.QHBoxLayout()
    run_btn = pya.QPushButton("Simulate in a new AEDT", dialog)
    exp_btn = pya.QPushButton("Export the job only", dialog)
    lay_btn = pya.QPushButton("Open simulation layout…", dialog)
    lay_btn.toolTip = ("Opens the geometry HFSS / Q3D would import (cut-out metal and gaps, junction sheets, port "
                       "polygons) in a new layout tab. No AEDT; the design and its build are not touched")
    cancel = pya.QPushButton("Cancel", dialog)
    run_btn.clicked(lambda _c=False: go("run"))
    exp_btn.clicked(lambda _c=False: go("export"))
    lay_btn.clicked(lambda _c=False: go("layout"))
    cancel.clicked(lambda _c=False: dialog.reject())
    for b in (run_btn, exp_btn, lay_btn, cancel):
        row.addWidget(b)
    buttons = pya.QWidget(dialog)
    buttons.setLayout(row)

    def reset_values(*_a):
        for key, value in simsetup.FAST[current()].items():
            edits[current()][key].text = "" if value is None else format(value, "g")

    for w in (r_q3d, r_eig):
        try:
            w.toggled(refresh)
        except Exception:  # noqa: BLE001
            pass
    reset.clicked(reset_values)
    if scope_box is not None:
        scope_box.currentIndexChanged(refresh)
    refresh()
    from qcc_kplugin import dialogs  # pylint: disable=import-outside-toplevel

    dialogs.fit(dialog, lay, buttons)
    dialog.sim_widgets = {"q3d": r_q3d, "eig": r_eig, "window": window, "scope": scope_box, "run": run_btn,
                          "feedback": feedback_label, "edits": edits, "reset": reset, "layout": lay_btn,
                          "export": exp_btn, "warn": warn}  # for tests
    try:
        accepted = dialog.exec_()
    finally:
        from qcc_kplugin import simview  # pylint: disable=import-outside-toplevel

        simview.end_temp()  # the preview was only for the dialog
    if not accepted and picked[0] is None:
        return None
    analysis = current()
    try:
        settings = simsetup.parse_settings(analysis, {k: e.text for k, e in edits[analysis].items()})
    except ValueError as e:
        message(f"Simulate: {e}", 10)
        return None
    saved[analysis] = settings
    set_config(CFG_SIM, json.dumps(saved))
    set_config(CFG_AEDT_WINDOW, "1" if window.checked else "")
    scope = "selection" if names else ("default", "whole")[max(0, scope_box.currentIndex)]
    return {"scope": scope, "analysis": analysis, "settings": settings, "window": bool(window.checked),
            "action": picked[0] or "run"}


def _subset_args(subset: str, names) -> list:
    return {"selection": ["--instances", ",".join(names)], "default": ["--default"], "whole": ["--whole"]}[subset]


# ---- Simulate: automatic ----------------------------------------------------------------------------------------
def simulate(wait: bool = False, names=None, subset: str | None = None, window: bool | None = None,
             analysis: str | None = None, settings: dict | None = None):
    """Flow ▸ Simulate: the Simulate dialog (:func:`simulate_dialog`: what is rendered, Q3D or eigenmode, the solver
    settings, the last run's convergence), then ``qcc sim auto`` in the background (or the job export). A run in
    progress is offered to stop instead. ``subset`` ("selection" | "default" | "whole") with ``names`` / ``window`` /
    ``analysis`` / ``settings`` skips the dialog (tests; no settings: the fast ones)."""
    try:
        running = _running("Simulate")
        if running is not None:
            st = running.status()
            pick = choose("Simulation running", f"A simulation is running ({st.get('message') or 'starting'}, "
                          f"{running.elapsed():.0f} s). Stop it? (Only the AEDT this run started is closed.)",
                          ["Stop the simulation"])
            if pick is not None:
                running.cancel()
            return running
        if not _design_ready() or _busy_check("Simulate"):
            return None
        names = selected_names() if names is None else list(names)
        if subset is None:
            picked = simulate_dialog(names)
            if picked is None:
                return None
            subset, analysis, settings = picked["scope"], picked["analysis"], picked.get("settings")
            window = picked["window"] if window is None else window
            if picked["action"] == "export":
                return export_job(wait, names, subset, analysis=analysis, settings=settings)
            if picked["action"] == "layout":
                return open_sim_layout(wait, names, subset, analysis=analysis)
        analysis = analysis or simsetup.Q3D
        design = SESSION.design_path
        status = _flow_dir() / "sim_status.json"
        status.unlink(missing_ok=True)
        if subset not in ("selection", "default", "whole"):
            return None
        args = ["sim", "auto", design, "--status", status, "--aedt", "gui" if window else "batch", "-a", analysis]
        args += _subset_args(subset, names) + (simsetup.cli_args(analysis, settings) if settings else ["--fast"])
        job = _run([args], "Simulate", _simulate_done, status, design.parent)
        message("Simulate: started (new AEDT in the background; progress shows here)", 8)
        return _finish(job, wait)
    except Exception:  # noqa: BLE001
        report_error("Simulate")
        return None


def _simulate_done(ok: bool, output: str) -> None:
    _update_strip()
    lines = [ln for ln in output.splitlines() if ln.strip()]
    if output.startswith("cancelled"):
        message("Simulate: stopped")
        return
    if not ok:
        err = next((ln for ln in reversed(lines) if ln.startswith("error:")), build_error(output))
        message(f"Simulate failed: {err[:200]} (details: {SESSION.layout_path.parent if SESSION.layout_path else ''})", 20)
        log("Simulate failed:\n" + "\n".join(lines[-25:]))
        info_window("Simulate failed", "\n".join(lines[-40:]) or "no output")
        return
    done = next((ln for ln in reversed(lines) if ln.startswith("done in")), "done")
    message(f"Simulate: {done}", 20)
    _rebuild()
    results(quiet=True)



# ---- Simulate: open the simulation layout (what HFSS / Q3D import, no AEDT) ------------------------------------------
SIMLAYOUT_PREFIX = "qcc_simlayout"
# Open simulation layout with nothing selected: the default subset (the first qubit with a readout) as each analysis
# renders it. Q3D keeps only the qubit's box (its readout cut to a stub port: the C matrix for the LOM); eigenmode
# takes the readout resonator and the feedline too (cut into 50 Ω ports at the box edge).
DEFAULT_LAYOUT_CHOICES = {
    simsetup.EIGEN: "The default subset for HFSS eigenmode: the first qubit, its readout resonator and the feedline "
                    "(cut into 50 Ω ports at the box)",
    simsetup.Q3D: "The default subset for Q3D: the first qubit's islands and couplers only (its readout resonator is "
                  "cut to a stub port)",
}
PORT_LAYERS = {"junction": (2000, "ports: junction (lumped L‖C sheet)"), "edge": (2001, "ports: 50 Ω / stub (edge port)")}


def simlayout_root() -> Path:
    import tempfile  # pylint: disable=import-outside-toplevel

    return Path(tempfile.gettempdir()) / SIMLAYOUT_PREFIX


def sim_layer_name(name: str) -> str:
    """A readable name for a KQC simulation layer (``1t1_gap``, ``1t1_signal_2``, ``1t1_ground``)."""
    if name.endswith("_gap"):
        return "gap: etched, no metal"
    if name.endswith("_ground"):
        return "ground: metal"
    if "_signal_" in name:
        n = name.rsplit("_", 1)[-1]
        return f"signal {n}: metal (net / port {n})"
    return name


def sim_layout_args(design, target, subset: str, names, analysis: str, group: str | None = None) -> list:
    """``qcc sim subset`` arguments of the simulation layout: the job export with nothing written to the design (and no
    AEDT): the selection, the default subset or a saved sim group, to ``target``."""
    args = ["sim", "subset", design, "-o", target, "-a", analysis, "--no-write-group", "--fast"]
    return args + (["--group", group] if subset == "group" else _subset_args(subset, names))


def sim_layout_missing_lj(subset: str, names, analysis: str, group: str | None, design_data: dict) -> str:
    """The Simulate dialog's pre-check, for Open simulation layout: an eigenmode / driven layout puts a lumped L‖C
    sheet on each junction, so a qubit without an L_J would fail the export. The warning that names them and says where
    to set the value, or "" (all set, or a capacitance analysis, which needs none)."""
    if analysis in simsetup.CAPACITANCE_ANALYSES:
        return ""
    from qcc_kplugin import jfetch, tools  # pylint: disable=import-outside-toplevel

    data = SESSION.data or {}
    if subset == "default":  # qcc picks the subset: ask the library which of its junctions have no value
        why = jfetch.missing_default(SESSION.design_path)
        return simsetup.missing_text(list(why), data, why)
    if subset == "group":
        members = ((design_data.get("sim_groups") or {}).get(group) or {}).get("select") or []
    elif subset == "whole":
        members = list(data.get("instances", {}))
    else:
        members = list(names or [])
    return simsetup.missing_text(simsetup.missing_junctions(members, data, tools.CATEGORY, design_data), data)


def open_sim_layout(wait: bool = False, names=None, subset: str | None = None, analysis: str | None = None,
                    group: str | None = None):
    """Simulate ▸ Open simulation layout…: export the job geometry of the selection, the default subset or a saved sim
    group (the same path as *Export the job only*, no AEDT) to a temporary folder and open the GDS that AEDT imports in
    a new layout tab, with readable layer names: the cut-out metal and gaps, the junction sheets and the port
    polygons. The design and its build are never touched. An eigenmode / driven layout with a qubit that has no L_J
    is not exported: a window names the qubit and offers the Q3D layout instead (:func:`sim_layout_missing_lj`)."""
    try:
        if not _design_ready():
            return None
        names = selected_names() if names is None else list(names)
        design_data = SESSION.design()
        groups = sorted(design_data.get("sim_groups", {}))
        if group:
            subset = "group"
        elif subset is None:
            if names:
                subset = "selection"
            else:
                pick = choose("Open simulation layout", "Nothing is selected. Show the geometry of:",
                              list(DEFAULT_LAYOUT_CHOICES.values())
                              + [f"The saved sim group {g}" for g in groups[:8]])
                if pick is None:
                    return None
                n = len(DEFAULT_LAYOUT_CHOICES)
                if pick[0] < n:  # each analysis renders the default subset its own way: say which, and use it
                    subset, group, analysis = "default", None, list(DEFAULT_LAYOUT_CHOICES)[pick[0]]
                else:
                    subset, group = "group", groups[pick[0] - n]
        if subset == "group":
            analysis = analysis or (design_data["sim_groups"][group].get("analyses") or ["eigenmode_epr"])[0]
        elif analysis is None:
            from qcc_kplugin import tools  # pylint: disable=import-outside-toplevel

            analysis = simsetup.recommend(names, SESSION.data or {}, tools.CATEGORY)[0] if names else simsetup.Q3D
        missing = sim_layout_missing_lj(subset, names, analysis, group, design_data)
        if missing:  # the same pre-check as the Simulate dialog: no export that would fail on the lumped junction
            message("Open simulation layout: a junction has no L_J (details in the window)", 12)
            info_window("Open simulation layout: no junction L_J", missing + "\n\nThe Q3D layout (capacitances only) "
                        "needs no L_J.", {"q3d": ("Open the Q3D layout instead", lambda: open_sim_layout(
                            names=names, subset=subset, analysis=simsetup.Q3D, group=group))})
            return None
        import shutil  # pylint: disable=import-outside-toplevel
        import time as _time  # pylint: disable=import-outside-toplevel

        root = simlayout_root()
        stem = SESSION.design_path.stem
        for old in root.glob(f"{stem}_*") if root.exists() else []:  # keep only the newest export of this design
            shutil.rmtree(old, ignore_errors=True)
        target = root / f"{stem}_{int(_time.time())}"
        target.parent.mkdir(parents=True, exist_ok=True)
        args = sim_layout_args(SESSION.design_path, target, subset, names, analysis, group)
        job = _run([args], "Open simulation layout", lambda ok, out: _sim_layout_done(ok, out, target))
        message("Open simulation layout: exporting the geometry (no AEDT)", 8)
        return _finish(job, wait)
    except Exception:  # noqa: BLE001
        report_error("Open simulation layout")
        return None


def _sim_layout_done(ok: bool, output: str, target: Path) -> None:
    try:
        if not ok:
            message("Open simulation layout failed (details in the window)", 15)
            info_window("Open simulation layout failed", output[-3000:])
            return
        folders = [Path(ln[4:].strip()) for ln in output.splitlines() if ln.startswith("job ")] or [target]
        shown = [show_sim_gds(f) for f in folders[:4]]
        shown = [s for s in shown if s]
        notes = [ln for ln in output.splitlines() if ln.startswith("note:")]
        message("Open simulation layout: " + (", ".join(shown) if shown else "no GDS found in the job folder")
                + (f" ({notes[0]})" if notes else ""), 12)
    except Exception:  # noqa: BLE001
        report_error("Open simulation layout")


def show_sim_gds(job_dir) -> str | None:
    """Open the GDS of the exported job folder in a new layout tab (not the design's view): layers get readable names
    and colours; the port polygons of ``<sim>.json`` are added as two extra layers in memory (the file is not changed).
    Returns the tab's title, or None when the folder holds no GDS."""
    job_dir = Path(job_dir)
    meta = {}
    try:
        meta = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    gds = job_dir / f"{meta.get('simulation_name', '')}.gds"
    if not gds.exists():
        found = sorted(job_dir.glob("*.gds"))
        if not found:
            return None
        gds = found[0]
    sim = {}
    try:
        sim = json.loads(gds.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    mw = pya.MainWindow.instance()
    mw.load_layout(str(gds), 1)  # mode 1: a new view (a new tab); 0 would replace the design's view
    view = mw.current_view()
    cv = view.active_cellview()
    layout = cv.layout()
    top = cv.cell
    # the port polygons (junction sheets, edge ports) as extra layers: what HFSS draws as port sheets
    extra = {}
    for port in sim.get("ports") or []:
        kind = "junction" if port.get("junction") else "edge"
        poly = [pya.DPoint(float(p[0]), float(p[1])) for p in port.get("polygon") or []]
        if len(poly) < 3:
            continue
        number, _ = PORT_LAYERS[kind]
        li = extra.get(kind)
        if li is None:
            li = extra[kind] = layout.layer(number, 0)
        top.shapes(li).insert(pya.DPolygon(poly))
    names = {int(v["layer"]): k for k, v in (sim.get("layers") or {}).items() if v.get("layer") is not None}
    view.clear_layers()
    view.add_missing_layers()
    colours = [0x4C78A8, 0xF58518, 0x54A24B, 0xB279A2, 0x72B7B2, 0xE45756, 0x9D755D]
    i = 0
    for lp in view.each_layer():
        num = lp.source_layer
        if num in names:
            lp.name = sim_layer_name(names[num]) + f"  [{names[num]}, {num}/0]"
        else:
            hit = next((label for k, (n, label) in PORT_LAYERS.items() if n == num), None)
            if hit:
                lp.name = hit
        lp.fill_color = lp.frame_color = colours[i % len(colours)]
        lp.dither_pattern = 1 if (names.get(num) or "").endswith(("_gap",)) else 0
        i += 1
    view.zoom_fit()
    title = f"simulation layout: {meta.get('design', '')} {meta.get('group', '')} {meta.get('analysis', '')}".strip()
    try:
        view.title = title
    except Exception:  # noqa: BLE001
        pass
    log(f"simulation layout opened from {gds} (layer names added; ports as layers 2000 / 2001 in memory)")
    return title


# ---- Simulate: manual -------------------------------------------------------------------------------------------
def export_job(wait: bool = False, names=None, subset: str | None = None, folder: str | None = None,
               analysis: str | None = None, settings: dict | None = None):
    """The Simulate dialog's *Export the job only* button: write the job folder (geometry, AEDT scripts, job.json,
    README.md with what to run and what to bring back, results_template.json) for the selected components, to solve by
    hand or elsewhere."""
    try:
        if not _design_ready() or _busy_check("Export sim job"):
            return None
        names = selected_names() if names is None else list(names)
        if subset is None:
            if names:
                subset = "selection"
            else:
                pick = choose("Export sim job", "No component is selected. Select a qubit with KLayout's select tool, "
                              "or choose:", ["Default subset: the first qubit with its readout resonator",
                                             "The whole chip (slow to solve)"])
                if pick is None:
                    return None
                subset = ("default", "whole")[pick[0]]
        design = SESSION.design_path
        folder = folder or ask_dir("Folder for the job (a sub-folder is made)", str(design.parent / "build" / "jobs"))
        if not folder:
            return None
        target = Path(folder) / f"{design.stem}_sim"
        if aedt_path_too_long(target):  # the automatic run moves such a job to %TEMP%\qcc_jobs by itself
            import tempfile  # pylint: disable=import-outside-toplevel

            short = Path(tempfile.gettempdir()) / "qcc_jobs" / target.name
            pick = choose("Export sim job", f"The job folder\n  {target}\nis too deep for AEDT: on Windows AEDT fails "
                          "when its result folders pass 260 characters, and this one would. Export to a short folder?",
                          [f"Export to {short}", "Export here anyway (to solve on another machine or a shorter path)"])
            if pick is None:
                return None
            if pick[0] == 0:
                target = short
        analysis = analysis or simsetup.Q3D
        args = ["sim", "subset", design, "-o", target, "-a", analysis] + _subset_args(subset, names)
        args += simsetup.cli_args(analysis, settings) if settings else ["--fast"]
        job = _run([args], "Export sim job", lambda ok, out: _export_done(ok, out, target))
        return _finish(job, wait)
    except Exception:  # noqa: BLE001
        report_error("Export sim job")
        return None


def _export_done(ok: bool, output: str, target: Path) -> None:
    if not ok:
        message("Export sim job failed (details in the window)", 15)
        info_window("Export sim job failed", output[-3000:])
        return
    folders = [Path(ln[4:].strip()) for ln in output.splitlines() if ln.startswith("job ")] or [target]
    warns = [ln for ln in output.splitlines() if ln.startswith("warning:")]
    text = ("The simulation job is ready:\n\n" + "\n".join(f"  {f}" for f in folders)
            + ("\n\n" + "\n".join(warns) if warns else "")
            + "\n\nIn each folder, README.md says what to run (simulation.bat, or scripts/qcc_solve.py in AEDT) and what "
            "to bring back. Then use Quantcore > Simulate > Import results...\n\n"
            + "\n".join(ln for ln in output.splitlines() if ln.startswith("note:")))
    message(f"Export sim job: written to {folders[0]}" + (" (see the warning)" if warns else ""), 12)
    info_window("Simulation job exported" + (" (with a warning)" if warns else ""), text,
                {"open": ("Open folder", lambda: open_folder(folders[0]))})


def import_results(wait: bool = False, source: str | None = None):
    """Flow ▸ Simulate ▸ Import results…: a solved job folder or a results.json → analysed against the design; the
    Results tab and dialog show the outcome."""
    try:
        if not _design_ready() or _busy_check("Import results"):
            return None
        design = SESSION.design_path
        if source is None:
            pick = choose("Import results", "What did you bring back? A job folder is read again from its AEDT "
                          "outputs when they are newer than its results, and its convergence table is read too. "
                          "After changing the setup and solving again in AEDT, run the job's scripts/qcc_collect.py "
                          "there first (Tools > Run Script; it exports what you solved), or close the project and "
                          "run qcc hfss collect JOB.",
                          ["A results.json file (capacitance matrix / eigenmodes, format in the README)",
                           "A solved job folder"])
            if pick is None:
                return None
            start = str(design.parent / "build" / "jobs")
            source = (ask_file("results.json", str(results_dir()) if results_dir().exists() else start)
                      if pick[0] == 0 else ask_dir("Solved job folder", start))
        if not source:
            return None
        job = _run([["results", "import", design, source]], "Import results", _import_done, None, design.parent)
        return _finish(job, wait)
    except Exception:  # noqa: BLE001
        report_error("Import results")
        return None


def results_dir() -> Path:
    """``<design folder>/build/<name>``: where ``qcc sim auto`` saves ``<name>_<group>_results.json`` (simsetup.run_dir;
    ``build/<name>`` is also where convergence.json and the run state live)."""
    return simsetup.run_dir(SESSION.design_path, design_io.read_design(SESSION.design_path).get("name", "")
                            or SESSION.design_path.stem)


def open_results_file(wait: bool = False, source: str | None = None):
    """Flow ▸ Simulate ▸ Open results file…: pick a results file (e.g. the ``<name>_<group>_results.json`` a run saved in
    ``build/<name>``, or one solved by hand) and analyse it against the design, without the job-folder question."""
    try:
        if not _design_ready() or _busy_check("Open results file"):
            return None
        if source is None:
            start = results_dir()
            source = ask_file("Open a results file", str(start if start.exists() else SESSION.design_path.parent))
        if not source:
            return None
        return import_results(wait, source=str(source))
    except Exception:  # noqa: BLE001
        report_error("Open results file")
        return None


def _import_done(ok: bool, output: str) -> None:
    _update_strip()
    lines = [ln for ln in output.splitlines() if ln.strip()]
    if not ok:
        err = next((ln for ln in reversed(lines) if ln.startswith("error:")), build_error(output))
        message(f"Import results failed: {err[:200]}", 20)
        info_window("Import results failed", "\n".join(lines[-40:]) + "\n\nThe expected format: qcc results template "
                    "--format (also in the job's README.md).")
        return
    warns = [ln for ln in lines if ln.startswith("warning:")]
    mesh = [ln for ln in lines if ": mesh " in ln]
    message("Import results: done" + (f" ({len(warns)} warning(s))" if warns else "")
            + (" · " + mesh[-1].split(": mesh ", 1)[1][:120] if mesh else ""), 15)
    _rebuild()
    results(quiet=True)
    if warns or any("NOT converged" in ln for ln in mesh):
        info_window("Import results: warnings", "\n".join(warns + mesh))


# ---- Results and tune -------------------------------------------------------------------------------------------
class ResultsDialog(_Window):
    """Latest values against the targets (the sidecar's ``results``: the same rows as the panel's Results tab), plus
    the tune buttons. Refreshes itself when the layout is rebuilt."""

    def __init__(self):
        super().__init__("Quantcore results", 700, 480)
        self.header = pya.QLabel("", self.dialog)
        self.header.wordWrap = True
        self.layout.addWidget(self.header)
        self.tree = pya.QTreeWidget(self.dialog)
        self.tree.setHeaderLabels(["element", "value", "target · status"])
        self.layout.addWidget(self.tree)
        self.add_button("propose", "Propose next revision…", lambda: propose(),
                        "Preview how the design would change to reach the targets")
        self.add_button("import", "Import results…", lambda: import_results())
        self.add_button("simulate", "Simulate…", lambda: simulate())
        self._listener = self.refresh
        SESSION.listeners.append(self._listener)
        self.dialog.finished(self._closed)
        self.refresh()
        self.finish()

    def _closed(self, *_a):
        if self._listener in SESSION.listeners:
            SESSION.listeners.remove(self._listener)

    def refresh(self) -> None:
        data = SESSION.data or {}
        rows = design_io.results_rows(data)
        self.rows = rows
        stale = any(e.get("stale") for e in (data.get("results") or {}).values())
        if not rows:
            self.header.text = ("No results yet. Simulate the selected qubit (Quantcore > Simulate), or import results "
                                "you solved by hand. Targets are set in each component's edit dialog.")
        else:
            self.header.text = ("Values from the last simulation or import, against the design's targets."
                                + (" STALE: the design changed since; simulate again for current values." if stale else ""))
        self.tree.clear()
        groups = {}
        for element, label, value, extra in rows:
            if element not in groups:
                groups[element] = pya.QTreeWidgetItem(self.tree, [element, "", ""])
            pya.QTreeWidgetItem(groups[element], [label, value, extra])
        self.tree.expandAll()
        for col in range(3):
            self.tree.resizeColumnToContents(col)


def results(wait: bool = False, quiet: bool = False):
    """Flow ▸ Results: the latest values against the targets in a window (and the panel's Results tab). ``quiet``
    (called when a background job ends, i.e. from a timer): a failure goes to the status bar and the log, no dialog."""
    try:
        if SESSION.data is None:
            SESSION.attach_view()
        try:  # also bring up the panel's Results tab
            from qcc_kplugin import dock  # pylint: disable=import-outside-toplevel

            if dock.DOCK:
                dock.DOCK[0].show_tab("Results")
        except Exception:  # noqa: BLE001
            pass
        for w in DIALOGS:
            if isinstance(w, ResultsDialog) and w.dialog.isVisible():
                w.refresh()
                w.dialog.raise_()
                return w
        return ResultsDialog()
    except Exception:  # noqa: BLE001
        if not quiet:
            report_error("Results")
        else:
            import traceback  # pylint: disable=import-outside-toplevel

            log("ERROR Results\n" + traceback.format_exc())
            message("Results: could not show the window (details in the Quantcore log)", 15)
        return None


def propose(wait: bool = False):
    """Flow ▸ Results ▸ Propose next revision…: ``loop.feedback`` in the background, then a preview of old → new knob
    values with Apply (writes them to design.json; Quantcore > Edit > Undo takes them back)."""
    try:
        if not _design_ready() or _busy_check("Propose"):
            return None
        design = SESSION.design_path
        out = _flow_dir() / "proposal.json"
        out.unlink(missing_ok=True)
        job = _run([["results", "propose", design, "-o", out]], "Propose revision",
                   lambda ok, output: _proposal_done(ok, output, out), None, design.parent)
        message("Propose revision: analysing (seconds; about half a minute for twenty qubits)…", 8)
        return _finish(job, wait)
    except Exception:  # noqa: BLE001
        report_error("Propose revision")
        return None


class ProposalWindow(_Window):
    def __init__(self, proposal: dict, path: Path):
        super().__init__("Next revision", 640, 420)
        self.proposal, self.path = proposal, path
        self.layout.addWidget(pya.QLabel(f"Based on: {proposal.get('basis', '')}"
                                         + ("  (the design changed since: values are stale)" if proposal.get("stale") else ""),
                                         self.dialog))
        self.table = pya.QTableWidget(0, 3, self.dialog)
        self.table.setHorizontalHeaderLabels(["knob", "now", "proposed"])
        rows = [(k["knob"], k["old"], k["new"]) for k in proposal.get("knobs", [])] + [
            (f"also: {m['path']}", m["old"], m["new"]) for m in proposal.get("moved", [])]
        self.table.setRowCount(len(rows))
        for i, (a, b, c) in enumerate(rows):
            for j, v in enumerate((a, b, c)):
                self.table.setItem(i, j, pya.QTableWidgetItem(f"{v:g}" if isinstance(v, (int, float)) else str(v)))
        self.layout.addWidget(self.table)
        note = pya.QLabel(proposal.get("message", ""), self.dialog)
        note.wordWrap = True
        self.layout.addWidget(note)
        if proposal.get("notes"):  # what Propose could not tune, and why (a drawn junction, no length knob, ...)
            self.notes = pya.QTextEdit(self.dialog)
            self.notes.readOnly = True
            self.notes.setPlainText("Not tuned:\n" + "\n".join(f"- {n}" for n in proposal["notes"]))
            self.layout.addWidget(self.notes)
        if proposal.get("tunable"):
            self.add_button("apply", "Apply and rebuild", self.apply,
                            "Write these values to design.json (Quantcore > Edit > Undo takes them back)")
        self.finish()

    def apply(self):
        apply_proposal(self.proposal, self.path)
        self.dialog.close()


def _proposal_done(ok: bool, output: str, path: Path) -> None:
    if not ok or not path.exists():
        lines = [ln for ln in output.splitlines() if ln.strip()]
        message("Propose revision failed (details in the window)", 15)
        info_window("Propose revision failed", "\n".join(lines[-40:]))
        return
    proposal = json.loads(path.read_text(encoding="utf-8"))
    message("Propose revision: " + (f"{len(proposal['knobs'])} knob(s) to change" if proposal["knobs"]
                                    else "nothing to change"), 10)
    ProposalWindow(proposal, path)


def apply_proposal(proposal: dict, path: Path, wait: bool = False):
    """Write a proposal's knobs to design.json through the session (one undo step) and rebuild."""
    design = SESSION.design_path
    new = path.with_name("proposal_design.json")
    new.unlink(missing_ok=True)
    start = design_io.design_fingerprint(design)

    def done(ok, output):
        if not ok or not new.exists():
            lines = [ln for ln in output.splitlines() if ln.strip()]
            message("Apply failed: " + (build_error(output) if lines else "no output")[:160], 20)
            return
        if design_io.design_fingerprint(design) != start:  # an edit made while qcc worked: keep it, do not overwrite
            message("Apply: the design was edited meanwhile, so the revision was not applied (Propose again)", 20)
            return
        what = "tune: " + ", ".join(f"{k['knob']} {k['old']:g} → {k['new']:g}" for k in proposal["knobs"][:4])
        SESSION.commit(design_io.read_design(new), what)
        message(what + " (Quantcore > Edit > Undo takes it back). Simulate again to check.", 15)

    job = _run([["results", "apply", design, path, "-o", new]], "Apply revision", done, None, design.parent)
    return _finish(job, wait)


# ---- Fab -----------------------------------------------------------------------------------------------------------
def fab(wait: bool = False, folder: str | None = None, force: bool = False):
    """Flow ▸ Fab: the fab mask (``qcc mask``, PDK fab layers, cheese and corner rounding), the netlist (circuit.json),
    ``design.py`` and a PNG, all into one folder."""
    try:
        if not _design_ready() or _busy_check("Fab export"):
            return None
        failed = (SESSION.data or {}).get("failed_routes") or {}
        if failed:  # a mask must not lack a route: refuse, name it and why (no "anyway": the mask build needs it too)
            name, f = next(iter(failed.items()))
            message(f"Fab export refused: route {name} failed to build ({str(f.get('error', ''))[:140]}). "
                    "Fix it (it is drawn in red) or delete it, then export again.", 30)
            return None
        errors = [i for i in (SESSION.data or {}).get("drc", []) if i.get("severity") == "error"]
        if errors and not force:
            pick = choose("Fab export", f"The design has {len(errors)} DRC error(s), e.g. {errors[0]['message'][:120]}. "
                          "Export the fab files anyway?", ["Export anyway"])
            if pick is None:
                return None
        design = SESSION.design_path
        folder = folder or ask_dir("Folder for the fab files (build/ is where the Flow strip looks for the mask)", str(design.parent / "build"))
        if not folder:
            return None
        out = Path(folder)
        out.mkdir(parents=True, exist_ok=True)
        name = design.stem
        steps = [["mask", design, "-o", out / f"{name}_fab.oas"],
                 ["circuit", "export", design, "-o", out / f"{name}.circuit.json"],
                 ["design", "to-python", design, "-o", out / f"{name}.py"]]
        fingerprint = design_io.design_fingerprint(design)

        def done(ok, output):
            if ok:
                design_io.set_mark(design, "fab", fingerprint)
            _fab_done(ok, output, out, name)

        job = _run(steps, "Fab export", done, None, design.parent)
        message("Fab export: writing the mask, netlist and design.py…", 8)
        return _finish(job, wait)
    except Exception:  # noqa: BLE001
        report_error("Fab export")
        return None


def save_python(wait: bool = False, path: str | None = None):
    """Quantcore ▸ Design ▸ Save as Python script…: ``qcc design to-python`` (the drawn chip as a Designer script, to
    continue it as code; the fab export puts the same script beside the mask)."""
    try:
        if not _design_ready() or _busy_check("Save as Python script"):
            return None
        design = SESSION.design_path
        path = path or pya.QFileDialog.getSaveFileName(None, "Save design as Python script",
                                                       str(design.with_suffix(".py")), "Python (*.py)")
        if not path:
            return None
        job = _run([["design", "to-python", design, "-o", path]], "Save as Python script",
                   lambda ok, out: message(f"design.py written: {path}" if ok else "Save as Python failed: "
                                           + build_error(out), 12), None, design.parent)
        return _finish(job, wait)
    except Exception:  # noqa: BLE001
        report_error("Save as Python script")
        return None


def _fab_done(ok: bool, output: str, out: Path, name: str) -> None:
    _update_strip()
    lines = [ln for ln in output.splitlines() if ln.strip()]
    png = out / f"{name}.png"
    try:
        view = pya.LayoutView.current()
        if ok and view is not None:
            view.save_image_with_options(str(png), 1600, 1200, 0, 2, 0, pya.DBox(), False)
    except Exception as e:  # noqa: BLE001
        log(f"fab: PNG not written: {e!r}")
    if not ok:
        message(f"Fab export failed: {build_error(output)[:160]} (details in the window)", 20)
        info_window("Fab export failed", "\n".join(lines[-40:]))
        return
    files = sorted(p.name for p in out.iterdir() if p.is_file())
    text = (f"Written to {out}:\n\n" + "\n".join(f"  {f}" for f in files) + "\n\n" + "\n".join(lines)
            + "\n\nThe mask is a negative mask (drawn = removed) on the Quantcore fab layers, with the PDK frame, "
            "device ID, 100 µm pad rule, cheese band and corner rounding. design.py rebuilds this design as Python.")
    message(f"Fab export: written to {out}", 12)
    info_window("Fab export", text, {"open": ("Open folder", lambda: open_folder(out))})


# not in the menu: "Export sim job" (the Simulate dialog has "Export the job only") and "Open results file" (Import results
# takes a results file); export_job / open_results_file stay for the dialog, the panel and the tests
ACTIONS = [  # (submenu, name, title, function, shortcut); submenu: design | simulate | results | fab (menu.py)
    ("design", "qcc_save_python", "Save as Python script (design.py)…", save_python, ""),
    ("simulate", "qcc_simulate", "Simulate selected components (automatic, in AEDT)…", simulate, ""),
    ("simulate", "qcc_sim_layout", "Open simulation layout…", open_sim_layout, ""),
    ("simulate", "qcc_import_results", "Import results…", import_results, ""),
    ("results", "qcc_results", "Results against targets…", results, ""),
    ("results", "qcc_propose", "Propose next revision…", propose, ""),
    ("fab", "qcc_fab", "Export for fab (mask, netlist, design.py, PNG)…", fab, ""),
]

