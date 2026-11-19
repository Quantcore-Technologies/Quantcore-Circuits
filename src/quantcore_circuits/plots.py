"""Plot helpers following the project plot style (thesis style), plus PlotSpec builders shared with the dashboard.

Style: the Quantcore palette, inward ticks with minor ticks on all sides
(:func:`thesis_axes`), serif LaTeX text when a TeX install works (checked once in a subprocess, cached), PDF fonts
embedded. Sizes: figure width = fraction of \\textwidth × 6.0 in, so the
matplotlib font size is the printed size; pick a layout from :data:`FIGSIZES` and its font tier with
:func:`figure`.

Data is passed around as *PlotSpecs* (``reviewer/contract/state.ts``): the same dict is drawn by the React dashboard
and by :func:`plot_spec` here. Builders: :func:`xy_spec`, :func:`bar_spec`, :func:`levels_spec`, :func:`heatmap_spec`.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

COLORS = ["#185adb", "#f9813a", "#da0037", "#206a5d", "#444444", "#c4fb6d", "#e84a5f", "#3edbf0", "#ff847c", "#ffc947"]

TIERS = {
    1: {
        "font.size": 12,
        "axes.labelsize": 12,
        "axes.titlesize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
    },
    2: {
        "font.size": 11,
        "axes.labelsize": 11,
        "axes.titlesize": 11,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 10,
    },
    3: {
        "font.size": 10,
        "axes.labelsize": 10,
        "axes.titlesize": 10,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 9,
    },
    4: {
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.titlesize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
    },
}

# (figsize inches, font tier, LaTeX width) — plot size tables A and B
FIGSIZES = {
    "single": ((6.0, 4.0), 1, r"\textwidth"),
    "wide": ((6.0, 2.0), 1, r"\textwidth"),
    "timetrace": ((6.0, 2.25), 1, r"\textwidth"),
    "square_big": ((4.5, 4.5), 1, r"0.75\textwidth"),
    "square_medium": ((3.6, 3.6), 1, r"0.6\textwidth"),
    "two": ((6.0, 2.5), 2, r"\textwidth"),
    "two_square": ((6.0, 3.2), 2, r"\textwidth"),
    "re_im": ((6.0, 2.8), 2, r"\textwidth"),
    "grid2x2": ((6.0, 5.0), 2, r"\textwidth"),
    "three": ((6.0, 2.0), 3, r"\textwidth"),
    "three_square": ((6.0, 2.6), 3, r"\textwidth"),
    "four_square": ((6.0, 1.9), 4, r"\textwidth"),
    "three_stacked": ((6.0, 6.5), 1, r"\textwidth"),
}

_RC = {
    "font.size": 12,
    "axes.labelsize": 12,
    "axes.titlesize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "legend.fontsize": 10,
    "figure.titlesize": 12,
    "font.family": "serif",
    "axes.linewidth": 1.2,
    "axes.labelpad": 4.0,
    "axes.titlepad": 6.0,
    "lines.linewidth": 2.2,
    "lines.markersize": 4.0,
    "lines.markeredgewidth": 0.9,
    "xtick.major.size": 6,
    "ytick.major.size": 6,
    "xtick.minor.size": 3,
    "ytick.minor.size": 3,
    "xtick.major.width": 1.2,
    "ytick.major.width": 1.2,
    "xtick.minor.width": 1.0,
    "ytick.minor.width": 1.0,
    "xtick.major.pad": 3.5,
    "ytick.major.pad": 3.5,
    "figure.dpi": 120,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "axes.grid": False,
}

_TEX_CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "qcc" / "usetex.json"


def latex_available(timeout: float = 120.0) -> bool:
    """Whether matplotlib ``text.usetex`` works here (tested once in a subprocess so a TeX prompt can't hang us)."""
    try:
        return bool(json.loads(_TEX_CACHE.read_text())["ok"])
    except (OSError, ValueError, KeyError):
        pass
    code = (
        "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt, tempfile, os;"
        "plt.rcParams.update({'text.usetex': True, 'font.family': 'serif'});"
        "f, a = plt.subplots(figsize=(1, 1)); a.set_title(r'$\\alpha\\,\\Phi_0$');"
        "f.savefig(os.path.join(tempfile.gettempdir(), '_qcc_latex_test.png'))"
    )
    try:
        ok = (
            subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=timeout, check=False).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    _TEX_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _TEX_CACHE.write_text(json.dumps({"ok": ok}))
    return ok


def use_style(usetex: bool | None = None) -> bool:
    """Apply the guideline style; returns whether LaTeX text is on (falls back to Computer Modern mathtext)."""
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    try:
        import scienceplots  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import

        plt.style.use(["science"])
    except ImportError:
        pass  # optional; the rcParams below are the guideline
    plt.rcParams["axes.prop_cycle"] = plt.cycler("color", COLORS)
    plt.rcParams.update(_RC)
    tex = latex_available() if usetex is None else usetex
    plt.rcParams.update({"text.usetex": True} if tex else {"text.usetex": False, "mathtext.fontset": "cm"})
    return tex


def use_tier(n: int) -> None:
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    plt.rcParams.update(TIERS[n])


def thesis_axes(ax, xminor: int = 5, yminor: int = 5):
    """Minor ticks and consistent spine widths (project plot style). Call once per axis."""
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
    from matplotlib.ticker import AutoMinorLocator  # pylint: disable=import-outside-toplevel

    if ax.get_xscale() == "linear":
        ax.xaxis.set_minor_locator(AutoMinorLocator(xminor))
    if ax.get_yscale() == "linear":
        ax.yaxis.set_minor_locator(AutoMinorLocator(yminor))
    ax.tick_params(which="both", top=True, right=True)
    for s in ax.spines.values():
        s.set_linewidth(plt.rcParams["axes.linewidth"])
    return ax


def figure(layout: str = "single", nrows: int = 1, ncols: int = 1, **kw):
    """``plt.subplots`` with the guideline figsize and font tier for ``layout`` (see :data:`FIGSIZES`)."""
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    size, tier, _ = FIGSIZES[layout]
    use_tier(tier)
    fig, axes = plt.subplots(nrows, ncols, figsize=size, layout="constrained", **kw)
    for ax in axes.flat if hasattr(axes, "flat") else [axes]:
        thesis_axes(ax)
    return fig, axes


_TEX = {
    "Φ0": r"\Phi_0",
    "Φ": r"\Phi",
    "α": r"\alpha",
    "χ": r"\chi",
    "κ": r"\kappa",
    "Σ": r"\Sigma",
    "µ": r"\mu",
    "μ": r"\mu",
    "Ω": r"\Omega",
    "ε": r"\varepsilon",
    "λ": r"\lambda",
    "‖": r"\|",
    "⟩": r"\rangle",
    "−": "-",
    "×": r"\times",
    "·": r"\cdot",
    "Δ": r"\Delta",
    "ω": r"\omega",
    "π": r"\pi",
}


_SUB = re.compile(r"(?<![A-Za-z0-9.])([A-Za-z])_([A-Za-z0-9ΣΦαχκΩλωπ]{1,3})(?![A-Za-z0-9_])")


def tex(s: str | None) -> str | None:
    """Unicode label → mathtext/LaTeX label: ``f_q``/``C_Σ`` (single-letter base) become subscripts, Greek and kets
    become math, and text-mode specials are escaped under usetex (``metal_lom`` stays literal)."""
    if s is None:
        return None
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    usetex = plt.rcParams.get("text.usetex")
    greek = sorted(_TEX.items(), key=lambda kv: -len(kv[0]))
    pieces = []  # (is_math, text)
    pos = 0
    for m in _SUB.finditer(s):
        pieces += [(False, s[pos : m.start()]), (True, f"{m.group(1)}_{{{m.group(2)}}}")]
        pos = m.end()
    pieces.append((False, s[pos:]))
    out = []
    for is_math, t in pieces:
        if is_math:
            for k, v in greek:
                t = t.replace(k, v + " " if v[0] == "\\" else v)
            out.append(f"${t}$")
            continue
        if usetex:
            for ch in ("_", "%", "&", "#"):
                t = t.replace(ch, "\\" + ch)
        for k, v in greek:
            t = t.replace(k, f"${v}$")
        out.append(t.replace("$$", "") if not usetex else t.replace("$$", "").replace("|", "$|$"))
    return "".join(out).replace("$$", "")


# ---- PlotSpec builders -----------------------------------------------------------------------------------------
def xy_spec(ident, title, tab, series, x_label=None, y_label=None, ref_lines=None, log_y=False, caption=None):
    """``series``: list of dicts {name, x, y, kind?, dashed?}."""
    spec = {"id": ident, "title": title, "tab": tab, "kind": "xy", "series": series}
    for k, v in (("xLabel", x_label), ("yLabel", y_label), ("refLines", ref_lines), ("caption", caption)):
        if v:
            spec[k] = v
    if log_y:
        spec["logY"] = True
    return spec


def bar_spec(ident, title, tab, bars, y_label=None, caption=None):
    """``bars``: list of {label, values: {series: value}}."""
    spec = {"id": ident, "title": title, "tab": tab, "kind": "bar", "bars": bars}
    if y_label:
        spec["yLabel"] = y_label
    if caption:
        spec["caption"] = caption
    return spec


def levels_spec(ident, title, tab, levels, caption=None):
    spec = {"id": ident, "title": title, "tab": tab, "kind": "levels", "levels": levels}
    if caption:
        spec["caption"] = caption
    return spec


def heatmap_spec(ident, title, tab, rows, cols, values, unit, caption=None):
    spec = {
        "id": ident,
        "title": title,
        "tab": tab,
        "kind": "heatmap",
        "heatmap": {"rows": rows, "cols": cols, "values": values, "unit": unit},
    }
    if caption:
        spec["caption"] = caption
    return spec


# ---- PlotSpec → matplotlib ---------------------------------------------------------------------------------------
def plot_spec(spec: dict, ax=None, legend: bool = True):
    """Draw a PlotSpec on ``ax`` (a new guideline-sized figure if omitted). Returns the axis."""
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
    import numpy as np  # pylint: disable=import-outside-toplevel

    if ax is None:
        layout = {"levels": "square_medium", "heatmap": "square_medium"}.get(spec["kind"], "single")
        _, ax = figure(layout)
    kind = spec["kind"]
    if kind == "xy":
        for i, s in enumerate(spec.get("series", [])):
            style = {"linestyle": "--" if s.get("dashed") else "-", "color": COLORS[i % len(COLORS)]}
            if s.get("kind") == "scatter":
                ax.plot(s["x"], s["y"], "o", label=tex(s["name"]), color=style["color"])
            elif s.get("kind") == "step":
                ax.step(s["x"], s["y"], where="mid", label=tex(s["name"]), **style)
            else:
                ax.plot(s["x"], s["y"], label=tex(s["name"]), **style)
        for r in spec.get("refLines", []):
            line = ax.axhline if r["axis"] == "y" else ax.axvline
            line(r["value"], color="#888888", linestyle=":", linewidth=1.0)
            if r["axis"] == "y":
                ax.annotate(
                    tex(r["label"]),
                    (1.0, r["value"]),
                    xycoords=("axes fraction", "data"),
                    ha="right",
                    va="bottom",
                    fontsize="small",
                    color="#666666",
                )
        if spec.get("logY"):
            ax.set_yscale("log")
        if legend and len(spec.get("series", [])) > 1:
            ax.legend(frameon=False)
    elif kind == "bar":
        bars = spec.get("bars", [])
        names = sorted({n for b in bars for n in b["values"]})
        width = 0.8 / max(len(names), 1)
        for j, n in enumerate(names):
            xs = [i + (j - (len(names) - 1) / 2) * width for i in range(len(bars))]
            ys = [b["values"].get(n) or 0 for b in bars]
            ax.bar(xs, ys, width, label=tex(n), color=COLORS[j % len(COLORS)])
        ax.set_xticks(
            range(len(bars)),
            [tex(b["label"]) for b in bars],
            rotation=30 if len(bars) > 3 else 0,
            ha="right" if len(bars) > 3 else "center",
        )
        ax.tick_params(axis="x", which="minor", bottom=False, top=False)
        ax.axhline(0, color="#888888", linewidth=0.8)
        if legend and len(names) > 1:
            ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize="small")
    elif kind == "levels":
        levels = spec.get("levels", [])
        groups = sorted({lv.get("group", "") for lv in levels}) or [""]
        for lv in levels:
            gx = groups.index(lv.get("group", ""))
            ax.hlines(lv["energy"], gx - 0.3, gx + 0.3, color=COLORS[0], linewidth=2)
            ax.annotate(tex(lv["label"]), (gx + 0.33, lv["energy"]), va="center", fontsize="small")
        ax.set_xlim(-0.6, len(groups) - 0.1)
        ax.set_xticks(range(len(groups)), [g or "" for g in groups])
        ax.tick_params(axis="x", which="both", length=0)
        ax.set_ylabel(spec.get("yLabel") or "Energy $E/h$ (GHz)")
    elif kind == "heatmap":
        hm = spec["heatmap"]
        vals = np.asarray(hm["values"], dtype=float)
        im = ax.imshow(np.abs(vals), cmap="Blues")
        for (i, j), v in np.ndenumerate(vals):
            ax.text(
                j,
                i,
                f"{v:.2f}",
                ha="center",
                va="center",
                fontsize="small",
                color="white" if abs(v) > 0.6 * np.abs(vals).max() else "#111111",
            )
        ax.set_xticks(range(len(hm["cols"])), [tex(c) for c in hm["cols"]], rotation=30, ha="right")
        ax.set_yticks(range(len(hm["rows"])), [tex(r) for r in hm["rows"]])
        ax.minorticks_off()
        plt.colorbar(im, ax=ax, label=tex(f"|C| ({hm['unit']})"))
    if spec.get("xLabel") and kind != "levels":
        ax.set_xlabel(tex(spec["xLabel"]))
    if spec.get("yLabel") and kind not in ("levels",):
        ax.set_ylabel(tex(spec["yLabel"]))
    ax.set_title(tex(spec.get("title")))
    return ax


# ---- FEM results: convergence, S21 with its notch fit, EPR ------------------------------------------------------
# Inputs are the dicts ``analysis.results.collect_results`` writes (``results.json``), a job folder (or its
# ``results/``), or an ``*_project_convergence.txt``. The matplotlib helpers and the dashboard specs read the same
# data (:func:`convergence_data`), so the notebook figure and the Plots tab agree.
def _read_results(x) -> dict:
    """``results.json`` dict from a dict, a ``results.json`` path, a job folder or its ``results/`` folder, or a
    ``*_project_convergence.txt`` (then only ``convergence`` is filled)."""
    if isinstance(x, dict):
        return x
    path = Path(x)
    if path.is_file() and path.suffix == ".txt":
        from quantcore_circuits.analysis.results import parse_convergence  # pylint: disable=import-outside-toplevel

        return {"convergence": {"file": path.name, **parse_convergence(path)}}
    for cand in (path, path / "results.json", path / "results" / "results.json"):
        if cand.is_file():
            return json.loads(cand.read_text(encoding="utf-8"))
    txt = sorted(path.glob("*_project_convergence.txt")) if path.is_dir() else []
    if txt:
        return _read_results(txt[0])
    raise FileNotFoundError(f"no results.json or convergence file under {path}")


def convergence_data(x, label: str | None = None) -> dict | None:
    """One job's adaptive-pass convergence as plain lists: ``label``, ``analysis``, ``criterion``, ``target``,
    ``converged``, ``passes``, ``elements`` (solved tets per pass), ``delta`` (None on pass 1), ``mode_GHz``
    (eigenmode jobs: mode -> frequency per pass). None when the job has no convergence data."""
    res = _read_results(x)
    conv = res.get("convergence") or {}
    if not conv.get("passes"):
        return None
    name = label or res.get("analysis") or conv.get("file") or "job"
    if res.get("group") and not label:
        name = f"{name} ({res['group']})"
    n = len(conv["passes"])
    return {
        "label": name,
        "analysis": res.get("analysis"),
        "criterion": conv.get("criterion"),
        "target": conv.get("target"),
        "converged": conv.get("converged"),
        "passes": list(conv["passes"]),
        "elements": list(conv.get("elements") or [None] * n),
        "delta": list(conv.get("delta") or [None] * n),
        "mode_GHz": conv.get("mode_GHz") or {},
    }


def _conv_inputs(x, label=None) -> list[dict]:
    # a dict is one job when it looks like a results dict, otherwise a mapping label -> job
    if isinstance(x, dict) and not {"convergence", "passes", "analysis"} & set(x):
        items = list(x.items())
    elif isinstance(x, (list, tuple)):
        items = [(None, v) for v in x]
    else:
        items = [(label, x)]
    out = []
    for k, v in items:
        if v is None:
            continue
        d = convergence_data(v, label=k if isinstance(k, str) else None)
        if d:
            out.append(d)
    return out


def _delta_points(j: dict) -> list[tuple]:
    return [(p, e, v) for p, e, v in zip(j["passes"], j["elements"], j["delta"]) if v is not None]


def plot_convergence(results_or_job, ax=None, label: str | None = None):
    """Adaptive-pass convergence of one job (a ``results.json`` dict / path, a job folder, a convergence text file) or
    of several (``{label: ...}`` or a list). Returns the first axis (``ax.figure.axes`` has the rest).

    With ``ax`` only that panel is drawn: the criterion (delta %, max delta f %, max |delta S|) against the pass, a
    dotted criterion line, and the mesh size (solved tets) on a secondary top axis for a single job; jobs with
    different criteria are drawn as delta / target so the line at 1 is the criterion. Without ``ax`` a figure with the
    pass panel, the same delta against the tet count (log), and, for an eigenmode job, each mode's frequency relative
    to its last pass.
    """
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
    import numpy as np  # pylint: disable=import-outside-toplevel
    from matplotlib.ticker import MaxNLocator  # pylint: disable=import-outside-toplevel

    jobs = _conv_inputs(results_or_job, label)
    if not jobs:
        raise ValueError("no convergence data in the given results")
    modes = jobs[0]["mode_GHz"] if len(jobs) == 1 else {}
    own = ax is None
    if own:
        _, axes = figure("three_square", 1, 3 if modes else 2)
        axes = list(axes.flat)
        ax = axes[0]
    rel = len({j["criterion"] for j in jobs}) > 1

    def series(j):
        d = _delta_points(j)
        scale = 1.0 / j["target"] if rel and j["target"] else 1.0
        return [p for p, _, _ in d], [e for _, e, _ in d], [v * scale for _, _, v in d]

    for i, j in enumerate(jobs):
        x, _, y = series(j)
        col = COLORS[i % len(COLORS)]
        ax.plot(x, y, "o-", color=col, label=tex(j["label"]) if len(jobs) > 1 else None, ms=4)
        if j["target"] is not None and not rel:
            ax.axhline(j["target"], color=col, linestyle=":", linewidth=1.0)
            ax.annotate(
                "criterion " + ("met" if j["converged"] else "not met"),
                (1.0, j["target"]),
                xycoords=("axes fraction", "data"),
                ha="right",
                va="bottom",
                fontsize="small",
                color="#666666",
            )
    if rel:
        ax.axhline(1.0, color="#888888", linestyle=":", linewidth=1.0)
    ax.set_yscale("log")
    ax.set_xlabel("adaptive pass")
    ax.set_ylabel("$\\Delta$ / target" if rel else tex(jobs[0]["criterion"] or "delta"))
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.set_minor_locator(plt.NullLocator())
    if len(jobs) > 1:
        ax.legend(frameon=False, fontsize="small")
    elif not own and None not in jobs[0]["elements"]:
        pa, el = np.asarray(jobs[0]["passes"], float), np.asarray(jobs[0]["elements"], float)
        top = ax.secondary_xaxis("top", functions=(lambda p: np.interp(p, pa, el), lambda n: np.interp(n, el, pa)))
        top.set_xlabel("solved tets")
    if own:
        ax.set_title("(a) per pass")
        bx = axes[1]
        for i, j in enumerate(jobs):
            _, e, y = series(j)
            col = COLORS[i % len(COLORS)]
            if e and None not in e:
                bx.plot(e, y, "o-", color=col, ms=4)
                if j["target"] is not None and not rel:
                    bx.axhline(j["target"], color=col, linestyle=":", linewidth=1.0)
        if rel:
            bx.axhline(1.0, color="#888888", linestyle=":", linewidth=1.0)
        bx.set_xscale("log")
        bx.set_yscale("log")
        bx.xaxis.set_minor_formatter(plt.NullFormatter())
        bx.set_xlabel("solved tets")
        bx.set_title("(b) per mesh size")
        if modes:
            cx = axes[2]
            for i, (m, fs) in enumerate(modes.items()):
                d = (np.asarray(fs) - fs[-1]) * 1e3
                cx.plot(range(1, len(fs) + 1), d, "o-", ms=3, color=COLORS[i % len(COLORS)], label=f"mode {m}")
            cx.axhline(0, color="#888888", linewidth=0.8)
            cx.set_xlabel("adaptive pass")
            cx.set_ylabel("$f - f_{\\mathrm{last}}$ (MHz)")
            cx.xaxis.set_major_locator(MaxNLocator(integer=True))
            cx.xaxis.set_minor_locator(plt.NullLocator())
            cx.legend(frameon=False, fontsize="x-small")
            cx.set_title("(c) mode frequencies")
    return ax


def convergence_specs(results_or_job, label: str | None = None, tab: str = "plots") -> list[dict]:
    """Dashboard specs of a job's convergence: delta per pass with the criterion line, delta against the tet count
    and, for eigenmode jobs, each mode's frequency per pass."""
    specs = []
    for j in _conv_inputs(results_or_job, label):
        key = re.sub(r"[^A-Za-z0-9]+", "_", j["label"]).strip("_").lower()
        pts = _delta_points(j)
        if not pts:
            continue
        crit = j["criterion"] or "delta"
        ref = [{"axis": "y", "value": j["target"], "label": "criterion"}] if j["target"] is not None else None
        status = "converged" if j["converged"] else "stopped before the criterion"
        specs.append(
            xy_spec(
                f"conv_{key}",
                f"Convergence: {j['label']}",
                tab,
                [{"name": crit, "x": [p for p, _, _ in pts], "y": [v for _, _, v in pts], "kind": "line"}],
                "Adaptive pass",
                crit,
                ref,
                log_y=True,
                caption=f"{crit}, target {j['target']}: {status} after {j['passes'][-1]} passes",
            )
        )
        if len(pts) > 1 and all(e is not None for _, e, _ in pts):
            specs.append(
                xy_spec(
                    f"conv_{key}_mesh",
                    f"Convergence against mesh: {j['label']}",
                    tab,
                    [{"name": crit, "x": [e for _, e, _ in pts], "y": [v for _, _, v in pts], "kind": "line"}],
                    "Solved tets",
                    crit,
                    ref,
                    log_y=True,
                    caption="criterion against the mesh size of each pass",
                )
            )
        if j["mode_GHz"]:
            ser = [
                {
                    "name": f"mode {m}",
                    "x": list(range(1, len(fs) + 1)),
                    "y": [round((v - fs[-1]) * 1e3, 4) for v in fs],
                    "kind": "line",
                }
                for m, fs in j["mode_GHz"].items()
            ]
            specs.append(
                xy_spec(
                    f"conv_{key}_modes",
                    f"Mode frequencies per pass: {j['label']}",
                    tab,
                    ser,
                    "Adaptive pass",
                    "f - f(last pass) (MHz)",
                    caption="each mode's frequency relative to its last-pass value",
                )
            )
    return specs


def _notch_model(f, f0, ql, qc_abs, phi, amp=1.0):
    import numpy as np  # pylint: disable=import-outside-toplevel

    return amp * np.abs(1 - (ql / qc_abs) * np.exp(1j * phi) / (1 + 2j * ql * (f / f0 - 1)))


def _s21_trace(results, f_GHz=None, s21=None, job_dir=None):
    """(f_GHz, complex S21) from explicit arrays, or the ``*_SMatrix.s2p`` next to a job's results; else None."""
    import numpy as np  # pylint: disable=import-outside-toplevel

    if f_GHz is not None and s21 is not None:
        return np.asarray(f_GHz, float), np.asarray(s21, complex)
    cands = []
    if job_dir:
        cands.append(Path(job_dir))
    if isinstance(results, (str, Path)):
        p = Path(results)
        base = p if p.is_dir() else p.parent
        cands += [base, base.parent]
    for base in cands:
        for fn in sorted(base.glob("*_SMatrix.s2p")) if base.is_dir() else []:
            from quantcore_circuits.analysis.results import parse_touchstone  # pylint: disable=import-outside-toplevel

            f, s, _ = parse_touchstone(fn)
            return f, s[:, 1, 0]
    return None


def _notch_window(n: dict, trace):
    """(f0, Q_l, |Q_c|, phi, half-width GHz, amplitude of the trace's baseline or 1) of one notch fit."""
    import numpy as np  # pylint: disable=import-outside-toplevel

    f0, ql, phi = n["f0_GHz"], n["Q_loaded"], n.get("phi", 0.0)
    half = 8 * f0 / ql  # eight linewidths each side
    amp = 1.0
    if trace is not None:
        f, s = trace
        amp = float(np.abs(s[np.abs(f - f0) <= max(half, 25 * f0 / ql)]).max())
    return f0, ql, n["Q_coupling"] * math.cos(phi), phi, half, amp


def plot_s21_fit(results, ax=None, f_GHz=None, s21=None, job_dir=None, notch: str | None = None):
    """|S21| of a driven job with its notch fit, the fitted f0, kappa_ext and Q_i written on the panel.

    ``results``: the ``results.json`` dict (``sparams.notch`` holds the fits), a path to it, or a job folder with an
    ``*_SMatrix.s2p`` (the trace is read and re-fitted with :func:`analysis.results.fit_notches`). The trace itself is
    not stored in ``results.json``: pass ``f_GHz`` / ``s21`` or ``job_dir`` to draw the data, otherwise only the fitted
    model curve (normalised to 1 off resonance) is shown and the title says so. ``notch``: one fit's key; default all
    fits, one panel each (up to 4) when ``ax`` is not given, the first when it is. Returns the first axis.
    """
    import numpy as np  # pylint: disable=import-outside-toplevel

    trace = _s21_trace(results, f_GHz, s21, job_dir)
    fits: dict = {}
    try:
        fits = (_read_results(results).get("sparams") or {}).get("notch") or {}
    except FileNotFoundError:
        pass
    if trace is not None and not fits:
        from quantcore_circuits.analysis.results import fit_notches  # pylint: disable=import-outside-toplevel

        fits = {f"S21#{i + 1}": fit for i, fit in enumerate(fit_notches(*trace))}
    if not fits:
        raise ValueError("no notch fit in the results (and no trace to fit)")
    keys = [notch] if notch else list(fits)
    keys = keys[: 1 if ax is not None else 4]
    if ax is None:
        _, axes = figure("three_square" if len(keys) > 1 else "single", 1, len(keys))
        axs = [axes] if len(keys) == 1 else list(axes.flat)
    else:
        axs = [ax]
    for a, k in zip(axs, keys):
        n = fits[k]
        f0, ql, qc, phi, half, amp = _notch_window(n, trace)
        if trace is not None:
            f, s = trace
            sel = np.abs(f - f0) <= half
            if sel.sum() < 5:
                sel = np.ones_like(f, dtype=bool)
            a.plot(f[sel], np.abs(s[sel]) / amp, ".", ms=3, color=COLORS[4], label="data")
            fx = np.linspace(f[sel].min(), f[sel].max(), 800)
        else:
            fx = np.linspace(f0 - half, f0 + half, 800)
        a.plot(fx, _notch_model(fx, f0, ql, qc, phi), "-", color=COLORS[0], label="notch fit")
        a.axvline(f0, color="#888888", linestyle=":", linewidth=1.0)
        a.set_xlabel("frequency (GHz)")
        a.set_ylabel("$|S_{21}|$ (norm.)")
        a.annotate(
            f"$f_0$ = {f0:.4f} GHz\n$\\kappa_{{ext}}$ = {n['kappa_ext_MHz']:.3g} MHz\n$Q_i$ = {n['Q_internal']:.2g}",
            (0.03, 0.05),
            xycoords="axes fraction",
            fontsize="small",
            va="bottom",
        )
        a.set_title(tex(k) + ("" if trace is not None else " (fit only: trace not stored)"))
        a.legend(frameon=False, fontsize="small", loc="lower right")
        a.ticklabel_format(axis="x", useOffset=False)
    return axs[0]


def s21_specs(results, f_GHz=None, s21=None, job_dir=None, tab: str = "plots", max_points: int = 400) -> list[dict]:
    """Dashboard spec per |S21| notch: the data when a trace is available (decimated to ``max_points``), the fit
    curve, and the fitted f0 / kappa_ext in the caption."""
    import numpy as np  # pylint: disable=import-outside-toplevel

    res = _read_results(results)
    trace = _s21_trace(results, f_GHz, s21, job_dir)
    specs = []
    for k, n in ((res.get("sparams") or {}).get("notch") or {}).items():
        f0, ql, qc, phi, half, amp = _notch_window(n, trace)
        fx = np.linspace(f0 - half, f0 + half, 200)
        series = []
        if trace is not None:
            f, s = trace
            sel = np.where(np.abs(f - f0) <= half)[0]
            sel = sel[:: max(1, len(sel) // max_points)]
            series.append(
                {
                    "name": "data",
                    "x": [round(float(v), 6) for v in f[sel]],
                    "y": [round(float(v), 5) for v in np.abs(s[sel]) / amp],
                    "kind": "scatter",
                }
            )
        series.append(
            {
                "name": "notch fit",
                "x": [round(float(v), 6) for v in fx],
                "y": [round(float(v), 5) for v in _notch_model(fx, f0, ql, qc, phi)],
                "kind": "line",
            }
        )
        specs.append(
            xy_spec(
                "s21_" + re.sub(r"[^A-Za-z0-9]+", "_", k).strip("_").lower(),
                f"|S21| notch {k}",
                tab,
                series,
                "Frequency (GHz)",
                "|S21| (norm.)",
                [{"axis": "x", "value": round(f0, 6), "label": f"f0 {f0:.4f} GHz"}],
                caption=f"f0 {f0:.5f} GHz, kappa_ext {n['kappa_ext_MHz']:.3g} MHz, Q_i {n['Q_internal']:.3g}"
                + ("" if trace is not None else "; fit only, the trace is not stored in results.json"),
            )
        )
    return specs


def plot_epr(epr_result: dict, ax=None):
    """Energy participation of an EPR result (:mod:`analysis.epr_lumped`): bars of p per mode, one colour per
    junction (log scale: resonator modes sit near 1e-3), and without ``ax`` also the chi matrix of the modes that
    touch a junction (signed, symmetric-log colour, values printed). Returns the first axis."""
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
    import numpy as np  # pylint: disable=import-outside-toplevel
    from matplotlib.colors import SymLogNorm  # pylint: disable=import-outside-toplevel

    p = np.asarray(epr_result["p"], float)
    modes = epr_result["modes"]
    juncs = epr_result["junctions"]
    own = ax is None
    if own:
        _, axes = figure("two", 1, 2)
        ax, bx = list(axes.flat)
    width = 0.8 / max(len(juncs), 1)
    for j, name in enumerate(juncs):
        xs = np.arange(len(modes)) + (j - (len(juncs) - 1) / 2) * width
        ax.bar(xs, np.clip(p[:, j], 1e-6, None), width, label=tex(name), color=COLORS[j % len(COLORS)])
    ax.set_yscale("log")
    ax.set_ylim(1e-4, 30)
    ax.set_xticks(range(len(modes)), [tex(f"{m['label']} {m['f_GHz']:.2f}") for m in modes], rotation=30, ha="right")
    ax.tick_params(axis="x", which="minor", bottom=False, top=False)
    ax.set_ylabel("participation $p_{mj}$")
    ax.set_title(("(a) " if own else "") + "method: " + str(epr_result["method"]))
    if len(juncs) > 1:
        ax.legend(frameon=False, fontsize="small", ncols=2, loc="upper right")
    if own:
        act = [i for i in range(len(modes)) if p[i].max(initial=0.0) > 1e-4]
        chi = np.asarray(epr_result["chi_MHz"], float)[np.ix_(act, act)] if act else np.zeros((1, 1))
        top = max(float(np.abs(chi).max()), 1e-6)
        im = bx.imshow(chi, cmap="RdBu_r", norm=SymLogNorm(linthresh=max(top * 1e-3, 1e-6), vmin=-top, vmax=top))
        for (i, k), v in np.ndenumerate(chi):
            bx.text(
                k,
                i,
                f"{v:.2g}",
                ha="center",
                va="center",
                fontsize="xx-small",
                color="white" if abs(v) > 0.3 * top else "#111111",
            )
        names = [tex(modes[i]["label"]) for i in act]
        bx.set_xticks(range(len(act)), names, rotation=30, ha="right")
        bx.set_yticks(range(len(act)), names)
        bx.minorticks_off()
        bx.tick_params(length=0)
        bx.set_title("(b) $\\chi$ matrix (MHz), diagonal $\\alpha$")
        plt.colorbar(im, ax=bx, label="MHz")
    return ax


def epr_specs(epr_result: dict, tab: str = "plots", prefix: str = "epr") -> list[dict]:
    """Dashboard specs of an EPR result: participation bars (mode -> junction) and the chi matrix (diagonal alpha)."""
    bars = [
        {
            "label": f"{m['label']} {m['f_GHz']:.2f} GHz",
            "values": {j: round(float(v), 6) for j, v in zip(epr_result["junctions"], row)},
        }
        for m, row in zip(epr_result["modes"], epr_result["p"])
    ]
    act = [i for i, row in enumerate(epr_result["p"]) if max(row, default=0.0) > 1e-4]
    names = [epr_result["modes"][i]["label"] for i in act]
    vals = [[round(float(epr_result["chi_MHz"][i][k]), 4) for k in act] for i in act]
    method = epr_result["method"]
    return [
        bar_spec(
            f"{prefix}_p",
            f"EPR participation ({method})",
            tab,
            bars,
            "p_mj",
            caption="energy participation of each junction in each mode",
        ),
        heatmap_spec(
            f"{prefix}_chi",
            f"EPR chi matrix ({method})",
            tab,
            names,
            names,
            vals,
            "MHz",
            caption="diagonal: self-Kerr alpha; off-diagonal: cross-Kerr chi",
        ),
    ]


def fem_specs(jobs, tab: str = "plots") -> list[dict]:
    """All FEM-result plot specs for the dashboard. ``jobs``: results dicts or ``FilledCircuit.jobs`` entries (which
    hold ``results``). Per job: its convergence set, the S21 notches of a driven job and the EPR of an eigenmode job
    that recorded it."""
    specs: list[dict] = []
    seen: set[str] = set()
    for j in jobs or []:
        res = j.get("results") if isinstance(j, dict) and "results" in j and "convergence" not in j else j
        if not isinstance(res, dict) or not res:
            continue
        group = res.get("group") or (j.get("group") if isinstance(j, dict) else "")
        name = f"{res.get('analysis', 'job')} ({group})" if group else res.get("analysis", "job")
        new = convergence_specs(res, name, tab) if (res.get("convergence") or {}).get("passes") else []
        if (res.get("sparams") or {}).get("notch"):
            new += s21_specs(res, tab=tab)
        if (res.get("epr") or {}).get("p_mj"):
            try:
                from quantcore_circuits.analysis.epr_lumped import epr_from_job  # pylint: disable=import-outside-toplevel

                new += epr_specs(epr_from_job(res), tab)
            except (KeyError, ValueError, ImportError):  # a plot must not stop the analysis
                pass
        for s in new:
            if s["id"] not in seen:
                seen.add(s["id"])
                specs.append(s)
    return specs


def save(fig, path, formats=("pdf", "png")) -> list[Path]:
    """Save ``fig`` next to ``path`` in each format (PDF for LaTeX, PNG for the dashboard/notebook)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for fmt in formats:
        p = path.with_suffix(f".{fmt}")
        fig.savefig(p)
        out.append(p)
    return out
