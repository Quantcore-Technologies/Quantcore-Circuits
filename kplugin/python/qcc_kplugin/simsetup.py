"""What Simulate runs: the analysis for a selection, and the last run's convergence.

Plain Python (no pya), unit-tested outside KLayout; the dialog is in ``flow.py``. KLayout is the quick-prototyping
route: Q3D capacitance and HFSS eigenmode only (driven / full-wave S-parameter runs are for scripts). The dialog's
solver settings start at the library's fast values (:data:`FAST`) and can be changed; or change the setup in AEDT,
solve there and read the result back with Import results (the job folder, after ``scripts/qcc_collect.py`` in AEDT).

* **Analysis** (:func:`recommend`): a selection with a resonator, a feedline or a pad is an HFSS **eigenmode** run of
  exactly what is selected (``qcc sim … -a hfss_eigenmode``: the library adds the routes joining the parts and a
  line's end pads; junctions are lumped L‖C ports, lines leaving the box end in 50 Ω) → f, Q, κ, χ. Qubits alone (or
  with couplers / capacitors) are a **Q3D capacitance** run: islands and couplers as nets, the resonators cut to a
  short stub port → the C matrix the LOM uses. The user can pick the other one.
* **Convergence** (:func:`last_feedback`): after a solve, and after Import results, the library writes
  ``build/<name>/convergence.json`` (passes, last Δ, target, converged); the dialog shows it.
"""

from __future__ import annotations

import json
from pathlib import Path

Q3D, EIGEN = "q3d_cmatrix", "hfss_eigenmode"
ANALYSES = (Q3D, EIGEN)
# Capacitance-only analyses: no lumped junction, so no L_J needed (a copy of the library's
# ``sim_tools.builder.CAPACITANCE_ANALYSES``, checked by a test). The others (eigenmode, EPR, driven) need it.
CAPACITANCE_ANALYSES = frozenset({"q3d_cmatrix", "elmer_cap", "palace_cap"})
WIDE_CATEGORIES = ("resonator", "launcher", "waveguide", "termination")


def recommend(names, data: dict, categories: dict) -> tuple[str, str]:
    """``(analysis, why)`` for the selected ``names`` (instances and routes; ``data`` = the sidecar, ``categories`` =
    component ref → class)."""
    instances, routes = (data or {}).get("instances", {}), (data or {}).get("routes", {})
    lines = [n for n in names if n in routes]
    wide = [n for n in names if n in instances and categories.get(instances[n].get("cell", "")) in WIDE_CATEGORIES]
    qubits = [n for n in names if n in instances and categories.get(instances[n].get("cell", "")) == "qubit"]
    if lines or wide:
        what = ", ".join((lines + wide)[:4])
        return EIGEN, (f"eigenmode: the selection has lines / resonators / pads ({what}); everything selected is "
                       "rendered, junctions as lumped L‖C, the pads and cut lines as 50 Ω ports")
    if qubits:
        return Q3D, (f"Q3D capacitance: qubits only ({', '.join(qubits[:4])}); their islands and couplers become "
                     "nets, the resonators are cut to a short stub port")
    return Q3D, "Q3D capacitance: the selected parts' conductors become nets"


def missing_junctions(names, data: dict, categories: dict, design: dict) -> list[str]:
    """Selected qubits without an L_J for the eigenmode / driven lumped port. The rule is the library's: the build
    sidecar's ``instances.<name>.junction`` (``Lj_eff_nH`` None, or an ``error`` at Φ = ½ with d = 0) says it, which
    counts a drawn trilayer junction's PDK value. A sidecar without that entry (an older build) falls back to the
    design's own ``junction.Lj_nH``."""
    out = []
    instances = (data or {}).get("instances", {})
    for n in names:
        if n not in instances:
            continue
        info = instances[n].get("junction")
        if isinstance(info, dict) and "kind" in info:  # any component the library gives a junction
            if info.get("Lj_eff_nH") is None or info.get("error"):
                out.append(n)
            continue
        if categories.get(instances[n].get("cell", "")) == "qubit":
            j = (design.get("instances", {}).get(n) or {}).get("junction") or {}
            if not j.get("Lj_nH"):
                out.append(n)
    return out


def missing_text(names, data: dict, extra: dict | None = None) -> str:
    """The Simulate dialog's warning for ``names`` without an L_J (``extra``: the library's own messages by name,
    e.g. ``qcc design junctions``): which, why, and where to set the value. "" for none."""
    if not names:
        return ""
    parts = []
    for n in names:
        info = (((data or {}).get("instances") or {}).get(n) or {}).get("junction") or {}
        parts.append((extra or {}).get(n) or info.get("error")
                     or f"{n}: no junction L_J (no design value and no drawn trilayer junction)")
    return ("; ".join(parts) + ". An eigenmode / driven run needs it for the lumped junction: set it in Edit selected "
            "component ▸ Junction (L_J, or I_c, or R_n).")


def run_dir(design_path, name: str) -> Path:
    """``<design folder>/build/<name>`` (guiflow.run_dir)."""
    return Path(design_path).resolve().parent / "build" / name


def last_feedback(design_path, name: str, analysis: str) -> dict | None:
    """The last solve's / import's convergence for ``analysis`` (``convergence.json``), or None."""
    try:
        data = json.loads((run_dir(design_path, name) / "convergence.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fb = data.get(analysis)
    if fb is None and analysis == EIGEN:
        fb = data.get("eigenmode_epr")
    return fb


# ---- solver settings in the dialog: the fast values, editable --------------------------------------------------------
# copies of quantcore_circuits.sim_tools.export FAST_SETTINGS / FAST_MESH_SEED / FAST_ISLAND_SEED (checked by
# tests/test_kplugin_sim.py); "minimum_passes" is passed but not shown
FAST = {
    Q3D: {"percent_error": 2.0, "maximum_passes": 8, "minimum_converged_passes": 1},
    EIGEN: {"n_modes": 2, "min_frequency": 3.0, "max_delta_f": 1.0, "maximum_passes": 3,
            "minimum_converged_passes": 1, "percent_refinement": 30, "gap_seed": 40.0, "island_seed": 10.0},
}
LABELS = {
    "percent_error": "Convergence: ΔC per pass %",
    "maximum_passes": "Maximum adaptive passes",
    "minimum_converged_passes": "Converged passes in a row",
    "n_modes": "Eigenmodes to find",
    "min_frequency": "Lowest mode frequency GHz",
    "max_delta_f": "Convergence: Δf per pass %",
    "percent_refinement": "Mesh refinement per pass %",
    "gap_seed": "Mesh seed on the CPW gaps µm (empty = none)",
    "island_seed": "Mesh seed on the junction islands µm (empty = none)",
}
_INT_KEYS = ("maximum_passes", "minimum_converged_passes", "n_modes", "percent_refinement")
_OPTIONAL = ("gap_seed", "island_seed")


def settings_for(analysis: str, saved: dict | None = None) -> dict:
    """The values the dialog shows: the fast defaults, with the user's last values for ``analysis`` on top."""
    return {**FAST.get(analysis, {}), **{k: v for k, v in (saved or {}).items() if k in FAST.get(analysis, {})}}


def parse_settings(analysis: str, texts: dict) -> dict:
    """The dialog's fields → numbers (mesh seeds may be empty = none); raises ``ValueError`` naming the field."""
    out = {}
    for k, text in texts.items():
        text = (text or "").strip()
        if not text:
            if k in _OPTIONAL:
                out[k] = None
                continue
            raise ValueError(f"{LABELS.get(k, k)}: empty")
        try:
            out[k] = int(text) if k in _INT_KEYS else float(text)
        except ValueError as e:
            raise ValueError(f"{LABELS.get(k, k)}: {text!r} is not a number") from e
        if out[k] <= 0:
            raise ValueError(f"{LABELS.get(k, k)}: must be positive")
    return out


def cli_args(analysis: str, settings: dict) -> list[str]:
    """``qcc sim auto / subset`` arguments: every value explicit on top of the analysis defaults (``--full``), so what
    the dialog shows is what runs."""
    out = ["--full", "--set", "minimum_passes=1"]
    for k, v in settings_for(analysis, settings).items():
        if v is None or v == "":
            continue
        out += ["--set", f"{k}={int(v) if k in _INT_KEYS else float(v)}"]
    return out
