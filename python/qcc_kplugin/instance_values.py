"""Per-instance values for the layout view: what each qubit and resonator is worth (LOM / FEM / consensus) next to its
target, and a colour for how far off it is. Display only: nothing here writes ``design.json``. No KLayout import, so
it is unit-tested without the GUI (``tests/test_kplugin_instance_values.py``); ``valuesview.py`` draws it.

Sources (all optional, read from the files the flow already writes):

* the targets: ``design.json`` ``targets.<element>.<key>`` (tolerances: :func:`design_io.target_tolerance`);
* the LOM value: ``build/<name>/lom.json`` ``params`` (``"Q1.f_q_GHz"``), written by Run LOM;
* the FEM value: the sidecar's per-instance ``results`` (a parameter whose ``source`` is a field solver), and the
  FEM methods of the consensus;
* the consensus: ``build/<name>/consensus.json`` (``chosen`` value and the relative spread between methods).
"""

from __future__ import annotations

import json
from pathlib import Path

from qcc_kplugin import design_io

# (key in the files, short label, unit): qubit f_q, α; resonator f_r, κ, χ
QUANTITIES = (
    ("f_q_GHz", "f_q", "GHz"),
    ("alpha_MHz", "α", "MHz"),
    ("f_GHz", "f_r", "GHz"),
    ("kappa_MHz", "κ", "MHz"),
    ("chi_MHz", "χ", "MHz"),
)
FEM_WORDS = ("fem", "hfss", "eigen", "driven", "q3d", "palace", "elmer", "sonnet")
GREEN, AMBER, RED, GREY = 0x2E9E4F, 0xE0A400, 0xD03030, 0x808080  # 0xRRGGBB, what KLayout markers take
COLOURS = {"ok": GREEN, "near": AMBER, "off": RED, "none": GREY}
RANK = {"none": 0, "ok": 1, "near": 2, "off": 3}


def is_fem(source) -> bool:
    return any(w in str(source or "").lower() for w in FEM_WORDS)


def grade(value, target, tol) -> str:
    """``"ok"`` (within the tolerance), ``"near"`` (up to twice it), ``"off"`` (beyond), ``"none"`` (no value or no
    target to compare with)."""
    if value is None or target is None or not tol:
        return "none"
    ratio = abs(value - target) / abs(tol)
    return "ok" if ratio <= 1 else "near" if ratio <= 2 else "off"


def _read(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sources(design_path, sidecar: dict | None = None) -> dict:
    """The raw inputs for ``design_path``: ``{"targets", "lom", "results", "consensus"}``."""
    design_path = Path(design_path)
    run = design_path.parent / "build" / design_path.stem
    design = _read(design_path) or {}
    lom = (_read(run / "lom.json") or {}).get("params") or {}
    consensus = _read(run / "consensus.json")
    return {"targets": design.get("targets") or {}, "lom": lom, "results": (sidecar or {}).get("results") or {},
            "consensus": consensus if isinstance(consensus, list) else []}


def collect(src: dict) -> dict[str, list[dict]]:
    """``{element: [row, ...]}``; a row is ``{key, label, unit, lom, fem, consensus, spread_rel, target, tol, value,
    grade}``. ``value`` is what the colour judges: the FEM value, else the LOM value, else the consensus."""
    targets, lom = src.get("targets") or {}, src.get("lom") or {}
    cons = {c.get("param"): c for c in src.get("consensus") or [] if isinstance(c, dict)}
    out: dict[str, list[dict]] = {}
    elements = set(targets) | {k.partition(".")[0] for k in lom} | set(src.get("results") or {})
    elements |= {k.partition(".")[0] for k in cons if k}
    for el in sorted(elements):
        rows = []
        for key, label, unit in QUANTITIES:
            full = f"{el}.{key}"
            fem = None
            for p in ((src.get("results") or {}).get(el) or {}).get("params") or []:
                if str(p.get("key") or "").endswith(key) and is_fem(p.get("source")) and p.get("value") is not None:
                    fem = float(p["value"])
            c = cons.get(full) or {}
            for method, v in (c.get("values") or {}).items():
                if fem is None and is_fem(method) and v is not None:
                    fem = float(v)
            tgt = (targets.get(el) or {}).get(key, c.get("target"))
            row = {"key": key, "label": label, "unit": unit, "lom": lom.get(full), "fem": fem,
                   "consensus": c.get("chosen"), "spread_rel": c.get("spread_rel"), "target": tgt,
                   "tol": design_io.target_tolerance(key, tgt) if tgt is not None else None}
            row["value"] = next((v for v in (fem, row["lom"], row["consensus"]) if v is not None), None)
            if row["value"] is None and tgt is None:
                continue
            row["grade"] = grade(row["value"], tgt, row["tol"])
            rows.append(row)
        if any(r["value"] is not None for r in rows):  # a target alone, with no value yet, draws nothing
            out[el] = rows
    return out


def worst(rows: list[dict]) -> str:
    return max((r["grade"] for r in rows), key=RANK.__getitem__, default="none")


def _num(v, digits: int = 4) -> str:
    return "–" if v is None else f"{v:.{digits}g}"


def line(row: dict) -> str:
    """One text line for the layout: ``f_q 5.228 GHz (target 5.1 ± 0.02)``."""
    text = f"{row['label']} {_num(row['value'])} {row['unit']}"
    if row["value"] is None:
        text = f"{row['label']} no value yet"
    if row["target"] is not None:
        text += f"  (target {_num(row['target'])} ± {_num(row['tol'], 2)})"
    return text


def detail(row: dict) -> tuple[str, str, str, str, str]:
    """Panel columns: LOM, FEM, consensus (± spread), target (± tolerance), grade."""
    cons = _num(row["consensus"])
    if row["consensus"] is not None and row["spread_rel"] is not None:
        cons += f" (spread {100 * row['spread_rel']:.2g} %)"
    target = "" if row["target"] is None else f"{_num(row['target'])} ± {_num(row['tol'], 2)}"
    return _num(row["lom"]), _num(row["fem"]), cons, target, row["grade"]


def readout(name: str, rows: list[dict]) -> str:
    """The panel's read-out for one instance (a few lines)."""
    return "\n".join([name] + ["  " + line(r) for r in rows])
