"""The live editing session inside KLayout: which design is open, its sidecar, and how edits get rebuilt.

Edits are written to ``design.json`` (never to the layout). A background ``qcc watch --no-klive`` process (started
on demand, so KQC is imported once) rebuilds in ~0.1 s; without it each commit runs ``qcc build``. When the layout
file changes after a commit the view reloads it in place, and the sidecar (``<name>.qcc.json``) is re-read so the
tool overlays follow the new geometry.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pya  # type: ignore

from qcc_kplugin import design_io

CFG_QCC = "qcc-kplugin-qcc-exe"
CFG_DESIGN = "qcc-kplugin-design"
CFG_GRID = "qcc-kplugin-grid"
CFG_CAPTURE = "qcc-kplugin-capture-px"
CFG_LOM_LIMIT = "qcc-kplugin-lom-limit-min"  # Run LOM stops itself after this many minutes (default 30)
CFG_LABEL_HEIGHT = "qcc-kplugin-label-height"  # instance name labels of the built layout, µm (KQC draws 280)
CFG_DIALOG_COLUMNS = "qcc-kplugin-dialog-columns"  # 2 (default): a long dialog puts its rows in two columns
DEFAULT_LABEL_HEIGHT = 70.0

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def config(key: str, default: str = "") -> str:
    value = pya.Application.instance().get_config(key)
    return value if value else default


def set_config(key: str, value) -> None:
    app = pya.Application.instance()
    app.set_config(key, str(value))
    app.commit_config()


def label_height() -> float:
    """Settings ▸ instance name label height (µm, 0 = none): the plugin's builds pass it as ``--label-height``."""
    try:
        return max(0.0, float(config(CFG_LABEL_HEIGHT, f"{DEFAULT_LABEL_HEIGHT:g}")))
    except ValueError:
        return DEFAULT_LABEL_HEIGHT


def label_args() -> list[str]:
    """``qcc build`` / ``qcc watch`` arguments for the label height (an annotation layer only: the fab mask, the
    simulations and the design hash do not change)."""
    return ["--label-height", f"{label_height():g}"]


LOG = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "qcc_kplugin.log"


def log(text: str) -> None:
    """Append to ``%TEMP%/qcc_kplugin.log``: KLayout started from the Start menu has no visible console."""
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
    except OSError:
        pass


def ok_cancel(dialog):
    """OK / Cancel buttons wired to ``dialog``. KLayout 0.30's pya has no ``QDialogButtonBox(buttons, parent)``
    constructor (it reads the flags as an orientation and raises), so the buttons are set afterwards."""
    box = pya.QDialogButtonBox(dialog)
    box.setStandardButtons(pya.QDialogButtonBox.Ok | pya.QDialogButtonBox.Cancel)
    box.accepted(dialog.accept)
    box.rejected(dialog.reject)
    return box


def message(text: str, secs: float = 6, log_it: bool = True) -> None:
    """Status-bar message (and console + log). Progress lines that repeat every timer tick pass ``log_it=False``."""
    pya.MainWindow.instance().message(text, int(secs * 1000))
    if log_it:
        print(f"[qcc] {text}".encode("ascii", "replace").decode("ascii"))  # KLayout's console is not UTF-8
        log(text)


ERRORS: list[str] = []  # what of every error reported (tests read it; capped)
_GUARDED_SEEN: set = set()


def guard_error(what: str) -> None:
    """An exception escaped a mouse / key / timer handler: log it and put a one-line note in the status bar. Never a
    dialog (a mouse-move handler runs ~60 times a second) and never re-raised (KLayout would show a "Script Error").
    The same error is logged once, then only counted."""
    import traceback  # pylint: disable=import-outside-toplevel

    tb = traceback.format_exc()
    ERRORS.append(what)
    del ERRORS[:-200]
    last = tb.strip().splitlines()[-1] if tb.strip() else "error"
    if (what, last) not in _GUARDED_SEEN:
        _GUARDED_SEEN.add((what, last))
        log(f"ERROR {what}\n{tb}")
    try:
        pya.MainWindow.instance().message(f"Quantcore: {what} failed: {last[:160]} (log: {LOG})", 8000)
    except Exception:  # noqa: BLE001
        pass


def report_error(what: str) -> None:
    """A tool action failed: the traceback goes to the log, a message box tells the user (not silently lost)."""
    import traceback  # pylint: disable=import-outside-toplevel

    tb = traceback.format_exc()
    ERRORS.append(what)
    del ERRORS[:-200]
    log(f"ERROR {what}\n{tb}")
    pya.MessageBox.warning("Quantcore", f"{what} failed:\n\n{tb[-1500:]}\n(log: {LOG})", pya.MessageBox.Ok)


def build_error(out: str) -> str:
    """The line of a failed ``qcc build`` output worth showing: the last exception line (``RoutingError: route R2:
    ...``), else the last line that is not a warning (a ``FutureWarning`` is printed after the error at exit and would
    hide it)."""
    lines = [ln.strip() for ln in out.splitlines() if ln.strip() and not ln.startswith(("|", "+", "│"))]
    for i, ln in enumerate(lines):  # pydantic: "1 validation error for Design", the reason on the next line
        if "validation error for Design" in ln and i + 1 < len(lines):
            return "design.json is not valid: " + lines[i + 1].split("[type=", 1)[0].strip()
    for ln in reversed(lines):
        head, _, rest = ln.partition(":")
        if head.endswith(("Error", "Exception")) and "Warning" not in head and " " not in head:
            # the status bar is short: no module path, and a routing error already starts with "route R2: ..."
            short = head.rsplit(".", 1)[-1]
            return rest.strip() if short == "RoutingError" else f"{short}: {rest.strip()}"
        if head.endswith(("Error", "Exception")) and "Warning" not in head:
            return ln
    for ln in reversed(lines):
        if "Warning" not in ln.split(":", 1)[0]:
            return ln
    return lines[-1] if lines else out[-300:].strip()


def failure_summary(failed: dict[str, str]) -> str:
    """Status-bar text for the routes a build left out: names and reasons, and where to fix them."""
    name, why = next(iter(failed.items()))
    why = why[len(f"route {name}: "):] if why.startswith(f"route {name}: ") else why
    more = f" (and {len(failed) - 1} more route(s))" if len(failed) > 1 else ""
    return (f"Route {name} failed: {why}{more}. It is drawn in red and left out of the layout; the rest of the design "
            "built. Fix it with the Route handles (nodes, double-click), or Quantcore > Undo")


def clean_env() -> dict:
    """Environment for child processes, so ``qcc`` (conda Python + pip ``klayout``) starts as from a terminal.

    Drops KLayout's embedded-Python variables and removes KLayout's own folders from PATH: otherwise the pip
    ``klayout`` extension in the child can pick up the GUI's ``klayout_*.dll`` (another version) and hang.
    """
    drop = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "PYTHONUSERBASE", "__PYVENV_LAUNCHER__")
    env = {k: v for k, v in os.environ.items() if k.upper() not in drop and not k.upper().startswith("QT_")}
    env.update({"PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "_TYPER_STANDARD_TRACEBACK": "1"})
    key = next((k for k in env if k.upper() == "PATH"), "PATH")
    parts = [p for p in env.get(key, "").split(os.pathsep) if p and not Path(p, "klayout_db.dll").exists()]
    env[key] = os.pathsep.join(parts)
    return env


def default_qcc() -> str:
    """``qcc`` when Settings has none: on PATH, else the conda env ``qcd`` (KLayout started from the Start menu does
    not see the conda env's Scripts folder)."""
    import shutil  # pylint: disable=import-outside-toplevel

    found = shutil.which("qcc")
    if found:
        return found
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~").expanduser()
    for base in (home / ".conda" / "envs", home / "miniconda3" / "envs", home / "anaconda3" / "envs"):
        exe = base / "qcd" / ("Scripts/qcc.exe" if os.name == "nt" else "bin/qcc")
        if exe.exists():
            return str(exe)
    return "qcc"


class Session:
    """Singleton (see :data:`SESSION`) shared by the menu actions and the tools."""

    def __init__(self):
        self.design_path: Path | None = None
        self.built: dict = {}  # id → transform of the components as last built (native-move detection)
        self._last_tick_error = ""
        self.layout_path: Path | None = None
        self.data: dict | None = None  # sidecar
        self._sidecar_mtime = 0.0
        self._layout_mtime = 0.0
        self._reload_after = None  # time of the last commit; reload the view when the layout is newer
        self.watcher: subprocess.Popen | None = None
        self.builder: subprocess.Popen | None = None
        self.listeners = []  # callables run after the sidecar changed
        self.timer = None
        self.history: list[dict] = []  # previous design.json contents, for undo
        self.future: list[dict] = []  # undone design.json contents, for redo
        self.last_error: str | None = None
        self.failed_routes: dict[str, str] = {}  # routes the last build left out → why (qcc build --keep-going)
        self._in_tick = False
        self._build_started = 0.0
        self._build_log: Path | None = None
        self._pending_build = False  # an edit arrived while a build was running
        self._known_design: dict | None = None  # design.json as this session last wrote or read it
        self._known_mtime = 0.0
        self._known_path: Path | None = None

    # ---- setup ------------------------------------------------------------------------------------------------
    @property
    def qcc(self) -> str:
        return config(CFG_QCC, "") or default_qcc()

    @property
    def grid(self) -> float:
        """Snap grid (µm): KLayout's editor grid (``edit-grid`` of the current view, else of the application), so
        the plugin's nodes snap like KLayout's own shapes; the plugin Settings grid when KLayout has none."""
        from qcc_kplugin.geometry import parse_grid  # pylint: disable=import-outside-toplevel

        sources = []
        try:
            view = pya.LayoutView.current()
            if view is not None:
                sources.append(view.get_config("edit-grid"))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            pass
        try:
            sources.append(pya.Application.instance().get_config("edit-grid"))
        except Exception:  # noqa: BLE001  pylint: disable=broad-except
            pass
        for text in sources:
            g = parse_grid(text)
            if g:
                return g
        return float(config(CFG_GRID, "1.0"))

    @property
    def capture_px(self) -> float:
        return float(config(CFG_CAPTURE, "12"))

    def sidecar_path(self) -> Path | None:
        if self.layout_path is None:
            return None
        return self.layout_path.with_name(self.layout_path.stem + ".qcc.json")

    def open(self, design_path) -> None:
        """Use ``design_path``; its layout is ``<design dir>/build/<stem>.oas`` unless the sidecar says otherwise."""
        self.design_path = Path(design_path).resolve()
        set_config(CFG_DESIGN, self.design_path)
        if self.layout_path is None or self.layout_path.stem != self.design_path.stem:
            self.layout_path = self.design_path.parent / "build" / f"{self.design_path.stem}.oas"
        self._start_timer()
        self._known_path = None
        self.check_external_edit()  # the baseline for spotting writes by others
        self.reload_sidecar(force=True)

    def attach_view(self, view=None) -> bool:
        """Pick up the design behind the layout shown in ``view`` (a qcc-written file with a sidecar)."""
        view = view or pya.LayoutView.current()
        if view is None:
            return False
        cv = view.active_cellview()
        if cv is None or not cv.is_valid() or not cv.filename():
            return self.data is not None
        layout = Path(cv.filename()).resolve()
        side = layout.with_name(layout.stem + ".qcc.json")
        if not side.exists():
            return self.data is not None
        if layout != self.layout_path:
            self.layout_path = layout
            data = json.loads(side.read_text(encoding="utf-8"))
            if data.get("design"):
                self.design_path = Path(data["design"])
                set_config(CFG_DESIGN, self.design_path)
            self._start_timer()
        return self.reload_sidecar(force=self.data is None)

    def reload_sidecar(self, force: bool = False) -> bool:
        side = self.sidecar_path()
        if side is None or not side.exists():
            return False
        mtime = side.stat().st_mtime
        if force or mtime != self._sidecar_mtime:
            try:
                self.data = json.loads(side.read_text(encoding="utf-8"))
            except ValueError:
                return self.data is not None  # half-written; next tick
            self._sidecar_mtime = mtime
            for fn in list(self.listeners):
                try:
                    fn()
                except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
                    print(f"[qcc] listener failed: {e}")
        return True

    # ---- design edits ------------------------------------------------------------------------------------------
    def ensure_design(self) -> bool:
        """A design to edit: the one open, else the one behind the layout in the current view (its sidecar), else
        the last design used (reopened and rebuilt, e.g. after a KLayout restart)."""
        if self.design_path is not None and self.design_path.exists():
            return True
        self.attach_view()
        if self.design_path is not None and self.design_path.exists():
            return True
        last = config(CFG_DESIGN)
        if last and Path(last).exists() and Path(last).suffix == ".json":
            self.open(last)
            self._reload_after = 0.0
            self._build()
            message(f"reopened the last design {Path(last).name} (rebuilding it into the view)")
            return True
        return False

    def design(self) -> dict:
        if not self.ensure_design():
            raise RuntimeError("no design open: Quantcore > New design... or Open design... first")
        return design_io.read_design(self.design_path)

    # ---- writes by others: qcc sim auto / sim subset (the sim group), a notebook, an editor ------------------------
    def _remember(self) -> None:
        try:
            self._known_design = design_io.read_design(self.design_path)
            self._known_mtime = self.design_path.stat().st_mtime
            self._known_path = self.design_path
        except (OSError, ValueError):
            self._known_path = None

    def check_external_edit(self) -> bool:
        """design.json was written by someone else since this session last wrote it.

        Sim groups are bookkeeping (``qcc sim auto`` / ``qcc sim subset`` write the group they simulate): they are kept
        as they are, and undo / redo carry them over, so undoing a drawing edit never drops the group the results
        belong to. Any other change becomes one undo step (Undo takes it back), and the layout is rebuilt when it can
        have changed. Returns True when the file changed."""
        path = self.design_path
        if path is None or path.suffix != ".json" or not path.exists():
            return False
        if self._known_path != path:  # another design was opened: this is the baseline
            self._remember()
            return False
        mtime = path.stat().st_mtime
        if mtime == self._known_mtime:
            return False
        try:
            now = design_io.read_design(path)
        except (OSError, ValueError):
            return False  # half-written: next tick
        old, self._known_design, self._known_mtime = self._known_design, now, mtime
        if old is None or now == old:
            return False
        changed = sorted(k for k in set(old) | set(now) if old.get(k) != now.get(k))
        if changed == ["sim_groups"]:
            log(f"design.json: sim groups written outside the GUI: {sorted(now.get('sim_groups') or {})}")
            return True
        self.history.append(old)
        del self.history[:-50]
        self.future.clear()
        message(f"design.json changed outside the GUI ({', '.join(changed)}): Quantcore > Edit > Undo takes it back")
        if design_io.design_fingerprint(old) != design_io.design_fingerprint(now) and not self.watching():
            self._reload_after = time.time()
            self._build()
        return True

    @staticmethod
    def _keep_sim_groups(restored: dict, current: dict) -> dict:
        """``restored`` (an undo / redo state) with the sim groups as they are now."""
        restored = dict(restored)
        if "sim_groups" in current:
            restored["sim_groups"] = current["sim_groups"]
        else:
            restored.pop("sim_groups", None)
        return restored

    def commit(self, design: dict, what: str = "") -> None:
        self.check_external_edit()  # a write by someone else first becomes its own step
        self.history.append(design_io.read_design(self.design_path))
        del self.history[:-50]
        self.future.clear()
        scrubbed = design_io.scrub_references(design, (self.data or {}).get("instances"))  # keep design.json valid
        if scrubbed:
            log("; ".join(scrubbed))
            what = (what + "; " if what else "") + "; ".join(scrubbed)
        design_io.write_design(self.design_path, design)
        self._remember()
        self._reload_after = time.time()
        if what:
            message(f"design.json: {what}")
        if not self.watching():
            self._build()

    def undo(self) -> bool:
        if not self.history:
            message("nothing to undo")
            return False
        self.check_external_edit()
        current = design_io.read_design(self.design_path)
        self.future.append(current)
        restored = self._keep_sim_groups(self.history.pop(), current)
        design_io.scrub_references(restored, (self.data or {}).get("instances"))  # a kept group may name a gone part
        design_io.write_design(self.design_path, restored)
        self._remember()
        self._reload_after = time.time()
        message("design.json: undone last edit")
        if not self.watching():
            self._build()
        return True

    def redo(self) -> bool:
        if not self.future:
            message("nothing to redo")
            return False
        self.check_external_edit()
        current = design_io.read_design(self.design_path)
        self.history.append(current)
        design_io.write_design(self.design_path, self._keep_sim_groups(self.future.pop(), current))
        self._remember()
        self._reload_after = time.time()
        message("design.json: redone edit")
        if not self.watching():
            self._build()
        return True

    def _build(self) -> None:
        if self.builder is not None and self.builder.poll() is None:
            self._pending_build = True  # one at a time: the timer starts another build when this one ends
            return
        self._pending_build = False
        self._build_started = time.time()
        # output goes to a file: a pipe nobody reads until exit deadlocks once a traceback fills its buffer
        self._build_log = self.layout_path.with_name(self.layout_path.stem + ".build.log")
        self._build_log.parent.mkdir(parents=True, exist_ok=True)
        with self._build_log.open("w", encoding="utf-8") as log:
            self.builder = subprocess.Popen(  # noqa: S603
                [self.qcc, "build", str(self.design_path), "-o", str(self.layout_path), "--keep-going", *label_args()],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=clean_env(),
                creationflags=_NO_WINDOW,
            )

    # ---- watcher ----------------------------------------------------------------------------------------------
    def watching(self) -> bool:
        return self.watcher is not None and self.watcher.poll() is None

    def start_watch(self) -> None:
        if self.design_path is None:
            raise RuntimeError("no design open")
        if self.watching():
            return
        self.watcher = subprocess.Popen(  # noqa: S603
            [self.qcc, "watch", str(self.design_path), "-o", str(self.layout_path), "--no-klive", *label_args()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_env(),
            creationflags=_NO_WINDOW,
        )
        self._start_timer()
        message(f"live rebuild: watching {self.design_path.name}")

    def stop_watch(self) -> None:
        if self.watching():
            self.watcher.terminate()
        self.watcher = None

    # ---- timer: rebuild results → view ----------------------------------------------------------------------------
    def _start_timer(self) -> None:
        if self.timer is None:
            self.timer = pya.QTimer(pya.Application.instance().main_window())
            self.timer.interval = 250
            self.timer.timeout(self.tick)
            self.timer.start()

    def tick(self) -> None:
        if self._in_tick:
            return
        self._in_tick = True
        try:
            self._tick()
        except Exception:  # noqa: BLE001  (a timer must never raise: KLayout would pop a script error every 250 ms)
            import traceback  # pylint: disable=import-outside-toplevel

            tb = traceback.format_exc()
            if tb != self._last_tick_error:
                self._last_tick_error = tb
                log(f"ERROR in the plugin timer\n{tb}")
                message(f"qcc plugin: {tb.strip().splitlines()[-1]} (details in {LOG})", 15)
        finally:
            self._in_tick = False

    def _tick(self) -> None:
        self.check_external_edit()
        if self.builder is not None and self.builder.poll() is None and time.time() - self._build_started > 120:
            self.builder.kill()  # watchdog: a build never takes minutes
            message("qcc build timed out after 120 s and was stopped", 30)
        if self.builder is not None and self.builder.poll() is not None:
            proc, self.builder = self.builder, None
            out = self._build_log.read_text(encoding="utf-8", errors="replace") if self._build_log else ""
            if proc.returncode != 0:
                # never modal here (this runs from a timer); the last good layout stays in the view
                self.last_error = build_error(out)
                self._reload_after = None
                print(("[qcc] build failed:\n" + out[-3000:]).encode("ascii", "replace").decode("ascii"))
                if "unknown instance" in out or "refers to unknown" in out or "is not a route" in out:
                    # names of removed parts left in sim groups / targets / couplings (e.g. a Simulate group from
                    # before a delete): drop them and build again (one undo step)
                    design = self.design()
                    if design_io.scrub_references(design, (self.data or {}).get("instances")):
                        self.commit(design, "removed references to deleted components")
                        return
                # the edit is in design.json, but nothing new shows until the design builds again
                message(f"Layout not updated: {self.last_error}  (edit saved; fix it, or Quantcore > Undo)", 30)
                for fn in list(self.listeners):
                    fn()
            else:
                self.last_error = None
                self._partial_build()
            if self._pending_build:  # edits made during that build: build the current design.json
                self._reload_after = time.time()
                self._build()
                return
        if self.layout_path is not None and self.layout_path.exists():
            mtime = self.layout_path.stat().st_mtime
            if self._reload_after is not None and mtime > self._reload_after and mtime != self._layout_mtime:
                self._layout_mtime = mtime
                self._reload_after = None
                self.reload_view()
        if not self.built:
            self.focus_chip()
        self.sync_native_moves()
        self.sync_live_pcells()
        self.reload_sidecar()

    def _partial_build(self) -> None:
        """A build that finished: the routes it left out (``failed_routes`` of the fresh sidecar) are named in the status
        bar; the rest of the design is in the layout, which reloads as after any build."""
        side = self.sidecar_path()
        try:
            failed = json.loads(side.read_text(encoding="utf-8")).get("failed_routes") if side else None
        except (OSError, ValueError):
            failed = None
        self.failed_routes = {n: str(f.get("error", "")) for n, f in (failed or {}).items()}
        if self.failed_routes:
            self.last_error = failure_summary(self.failed_routes)
            message(self.last_error, 30)
            for fn in list(self.listeners):
                fn()

    def find_view(self):
        """(view, cellview index) showing the design's layout, or (None, None)."""
        window = pya.MainWindow.instance()
        if self.layout_path is None:
            return None, None
        for i in range(window.views()):
            view = window.view(i)
            for j in range(view.cellviews()):
                fn = view.cellview(j).filename()
                if fn and Path(fn).resolve() == self.layout_path:
                    return view, j
        return None, None

    def chip_cell(self):
        """The DesignChip cell of the layout in the view (its instances are the design's components)."""
        view, j = self.find_view()
        if view is None:
            return None
        cv = view.cellview(j)
        if not cv.is_valid():
            return None
        layout = cv.layout()
        current = layout.cell(cv.cell_index) if cv.cell_index is not None else None
        if current is not None and current.name.startswith("Design"):
            return current  # the view already shows the chip cell
        # a deleted component leaves its cell as an extra top cell: look through every top cell, not top_cell()
        for top in layout.top_cells():
            chip = design_io.find_chip_cell(top)
            if chip is not top or top.name.startswith("Design"):
                return chip
        return None

    def focus_chip(self) -> None:
        """Show the DesignChip cell as the view's cell: its components are then top-level instances, so KLayout's own
        select / move / rotate / properties work on them (each move is written back to design.json)."""
        view, j = self.find_view()
        chip = self.chip_cell()
        if view is None or chip is None:
            return
        cv = view.cellview(j)
        if cv.cell_index != chip.cell_index():
            cv.cell = chip
        self.built = design_io.placed_instances(chip)
        from qcc_kplugin.pcells import LIVE  # pylint: disable=import-outside-toplevel

        if LIVE.active():  # Settings > live PCells: the components become Quantcore library PCells (same geometry)
            try:
                LIVE.after_build(self, chip)
            except Exception:  # noqa: BLE001  pylint: disable=broad-except  (the static layout stays usable)
                import traceback  # pylint: disable=import-outside-toplevel

                log(f"ERROR live PCells after the build\n{traceback.format_exc()}")

    def sync_native_moves(self) -> None:
        """Components moved / rotated with KLayout's own tools (or its properties dialog) → design.json, rebuilt."""
        if self.builder is not None or self._reload_after is not None or self.design_path is None:
            return
        chip = self.chip_cell()
        if chip is None or not self.built:
            return
        now = design_io.placed_instances(chip)
        moved = [n for n, t in now.items() if n in self.built and not design_io._same(t, self.built[n])]  # noqa: SLF001
        gone = [n for n in self.built if n not in now]  # deleted with KLayout's own Delete
        if not moved and not gone:
            return
        design = self.design()
        report = []
        if moved:
            design, report = design_io.sync_placements(design, chip, self.built)
        for name in gone:
            if name in design.get("instances", {}):
                design, routes = design_io.delete_instance(design, name)
                report.append(f"deleted {name}" + (f" and its routes {', '.join(routes)}" if routes else ""))
            elif name in design.get("routes", {}):
                del design["routes"][name]
                report.append(f"deleted route {name}")
        self.built = now
        if report:
            self.commit(design, "; ".join(report))

    def sync_live_pcells(self) -> None:
        """Settings > live PCells: Quantcore PCells placed with KLayout's Instance tool, or edited in its PCell dialog
        → design.json (one commit, so Undo takes it back), rebuilt."""
        if self.builder is not None or self._reload_after is not None or self.design_path is None:
            return
        from qcc_kplugin.pcells import LIVE  # pylint: disable=import-outside-toplevel

        if LIVE.active():
            LIVE.sync(self, self.chip_cell())

    def reload_view(self) -> None:
        """Reload the rebuilt layout in place. Reloading drops KLayout back to its select mode, so the Quantcore tool
        that was active (Connect, Route handles, Move/Snap) is switched on again: drawing goes on after each edit."""
        from qcc_kplugin import tools  # pylint: disable=import-outside-toplevel  (tools imports this module)

        tool = tools.ACTIVE[0] if tools.ACTIVE and tools.ACTIVE[0].active else None
        mode = {tools.ConnectTool: "qcc_connect", tools.RouteEditTool: "qcc_route_edit",
                tools.SnapTool: "qcc_snap"}.get(type(tool))
        keep = tool.keep_state() if hasattr(tool, "keep_state") else None  # the route being drawn survives the reload
        view, j = self.find_view()
        if view is not None:
            view.reload_layout(j)
        else:
            pya.MainWindow.instance().load_layout(str(self.layout_path), 1)
        self.focus_chip()
        if mode is not None and not tool.active:
            action = pya.MainWindow.instance().menu().action(f"@toolbar.{mode}")
            if action is not None:
                action.trigger()
        if keep and tools.ACTIVE and type(tools.ACTIVE[0]) is type(tool):
            tools.ACTIVE[0].restore_state(keep)
        tools.refresh_failed_overlay()


SESSION = Session()
