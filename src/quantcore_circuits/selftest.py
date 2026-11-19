"""``qcc selftest``: does this install work?

pip cannot run tests while it installs, so this is the check to run right after an install (the install scripts in
``scripts/install_sim_pc.*`` call it). One line per check, ``ok`` / ``FAIL`` / ``skip``; the exit code is non-zero when
any check failed. It never starts AEDT and runs no solver.

Checks: the imports of the core and of every extra (with versions), then a small Q1 + R1 chip shipped as package data
(``data/selftest_q1_r1.json``): build, DRC, the layout LOM netlist, a LOM simulation (needs the ``analysis`` extra),
one simulation job exported into a temporary folder, and whether ``ansysedt`` is found.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.metadata as md
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DESIGN_RESOURCE = Path(__file__).parent / "data" / "selftest_q1_r1.json"

# group -> [(label, import name, distribution name)]
IMPORTS: dict[str, list[tuple[str, str, str]]] = {
    "core": [
        ("klayout", "klayout.db", "klayout"),
        ("kqcircuits", "kqcircuits", "kqcircuits"),
        ("numpy", "numpy", "numpy"),
        ("scipy", "scipy", "scipy"),
        ("networkx", "networkx", "networkx"),
        ("pydantic", "pydantic", "pydantic"),
        ("typer", "typer", "typer"),
    ],
    "analysis": [
        ("quantum-metal", "qiskit_metal", "quantum-metal"),
        ("pyEPR", "pyEPR", "pyEPR-quantum"),
        ("scqubits", "scqubits", "scqubits"),
        ("qutip", "qutip", "qutip"),
        ("SQcircuit", "SQcircuit", "SQcircuit"),
        ("qucat", "qucat", "qucat"),
    ],
    "sim": [
        ("gmsh", "gmsh", "gmsh"),
        ("pyaedt", "ansys.aedt.core", "pyaedt"),
        ("scikit-rf", "skrf", "scikit-rf"),
    ],
    "notebook": [
        ("ipykernel", "ipykernel", "ipykernel"),
        ("nbclient", "nbclient", "nbclient"),
        ("matplotlib", "matplotlib", "matplotlib"),
    ],
}
OPTIONAL = [("torch", "torch", "torch")]  # surrogates only: reported, never a failure

OK, FAIL, SKIP = "ok", "FAIL", "skip"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    seconds: float = 0.0

    def line(self) -> str:
        tail = f"  ({self.seconds:.1f} s)" if self.seconds >= 0.5 else ""
        return f"[{self.status:>4}] {self.name:<30} {self.detail}{tail}".rstrip()


def _version(dist: str, module) -> str:
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return str(getattr(module, "__version__", "?"))


def _import_check(label: str, mod: str, dist: str, required: bool) -> Check:
    t0 = time.time()
    try:
        module = importlib.import_module(mod)
    except Exception as exc:  # a broken install can raise anything (DLL load, version clash)
        status = FAIL if required else SKIP
        return Check(f"import {label}", status, f"{type(exc).__name__}: {exc}"[:200], time.time() - t0)
    return Check(f"import {label}", OK, _version(dist, module), time.time() - t0)


def find_ansysedt() -> tuple[str, str]:
    """(status, detail): whether ``ansysedt`` is found. Looks for the file only; AEDT is never started."""
    try:
        from quantcore_circuits.sim_tools.ansys import aedt_version, find_ansys_executable

        exe = find_ansys_executable()
    except Exception as exc:
        return SKIP, f"lookup failed: {type(exc).__name__}: {exc}"
    if exe is None:
        return SKIP, "not found (fine for layout / LOM; install AEDT 2024 R1+ or set QCC_ANSYS_EXECUTABLE to solve)"
    if not Path(exe).is_file():
        return SKIP, f"QCC_ANSYS_EXECUTABLE points to a missing file: {exe}"
    return OK, f"{exe} (v{aedt_version(exe)})"


def _step(name: str, fn: Callable[[], str]) -> Check:
    t0 = time.time()
    try:
        return Check(name, OK, fn() or "", time.time() - t0)
    except Exception as exc:
        return Check(name, FAIL, f"{type(exc).__name__}: {exc}"[:300], time.time() - t0)


def run_checks(allow_missing: bool = False, emit: Callable[[Check], None] | None = None) -> list[Check]:
    """Run all checks in order; ``emit`` is called with each as it finishes."""
    results: list[Check] = []

    def add(c: Check) -> Check:
        results.append(c)
        if emit:
            emit(c)
        return c

    add(Check("python", OK if sys.version_info >= (3, 11) else FAIL, f"{sys.version.split()[0]} ({sys.platform})"))
    with contextlib.suppress(Exception):
        from quantcore_circuits import __version__

        add(Check("quantcore-circuits", OK, __version__))
    groups_ok: dict[str, bool] = {}
    for group, items in IMPORTS.items():
        res = [add(_import_check(*item, required=(group == "core" or not allow_missing))) for item in items]
        groups_ok[group] = all(r.status == OK for r in res)
    for item in OPTIONAL:
        add(_import_check(*item, required=False))

    if not groups_ok["core"]:
        add(Check("chip checks", SKIP, "core imports failed"))
        add(Check("ansysedt", *find_ansysedt()))
        return results

    tmp = Path(tempfile.mkdtemp(prefix="qcc_selftest_"))
    cwd = os.getcwd()
    state: dict = {}
    try:
        os.chdir(tmp)
        design = tmp / "selftest_q1_r1.json"
        if not DESIGN_RESOURCE.is_file():
            add(Check("design file", FAIL, f"missing package data {DESIGN_RESOURCE}"))
            return results
        shutil.copy2(DESIGN_RESOURCE, design)
        add(Check("design file", OK, "Q1 + R1 chip, package data"))

        def build() -> str:
            from quantcore_circuits.assembly import build as build_design

            state["built"] = build_design(design)
            return f"{design.stem} built"

        def drc() -> str:
            from quantcore_circuits.assembly.drc import check

            report = check(design, netlist=True)
            if not report.ok:
                why = "; ".join(str(i.message) for i in report.errors[:2])
                raise RuntimeError(f"{len(report.errors)} DRC error(s): {why}")
            return f"clean, {len(report.warnings)} warning(s)"

        def netlist() -> str:
            from quantcore_circuits.circuit.derive import circuit_from_design

            model = circuit_from_design(design, "chip")
            state["model"] = model
            return f"{len(model.nodes)} nodes, {len(model.branches)} branches"

        def lom() -> str:
            from quantcore_circuits.circuit.fill import fill
            from quantcore_circuits.lom.simulate import simulate

            res = simulate(fill(state["model"], design))
            if not res.modes:
                raise RuntimeError("no modes")
            return ", ".join(f"{m.label} {m.f_GHz:.3f} GHz" for m in res.modes[:3])

        def job() -> str:
            from quantcore_circuits.sim_tools import build_simulation, export_job

            out = tmp / "job"
            export_job(build_simulation(design, "Q1R1", "q3d_cmatrix"), out, overwrite=True)
            files = [p for p in out.rglob("*") if p.is_file()]
            if not files:
                raise RuntimeError("the job folder is empty")
            return f"{len(files)} files, no solver started"

        add(_step("build Q1 + R1 chip", build))
        if results[-1].status == OK:
            add(_step("DRC", drc))
            add(_step("LOM netlist", netlist))
            if results[-1].status != OK:
                add(Check("LOM simulation", SKIP, "no netlist"))
            elif not groups_ok["analysis"]:
                add(Check("LOM simulation", SKIP, "needs the analysis extra"))
            else:
                add(_step("LOM simulation", lom))
            add(_step("export sim job (q3d_cmatrix)", job))
        else:
            add(Check("DRC / LOM / job", SKIP, "the build failed"))
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    add(Check("ansysedt", *find_ansysedt()))
    return results


def main(allow_missing: bool = False, as_json: bool = False) -> int:
    results = run_checks(allow_missing, emit=None if as_json else lambda c: print(c.line(), flush=True))
    failed = [c for c in results if c.status == FAIL]
    if as_json:
        print(json.dumps([c.__dict__ for c in results], indent=1))
    else:
        summary = f"selftest: {len(results) - len(failed)} of {len(results)} checks ok"
        print(summary + (f", {len(failed)} FAILED" if failed else ""))
    return 1 if failed else 0
