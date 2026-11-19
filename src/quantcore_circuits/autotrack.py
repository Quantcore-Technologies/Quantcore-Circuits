"""Automatic run tracking: the library's own calls record into ``build/<run>/state.json`` for the dashboard.

Switch it on with one line (``from quantcore_circuits import track; track.start("t04")``) or ``QCC_TRACK=1`` in the
environment (a name instead of ``1`` names the run). From then on the hooks in the library report to the
:class:`Session`:

=========================  =====================================================================================
library call               what the dashboard gets
=========================  =====================================================================================
``write_layout``           Layout step, design block, headless KLayout snapshot (``shots/chip*.png``, background)
``assembly.drc.check``     DRC counts on the Layout step
``circuit.fill.fill``      circuit (values, estimate vs FEM) and C-matrix, ``femCompare`` table, Extract step
``lom.simulate.simulate``  Hamiltonian step, targets with values, goal, plots, cards, one history row per design
``analysis.extract.*``     (old API) targets with values
``optimise.optimise``      one history row per evaluation, with the knobs
``loop.analyse/feedback``  as before (explicit :class:`~quantcore_circuits.track.Run` or the session's)
FEM jobs under build/jobs  a watcher thread polls ``job.json`` / ``solve.log`` / ``*_convergence.txt`` /
                           ``results/results.json`` (and the tutorials' kept results) once a second
=========================  =====================================================================================

Run naming: ``track.start("t04")`` records everything into ``build/t04`` whatever the design is called (the
tutorial's revisions all land in one run); ``track.start()`` keeps one run per design name (``build/<design>``,
what ``loop.analyse`` and ``Run(design)`` use). ``build/_live.json`` points at the run that saw the latest event;
``qcc dashboard`` follows it.

Nothing here may break a notebook: every handler is wrapped, a failure is logged once in the run's log.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

POINTER = "_live.json"
MAX_SHOTS = 12


class Session:
    def __init__(
        self,
        name: str | None = None,
        root: str | Path = "build",
        reset: bool = True,
        snapshots: bool = True,
        watch: bool = True,
    ):
        self.name = name
        self.root = Path(root)
        self.reset = reset
        self.snapshots = snapshots
        self.runs: dict[str, object] = {}  # run dir name → Run
        self.current = None  # the Run that saw the latest event
        self.quiet_depth = 0
        self.pending: list[tuple[str, dict]] = []  # events that had no design yet (synthesis)
        self.lom_hashes: dict[str, list[str]] = {}
        self.lom_designs: dict[str, dict[str, dict]] = {}
        self.lom_rows: dict[str, dict[str, dict]] = {}
        self.lom_last: dict[str, tuple] = {}
        self._warned: set[str] = set()
        self._jobs_active: dict[str, set[str]] = {}  # run dir → "render"/"simulate" steps the watcher started
        self._stage_depth: dict[tuple, int] = {}  # (run dir, step) → nesting of track.stage blocks
        self._stage_failed: dict[tuple, str] = {}
        self._lock = threading.RLock()
        self._work: dict[str, tuple] = {}  # key → (due time, fn): latest wins
        self._last_run_of: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="qcc-track", daemon=True)
        self._watch = watch
        from quantcore_circuits.analysis import results as _results  # noqa: F401  pylint: disable=C0415
        # (imported here, on the caller's thread: the watcher thread must never import under the Run lock)

        self._thread.start()

    # ---- runs -------------------------------------------------------------------------------------------------
    def run_for(self, design=None, model_name: str | None = None):
        """The Run events about ``design`` (a Design, or None + ``model_name``) go to; made and reset on first use."""
        from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.track import Run  # pylint: disable=import-outside-toplevel

        if design is not None and not hasattr(design, "instances"):  # a path or dict (loop.analyse(design_path))
            design = load_design(design)
        name = self.name or (design.name if design is not None else (model_name or None))
        if name is None:
            return self.current
        with self._lock:
            run = self.runs.get(name)
            if run is None:
                run_dir = self.root / name
                first = design if design is not None else None
                run = Run(first, run_dir, reset=self.reset, name=name)
                self.runs[name] = run
                run.log(f"tracking started ({'run ' + name if self.name else 'design ' + name})")
            elif design is not None and run.state["design"].get("hash") != _hash(design):
                run.follow(design, design.name)
            self._touch(run)
            if self.pending:
                pend, self.pending = self.pending, []
                for ev, kw in pend:
                    self.handle(ev, kw, run)
            return run

    def _touch(self, run) -> None:
        self.current = run
        try:
            tmp = self.root / (POINTER + ".tmp")
            tmp.write_text(
                json.dumps({"run": run.dir.name, "dir": str(run.dir), "time": time.time()}), encoding="utf-8"
            )
            os.replace(tmp, self.root / POINTER)
        except OSError:
            pass

    # ---- events -----------------------------------------------------------------------------------------------
    def handle(self, event: str, kw: dict, run=None) -> None:
        if self.quiet_depth and event in ("fill", "lom", "drc", "compare"):
            return
        try:
            getattr(self, f"on_{event}")(run, **kw)
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            key = f"{event}:{type(e).__name__}"
            if key not in self._warned:
                self._warned.add(key)
                target = run or self.current
                if target is not None:
                    target.log(f"tracking '{event}' failed: {type(e).__name__}: {e}", "warn")

    def on_layout(self, run, result, path):
        design = result.design
        run = run or self.run_for(design)
        if run.state["design"].get("hash") != _hash(design):
            run.follow(design, design.name)
        lengths = ", ".join(f"{n} {v:.1f} µm" for n, v in result.route_lengths().items())
        fresh = run.state["steps"][1].get("metrics", {}).get("hash") != result.hash
        self._step(run, "layout", "done", f"{design.name}: {lengths}" if lengths else design.name, hash=result.hash)
        if run._step("synthesis")["status"] == "pending":  # noqa: SLF001  (drawn directly, not synthesised)
            self._step(run, "synthesis", "skipped", "not used: the design is drawn directly")
            run.state["currentStep"] = "layout"
        if fresh:  # a live Designer redraws on every change: log only a new geometry
            run.log(f"layout written: {design.name} ({result.hash[:8]})")
        if self.snapshots:
            self._submit(f"snap:{run.dir.name}", 1.2, lambda: self._snapshot(run, design.name, Path(path)))

    def on_drc(self, run, report, design):
        run = run or (self.run_for(design) if design is not None else self.current)
        if run is None:
            return
        n_e, n_w = len(report.errors), len(report.warnings)
        n_d = len([i for i in report.issues if i.severity == "design"])
        text = f"DRC {'clean' if report.ok else 'ERRORS'}: {n_e} errors, {n_w} warnings, {n_d} PDK design warnings"
        step = run._step("layout")  # noqa: SLF001
        base = (step.get("summary") or "").split(" · DRC")[0]
        step["summary"] = f"{base} · {text}" if base else text
        step["metrics"] = {**(step.get("metrics") or {}), "drc_errors": n_e, "drc_warnings": n_w, "drc_design": n_d}
        for i in report.errors[:5]:
            run.log(f"DRC {i.rule}: {i.message}", "error")
        run.save()

    def on_fill(self, run, filled, job=None):
        from quantcore_circuits import loop  # pylint: disable=import-outside-toplevel

        run = run or self._run_of(filled)
        if run is None:
            return
        fem = filled.cmatrix is not None
        circuit, compare = loop.dashboard_circuit(filled), _fem_compare(filled) if fem else None
        cur = run.state.get("circuit") or {}
        if _keep_shown(cur, circuit):
            circuit = cur  # phase C: a sub-circuit or an estimate-only fill does not hide the FEM-filled whole chip
        old_rows = run.state.get("femCompare") or []
        if compare is None or ({r["branch"] for r in compare} < {r["branch"] for r in old_rows}):
            compare = old_rows
        run.set(
            circuit=circuit,
            cmatrix={**filled.cmatrix, "unit": "fF", "job": filled.job} if fem else run.state.get("cmatrix"),
            femCompare=compare,
        )
        if fem:
            self._step(run, "extract", "done", f"FEM values from {filled.job}: C-matrix → circuit branches")
            self._results_loaded(run, f"FEM results of {filled.job}")
        else:
            self._step(run, "extract", "done", "layout estimates (no FEM results used)")

    def on_lom(self, run, result, filled):
        from quantcore_circuits import loop  # pylint: disable=import-outside-toplevel
        from quantcore_circuits import plots as P
        from quantcore_circuits.circuit.consensus import consensus, goal  # pylint: disable=import-outside-toplevel

        design = filled.design if hasattr(filled.design, "instances") else None
        run = run or self.run_for(design, filled.model.name)
        rows = consensus({"lom": dict(result.params)}, filled.model.targets)
        # the same design simulated again on a sub-circuit (a pair's exchange coupling): keep the other rows
        key = run.dir.name
        h = _hash(design) if design is not None else "model"
        last_h, last_rows = self.lom_last.get(key, (None, {}))
        new = {r.param: r for r in rows}
        if last_h == h and len(new) < len(last_rows):  # a sub-circuit run: it only adds what the full run lacks
            merged = {**new, **last_rows}
        else:
            merged = new
        self.lom_last[key] = (h, merged)
        rows = list(merged.values())
        gl = goal(rows)
        fem = filled.cmatrix is not None
        d = result.dressed or {}
        levels = [{**lv, "group": "LOM"} for lv in d.get("levels", [])[:8]]
        run.set(targets=loop.dashboard_targets(rows), goal=gl, consensus=loop.dashboard_consensus(rows))
        if levels:
            run.plot(P.levels_spec("levels", "Dressed spectrum (LOM)", "hamiltonian", levels))
        shown = ", ".join(f"{r.param} {r.chosen:.4g}" for r in rows if r.chosen is not None)[:160]
        self._step(run, "hamiltonian", "done", f"LOM ({'FEM' if fem else 'estimates'}): {shown}")
        self._step(run, "compare", "done", gl["summary"])
        run.log(
            f"LOM ({'FEM' if fem else 'estimates'}) {_hash(design)[:8] if design is not None else ''}: {gl['summary']}"
        )
        self._lom_iteration(run, design, rows, fem)
        if design is not None and not any(h.get("kind") != "lom" for h in run.state["history"]):
            self._cards(run, design, filled, rows, gl)  # ~0.05 s: on the calling thread (KLayout is not thread-safe)
        run.save()

    def on_compare(self, run, targets, extracted, design=None):
        """The old extract/compare API: values vs targets."""
        run = run or (self.run_for(design) if design is not None else self._any_run())
        if run is None:
            return
        out, passed = [], 0
        for inst, tgt in targets.items():
            got = extracted.get(inst, {})
            for key, want in tgt.items():
                v = got.get(key, got.get(key.replace("_GHz", "_eig_GHz")))
                tol = max(abs(want) * 0.01, 1e-9)
                status = "unknown" if v is None else ("pass" if abs(v - want) <= tol else "fail")
                passed += status == "pass"
                out.append(
                    {
                        "key": f"{inst}.{key}",
                        "label": f"{inst} {key.rsplit('_', 1)[0]}",
                        "symbol": key.rsplit("_", 1)[0],
                        "unit": key.rsplit("_", 1)[1] if "_" in key else "",
                        "target": want,
                        "tol": tol,
                        "value": v,
                        "source": "extract",
                        "status": status,
                    }
                )
        run.set(
            targets=out,
            goal={
                "reached": bool(out) and passed == len(out),
                "passed": passed,
                "total": len(out),
                "summary": f"{passed} of {len(out)} targets within 1 %",
            },
        )
        self._results_loaded(run, "job results loaded")
        self._step(run, "extract", "done", "parameters extracted from the job results")
        self._step(run, "compare", "done", f"{passed} of {len(out)} targets within 1 %")

    def on_synthesis(self, run, targets, result):
        run = run or self._any_run()
        if run is None:
            self.pending.append(("synthesis", {"targets": targets, "result": result}))
            return
        r = result
        self._step(
            run,
            "synthesis",
            "done",
            f"Lj {r.get('Lj_nH', 0):.2f} nH · C_Σ {r.get('C_sigma_fF', 0):.1f} fF · "
            f"C_g {r.get('Cg_fF', 0):.2f} fF · λ/4 {r.get('resonator_length_um', 0):.0f} µm",
        )
        run.save()

    def on_optimise(self, run, index, knobs, metrics, error, tol, design):
        run = run or self.run_for(design)
        res = {k: v / tol.get(k, 1.0) for k, v in error.items()}
        obj = sum(v * v for v in res.values()) ** 0.5
        run.iteration(
            {
                "iteration": index,
                "objective": obj,
                "residuals": res,
                "knobs": dict(knobs),
                "accepted": True,
                "kind": "optimise",
            }
        )
        self._step(run, "feedback", "running", f"optimiser evaluation {index}: ‖r‖ {obj:.3g} tolerances")

    def _results_loaded(self, run, what: str) -> None:
        """Results that were solved earlier (kept / existing job) and are now read back: the Simulate step is done
        (a notebook with ``RUN_FEM = False`` never runs a solve); a running or failed step is left as it is."""
        if run._step("simulate")["status"] == "pending":  # noqa: SLF001
            self._step(run, "simulate", "done", f"{what} (solved earlier, not re-run)")

    def on_optimise_end(self, run, converged, error=None, evaluations=0, design=None):
        run = run or (self.run_for(design) if design is not None else self._any_run())
        if run is None:
            return
        if error:
            self._step(run, "feedback", "failed", f"optimiser stopped after {evaluations} evaluation(s): {error}")
        else:
            self._step(
                run, "feedback", "done",
                f"optimiser {'converged' if converged else 'stopped (not converged)'} after {evaluations} evaluation(s)",
            )

    def on_stage(self, run, step, phase, label="", detail=""):
        """A library stage (render / export): running → done / failed; nested stages of a step mark the outermost."""
        run = run or self._any_run()
        if run is None:
            return
        key = (run.dir.name, step)
        depth = self._stage_depth.get(key, 0)
        name = f"{label}: " if label else ""
        if phase == "running":
            self._stage_depth[key] = depth + 1
            if depth == 0:
                self._stage_failed.pop(key, None)
                self._step(run, step, "running", f"{name}started")
            return
        self._stage_depth[key] = max(depth - 1, 0)
        if phase == "failed":
            self._stage_failed[key] = detail or "failed"
        if depth <= 1:
            failed = self._stage_failed.pop(key, None)
            if failed:
                self._step(run, step, "failed", f"{name}{failed}")
            else:
                self._step(run, step, "done", f"{name}{detail or 'done'}")

    # ---- helpers ----------------------------------------------------------------------------------------------
    def _any_run(self):
        """The run of the latest event; a named session has one from the start (a model-only run)."""
        return self.current or (self.run_for(None) if self.name else None)

    def _run_of(self, filled):
        design = filled.design if hasattr(filled.design, "instances") else None
        return self.run_for(design, filled.model.name)

    def _step(self, run, step_id, status, summary="", **metrics):
        with _LOCK:
            self._step_locked(run, step_id, status, summary, **metrics)

    def _step_locked(self, run, step_id, status, summary="", **metrics):
        s = run._step(step_id)  # noqa: SLF001
        now = _now()
        if s["status"] != status:
            s.update(status=status, started=s.get("started") or now)
            s.pop("finished", None)
        if status == "done":
            s["finished"] = now
        s["summary"] = summary
        if metrics:
            s["metrics"] = {**(s.get("metrics") or {}), **{k: v for k, v in metrics.items()}}
        if status == "running":
            run.state["currentStep"] = step_id
        elif run.state.get("currentStep") in (None, step_id) or step_id in ("layout", "hamiltonian"):
            run.state["currentStep"] = step_id
        run.save()

    def _lom_iteration(self, run, design, rows, fem):
        key = run.dir.name
        h = _hash(design) if design is not None else "model"
        seen = self.lom_hashes.setdefault(key, [])
        designs = self.lom_designs.setdefault(key, {})
        if h not in seen:
            seen.append(h)
        designs[h] = _flat(design) if design is not None else {}
        res = {r.param: r.residual for r in rows if r.residual is not None}
        if not res:
            return
        self.lom_rows.setdefault(key, {})[h] = res
        if any(h_.get("kind") not in ("lom", None) for h_ in run.state["history"]):
            return  # feedback / optimiser rows own the table
        varying = sorted(
            {k for dd in designs.values() for k in dd if len({repr(x.get(k)) for x in designs.values()}) > 1}
        )
        label = "FEM" if fem else "LOM"
        run.state["history"] = [
            {
                "time": _now(),
                "iteration": i,
                "objective": _norm(self.lom_rows[key].get(hh, {})),
                "residuals": self.lom_rows[key].get(hh, {}),
                "knobs": {k: designs[hh][k] for k in varying if k in designs[hh]},
                "accepted": True,
                "kind": "lom",
                "label": f"{label} {hh[:6]}",
            }
            for i, hh in enumerate(seen)
            if hh in self.lom_rows[key]
        ]
        run.save()

    def _cards(self, run, design, filled, rows, gl):
        from quantcore_circuits import loop  # pylint: disable=import-outside-toplevel

        an = loop.Analysis(filled.model, filled, {"lom": {}}, rows, gl)
        loop.update_cards(run, design, an)

    def _snapshot(self, run, design_name, path):
        ident = "chip" if not self.name else f"chip-{design_name}"
        png = run.dir / "shots" / f"{ident}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        # a separate process: KLayout's python module is not thread-safe, the notebook keeps building meanwhile
        code = (
            "import sys; from quantcore_circuits.live.snapshot import snapshot; "
            "snapshot(sys.argv[1], sys.argv[2], size=(1400, 1400))"
        )
        shot = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code, str(path), str(png)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            creationflags=0x08000000 if os.name == "nt" else 0,  # CREATE_NO_WINDOW
        )
        if shot.returncode != 0 or not png.exists():
            raise RuntimeError((shot.stderr or "snapshot failed").strip().splitlines()[-1][:200])
        run.screenshot(
            png,
            "Chip" if not self.name else f"Chip — {design_name}",
            "layout",
            f"{design_name} (headless KLayout render)",
            "headless",
            ident,
        )
        shots = run.state["screenshots"]
        if len(shots) > MAX_SHOTS:
            run.state["screenshots"] = shots[-MAX_SHOTS:]
            run.save()

    # ---- worker: debounced background jobs + FEM watcher --------------------------------------------------------
    def _submit(self, key, min_interval, fn):
        with self._lock:
            due = max(time.time(), self._last_run_of.get(key, 0) + min_interval)
            self._work[key] = (due, fn)

    def flush(self, timeout: float = 30.0) -> None:
        """Wait until the background jobs (snapshots, cards) queued so far are done (scripts, tests)."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self._lock:
                if not self._work and not getattr(self, "_busy", False):
                    return
            time.sleep(0.05)

    def _loop(self):
        last_watch = 0.0
        while not self._stop.is_set():
            job = None
            with self._lock:
                now = time.time()
                for key, (due, fn) in list(self._work.items()):
                    if due <= now:
                        del self._work[key]
                        self._last_run_of[key] = now
                        self._busy = True
                        job = (key, fn)
                        break
            if job:
                try:
                    job[1]()
                except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
                    if self.current is not None and job[0] not in self._warned:
                        self._warned.add(job[0])
                        self.current.log(f"tracking '{job[0].split(':')[0]}' failed: {type(e).__name__}: {e}", "warn")
                finally:
                    self._busy = False
                continue
            if self._watch and time.time() - last_watch > 1.0:
                last_watch = time.time()
                try:
                    self._watch_jobs()
                except Exception:  # noqa: BLE001  pylint: disable=broad-except
                    pass
            self._stop.wait(0.15)

    def _watch_jobs(self):
        for run in list(self.runs.values()):
            before = {j["name"]: j["status"] for j in run.state.get("jobs") or []}
            jobs = run.refresh_jobs()
            for j in jobs:
                if before.get(j["name"], j["status"]) != j["status"]:
                    run.log(
                        f"job {j['name']}: {before[j['name']]} → {j['status']}",
                        "error" if j["status"] in ("failed", "interrupted") else "info",
                    )
            running = [j for j in jobs if j["status"] in ("solving", "rendering", "running")]  # not "interrupted"
            active = self._jobs_active.setdefault(run.dir.name, set())
            if running:
                for j in running:
                    step = "render" if j["status"] == "rendering" else "simulate"
                    p = j.get("progress") or {}
                    bits = [j["name"], j["status"]]
                    if p.get("pass") is not None:
                        bits.append(f"pass {p['pass']}" + (f"/{p['maxPasses']}" if p.get("maxPasses") else ""))
                    if p.get("elapsedS") is not None:
                        bits.append(f"{p['elapsedS']:.0f} s")
                    self._step(run, step, "running", " · ".join(bits))
                    active.add(step)
            else:
                for step in list(active):
                    solved = [j for j in jobs if j["hasResults"]]
                    failed = [j for j in jobs if j["status"] in ("failed", "render_failed")]
                    msg = f"{len(solved)} of {len(jobs)} jobs with results"
                    self._step(run, step, "failed" if failed and not solved else "done", msg)
                    active.discard(step)

    def stop(self):
        self._stop.set()
        try:  # a last look at the FEM jobs: a solve that ended within the watcher's last second shows as done
            self._watch_jobs()
        except Exception:  # noqa: BLE001  pylint: disable=broad-except  # tracking never breaks the caller
            pass


# ---- module-level helpers -------------------------------------------------------------------------------------------
from quantcore_circuits.track import _LOCK  # noqa: E402  pylint: disable=wrong-import-position


def _now() -> str:
    from quantcore_circuits.track import _now as now  # pylint: disable=import-outside-toplevel

    return now()


def _hash(design) -> str:
    from quantcore_circuits.design import design_hash  # pylint: disable=import-outside-toplevel

    return design_hash(design)


def _norm(res: dict) -> float:
    return float(sum(v * v for v in res.values()) ** 0.5)


def _flat(design) -> dict[str, float]:
    """Numeric instance parameters, junction values and route lengths of ``design`` as ``{"Q1.cross_length": 300}``."""
    d = design.to_json_dict()
    out: dict[str, float] = {}
    for n, inst in (d.get("instances") or {}).items():
        for k, v in (inst.get("params") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{n}.{k}"] = v
        for k, v in (inst.get("junction") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{n}.junction.{k}"] = v
        at = (inst.get("place") or {}).get("at")
        if at:
            out[f"{n}.x"], out[f"{n}.y"] = at[0], at[1]
    for n, r in (d.get("routes") or {}).items():
        if isinstance(r.get("length"), (int, float)):
            out[f"{n}.length"] = r["length"]
    for n, c in (d.get("couplings") or {}).items() if isinstance(d.get("couplings"), dict) else []:
        for k, v in c.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{n}.{k}"] = v
    return out


def _keep_shown(cur: dict, new: dict) -> bool:
    """Whether the dashboard keeps the circuit it shows: it has FEM values and the new one is a strict sub-circuit of
    it (a per-pair fill or a J sweep after the whole chip's subset read-back, phase C). A fill of the same or a larger
    circuit (a new revision) always replaces it."""
    if not any(str(b.get("source", "")).startswith("fem") for b in cur.get("branches", [])):
        return False
    return {b["id"] for b in new.get("branches", [])} < {b["id"] for b in cur["branches"]}


def _fem_compare(filled) -> list[dict]:
    rows = []
    for r in filled.branch_table():
        if r.get("extracted") is None or not r.get("estimate"):
            continue
        rows.append(
            {
                "branch": r["branch"],
                "nodes": list(r["nodes"]),
                "type": r["type"],
                "unit": r.get("unit", ""),
                "estimate": r["estimate"],
                "fem": r["extracted"],
                "deltaPct": 100 * (r["extracted"] - r["estimate"]) / abs(r["estimate"]),
                # the job that gave the value (subset read-back: several jobs fill one circuit)
                "job": r["source"].split(":", 1)[1] if str(r.get("source", "")).startswith("cmatrix:") else r["source"],
            }
        )
    return rows


@contextlib.contextmanager
def quiet(session):
    session.quiet_depth += 1
    try:
        yield
    finally:
        session.quiet_depth -= 1
