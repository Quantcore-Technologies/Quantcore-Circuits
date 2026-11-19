"""Shared helpers for the amplifier notebooks (``examples/designs/amplifiers``): PDK facts, value tables, plots.

The physics lives in :mod:`quantcore_circuits.analysis.amplifiers`; the cells in
:mod:`quantcore_circuits.layouts.others.amplifiers`. These helpers only format.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless runs; notebooks show the saved PNG
import matplotlib.pyplot as plt  # noqa: E402
from IPython.display import Image, Markdown, display  # noqa: E402

COLORS = ["#2a6fdb", "#e0672f", "#2e9e5b", "#8a4fc9", "#777777"]


def pdk_facts_md(pdk) -> str:
    """The PDK facts an amplifier chip uses, as a table (template step 2)."""
    from quantcore_circuits.circuit.kinetic import sheet_inductance_pH_sq  # pylint: disable=C0415

    s, j, f = pdk.stack, pdk.junction, pdk.frame
    rows = [
        ("substrate", f"{s.substrate_material} {s.substrate_height:g} µm, εr {s.substrate_permittivity:g}"),
        (
            "film",
            f"Nb {s.metal_thickness_um * 1e3:g} nm, λ_L {s.london_penetration_depth_um * 1e3:g} nm → "
            f"L_s {sheet_inductance_pH_sq(pdk):.3f} pH/□ (kinetic, in every CPW / wire formula)",
        ),
        (
            "junction rule",
            f"{j.material}, Δ {j.gap_meV:g} meV, J_c {j.jc_uA_per_um2:.3f} µA/µm², R_n window "
            f"{j.rn_target_kohm[0]:g}–{j.rn_target_kohm[1]:g} kΩ, fingers {j.finger_range_um[0]:g}–"
            f"{j.finger_range_um[1]:g} µm",
        ),
        (
            "frame",
            f"die {pdk.die_size[0] / 1e3:g} × {pdk.die_size[1] / 1e3:g} mm standard, margin {f.margin:g} µm, "
            f"marker areas {f.marker_area:g} µm, brand {pdk.brand}",
        ),
        ("pad rule", f'outer etch {f.pad_edge:g} µm (one dicing-marker width) from the die edge (`edge="auto"`)'),
        (
            "cheese",
            f"PDK band {pdk.cheese.rows} rows of {pdk.cheese.size:g} µm squares, {pdk.cheese.gap:g} µm gap, "
            "around the 3/0 keep-outs (unless the original has its own)",
        ),
        ("3/0 keep-out", f"routes + {pdk.keepout.route_margin:g} µm, components + {pdk.keepout.component_margin:g} µm"),
    ]
    return "| PDK | value |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in rows)


def table_md(header: list[str], rows: list[list]) -> str:
    def fmt(v):
        if isinstance(v, float):
            return f"{v:.4g}"
        return "–" if v is None else str(v)

    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def show_md(text: str) -> None:
    display(Markdown(text))


def plot(
    png,
    series: list[tuple],
    xlabel: str,
    ylabel: str,
    title: str = "",
    hline=None,
    vline=None,
    ylim=None,
    size=(7.0, 4.0),
    width: int = 640,
) -> Path:
    """Line plot of ``series`` = [(x, y, label), ...] (or (x, y, label, style)), saved to ``png`` and shown."""
    fig, ax = plt.subplots(figsize=size, dpi=130)
    for i, s in enumerate(series):
        x, y, label = s[:3]
        style = s[3] if len(s) > 3 else "-"
        ax.plot(x, y, style, color=COLORS[i % len(COLORS)], lw=1.6, label=label)
    if hline is not None:
        ax.axhline(hline, color="#999999", lw=0.8, ls="--")
    if vline is not None:
        ax.axvline(vline, color="#999999", lw=0.8, ls="--")
    if ylim:
        ax.set_ylim(*ylim)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title, fontsize=10)
    ax.grid(alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    if any(s[2] for s in series):
        ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    png = Path(png)
    fig.savefig(png)
    plt.close(fig)
    display(Image(filename=str(png), width=width))
    return png


def lom_values(lb, prefix: str) -> dict:
    """Branch values of the LOM circuit whose names start with ``prefix`` → {name: value dict}."""
    return {n: dict(b.value or {}) for n, b in lb.model.branches.items() if n.startswith(prefix)}


def c_fF(value: dict) -> float:
    return float(value.get("C_fF", value.get("estimate")))


def lom_sparams(model, f, ports: list[str], z0: float = 50.0):
    """Linear AC of a LOM circuit (``lb.model``): S-parameters between the circuit nodes ``ports`` (their 50 Ω
    ``Port_*`` resistors become the reference ports). C, L, R branches as given; a junction is its linear L_J ∥ C_J
    (small signal, no pump). Returns S with shape (len(f), n_ports, n_ports)."""
    import numpy as np  # pylint: disable=import-outside-toplevel

    gnd = model.ground
    nodes = [n for n in model.nodes if n != gnd]
    idx = {n: i for i, n in enumerate(nodes)}
    w = 2 * np.pi * np.asarray(f, dtype=float)
    y = np.zeros((len(w), len(nodes), len(nodes)), dtype=complex)

    def stamp(a, b, adm):
        for n in (a, b):
            if n != gnd:
                y[:, idx[n], idx[n]] += adm
        if a != gnd and b != gnd:
            y[:, idx[a], idx[b]] -= adm
            y[:, idx[b], idx[a]] -= adm

    for name, br in model.branches.items():
        v, (a, b) = dict(br.value or {}), br.nodes
        if br.type == "C":
            stamp(a, b, 1j * w * c_fF(v) * 1e-15)
        elif br.type == "L" and v.get("L_nH"):
            stamp(a, b, 1 / (1j * w * v["L_nH"] * 1e-9))
        elif br.type in ("JJ", "SQUID") and v.get("Lj_nH"):
            stamp(a, b, 1 / (1j * w * v["Lj_nH"] * 1e-9) + 1j * w * (v.get("Cj_fF") or 0.0) * 1e-15)
        elif br.type == "R" and not (name.startswith("Port_") and ({a, b} & set(ports))):
            stamp(a, b, 1 / v.get("R_ohm", 50.0))
    p = [idx[n] for n in ports]
    z = np.linalg.inv(y)[:, p][:, :, p]
    eye = np.eye(len(p))
    return (z - z0 * eye) @ np.linalg.inv(z + z0 * eye)


__all__ = [
    "COLORS",
    "Image",
    "Markdown",
    "c_fF",
    "display",
    "lom_sparams",
    "lom_values",
    "pdk_facts_md",
    "plot",
    "show_md",
    "table_md",
]


# ---- v2 design notebooks (nb-v2-B, batch B4, 2026-11-19): kept FEM results in amplifier terms -----------------------
# Additive: nothing above changed (the .v1 notebooks import the names above). These only read files a solve left
# (``<job>/results/results.json``, the driven job's Touchstone file); nothing here solves, builds or simulates.
def _results(folder) -> dict:
    import json  # pylint: disable=import-outside-toplevel

    if not folder:
        return {}
    path = Path(folder) / "results" / "results.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def cmatrix_to_ground(keep) -> dict:
    """``{net: capacitance to ground (fF)}`` of a kept Q3D job: the row sums of its Maxwell C-matrix (the off-diagonal
    entries are minus the mutual capacitances, so a row sums to what the net sees of ground). ``{}`` without
    results."""
    cm = _results(keep).get("cmatrix") or {}
    return {n: float(sum(row)) for n, row in zip(cm.get("labels") or [], cm.get("matrix") or [])}


def cmatrix_between(keep, a: str, b: str) -> float | None:
    """The mutual capacitance (fF, positive) between nets ``a`` and ``b`` of a kept Q3D job; None if either is not a
    net of it (or there are no results)."""
    cm = _results(keep).get("cmatrix") or {}
    labels = list(cm.get("labels") or [])
    if a not in labels or b not in labels:
        return None
    return -float(cm["matrix"][labels.index(a)][labels.index(b)])


def jpa_mode(keep, f_guess: float | None, q_min: float = 10.0) -> dict:
    """The JPA's mode in a kept eigenmode/EPR job: the solved mode nearest ``f_guess`` (GHz, e.g. the LOM's f0) with
    Q > ``q_min`` (a JPA is strongly coupled, Q_ext ≈ 50–300: below the Q > 100 the qubit-chip helpers ask for).

    Returns ``{"mode", "f_GHz", "Q", "Q_ext", "kappa_MHz"}`` — κ = f / Q_ext, Q_ext the mode Q with pyEPR's bulk
    dielectric Q removed when the job has it (the 50 Ω-terminated lines leaving the box are then the only loss) —
    plus pyEPR's ``"f_epr_GHz"`` (dressed), ``"kerr_MHz"`` (self-Kerr χ_mm) and ``"p_J"`` (the largest junction
    participation) when the job has them; ``{}`` without results."""
    res = _results(keep)
    modes = res.get("eigenmodes") or []
    cand = [i for i, m in enumerate(modes) if (m.get("Q") or 0) > q_min]
    if not cand or f_guess is None:
        return {}
    i = min(cand, key=lambda j: abs(modes[j]["f_GHz"] - f_guess))
    m, epr = modes[i], res.get("epr") or {}
    q, qds = float(m["Q"]), epr.get("Q_dielectric") or []
    qd = qds[i] if i < len(qds) else None
    q_ext = 1 / (1 / q - 1 / qd) if qd and 1 / q > 1 / qd else q
    out = {"mode": m.get("mode", i + 1), "f_GHz": float(m["f_GHz"]), "Q": q, "Q_ext": q_ext,
           "kappa_MHz": 1e3 * float(m["f_GHz"]) / q_ext}
    if i < len(epr.get("f_GHz") or []):
        out["f_epr_GHz"] = float(epr["f_GHz"][i])
    if i < len(epr.get("chi_MHz") or []):
        out["kerr_MHz"] = float(epr["chi_MHz"][i][i])
    if i < len(epr.get("p_mj") or []):
        out["p_J"] = float(max(epr["p_mj"][i]))
    return out


def reflection_values(port: str, *folders) -> dict:
    """f0 and κ of the reflection resonance seen at ``port`` (the name of a line the box cuts, e.g. ``"L_SIG"``) of a
    solved driven job: S_pp of the Touchstone file (``*_SMatrix*.s<n>p``) the solve left in one of ``folders`` (the
    kept copy, the job folder), its port order from ``results.json``; ``analysis.amplifiers.resonance`` (steepest
    phase, κ = 4 / max|dφ/df|). The kept copy in ``fem/`` holds ``results.json`` only and a new export empties the
    job folder, so the trace is there in the run that solved it. ``{}`` when the file or the port is not there."""
    from quantcore_circuits.analysis.amplifiers import resonance  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.analysis.results import parse_touchstone  # pylint: disable=import-outside-toplevel

    names, trace = None, None
    for folder in (f for f in folders if f):
        sp = _results(folder).get("sparams") or {}
        if names is None and sp.get("ports"):
            names = list(sp["ports"])
        if trace is None:
            trace = next(iter(sorted(Path(folder).glob("*_SMatrix*.s*p"))), None)
    if not names or trace is None or port not in names:
        return {}
    f_GHz, s, _ = parse_touchstone(trace)
    k = names.index(port)
    f0, kappa = resonance(f_GHz * 1e9, s[:, k, k])
    return {"f_GHz": f0 / 1e9, "kappa_MHz": kappa / 1e6, "file": trace.name}


__all__ += ["cmatrix_between", "cmatrix_to_ground", "jpa_mode", "reflection_values"]
