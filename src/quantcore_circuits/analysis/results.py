"""Solver outputs → one result schema (``job/results/results.json``).

Schema (all optional except ``analysis``)::

    {"analysis": "q3d_cmatrix", "design_hash": ..., "group": ...,
     "cmatrix": {"labels": [...], "unit": "fF", "matrix": [[...]]},       # Maxwell matrix, signal nets only
     "eigenmodes": [{"f_GHz": 5.1, "Q": 1e6}, ...],
     "epr": {...}, "raw_files": [...]}

Parsers read KQC's job outputs (``<sim>_project_results.json``, ``<sim>_project_modes.eig``, pyEPR ``QData_*.csv``)
and Palace's ``postpro`` CSVs.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def net_labels(job: dict, n: int, rows: list[str] | None = None) -> list[str]:
    """Labels for C-matrix rows (KQC excitations 1..n, or the AEDT signal nets ``rows`` such as ``["Net1", "Net2"]``
    in matrix order, as recorded by ``qcc_solve.py``; AEDT net ``Net<k>`` is KQC excitation k).

    Jobs record ``nets`` (excitation → label, probed from KQC's conductor partition at export); older jobs fall back
    to excitation k ↔ port k. Unlabelled conductors are ``floating_<k>``.
    """
    order = list(range(1, n + 1))
    if rows:
        nums = [re.fullmatch(r"Net(\d+)", r) for r in rows]
        if all(nums):
            order = [int(m.group(1)) for m in nums]
    if job.get("nets"):
        nets = {int(k): v for k, v in job["nets"].items()}
        return [nets.get(k, f"floating_{k}") for k in order]
    by_number = {p["number"]: p.get("excitation") or p["name"] for p in job.get("ports", [])}
    return [by_number.get(k, f"floating_{k}") for k in range(1, n + 1)]


def to_maxwell(c) -> tuple[np.ndarray, str]:
    """Return the Maxwell form of a capacitance matrix (positive diagonal, non-positive off-diagonal).

    AEDT Q3D results exported by KQC's scripts carry the mutual capacitances as *positive* off-diagonal entries
    (diagonal = total capacitance of the net, as in the Maxwell matrix); Palace and Elmer write the Maxwell matrix.
    Both are accepted; the returned tag says which convention was found ("maxwell" or "mutual").
    """
    c = np.asarray(c, dtype=float)
    off = c - np.diag(np.diag(c))
    tol = 1e-9 * (float(np.abs(c).max()) or 1.0)
    if (off >= -tol).all() and (off > tol).any():
        return np.diag(np.diag(c)) - off, "mutual"
    return c, "maxwell"


def parse_cmatrix_json(path: Path) -> np.ndarray:
    data = json.loads(path.read_text(encoding="utf-8"))
    mat = data.get("CMatrix") or data.get("Cs")
    if mat is None:
        raise ValueError(f"{path}: no CMatrix")
    return np.asarray(mat, dtype=float)


def parse_eig(path: Path) -> list[dict]:
    """HFSS ``ExportEigenmodes`` text. Tolerant: accepts ``idx f [Q]`` rows (GHz or Hz), ``(re, im)`` pairs and AEDT
    2024's ``idx  f_re + f_im j  Q`` rows (``Q`` = f_re / 2 f_im when the column is missing)."""
    modes = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cplx = re.search(rf"\(\s*({_NUM})\s*,\s*({_NUM})\s*\)", line)
        aedt = re.match(rf"^\s*(\d+)\s+({_NUM})\s*([-+])\s*({_NUM})\s*j\s*({_NUM})?\s*$", line)
        nums = [float(x) for x in re.findall(_NUM, line)]
        if not nums or not line.strip()[0].isdigit():
            continue
        if aedt:
            re_f = float(aedt.group(2))
            im_f = float(aedt.group(4)) * (-1 if aedt.group(3) == "-" else 1)
            f = re_f / 1e9 if re_f > 1e6 else re_f
            q = float(aedt.group(5)) if aedt.group(5) else (re_f / (2 * im_f) if im_f else float("inf"))
            modes.append({"mode": int(aedt.group(1)), "f_GHz": f, "Q": q})
            continue
        if cplx:
            re_f, im_f = float(cplx.group(1)), float(cplx.group(2))
            f = re_f / 1e9 if re_f > 1e6 else re_f
            q = re_f / (2 * im_f) if im_f else float("inf")
        elif len(nums) >= 2:
            f = nums[1] / 1e9 if nums[1] > 1e6 else nums[1]
            q = nums[2] if len(nums) > 2 else None
        else:
            continue
        modes.append({"mode": int(nums[0]), "f_GHz": f, "Q": q})
    return modes


def parse_palace_terminal_c(path: Path) -> np.ndarray:
    """Palace ``terminal-C.csv``: first column terminal index, then C[i][j] in F."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r and not r[0].strip().startswith("#")]
    body = [r for r in rows if re.fullmatch(_NUM, r[0].strip())]
    return np.asarray([[float(x) for x in r[1:]] for r in body], dtype=float)


def parse_palace_eig(path: Path) -> list[dict]:
    """Palace ``eig.csv``: m, Re{f} (GHz), Im{f} (GHz), Q, ..."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r]
    out = []
    for r in rows:
        if not re.fullmatch(_NUM, r[0].strip()):
            continue
        vals = [float(x) for x in r]
        out.append({"mode": int(vals[0]), "f_GHz": vals[1], "Q": vals[3] if len(vals) > 3 else None})
    return out


def parse_touchstone(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """Touchstone v1 ``.sNp`` (as KQC's ``export_solution_data.py`` writes ``<sim>_SMatrix.sNp``).

    Returns ``(f_GHz, S, z0)`` with ``S[k, i, j]`` complex (S_ij at frequency k, ports 1-based in the file, 0-based
    here). Handles the ``# <unit> S <MA|DB|RI> R <z0>`` option line and values wrapped over several lines.
    """
    n = int(re.search(r"\.s(\d+)p$", path.name.lower()).group(1))
    unit, fmt, z0 = "GHZ", "MA", 50.0
    nums: list[float] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            tok = line[1:].upper().split()
            unit = next((t for t in tok if t in ("HZ", "KHZ", "MHZ", "GHZ")), unit)
            fmt = next((t for t in tok if t in ("MA", "DB", "RI")), fmt)
            if "R" in tok and tok.index("R") + 1 < len(tok):
                z0 = float(tok[tok.index("R") + 1])
            continue
        nums.extend(float(x) for x in line.split())
    per = 1 + 2 * n * n
    data = np.asarray(nums[: len(nums) // per * per]).reshape(-1, per)
    scale = {"HZ": 1e-9, "KHZ": 1e-6, "MHZ": 1e-3, "GHZ": 1.0}[unit]
    f = data[:, 0] * scale
    a, b = data[:, 1::2], data[:, 2::2]
    if fmt == "RI":
        vals = a + 1j * b
    elif fmt == "DB":
        vals = 10 ** (a / 20) * np.exp(1j * np.radians(b))
    else:
        vals = a * np.exp(1j * np.radians(b))
    S = vals.reshape(-1, n, n)
    if n == 2:  # Touchstone 2-port order is S11 S21 S12 S22 (column-major)
        S = S.transpose(0, 2, 1)
    return f, S, z0


def fit_notch(f_GHz, s21, min_depth: float = 1e-3, window: float = 25.0) -> dict:
    """Fit a notch (hanger) resonance to complex S21 (Khalil/Probst model, real-coupling approximation).

    S21 = A e^{iα} [1 − (Q_l/Q_c) e^{iφ} / (1 + 2i Q_l (f/f0 − 1))]. Returns f0, Q_l, Q_c, Q_i and the linewidths
    κ = f0/Q_l, κ_ext = f0/Q_c (MHz) — κ_ext is what the LOM hanger coupling (``HANGER`` k) predicts. A cable delay
    is not removed: export S-parameters de-embedded to the ports (KQC does by default). Raises ``ValueError`` when
    the |S21| dip is shallower than ``min_depth`` (no resonance in the band); fits ±``window`` linewidths around the
    dip when the band is wider.
    """
    from scipy.optimize import least_squares  # pylint: disable=import-outside-toplevel

    f = np.asarray(f_GHz, dtype=float)
    s = np.asarray(s21, dtype=complex)
    k0 = int(np.argmin(np.abs(s)))
    depth = 1 - abs(s[k0]) / max(np.abs(s).max(), 1e-12)
    if depth < min_depth:
        raise ValueError(f"no resonance in the trace (|S21| dip {depth:.2e} < {min_depth:g})")
    width = _dip_width(f, s, k0)
    # a band much wider than the line: fit ±window linewidths around the dip (keeps the baseline local)
    keep = np.abs(f - f[k0]) <= window * width
    if keep.sum() >= 50 and keep.sum() < len(f):
        f, s = f[keep], s[keep]
        k0 = int(np.argmin(np.abs(s)))
    f0 = f[k0]
    ql0 = f0 / width

    def model(x):
        a, alpha, fr, ql, qc, phi = x
        return a * np.exp(1j * alpha) * (1 - (ql / qc) * np.exp(1j * phi) / (1 + 2j * ql * (f / fr - 1)))

    def residual(x):
        d = model(x) - s
        return np.concatenate([d.real, d.imag])

    x0 = [np.abs(s).max(), float(np.angle(s[0])), f0, ql0, ql0 / max(depth, 1e-3), 0.0]
    lo = [0, -np.pi * 4, f.min(), 1.0, 1.0, -np.pi / 2]
    hi = [10, np.pi * 4, f.max(), 1e9, 1e10, np.pi / 2]
    sol = least_squares(residual, x0, bounds=(lo, hi), x_scale="jac")
    a, alpha, fr, ql, qc, phi = sol.x
    qc_re = qc / np.cos(phi)  # effective real coupling Q
    inv_qi = 1 / ql - 1 / qc_re
    return {
        "f0_GHz": float(fr),
        "Q_loaded": float(ql),
        "Q_coupling": float(qc_re),
        "Q_internal": float(1 / inv_qi) if inv_qi > 0 else float("inf"),
        "kappa_MHz": float(fr / ql * 1e3),
        "kappa_ext_MHz": float(fr / qc_re * 1e3),
        "phi": float(phi),
        "residual_rms": float(np.sqrt(np.mean(np.abs(model(sol.x) - s) ** 2))),
    }


def _dip_width(f: np.ndarray, s: np.ndarray, k0: int) -> float:
    """Full width at half depth (in |S21|²) of the dip at ``k0``, walking out from it — the contiguous dip only, so
    a second notch elsewhere in the band does not widen it (fem_loop, 2026-11-04)."""
    a = np.abs(s) ** 2
    level = (a.max() + a[k0]) / 2
    i = j = k0
    while i > 0 and a[i - 1] <= level:
        i -= 1
    while j < len(a) - 1 and a[j + 1] <= level:
        j += 1
    step = f[1] - f[0] if len(f) > 1 else 1e-6
    return max(f[j] - f[i], step)


def fit_notches(f_GHz, s21, min_depth: float = 1e-2, window: float = 25.0, max_notches: int = 8) -> list[dict]:
    """Every notch in a trace (several resonators on one feedline), lowest frequency first: dips of prominence
    ≥ ``min_depth`` (relative to the baseline), each fitted with :func:`fit_notch` on its own stretch of the band
    (between the midpoints to its neighbours)."""
    from scipy.signal import find_peaks  # pylint: disable=import-outside-toplevel

    f = np.asarray(f_GHz, dtype=float)
    s = np.asarray(s21, dtype=complex)
    mag = np.abs(s)
    dips, _ = find_peaks(-mag, prominence=min_depth * float(np.median(mag)))
    dips = sorted(dips, key=lambda k: mag[k])[:max_notches]  # the deepest ones
    dips = sorted(dips)
    out = []
    for n, k in enumerate(dips):
        lo = 0 if n == 0 else (dips[n - 1] + k) // 2
        hi = len(f) if n == len(dips) - 1 else (k + dips[n + 1]) // 2
        try:
            fit = fit_notch(f[lo:hi], s[lo:hi], min_depth=min_depth / 10, window=window)
        except (ValueError, RuntimeError):
            continue
        fit["depth"] = float(1 - mag[k] / max(mag.max(), 1e-12))
        out.append(fit)
    return out


def parse_convergence(path: Path) -> dict:
    """AEDT ``ExportConvergence`` text: passes, solved elements, the criterion per pass and whether it converged."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    rows = re.findall(rf"^\s*(\d+)\|\s*(\d+)\|\s*({_NUM}|N/A)\|", text, flags=re.M)
    crit = re.search(r"Criterion\s*:\s*(.+)", text)
    target = re.search(rf"Target\s*:\s*({_NUM})", text)
    return {
        "converged": bool(re.search(r"Converged\s*:\s*Yes", text)),
        "criterion": crit.group(1).strip() if crit else None,
        "target": float(target.group(1)) if target else None,
        "passes": [int(r[0]) for r in rows],
        "elements": [int(r[1]) for r in rows],
        "delta": [None if r[2] == "N/A" else float(r[2]) for r in rows],
    }


def parse_report_csv(path: Path) -> dict[str, list[float]]:
    """An AEDT report exported as CSV (e.g. KQC's eigenmode "Solution Convergence": Pass, re(Mode(n)))."""
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = [r for r in csv.reader(f) if r]
    head, body = rows[0], rows[1:]
    out: dict[str, list[float]] = {}
    for i, name in enumerate(head):
        unit = re.search(r"\[([A-Za-z]*)\]\s*$", name)
        scale = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}.get(unit.group(1).lower(), 1.0) if unit else 1.0
        key = re.sub(r"\s*\[[^\]]*\]\s*$", "", name).strip().strip('"')
        vals = []
        for r in body:
            try:
                vals.append(float(r[i]) * scale)
            except (ValueError, IndexError):
                vals.append(float("nan"))
        out[key] = vals
    return out


def extrapolate_mesh(elements, values, last: int = 5) -> dict | None:
    """f(N) = f∞ − C N^(−p) fitted to the last ``last`` adaptive passes (N = solved elements): the mesh-converged
    estimate of a quantity whose adaptive run stopped before its criterion. None if the fit is not meaningful."""
    from scipy.optimize import curve_fit  # pylint: disable=import-outside-toplevel

    n = np.asarray(elements[-last:], dtype=float)
    f = np.asarray(values[-last:], dtype=float)
    if len(n) < 4 or not np.all(np.isfinite(f)):
        return None
    try:
        x = n / n[-1]
        (finf, c, p), _ = curve_fit(
            lambda x, a, b, q: a - b * x ** (-q), x, f, p0=(f[-1], f[-1] - f[0], 1.0), maxfev=20000
        )
    except (RuntimeError, ValueError):
        return None
    if not (0.05 < p < 5) or not np.isfinite(finf):
        return None
    return {
        "value": float(finf),
        "last": float(f[-1]),
        "change": float(finf - f[-1]),
        "p": float(p),
        "passes_used": len(n),
    }


def fem_kappa(results: dict, resonators: dict[str, float], max_residual: float = 0.05) -> dict[str, dict]:
    """External linewidth κ_ext/2π per resonator from a solved job.

    Driven jobs: the S_ij notch fit whose f0 is closest to the resonator's expected frequency (``resonators``: name →
    GHz, e.g. its λ/4 estimate). Eigenmode jobs (feedline terminated in 50 Ω): f/Q_ext of the nearest mode that is
    not a qubit mode (junction participation < 0.5), with the bulk-dielectric loss removed when the EPR substrate
    participation is known. Returns name → ``{"kappa_MHz", "f_GHz", "Q_ext", "source"}``.
    """
    out: dict[str, dict] = {}
    sp = results.get("sparams") or {}
    fits = [
        (k, v)
        for k, v in (sp.get("notch") or {}).items()
        if v.get("residual_rms", 1.0) < max_residual and np.isfinite(v.get("kappa_ext_MHz", np.nan))
    ]
    for r, f_guess in sorted(resonators.items(), key=lambda x: x[1]):
        if not fits:
            break
        k, v = min(fits, key=lambda kv: abs(kv[1]["f0_GHz"] - f_guess))
        fits.remove((k, v))
        out[r] = {
            "kappa_MHz": v["kappa_ext_MHz"],
            "f_GHz": v["f0_GHz"],
            "Q_ext": v["Q_coupling"],
            "source": f"driven {k} notch fit ({sp.get('file')})",
        }
    if out:
        return out
    eig = results.get("eigenmodes") or []
    epr = results.get("epr") or {}
    p, q_d = epr.get("p_mj"), epr.get("Q_dielectric")
    free = [i for i in range(len(eig)) if not p or i >= len(p) or max(p[i]) < 0.5]
    for r, f_guess in sorted(resonators.items(), key=lambda x: x[1]):
        if not free:
            break
        i = min(free, key=lambda i: abs(eig[i]["f_GHz"] - f_guess))
        free.remove(i)
        q = eig[i].get("Q")
        if not q or not np.isfinite(q):
            continue
        qd = q_d[i] if q_d and i < len(q_d) else None
        q_ext = 1 / (1 / q - 1 / qd) if qd and 1 / q > 1 / qd else q
        out[r] = {
            "kappa_MHz": eig[i]["f_GHz"] / q_ext * 1e3,
            "f_GHz": eig[i]["f_GHz"],
            "Q_ext": q_ext,
            "source": f"eigenmode {eig[i].get('mode', i + 1)} Q (50 Ω-terminated feedline)",
        }
    return out


def combine_jobs(primary: str | Path, others: list[str | Path], out_dir: str | Path, same_design: bool = True) -> Path:
    """A job directory that ``loop.analyse`` / ``circuit.fill`` read as one: the ``primary`` job's ``job.json``
    (C-matrix metadata: ports, stub length, stack) with its results, plus the ``eigenmodes`` / ``epr`` / ``sparams``
    of the ``others``. E.g. Q3D C-matrix → LOM estimators and eigenmode EPR → pyEPR in one consensus.
    ``results.json`` records where each part came from (``combined_from``). The others must come from the same design
    (hash) unless ``same_design=False`` (e.g. a copy that only adds a sim group); mismatches are then listed."""
    primary, out = Path(primary), Path(out_dir)
    job = json.loads((primary / "job.json").read_text(encoding="utf-8"))
    res = json.loads((primary / "results" / "results.json").read_text(encoding="utf-8"))
    sources = {k: str(primary) for k in ("cmatrix", "eigenmodes", "epr", "sparams") if k in res}
    mismatch = []
    for other in map(Path, others):
        ojob = json.loads((other / "job.json").read_text(encoding="utf-8"))
        if ojob["design_hash"] != job["design_hash"]:
            if same_design:
                raise ValueError(f"{other}: design hash {ojob['design_hash']} differs from {job['design_hash']}")
            mismatch.append(f"{other.name}: design hash {ojob['design_hash']} (primary {job['design_hash']})")
        ores = json.loads((other / "results" / "results.json").read_text(encoding="utf-8"))
        for key in ("eigenmodes", "epr", "sparams"):
            if key in ores:
                res[key] = ores[key]
                sources[key] = str(other)
    res["combined_from"] = sources
    if mismatch:
        res["combined_hash_mismatch"] = mismatch
    (out / "results").mkdir(parents=True, exist_ok=True)
    job = {**job, "status": "done", "combined_from": sorted(set(sources.values()))}
    (out / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    (out / "results" / "results.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    return out


def read_extras(job_dir: str | Path) -> dict:
    """``<sim>_project_qcc.json`` written by ``qcc_solve.py`` inside AEDT ({} if absent); ``_file`` = its name."""
    hits = sorted(Path(job_dir).glob("*_project_qcc.json"))
    if not hits:
        return {}
    data = json.loads(hits[0].read_text(encoding="utf-8"))
    data["_file"] = hits[0].name
    return data


def signal_nets(extras: dict) -> list[str]:
    """Q3D signal nets in ``GetExcitations`` order (KQC's ``export_solution_data.py`` C-matrix row order)."""
    exc = extras.get("excitations") or []
    return [name for name, kind in zip(exc[::2], exc[1::2]) if kind == "SignalNet"]


def smatrix_ports(job: dict, extras: dict, n: int) -> list[int]:
    """Port numbers of the S-matrix columns: AEDT's excitation order (``"2"``, ``"3"`` …) when recorded, else the
    job's non-junction ports (``qcc_solve.py`` turns driven junction ports into lumped L/C)."""
    exc = extras.get("excitations") or []
    nums = []
    for name in exc:
        m = re.fullmatch(r"(?:Port)?(\d+)(?:_T\d+)?", str(name))
        if m and int(m.group(1)) not in nums:
            nums.append(int(m.group(1)))
    if len(nums) == n:
        return nums
    ports = sorted(job.get("ports", []), key=lambda p: p["number"])
    real = [p["number"] for p in ports if p.get("kind") != "junction"]
    return real if len(real) == n else [p["number"] for p in ports][:n]


def _junction_names(job: dict, numbers: list[str]) -> list[str]:
    by_number = {str(p["number"]): p.get("name") for p in job.get("ports", [])}
    return [by_number.get(str(n), f"junction_{n}") for n in numbers]


def collect_results(job_dir: str | Path) -> dict:
    """Parse whatever results exist in ``job_dir`` and write ``results/results.json``."""
    job_dir = Path(job_dir)
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    out = {"analysis": job["analysis"], "design_hash": job["design_hash"], "group": job["group"], "raw_files": []}

    extras = read_extras(job_dir)
    if extras:
        out["aedt"] = {k: extras.get(k) for k in ("aedt", "python", "tool", "solve_seconds", "convergence_file")}
        out["raw_files"].append(extras["_file"])
    cmats = sorted(job_dir.glob("*_project_results.json"))
    for path in cmats:
        try:
            c = parse_cmatrix_json(path)
        except ValueError:
            continue
        c, convention = to_maxwell(c)
        rows = signal_nets(extras)
        out["cmatrix"] = {
            "labels": net_labels(job, len(c), rows if len(rows) == len(c) else None),
            "unit": "fF",
            "matrix": (c * 1e15).tolist(),
            "form": "maxwell",
            "source_convention": convention,
        }
        if len(rows) == len(c):
            out["cmatrix"]["aedt_nets"] = rows
        out["raw_files"].append(path.name)
    for path in sorted(job_dir.glob("*_project_modes.eig")):
        out["eigenmodes"] = parse_eig(path)
        out["raw_files"].append(path.name)
    for path in sorted(job_dir.glob("*_project_convergence.txt")):
        out["convergence"] = {"file": path.name, **parse_convergence(path)}
        out["raw_files"].append(path.name)
    for _name, fname in sorted((extras.get("convergence_reports") or {}).items()):
        path = job_dir / fname
        if not path.exists() or "eigenmodes" not in out:
            continue
        table = parse_report_csv(path)
        conv = out.setdefault("convergence", {"passes": []})
        cols = {k: v for k, v in table.items() if re.search(r"Mode\((\d+)\)", k)}
        # AEDT 2024 writes the header unit as "[]" with the values in Hz
        cols = {k: [x / 1e9 for x in v] if np.nanmedian(v) > 1e6 else v for k, v in cols.items()}
        conv["mode_GHz"] = {re.search(r"Mode\((\d+)\)", k).group(1): v for k, v in cols.items()}
        conv["report"] = fname
        elements = conv.get("elements") or []
        for mode in out["eigenmodes"]:
            series = conv["mode_GHz"].get(str(mode["mode"]))
            if series and len(series) == len(elements):
                mode["f_extrapolated"] = extrapolate_mesh(elements, series)
        out["raw_files"].append(fname)
    for path in sorted(job_dir.glob("QData_*.csv")):  # KQC's run_pyepr_t1_estimate.py output (not run by qcc)
        import pandas as pd  # pylint: disable=import-outside-toplevel

        out["epr_kqc"] = pd.read_csv(path).to_dict(orient="list")
        out["raw_files"].append(path.name)
    if extras.get("epr", {}).get("modes"):
        from quantcore_circuits.analysis.epr import epr_analysis  # pylint: disable=import-outside-toplevel

        eig = out.get("eigenmodes") or []
        n = len(extras["epr"]["modes"])
        freqs = [m["f_GHz"] for m in eig[:n]] if len(eig) >= n else None
        tan_d = (job.get("settings", {}).get("pyepr") or {}).get("substrate_loss_tangent")
        try:
            out["epr"] = epr_analysis(
                extras["epr"], freqs, Q=[m.get("Q") for m in eig[:n]] if freqs else None, tan_delta=tan_d
            )
            out["epr"]["junction_names"] = _junction_names(job, out["epr"]["junctions"])
        except Exception as e:  # noqa: BLE001  (keep the other results if the EPR step cannot evaluate)
            out["epr"] = {"error": f"{type(e).__name__}: {e}"}
    palace_c = next(iter(job_dir.glob("**/terminal-C.csv")), None)
    if palace_c is not None:
        c, convention = to_maxwell(parse_palace_terminal_c(palace_c))
        out["cmatrix"] = {
            "labels": net_labels(job, len(c)),
            "unit": "fF",
            "matrix": (c * 1e15).tolist(),
            "form": "maxwell",
            "source_convention": convention,
        }
        out["raw_files"].append(str(palace_c.relative_to(job_dir)))
    for path in sorted(job_dir.glob("*_SMatrix*.s*p")):  # HFSS driven (hfss_driven): S-parameters → notch fits
        f, S, z0 = parse_touchstone(path)
        numbers = smatrix_ports(job, extras, S.shape[1])
        by_number = {p["number"]: p.get("name") for p in job.get("ports", [])}
        labels = [by_number.get(n, str(n)) for n in numbers]
        out["sparams"] = {
            "file": path.name,
            "ports": labels,
            "port_numbers": numbers,
            "z0_ohm": z0,
            "f_GHz": [float(f.min()), float(f.max())],
            "n_points": len(f),
        }
        if S.shape[1] >= 2:
            # one fit per notch: "S21" is the deepest (the single-resonator case as before), further notches of
            # the same trace (several resonators on one feedline) are "S21#2", "S21#3", … (deepest first)
            fits = {}
            for i in range(S.shape[1]):
                for j in range(i):
                    found = sorted(fit_notches(f, S[:, i, j]), key=lambda v: -v["depth"])
                    if not found:
                        try:
                            found = [fit_notch(f, S[:, i, j])]
                        except (ValueError, RuntimeError):
                            continue
                    for n, fit in enumerate(found):
                        fits[f"S{i + 1}{j + 1}" + (f"#{n + 1}" if n else "")] = fit
            out["sparams"]["notch"] = fits
        out["raw_files"].append(path.name)
    palace_eig = next(iter(job_dir.glob("**/eig.csv")), None)
    if palace_eig is not None:
        out["eigenmodes"] = parse_palace_eig(palace_eig)
        out["raw_files"].append(str(palace_eig.relative_to(job_dir)))

    (job_dir / "results").mkdir(exist_ok=True)
    (job_dir / "results" / "results.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out
