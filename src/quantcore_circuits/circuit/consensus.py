"""Consensus across estimators (M10): per parameter the estimator values, spread, chosen value, residual, pass/fail.

Selection policy (configurable, first available wins): pyEPR for χ/α when eigenmode data exists, SQcircuit for qubit
spectra, QuCat for κ and χ, Metal LOM as the C-matrix reference. A parameter whose relative spread exceeds its
``spread_tol`` is *flagged*: the estimators disagree, which is a modelling problem rather than a design problem.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

POLICY: dict[str, list[str]] = {
    "f_q_GHz": ["pyepr", "sqcircuit", "scqubits", "qucat", "metal_lom"],
    "alpha_MHz": ["pyepr", "sqcircuit", "scqubits", "qucat", "metal_lom"],
    "chi_MHz": ["pyepr", "qucat", "sqcircuit", "scqubits", "metal_lom", "qutip"],
    # pyEPR values exist only for eigenmode jobs: the FEM resonator frequency and the eigenmode κ (f/Q with the
    # feedline terminated in 50 Ω) then win over the λ/4 + coupled-line LOM estimates
    "f_GHz": ["pyepr", "qucat", "sqcircuit", "scqubits", "metal_lom"],
    "g_MHz": ["metal_lom", "scqubits"],
    "kappa_MHz": ["pyepr", "qucat", "metal_lom"],
    "EJ_GHz": ["metal_lom", "sqcircuit"],
    "EC_GHz": ["metal_lom", "sqcircuit"],
}
SPREAD_TOL = {"f_q_GHz": 0.01, "alpha_MHz": 0.05, "chi_MHz": 0.15, "f_GHz": 0.005, "g_MHz": 0.10, "kappa_MHz": 0.2}
LABELS = {
    "f_q_GHz": ("f_q", "GHz", "qubit frequency"),
    "alpha_MHz": ("α", "MHz", "anharmonicity"),
    "chi_MHz": ("χ", "MHz", "dispersive shift"),
    "f_GHz": ("f_r", "GHz", "resonator frequency"),
    "g_MHz": ("g", "MHz", "coupling"),
    "kappa_MHz": ("κ", "MHz", "linewidth"),
    "EJ_GHz": ("E_J", "GHz", "Josephson energy"),
    "EC_GHz": ("E_C", "GHz", "charging energy"),
}


@dataclass
class Row:
    param: str  # "Q1.f_q_GHz"
    quantity: str  # "f_q_GHz"
    symbol: str
    unit: str
    values: dict[str, float]
    chosen: float | None
    chosen_by: str | None
    spread_rel: float | None
    flagged: bool
    target: float | None = None
    tol: float | None = None
    residual: float | None = None  # (chosen − target) / tol
    status: str = "unknown"  # pass | fail | unknown
    notes: list[str] = field(default_factory=list)


def consensus(estimates: dict[str, dict], targets: dict | None = None, policy=None, spread_tol=None) -> list[Row]:
    """``estimates``: estimator → ParamSet; ``targets``: param → {"value", "tol"} (``CircuitModel.targets`` form)."""
    policy = {**POLICY, **(policy or {})}
    spread_tol = {**SPREAD_TOL, **(spread_tol or {})}
    targets = targets or {}
    params = sorted({k for ps in estimates.values() if "error" not in ps for k in ps})
    rows = []
    for param in params:
        quantity = param.split(".", 1)[1] if "." in param else param
        if quantity not in LABELS:
            continue
        values = {n: ps[param] for n, ps in estimates.items() if "error" not in ps and param in ps}
        order = policy.get(quantity, list(values))
        chosen_by = next((n for n in order if n in values), next(iter(values), None))
        chosen = values.get(chosen_by)
        spread = None
        if len(values) > 1:
            vs = list(values.values())
            mean = sum(vs) / len(vs)
            spread = (max(vs) - min(vs)) / abs(mean) if mean else None
        symbol, unit, _ = LABELS[quantity]
        row = Row(
            param,
            quantity,
            symbol,
            unit,
            values,
            chosen,
            chosen_by,
            spread,
            bool(spread is not None and spread > spread_tol.get(quantity, 0.05)),
        )
        t = targets.get(param)
        if t is not None:
            tv = t.value if hasattr(t, "value") else t.get("value")
            tt = t.tol if hasattr(t, "tol") else t.get("tol")
            row.target, row.tol = tv, tt
            if tv is not None and tt and chosen is not None:
                row.residual = (chosen - tv) / tt
                row.status = "pass" if abs(row.residual) <= 1 else "fail"
        rows.append(row)
    return rows


def flag_near_resonance(rows: list[Row], pairs, factor: float = 5.0) -> list[str]:
    """Flag qubit–resonator pairs with |f_q − f_r| < ``factor``·g: the modes hybridise, so dispersive quantities and
    the estimators' mode labels disagree by construction (not an estimator bug). ``pairs``: objects with ``qubit``
    and ``resonator`` names (``FilledCircuit.pairs``). Adds a note and ``flagged`` to the f_q, f_r, χ and g rows and
    returns the notes."""
    by = {r.param: r for r in rows}
    out = []
    for p in pairs:
        fq, fr, g = by.get(f"{p.qubit}.f_q_GHz"), by.get(f"{p.resonator}.f_GHz"), by.get(f"{p.resonator}.g_MHz")
        if not (fq and fr and g) or None in (fq.chosen, fr.chosen, g.chosen):
            continue
        delta_mhz = abs(fq.chosen - fr.chosen) * 1e3
        if delta_mhz < factor * abs(g.chosen):
            note = (
                f"{p.qubit}–{p.resonator}: |Δ| = {delta_mhz:.0f} MHz < {factor:g} g (g = {g.chosen:.0f} MHz) — modes "
                "hybridise; dispersive values and estimator mode labels are unreliable"
            )
            out.append(note)
            for key in (f"{p.qubit}.f_q_GHz", f"{p.resonator}.f_GHz", f"{p.resonator}.chi_MHz", f"{p.resonator}.g_MHz"):
                if key in by:
                    by[key].notes.append(note)
                    by[key].flagged = True
    return out


def goal(rows: list[Row]) -> dict:
    with_target = [r for r in rows if r.target is not None]
    passed = sum(r.status == "pass" for r in with_target)
    return {
        "reached": bool(with_target) and passed == len(with_target),
        "passed": passed,
        "total": len(with_target),
        "summary": f"{passed} of {len(with_target)} targets within tolerance",
    }


def report_markdown(rows: list[Row], title: str = "Consensus") -> str:
    names = sorted({n for r in rows for n in r.values})
    head = "| parameter | " + " | ".join(names) + " | chosen | spread | target | residual/tol | status |"
    lines = [f"# {title}", "", head, "|" + "---|" * (len(names) + 6)]
    for r in rows:
        vals = " | ".join(f"{r.values[n]:.4g}" if n in r.values else "–" for n in names)
        spread = f"{100 * r.spread_rel:.2f} %" if r.spread_rel is not None else "–"
        flag = " ⚑" if r.flagged else ""
        tgt = f"{r.target:g} ± {r.tol:g}" if r.target is not None else "–"
        res = f"{r.residual:+.2f}" if r.residual is not None else "–"
        lines.append(
            f"| {r.param} ({r.unit}) | {vals} | **{r.chosen:.4g}** ({r.chosen_by}) | {spread}{flag} | {tgt} | {res} |"
            f" {r.status} |"
        )
    return "\n".join(lines) + "\n"


def save(rows: list[Row], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in rows], indent=2) + "\n", encoding="utf-8")
    return path
