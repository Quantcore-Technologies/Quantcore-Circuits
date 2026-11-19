"""Status table of every design notebook → ``docs/designs/STATUS.md``.

    python scripts/design_status.py            # all of examples/designs/<group>/<id>.json
    python scripts/design_status.py legacy kqc # only these groups

Per design, from the saved ``<id>.json`` and the executed ``<id>.ipynb`` (nothing is re-executed):

* **notebook** — executed (every code cell has run, no error output) / errors / no saved outputs / missing;
* **DRC** — fast DRC (``assembly.drc.check(..., netlist=False)``) errors / warnings, with the error rules;
* **components** — instances (+ chip launchers), routes; **LOM nodes** — non-ground nodes of the whole-chip netlist and
  unconnected ports;
* **LOM simulation** — f_q and f_r ranges parsed from the notebook's saved ``groups_md`` tables (QuTiP dressed values),
  or "junction table" for test-structure chips;
* **FEM jobs** — sim groups whose declared analyses all export (``build_simulation`` + ``export_job``, no solve) with
  ports and named nets;
* **PNGs** — images shown in the notebook (whether they were *looked at* is in the agents' status tables).
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGNS = ROOT / "examples" / "designs"
OUT = ROOT / "docs" / "designs" / "STATUS.md"


def notebook_state(path: Path) -> tuple[str, list[str], int]:
    """(state, markdown/text outputs, number of images)."""
    if not path.exists():
        return "missing", [], 0
    nb = json.loads(path.read_text(encoding="utf-8"))
    code = [c for c in nb.get("cells", []) if c.get("cell_type") == "code" and "".join(c.get("source", [])).strip()]
    texts, images, errors, unrun = [], 0, 0, 0
    for c in code:
        if c.get("execution_count") is None:
            unrun += 1
        for o in c.get("outputs", []):
            if o.get("output_type") == "error":
                errors += 1
            data = o.get("data", {})
            if "image/png" in data:
                images += 1
            for key in ("text/markdown", "text/plain"):
                if key in data:
                    v = data[key]
                    texts.append("".join(v) if isinstance(v, list) else str(v))
            if o.get("output_type") == "stream":
                texts.append("".join(o.get("text", [])))
    if errors:
        return "errors", texts, images
    state = "no saved outputs" if unrun == len(code) else ("partly run" if unrun else "executed")
    return state, texts, images


def _table_column(texts: list[str], header: str) -> list[float]:
    """Numbers in the column ``header`` of every markdown table in ``texts`` (bracketed targets dropped)."""
    out = []
    for t in texts:
        lines = [x.strip() for x in t.splitlines() if x.strip().startswith("|")]
        for i, line in enumerate(lines):
            cols = [c.strip() for c in line.strip("|").split("|")]
            if header in cols:
                k = cols.index(header)
                for row in lines[i + 2 :]:
                    cells = [c.strip() for c in row.strip("|").split("|")]
                    if len(cells) != len(cols):
                        break
                    m = re.match(r"^-?\d+(\.\d+)?", cells[k])
                    if m:
                        out.append(float(m.group(0)))
    return out


def _span(vals: list[float]) -> str:
    if not vals:
        return "–"
    lo, hi = min(vals), max(vals)
    return f"{lo:.3g}" if abs(hi - lo) < 1e-9 else f"{lo:.3g}–{hi:.3g}"


def lom_sim(texts: list[str]) -> str:
    fq, fr = _table_column(texts, "f_q (GHz)"), _table_column(texts, "f_r (GHz)")
    if fq or fr:
        return f"f_q {_span(fq)} / f_r {_span(fr)} GHz"
    if any("L_J" in t and "R_n" in t for t in texts):
        return "junction table"
    modes = _table_column(texts, "f (GHz)")
    return f"modes {_span(modes)} GHz" if modes else "–"


def fem_jobs(path: Path, design) -> str:
    from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=import-outside-toplevel

    groups = list(design.sim_groups)
    if not groups:
        return "no sim groups"
    ok, bad = 0, []
    with tempfile.TemporaryDirectory() as tmp:
        for g in groups:
            try:
                for a in design.sim_groups[g].analyses:
                    s = build_simulation(path, g, a)
                    job = export_job(s, Path(tmp) / f"{g}_{a}", overwrite=True)
                    meta = json.loads((Path(job) / "job.json").read_text(encoding="utf-8"))
                    if not meta.get("ports") or not all(meta.get("nets", {}).values()):
                        raise ValueError("no ports / unnamed nets")
                ok += 1
            except Exception as e:  # noqa: BLE001
                bad.append(f"{g} ({type(e).__name__})")
    return f"{ok}/{len(groups)}" + (f" — failed: {', '.join(bad[:3])}" + (" …" if len(bad) > 3 else "") if bad else "")


def row(path: Path) -> dict:
    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.drc import check  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom import lom_from_design  # pylint: disable=import-outside-toplevel

    group, ident = path.parent.relative_to(DESIGNS).as_posix(), path.stem
    nb_state, texts, images = notebook_state(path.with_suffix(".ipynb"))
    v1 = path.with_name(path.stem + ".v1.ipynb")  # the notebook before its v2 rewrite, outputs kept (nb-plan)
    if nb_state == "no saved outputs" and v1.exists():
        v1_state, texts, images = notebook_state(v1)
        nb_state = f"v2 not run yet; values from the v1 run ({v1_state})"
    out = {"group": group, "id": ident, "notebook": nb_state, "pngs": images}
    t0 = time.perf_counter()
    try:
        design = load_design(path)
        result = build(path)
        report = check(result, netlist=False)
        rules = sorted({i.rule for i in report.errors})
        out["drc"] = f"{len(report.errors)} / {len(report.warnings)}" + (f" ({', '.join(rules)})" if rules else "")
        launchers = design.chip.launchers
        n_l = len(launchers.get("assign", {})) if isinstance(launchers, dict) else (1 if launchers else 0)
        extra = " + launchers" if n_l else ""
        out["components"] = f"{len(design.instances)}{extra}, {len(design.routes)} routes"
        lb = lom_from_design(design)
        nodes = sum(1 for s in lb.model.nodes.values() if not s.ground)
        out["lom"] = f"{nodes}" + (f" ({len(lb.unconnected)} free ports)" if lb.unconnected else "")
        out["fem"] = fem_jobs(path, design)
    except Exception as e:  # noqa: BLE001
        out.update(drc=f"build failed: {type(e).__name__}", components="–", lom="–", fem="–")
    out["sim"] = lom_sim(texts)
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def main(argv: list[str]) -> None:
    import os  # pylint: disable=import-outside-toplevel

    os.chdir(ROOT)
    os.environ.setdefault("QCC_LIVE", "0")
    groups = argv or sorted(p.name for p in DESIGNS.iterdir() if p.is_dir() and not p.name.startswith("_"))
    rows = []
    for g in groups:
        for path in sorted((DESIGNS / g).rglob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not str(raw.get("schema", "")).startswith(("qcc/", "qcd/")):
                continue
            r = row(path)
            rows.append(r)
            print(f"{r['group']}/{r['id']}: {r['notebook']}, DRC {r['drc']}, FEM {r['fem']}", flush=True)
    lines = [
        "# Design notebooks: status",
        "",
        f"Generated by `python scripts/design_status.py` on {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        "from the saved JSONs and the notebooks' saved outputs (nothing re-executed; a notebook saved without",
        "outputs, as the repository keeps them, shows \"no saved outputs\" and \"–\" for its LOM values). DRC = fast",
        "DRC errors / warnings; FEM = sim groups whose declared analyses all export with ports and named nets (no",
        "solver); LOM sim = QuTiP dressed values from the notebook's saved tables. Whether each snapshot was",
        "looked at is recorded in the notebook. *Free ports* are component",
        "ports nothing is wired to (unused claws, open pads); each still maps to a LOM node",
        "(`tests/test_examples.py` node-connected check).",
        "",
        "| design | group | notebook | DRC (err / warn) | #components | #LOM nodes | LOM simulation | FEM jobs "
        "| PNGs |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['group']} | {r['notebook']} | {r['drc']} | {r['components']} | {r['lom']} "
            f"| {r['sim']} | {r['fem']} | {r['pngs']} |"
        )
    if not argv:
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("wrote", OUT)
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
