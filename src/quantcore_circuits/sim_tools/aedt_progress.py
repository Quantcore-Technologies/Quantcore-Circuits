"""Live progress of an AEDT render / solve, read from the job directory while it runs (any AEDT mode).

AEDT in batch mode prints nothing to its log, so a stuck run and a slow one look the same. This reads what AEDT and
the qcc script write as they go:

* ``qcc_<mode>_status.txt`` (:mod:`.aedt_scripts`): the current step (``import``, ``solve``, ``export``, ``epr``);
* ``<project>.aedtresults/<Design>.results/*.EMConvData`` (HFSS eigenmode / driven): one block per adaptive pass with
  the solved tetrahedra and ``MaxDeltaFreq`` (%) or ``MaxMagDeltaS``, the target and the pass limit;
* ``*_SOL*_M<n>_V*.sd`` (eigenmode): the mode frequencies of pass ``n``;
* ``*_SOL*_MCAP<n>_V*.sd`` (Q3D): the capacitance matrix of pass ``n``; ΔC is the largest relative change of a
  diagonal entry from the previous pass (an estimate of Q3D's own % error);
* ``*/current.stats``: the current mesh size (``NumTotalTets`` / ``NumTotalTris``).

:func:`read_progress` returns a dict, :func:`format_progress` one line for the notebook (printed every ~30 s by
:func:`quantcore_circuits.sim_tools.hfss.solve_job`).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

__all__ = ["format_progress", "parse_em_conv", "read_progress"]

_PASS_RE = re.compile(r"PassNo=(\d+)")
_VAL_RE = re.compile(r"(\w+)\(([-+0-9.eE]+),")


def parse_em_conv(text: str) -> dict:
    """An HFSS ``.EMConvData`` file → ``{"passes": [{"pass", "elements", "delta"}], "criterion", "target",
    "max_passes", "converged"}`` (``delta`` in % for ΔF, absolute for ΔS; frequency-point repeats are merged)."""
    info = {}
    for key in ("IsConverged", "MaxPasses", "MinPasses", "ConvTarget"):
        m = re.search(rf"{key}='?([^'\n]+)'?", text)
        if m:
            info[key] = m.group(1).strip()
    passes: dict[int, dict] = {}
    criterion = None
    for block in text.split("$begin 'QuantityValues'")[1:]:
        m = _PASS_RE.search(block)
        if not m:
            continue
        n = int(m.group(1))
        rec = passes.setdefault(n, {"pass": n, "elements": None, "delta": None})
        for name, value in _VAL_RE.findall(block):
            if name == "SolvedElements":
                rec["elements"] = int(float(value))
            elif name.startswith("Max") and "Delta" in name:
                criterion = {"MaxDeltaFreq": "ΔF", "MaxMagDeltaS": "ΔS"}.get(name, name)
                rec["delta"] = float(value) if rec["delta"] is None else max(rec["delta"], float(value))
    target = info.get("ConvTarget")
    return {
        "passes": [passes[k] for k in sorted(passes)],
        "criterion": criterion,
        "target": float(target) if target else None,
        "max_passes": int(info["MaxPasses"]) if info.get("MaxPasses", "").isdigit() else None,
        "converged": info.get("IsConverged", "").lower() == "true",
    }


def _newest(paths):
    paths = [p for p in paths if p.is_file()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def _mesh_size(results: Path) -> tuple[int | None, str | None]:
    stats = _newest(results.glob("*/current.stats"))
    if stats is None:
        return None, None
    text = stats.read_text(encoding="utf-8", errors="replace")
    for key, unit in (("NumTotalTets", "tets"), ("NumTotalTris", "triangles")):
        m = re.search(rf"{key}\s+(\d+)", text)
        if m:
            return int(m.group(1)), unit
    return None, None


def _eigen_modes(results: Path) -> tuple[int | None, list[float]]:
    """(pass, mode frequencies in GHz) of the newest per-pass eigenmode solution file."""
    best = None
    for p in results.glob("*_M*_V*.sd"):
        m = re.search(r"_M(\d+)_V\d+\.sd$", p.name)
        if p.is_file() and m and int(m.group(1)) > 0 and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), p)
    if best is None:
        return None, []
    text = best[1].read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\bModes\(([^)]*)\)", text) if "SolveMaxModes" in text else None  # eigenmode solutions only
    vals = [float(x) for x in m.group(1).split(",") if x.strip()] if m else []
    return best[0], [vals[i] / 1e9 for i in range(0, len(vals), 2)]


def _diag(text: str) -> list[float]:
    out = []
    for i, row in enumerate(re.findall(r"\$begin 'r\d+'(.*?)\$end", text, re.S)):
        vals = re.findall(r"c\(([-+0-9.eE]+)\)", row)
        if i < len(vals):
            out.append(float(vals[i]))
    return out


def _q3d_passes(results: Path) -> list[dict]:
    """Per adaptive Q3D pass: the diagonal of its C matrix and ΔC (%) from the previous pass."""
    files = {}
    for p in results.glob("*_MCAP*_V*.sd"):
        m = re.search(r"_MCAP(\d+)_V\d+\.sd$", p.name)
        if p.is_file() and m and int(m.group(1)) > 0:
            files[int(m.group(1))] = p
    out, prev = [], None
    for n in sorted(files):
        diag = _diag(files[n].read_text(encoding="utf-8", errors="replace"))
        delta = None
        if prev and len(prev) == len(diag) and all(diag):
            delta = 100 * max(abs(a - b) / abs(a) for a, b in zip(diag, prev))
        out.append({"pass": n, "delta": delta, "C_fF": [c * 1e15 for c in diag]})
        prev = diag
    return out


def _status(job_dir: Path, mode: str) -> list[str]:
    p = job_dir / f"qcc_{mode}_status.txt"
    return p.read_text(encoding="utf-8", errors="replace").splitlines() if p.exists() else []


def read_progress(job_dir: str | Path, mode: str = "solve") -> dict:
    """What a running (or finished) AEDT job has done so far; see the module docstring. Missing files → ``None``."""
    job_dir = Path(job_dir)
    status = _status(job_dir, mode)
    steps = [s[5:] for s in status if s.startswith("step ")]
    out: dict = {
        "step": steps[-1] if steps else None,
        "finished": any(s in ("done", "error", "end") for s in status),
        "failed": any(s == "error" for s in status),
        "status_tail": status[-1] if status else None,
        "pass": None,
        "max_passes": None,
        "criterion": None,
        "delta": None,
        "target": None,
        "elements": None,
        "element_unit": None,
        "converged": None,
        "modes_GHz": [],
        "last_write": None,
    }
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        job = {}
    settings = job.get("settings") or {}
    results = sorted(job_dir.glob("*_project.aedtresults/*.results"))
    if not results:
        return out
    res = results[0]
    stamps = [p.stat().st_mtime for p in res.iterdir()] if res.is_dir() else []
    out["last_write"] = max(stamps) if stamps else None
    out["elements"], out["element_unit"] = _mesh_size(res)
    conv = _newest(res.glob("*.EMConvData"))
    if conv is not None:
        c = parse_em_conv(conv.read_text(encoding="utf-8", errors="replace"))
        last = c["passes"][-1] if c["passes"] else {}
        delta = next((p["delta"] for p in reversed(c["passes"]) if p["delta"] is not None), None)
        out.update(criterion=c["criterion"], target=c["target"], max_passes=c["max_passes"],
                   converged=c["converged"], delta=delta)
        out["pass"] = last.get("pass")
        if last.get("elements"):
            out["elements"], out["element_unit"] = last["elements"], "tets"
    passes = _q3d_passes(res)
    if passes:
        out["pass"], out["criterion"] = passes[-1]["pass"], "ΔC"
        out["delta"] = next((p["delta"] for p in reversed(passes) if p["delta"] is not None), None)
        out["target"] = settings.get("percent_error")
        out["max_passes"] = settings.get("maximum_passes")
    n, modes = _eigen_modes(res)
    if modes:
        out["modes_GHz"] = modes
        out["pass"] = max(out["pass"] or 0, n)
    if out["max_passes"] is None:
        out["max_passes"] = settings.get("maximum_passes")
    return out


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def echo(text: str) -> None:
    """``print`` a progress line, flushed; on a console that cannot encode it (Windows cp1252: Δ, →, µ) the
    unencodable characters become ``?`` instead of raising (a script solve died on its first progress line)."""
    import sys  # pylint: disable=import-outside-toplevel

    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"), flush=True)


def format_progress(p: dict, elapsed: float | None = None, label: str = "", now: float | None = None) -> str:
    """One status line: ``[aedt 4:30 batch pid 1234] solve · pass 7/14 · 65 324 tets · ΔF 8.09 % (target 0.2 %)``."""
    head = " ".join(x for x in ("aedt", _fmt_elapsed(elapsed) if elapsed is not None else "", label) if x)
    parts = [p.get("step") or "starting"]
    if p.get("pass"):
        parts.append(f"pass {p['pass']}" + (f"/{p['max_passes']}" if p.get("max_passes") else ""))
    if p.get("elements"):
        parts.append(f"{p['elements']:,} {p.get('element_unit') or 'elements'}".replace(",", " "))
    if p.get("criterion") and p.get("delta") is not None:
        unit = "" if p["criterion"] == "ΔS" else " %"
        tgt = f" (target {p['target']:g}{unit})" if p.get("target") is not None else ""
        parts.append(f"{p['criterion']} {p['delta']:.3g}{unit}{tgt}")
    if p.get("converged"):
        parts.append("converged")
    if p.get("modes_GHz"):
        parts.append("f " + ", ".join(f"{f:.4f}" for f in p["modes_GHz"][:6]) + " GHz")
    if p.get("finished"):
        parts.append("FAILED" if p.get("failed") else "finished")
    elif p.get("last_write") and p.get("step") == "solve":
        idle = (now or time.time()) - p["last_write"]
        if idle > 300:
            parts.append(f"no solver output for {_fmt_elapsed(idle)} (meshing / a large pass, or stuck)")
    return f"[{head}] " + " · ".join(parts)
