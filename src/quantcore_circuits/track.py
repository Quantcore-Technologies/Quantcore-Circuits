"""Live run state for the dashboard (``reviewer/``, served by ``qcc review``): ``build/<design>/state.json``.

A :class:`Run` records the design loop as it happens — which step is running, targets vs current values, KLayout
screenshots, plots (as data, rendered by the dashboard and by :mod:`quantcore_circuits.plots`), the circuit, the
Hamiltonian, the estimator consensus, simulation jobs, optimiser history and a log. Every mutation rewrites
``state.json`` atomically (inside :meth:`Run.deferred`: step starts / ends and the end of the block only); the server
pushes a Server-Sent Event and the browser refetches. The JSON follows the contract in ``reviewer/contract/state.ts``.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

STATE_SCHEMA = "qcc-state/0.1"
STEPS = [
    ("synthesis", "LOM synthesis"),
    ("layout", "Layout"),
    ("render", "HFSS render"),
    ("simulate", "Simulate"),
    ("extract", "Extract"),
    ("hamiltonian", "Hamiltonian"),
    ("compare", "Compare to targets"),
    ("feedback", "Feedback"),
]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_dir_for(design_name: str, root: str | Path = "build") -> Path:
    return Path(root) / design_name


_LOCK = threading.RLock()  # the notebook thread and the tracking threads (snapshots, FEM watcher) share Run objects
_RUNS: dict[str, Run] = {}  # one Run object per run directory in a process (two writers on a state.json clobber it)


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        with _LOCK:
            return fn(*a, **k)

    return wrapper


class Run:
    def __new__(
        cls, design_source=None, run_dir: str | Path | None = None, reset: bool = False, name: str | None = None
    ):
        key = None
        if run_dir is not None or name is not None:
            key = str(Path(run_dir if run_dir is not None else run_dir_for(name)).resolve())
        elif design_source is not None:
            from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

            key = str(run_dir_for(load_design(design_source).name).resolve())
        with _LOCK:
            if key is not None and key in _RUNS:
                return _RUNS[key]
            self = super().__new__(cls)
            if key is not None:
                _RUNS[key] = self
            return self

    @_locked
    def __init__(
        self, design_source=None, run_dir: str | Path | None = None, reset: bool = False, name: str | None = None
    ):
        """``design_source`` None: a model-only run named ``name`` (a stand-alone ``circuit.json``, no layout)."""
        from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

        self.design_source = design_source
        design = load_design(design_source) if design_source is not None else None
        self.dir = Path(run_dir) if run_dir else run_dir_for(design.name if design else name)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "state.json"
        if not hasattr(self, "design_names"):
            self.design_names: set[str] = set()
        if self.path.exists() and not reset:
            self.state = {**self._empty(), **json.loads(self.path.read_text(encoding="utf-8"))}
        else:
            self.state = self._empty()
        self.follow(design, design_source, name, save=False)
        self.save()

    @_locked
    def follow(self, design, design_source=None, name: str | None = None, save: bool = True) -> None:
        """Point the run's ``design`` block at ``design`` (a revision of the same run). ``None``: a model-only run."""
        from quantcore_circuits.design import design_hash  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

        if design is None:
            stack = get_pdk().stack
            info = {
                "name": name or "model",
                "path": "",
                "hash": "",
                "pdk": get_pdk().name,
                "chipBox": [0, 0, 1000, 1000],
                "instances": 0,
                "routes": 0,
            }
        else:
            stack = get_pdk(design.pdk).stack
            info = {
                "name": design.name,
                "path": str(design_source) if isinstance(design_source, (str, Path)) else design.name,
                "hash": design_hash(design),
                "pdk": design.pdk,
                "chipBox": list(design.chip.box),
                "instances": len(design.instances),
                "routes": len(design.routes),
            }
            self.design_names.add(design.name)
        info["stack"] = {
            "substrate": stack.substrate_material,
            "epsR": stack.substrate_permittivity,
            "thickness_um": stack.substrate_height,
        }
        self.state["design"] = info
        if save:
            self.save()

    @staticmethod
    def _empty() -> dict:
        return {
            "schema": STATE_SCHEMA,
            "updated": _now(),
            "design": {},
            "currentStep": None,
            "steps": [{"id": i, "index": k + 1, "title": t, "status": "pending"} for k, (i, t) in enumerate(STEPS)],
            "goal": {"reached": False, "passed": 0, "total": 0, "summary": "no targets evaluated yet"},
            "targets": [],
            "screenshots": [],
            "plots": [],
            "circuit": None,
            "hamiltonian": None,
            "consensus": [],
            "jobs": [],
            "cmatrix": None,
            "history": [],
            "log": [],
            "sections": [],
            "cards": [],
            "summary": [],
            "elements": [],
            "femCompare": [],
        }

    # ---- persistence ------------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def deferred(self):
        """Within this block ``state.json`` is written when a step starts, ends or fails and once at the end, not on
        every log line, plot or field (an analysis of many qubit pairs adds dozens of them; each write encodes the
        whole state)."""
        with _LOCK:
            self._defer = getattr(self, "_defer", 0) + 1
        try:
            yield self
        finally:
            with _LOCK:
                self._defer -= 1
                if not self._defer:
                    self.save()

    @_locked
    def save(self, force: bool = False) -> Path:
        if getattr(self, "_defer", 0) and not force:
            return self.path
        self.state["updated"] = _now()
        data = json.dumps(self.state, indent=1, ensure_ascii=False, default=_json_default)
        self.dir.mkdir(parents=True, exist_ok=True)  # the run dir may have been removed mid-run
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=self.dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        # Windows refuses to replace a file another process has open (the dashboard server reading it): retry briefly
        for attempt in range(40):
            try:
                os.replace(tmp, self.path)
                break
            except PermissionError:
                if attempt == 39:
                    os.remove(tmp)
                    raise
                time.sleep(0.025)
        return self.path

    # ---- steps ------------------------------------------------------------------------------------------------
    def _step(self, step_id: str) -> dict:
        for s in self.state["steps"]:
            if s["id"] == step_id:
                return s
        raise KeyError(step_id)

    @_locked
    def start(self, step_id: str, summary: str | None = None) -> None:
        s = self._step(step_id)
        s.update(status="running", started=_now())
        s.pop("finished", None)
        if summary:
            s["summary"] = summary
        self.state["currentStep"] = step_id
        self.log(f"{s['title']}: started")
        if getattr(self, "_defer", 0):
            self.save(force=True)

    @_locked
    def done(self, step_id: str, summary: str = "", **metrics) -> None:
        s = self._step(step_id)
        s.update(status="done", finished=_now(), summary=summary or s.get("summary", ""))
        if metrics:
            s["metrics"] = {k: _plain(v) for k, v in metrics.items()}
        self.log(f"{s['title']}: {summary}" if summary else f"{s['title']}: done")
        if getattr(self, "_defer", 0):
            self.save(force=True)

    @_locked
    def fail(self, step_id: str, message: str) -> None:
        s = self._step(step_id)
        s.update(status="failed", finished=_now(), summary=message)
        self.state["currentStep"] = step_id
        self.log(f"{s['title']}: {message}", "error")
        if getattr(self, "_defer", 0):
            self.save(force=True)

    @_locked
    def skip(self, step_id: str, reason: str) -> None:
        s = self._step(step_id)
        s.update(status="skipped", summary=reason)
        self.log(f"{s['title']}: skipped ({reason})", "warn")

    @_locked
    def reset_from(self, step_id: str) -> None:
        """Mark ``step_id`` and every later step pending again (a new loop iteration)."""
        hit = False
        for s in self.state["steps"]:
            hit = hit or s["id"] == step_id
            if hit:
                s.update(status="pending")
                for k in ("started", "finished"):
                    s.pop(k, None)
        self.save()

    # ---- content ----------------------------------------------------------------------------------------------
    @_locked
    def log(self, msg: str, level: str = "info") -> None:
        self.state["log"].append({"t": _now(), "level": level, "msg": msg})
        self.state["log"] = self.state["log"][-500:]
        self.save()

    @_locked
    def screenshot(
        self,
        png: str | Path,
        title: str,
        step: str | None = None,
        caption: str = "",
        source: str = "headless",
        ident: str | None = None,
    ) -> dict:
        """Copy ``png`` into ``<run>/shots/`` and register it (same ``ident`` replaces the earlier one)."""
        png = Path(png)
        shots = self.dir / "shots"
        shots.mkdir(parents=True, exist_ok=True)
        ident = ident or png.stem
        target = shots / f"{ident}.png"
        if png.resolve() != target.resolve():
            shutil.copyfile(png, target)
        entry = {
            "id": ident,
            "title": title,
            "url": f"/files/shots/{target.name}?v={int(target.stat().st_mtime)}",
            "step": step,
            "caption": caption,
            "created": _now(),
            "source": source,
        }
        self.state["screenshots"] = [s for s in self.state["screenshots"] if s["id"] != ident] + [entry]
        self.save()
        return entry

    @_locked
    def plot(self, spec: dict) -> None:
        """Add or replace a PlotSpec (``id`` is the key)."""
        spec = _plain(spec)
        self.state["plots"] = [p for p in self.state["plots"] if p["id"] != spec["id"]] + [spec]
        self.save()

    @_locked
    def set(self, **fields) -> None:
        """Set top-level fields: targets, goal, circuit, hamiltonian, consensus, jobs, cmatrix, history."""
        for k, v in fields.items():
            self.state[k] = _plain(v)
        self.save()

    @_locked
    def iteration(self, entry: dict) -> None:
        self.state["history"] = [h for h in self.state["history"] if h["iteration"] != entry["iteration"]]
        self.state["history"].append(_plain({"time": _now(), **entry}))
        self.state["history"].sort(key=lambda h: h["iteration"])
        self.save()

    def refresh_jobs(self, jobs_root: str | Path | None = None, keep_root: str | Path | None = "auto") -> list[dict]:
        """Scan ``jobs_root`` (and the tutorials' kept FEM results) for the job directories of this run's design(s):
        status, results, and the solve progress (:func:`job_progress`). Returns the jobs and stores them."""
        # no lock while scanning (file reads, imports): a thread that holds _LOCK and waits for an import lock
        # deadlocks with the thread that is importing and calls into a Run
        names = set(self.design_names) | {self.state["design"].get("name")}
        roots = [Path(jobs_root)] if jobs_root else [self.dir.parent / "jobs", Path.cwd() / "build" / "jobs"]
        found: dict[str, dict] = {}
        for root in dict.fromkeys(r.resolve() for r in roots):  # the run root's jobs, and the cwd's (examples/build)
            found.update({j["name"]: j for j in scan_jobs(names, root, keep_root)})
        jobs = sorted(found.values(), key=lambda j: j["name"])
        if json.dumps(jobs, sort_keys=True) != json.dumps(self.state.get("jobs"), sort_keys=True):
            self.set(jobs=jobs)
        return jobs


# ---- FEM jobs -----------------------------------------------------------------------------------------------------
_RUNNING = ("solving", "rendering", "running")
_NOISE = ("vgl_", "SYS_ERROR", "type=", "Argument is not")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pid_alive(pid: int) -> bool:
    """Whether process ``pid`` exists (never signals it: a query only)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes  # pylint: disable=import-outside-toplevel

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def job_alive(d: Path, job: dict) -> bool:
    """A job whose ``job.json`` says "solving" / "rendering": is the AEDT process still there? (``<log>.pid``, written
    by ``hfss.run_aedt``). Without a pid file a job that started under a minute ago counts as alive."""
    for stem in ("solve.log.pid", "render.log.pid"):
        f = d / stem
        if f.exists():
            try:
                pid = int(f.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            if job.get("started") and f.stat().st_mtime < job["started"] - 5:
                continue  # the pid of an earlier run
            if pid_alive(pid):
                return True
            # AEDT has exited but qcc is still collecting the results (pyEPR, notch fits) before job.json says done:
            # the status file ends with "end" — finishing, not interrupted (for a few minutes at most)
            status = d / ("qcc_solve_status.txt" if stem.startswith("solve") else "qcc_render_status.txt")
            try:
                lines = status.read_text(encoding="utf-8", errors="replace").split()
                return bool(lines) and lines[-1] == "end" and time.time() - status.stat().st_mtime < 600
            except OSError:
                return False
    return bool(job.get("started")) and time.time() - job["started"] < 60


def _live_progress(d: Path) -> dict:
    """``sim_tools.aedt_progress.read_progress`` in the dashboard's ``JobProgress`` shape (``pass``, ``maxPasses``,
    ``delta`` / ``elements`` as one-entry lists, ``criterion``, ``target``, ``converged``, ``modesGHz``); empty when
    AEDT has written no adaptive pass yet."""
    from quantcore_circuits.sim_tools.aedt_progress import read_progress  # pylint: disable=import-outside-toplevel

    try:
        p = read_progress(d)
    except (OSError, ValueError):
        return {}
    if p.get("pass") is None:
        return {}
    out = {"pass": p["pass"], "criterion": p.get("criterion"), "target": p.get("target"), "delta": [p.get("delta")]}
    if p.get("converged") is not None:  # HFSS says so in EMConvData; Q3D's ΔC is only an estimate
        out["converged"] = bool(p["converged"])
    if p.get("max_passes"):
        out["maxPasses"] = p["max_passes"]
    if p.get("elements"):
        out["elements"] = [p["elements"]]
    if p.get("modes_GHz"):
        out["modesGHz"] = [round(f, 4) for f in p["modes_GHz"]]
    return out


def job_progress(d: Path, job: dict) -> dict | None:
    """Solve progress of the job directory ``d`` from the files the solve leaves behind: ``job.json`` (status, start
    time, settings), ``qcc_solve_status.txt`` / ``solve.log`` (last lines), ``*_convergence.txt`` (adaptive passes,
    mesh, criterion), ``results/results.json``. None when there is nothing to show (an exported job)."""
    status = job.get("status", "exported")
    prog: dict = {}
    if status in _RUNNING and not job_alive(d, job):
        prog["stale"] = True  # job.json still says "solving" but the process is gone (killed kernel, crash)
    elif job.get("started") and status in _RUNNING:
        prog["elapsedS"] = round(time.time() - job["started"], 1)
    elif job.get("solve_seconds") is not None:
        prog["elapsedS"] = job["solve_seconds"]
    settings = job.get("settings") or {}
    if settings.get("maximum_passes"):
        prog["maxPasses"] = settings["maximum_passes"]
    for stem in ("qcc_solve_status.txt", "qcc_render_status.txt"):
        f = d / stem
        if f.exists():
            lines = [ln.strip() for ln in f.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
            if lines:
                prog["stage"] = lines[-1][:160]
                break
    log = d / "solve.log"
    if log.exists():
        try:
            with log.open("rb") as fh:
                fh.seek(max(0, log.stat().st_size - 4096))
                tail = fh.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            tail = []
        tail = [ln.strip() for ln in tail if ln.strip() and not any(n in ln for n in _NOISE)]
        if tail:
            prog["logTail"] = tail[-1][:200]
    conv_files = sorted(d.glob("*_project_convergence.txt"))  # written by AEDT at the end of the solve
    if not conv_files:  # still running: gui-live's reader (EMConvData, per-pass Q3D / eigenmode .sd, mesh stats)
        prog.update(_live_progress(d))
    if conv_files:
        from quantcore_circuits.analysis.results import parse_convergence  # pylint: disable=import-outside-toplevel

        try:
            c = parse_convergence(conv_files[0])
        except (OSError, ValueError):
            c = None
        if c and c["passes"]:
            prog.update(
                passes=c["passes"],
                elements=c["elements"],
                delta=c["delta"],
                converged=c["converged"],
                criterion=c["criterion"],
                target=c["target"],
                pass_=c["passes"][-1],
            )
            prog["pass"] = prog.pop("pass_")
    return prog if set(prog) - {"maxPasses"} else None  # an exported job has nothing to show


def scan_jobs(names, jobs_root: str | Path = "build/jobs", keep_root: str | Path | None = "auto") -> list[dict]:
    """Jobs (``job.json``) of designs ``names`` under ``jobs_root``; with ``keep_root`` ("auto": the tutorials'
    ``examples/tutorials/fem``) kept results of a job count when the build copy has none (``source: "kept"``)."""
    names = {n for n in names if n}
    roots = [Path(jobs_root)]
    if keep_root == "auto":
        keep_root = Path(jobs_root).parent.parent / "examples" / "tutorials" / "fem"
    if keep_root:
        roots.append(Path(keep_root))
    found: dict[str, dict] = {}
    for root in roots:
        if not root.exists():
            continue
        for job_json in sorted(root.glob("*/job.json")):
            job = _read_json(job_json)
            if job.get("design") not in names:
                continue
            d = job_json.parent
            has_res = (d / "results" / "results.json").exists()
            project = next(iter(sorted(d.glob("*_project.aedt"))), None)
            fin = job.get("finished")
            entry = {
                "name": d.name,
                "group": job.get("group"),
                "analysis": job.get("analysis"),
                "solver": job.get("solver"),
                "status": "interrupted"
                if job.get("status") in _RUNNING and not job_alive(d, job)
                else job.get("status", "exported"),
                "created": job.get("created"),
                "finished": datetime.fromtimestamp(fin, UTC).isoformat(timespec="seconds") if fin else None,
                "hasResults": has_res,
                "project": str(project) if project else None,
                "progress": job_progress(d, job),
            }
            old = found.get(d.name)
            if old is None:
                found[d.name] = entry
            elif has_res and not old["hasResults"] and old["status"] not in _RUNNING:
                # kept results of a job whose build copy was not solved in this checkout
                found[d.name] = {
                    **old,
                    "status": "done",
                    "hasResults": True,
                    "source": "kept",
                    "finished": entry["finished"] or old["finished"],
                }
    return sorted(found.values(), key=lambda j: j["name"])


def _json_default(o):
    if hasattr(o, "tolist"):
        return o.tolist()
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def _plain(v):
    """numpy scalars/arrays, tuples and dataclasses → JSON-safe Python values."""
    return json.loads(json.dumps(v, default=_json_default))


# ---- automatic tracking (see :mod:`quantcore_circuits.autotrack`) ----------------------------------------------------
_SESSION = None
_ENV_CHECKED = False


def default_root() -> Path:
    """``<repo>/build``: the folder with the pyproject.toml above the working directory (notebooks run from
    ``examples/``, ``examples/tutorials/`` or the root all share one set of runs), else ``./build``."""
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if (p / "pyproject.toml").exists() and (p / "src" / "quantcore_circuits").exists():
            return p / "build"
    return Path("build")


def start(
    name: str | None = None,
    *,
    reset: bool = True,
    snapshots: bool = True,
    root: str | Path | None = None,
    dashboard: bool = False,
    port: int = 8765,
    open_browser: bool = True,
    watch: bool = True,
):
    """Record the library's calls (builds, DRC, LOM, FEM jobs, feedback) into ``build/<name>/state.json``.

    ``name``: one run for everything (e.g. a tutorial's revisions); None: one run per design name. ``reset``: start
    the run(s) fresh. ``dashboard=True`` also serves the dashboard from this process (background thread) following
    the run. Returns the session (``.flush()`` waits for the background snapshots)."""
    global _SESSION, _ENV_CHECKED  # noqa: PLW0603
    from quantcore_circuits.autotrack import Session  # pylint: disable=import-outside-toplevel

    root = Path(root) if root is not None else default_root()

    _ENV_CHECKED = True
    if _SESSION is not None:
        _SESSION.stop()
    _SESSION = Session(name, root, reset=reset, snapshots=snapshots, watch=watch)
    if dashboard:
        from quantcore_circuits.review.server import serve_live  # pylint: disable=import-outside-toplevel

        _SESSION.server = serve_live(root=root, run=name, port=port, open_browser=open_browser, background=True)
    return _SESSION


def stop() -> None:
    global _SESSION  # noqa: PLW0603
    if _SESSION is not None:
        _SESSION.flush()
        _SESSION.stop()
        server = getattr(_SESSION, "server", None)
        if server is not None:
            server.shutdown()
            server.server_close()
    _SESSION = None


def session():
    """The active tracking session or None (``QCC_TRACK=1`` / ``QCC_TRACK=<run name>`` starts one on first use)."""
    global _ENV_CHECKED  # noqa: PLW0603
    if _SESSION is None and not _ENV_CHECKED:
        _ENV_CHECKED = True
        env = os.environ.get("QCC_TRACK", "").strip()
        if env and env.lower() not in ("0", "false", "no", "off"):
            start(None if env.lower() in ("1", "true", "yes", "on") else env)
    return _SESSION


def emit(event: str, **kw) -> None:
    """Library hook: report ``event`` to the tracking session (no-op when tracking is off; never raises)."""
    s = session()
    if s is not None:
        s.handle(event, kw)


def run_for(design=None, model_name: str | None = None):
    """The tracking session's Run for ``design`` (None when tracking is off): what ``loop.analyse`` records into."""
    s = session()
    if s is None:
        return None
    try:
        return s.run_for(design, model_name)
    except Exception:  # noqa: BLE001  pylint: disable=broad-except  # tracking never breaks the caller
        return None


@contextlib.contextmanager
def quiet():
    """Suspend the automatic fill/LOM/DRC hooks (a caller that records those results itself, e.g. ``loop.analyse``)."""
    s = _SESSION
    if s is None:
        yield
        return
    s.quiet_depth += 1
    try:
        yield
    finally:
        s.quiet_depth -= 1


class _Stage:
    """Handle of :func:`stage`: ``fail(msg)`` ends the stage "failed" without raising; ``note`` is the done summary."""

    def __init__(self, note: str = ""):
        self.failed: str | None = None
        self.note = note

    def fail(self, msg: str = "failed") -> None:
        self.failed = msg


@contextlib.contextmanager
def stage(step: str, label: str = ""):
    """Mark dashboard step ``step`` running, then done (or failed on an exception / ``handle.fail(msg)``) when the
    block ends. Nested stages of one step (``hfss.render`` exporting its job) mark only the outermost. No-op when
    tracking is off; never raises on its own."""
    h = _Stage()
    if session() is None:
        yield h
        return
    emit("stage", step=step, phase="running", label=label)
    try:
        yield h
    except BaseException as e:
        emit("stage", step=step, phase="failed", label=label, detail=f"{type(e).__name__}: {e}")
        raise
    emit(
        "stage",
        step=step,
        phase="failed" if h.failed else "done",
        label=label,
        detail=h.failed or h.note,
    )
