"""Check exported FEM job folders, or audit the simulation export of every catalog cell (export only, never solves).

    python scripts/check_sim_export.py check <job dir> [<job dir> ...]
        geometry checks of exported Ansys jobs (quantcore_circuits.sim_tools.geometry_check): nets disjoint, no
        point / edge contacts inside a net, junction ports with a KQC-built polygon in the gap, no floating metal to
        the domain boundary. Exit code 1 when a job has errors.

    python scripts/check_sim_export.py audit --out <scratch dir> [--cells Flipmon,Xmon] [--analyses q3d_cmatrix,...]
        every catalog cell (``qcc components``) that has a port or a junction, or is a qubit / resonator / coupler /
        junction, is placed alone in a small scratch design (qubits: two BondPads, a feedline and a hanger readout
        from their readout port, exported like the GUI's Simulate = ``guiflow.export_manual``; other cells: inline
        between two BondPads, sim group = the cell, the lines cut by the box), exported for each analysis and checked.
        Also records KQC's "Unable to create polygon for port" log lines. Writes ``<out>/audit.json`` (one row per
        cell × analysis) and ``<out>/audit_raw.md``. Never starts AEDT.

Run from the repository root with the project environment (``qcd``). Set ``QCC_LIVE=0`` / ``QCC_TRACK=0`` (done here).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
import traceback
import warnings
from pathlib import Path

os.environ.setdefault("QCC_LIVE", "0")
os.environ.setdefault("QCC_TRACK", "0")
os.environ.setdefault("QCC_KLAYOUT_GUI", "0")

BOX = 10000.0
Y_LINE = 5000.0  # feedline / inline-cell height
Y_QUBIT = 7000.0  # qubit centre (readout down to the feedline)
LJ = {"Lj_nH": 10.0, "Cj_fF": 2.0}
SKIP_CATEGORIES = {"chip", "marker", "shape"}  # no ports, no circuit: nothing to simulate
ALWAYS_CATEGORIES = {"qubit", "resonator", "coupler", "junction"}
NOT_READOUT = re.compile(r"squid_|drive|flux|gate|charge|control|fbl|pump|common", re.I)
READOUT_ORDER = ("read", "rdout", "claw", "cplr", "coupler", "cpl", "right", "pin", "bus", "a", "")
# cells that need parameters or neighbours to have a readout at all
QUBIT_PARAMS = {"TransmonTaperedInsets": {"connection_pads": {"readout": {}}}}


# ---- check ---------------------------------------------------------------------------------------------------------
def cmd_check(jobs: list[str]) -> int:
    from quantcore_circuits.sim_tools.geometry_check import check_job  # pylint: disable=import-outside-toplevel

    bad = 0
    for job in jobs:
        r = check_job(job)
        status = "FAIL" if r["errors"] else "ok"
        print(f"{status}  {job}  ({r['nets']} signal nets, {r['objects']} metal objects)")
        for e in r["errors"]:
            print(f"   error:   {e}")
        for w in r["warnings"]:
            print(f"   warning: {w}")
        bad += bool(r["errors"])
    return 1 if bad else 0


# ---- audit: scratch designs ----------------------------------------------------------------------------------------
def _angle(v) -> float | None:
    return None if v is None else math.degrees(math.atan2(v.y, v.x))


def _ports(comp, params: dict) -> dict:
    try:
        return comp.ports_of(**params)
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        return {}


def _cpw_ports(ports: dict) -> list[str]:
    return [n for n, p in ports.items() if p.dir is not None and not NOT_READOUT.search(n)]


def _readout(ports: dict) -> str | None:
    cands = _cpw_ports(ports)
    for key in READOUT_ORDER:
        for n in cands:
            if key in n.lower():
                return n
    return None


def _pads(y: float) -> dict:
    return {
        "BP_W": {"cell": "BondPad", "place": {"at": [800.0, y], "rot": 270.0}},
        "BP_E": {"cell": "BondPad", "place": {"at": [BOX - 800.0, y], "rot": 90.0}},
    }


def _base(name: str) -> dict:
    return {"schema": "qcc/0.1", "name": name, "pdk": "quantcore_nb_sapphire_v1",
            "chip": {"box": [0.0, 0.0, BOX, BOX], "params": {"name_chip": "AUDIT"}},
            "instances": {}, "routes": {}, "sim_groups": {}}


def _rot_to(ports: dict, port: str, want: float) -> float:
    a = _angle(ports[port].dir)
    return (want - a) % 360.0


def scratch_designs(comp) -> list[tuple[str, dict, str]]:
    """``[(context, design dict, kind)]`` to try in order (the first that builds is used); kind "qubit" | "cell"."""
    from quantcore_circuits.design import Design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.subset import has_junction  # pylint: disable=import-outside-toplevel

    ref = comp.ref
    params = dict(QUBIT_PARAMS.get(ref, {}))
    ports = _ports(comp, params)
    junction = "squid_a" in ports or "squid_b" in ports or comp.category in ("qubit",)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", ref).strip("_").lower()
    out = []
    alone = _base(f"audit_{safe}")
    alone["instances"]["X"] = {"cell": ref, "params": params, "place": {"at": [BOX / 2, Y_QUBIT], "rot": 0.0},
                               **({"junction": LJ} if junction else {})}
    probe = _base("probe")
    probe["instances"]["X"] = alone["instances"]["X"]
    try:
        is_qubit = has_junction(Design.model_validate(probe), "X")
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        is_qubit = comp.category == "qubit"
    kind = "qubit" if is_qubit else "cell"
    if ref == "Gatemon":  # its readout is an island edge: a GatemonCoupler sits on it, the feedline runs through
        d = _base(f"audit_{safe}")
        d["instances"].update(_pads(Y_LINE))
        d["instances"]["X"] = {"cell": ref, "place": {"at": [BOX / 2, Y_LINE - 120.0], "rot": 0.0}, "junction": LJ}
        d["instances"]["GC"] = {"cell": "GatemonCoupler", "place": {"snap": "qubit", "to": "X.readout"}}
        d["routes"]["FL_W"] = {"from": "BP_W.a", "to": "GC.o1", "type": "cpw"}
        d["routes"]["FL_E"] = {"from": "GC.o2", "to": "BP_E.a", "type": "cpw"}
        out.append(("pads + feedline through a GatemonCoupler on the readout edge", d, kind))
    elif kind == "qubit":
        ro = _readout(ports)
        if ro is not None:
            d = _base(f"audit_{safe}")
            d["instances"].update(_pads(Y_LINE))
            d["instances"]["X"] = {"cell": ref, "params": params, "junction": LJ,
                                   "place": {"at": [BOX / 2, Y_QUBIT], "rot": _rot_to(ports, ro, -90.0)}}
            d["routes"]["FL"] = {"from": "BP_W.a", "to": "BP_E.a", "type": "cpw"}
            d["routes"]["R"] = {"from": f"X.{ro}", "type": "cpw",
                                "to": {"hanger": "FL", "near": [BOX / 2, Y_LINE], "length": 500.0, "side": "left",
                                       "end": "short", "direction": "forward"}}
            out.append((f"pads + feedline + hanger readout from {ro}", d, kind))
        d = _base(f"audit_{safe}")
        d["instances"].update(_pads(Y_LINE))
        d["instances"]["X"] = dict(alone["instances"]["X"], junction=LJ)
        d["routes"]["FL"] = {"from": "BP_W.a", "to": "BP_E.a", "type": "cpw"}
        out.append(("pads + feedline, no readout" + ("" if ro is None else f" (readout route from {ro} failed)"),
                    d, kind))
    else:
        cpw = _cpw_ports(ports)
        if len(cpw) >= 2:
            d = _base(f"audit_{safe}")
            d["instances"].update(_pads(Y_LINE))
            d["instances"]["X"] = {**alone["instances"]["X"],
                                   "place": {"at": [BOX / 2, Y_LINE], "rot": _rot_to(ports, cpw[0], 180.0)}}
            d["routes"]["L_W"] = {"from": "BP_W.a", "to": f"X.{cpw[0]}", "type": "cpw"}
            d["routes"]["L_E"] = {"from": f"X.{cpw[1]}", "to": "BP_E.a", "type": "cpw"}
            out.append((f"inline between two pads ({cpw[0]} → {cpw[1]})", d, kind))
        if cpw:
            d = _base(f"audit_{safe}")
            d["instances"]["BP_W"] = _pads(Y_LINE)["BP_W"]
            d["instances"]["X"] = {**alone["instances"]["X"],
                                   "place": {"at": [BOX / 2, Y_LINE], "rot": _rot_to(ports, cpw[0], 180.0)}}
            d["routes"]["L_W"] = {"from": "BP_W.a", "to": f"X.{cpw[0]}", "type": "cpw"}
            out.append((f"one pad into {cpw[0]}", d, kind))
    out.append(("alone", alone, kind))
    return out


def _wanted(comp, ports: dict) -> bool:
    if comp.category in SKIP_CATEGORIES:
        return bool(ports)
    return bool(ports) or comp.category in ALWAYS_CATEGORIES


# ---- audit: export + check -----------------------------------------------------------------------------------------
class _LogTap(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _short(e: BaseException) -> str:
    msg = f"{type(e).__name__}: {e}"
    return msg.splitlines()[0][:300] if msg else type(e).__name__


def export_case(design_path: Path, kind: str, analysis: str, job: Path) -> dict:
    """Export one job (no solve) and check it; ``{"export": "ok"|"failed", "reason", "kqc_warnings", "check"}``."""
    from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.geometry_check import check_job  # pylint: disable=import-outside-toplevel

    tap = _LogTap()
    root = logging.getLogger()
    root.addHandler(tap)
    row = {"export": "ok", "reason": "", "kqc_warnings": [], "py_warnings": [], "check": None, "jobs": []}
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if kind == "qubit":
                from quantcore_circuits.guiflow import export_manual  # pylint: disable=import-outside-toplevel

                jobs = export_manual(design_path, names=["X"], analysis=analysis, out=job, say=lambda *a, **k: None)
            else:
                data = json.loads(design_path.read_text(encoding="utf-8"))
                data["sim_groups"] = {"cell": {"select": ["X"], "margin_um": 100.0, "analyses": [analysis]}}
                design_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
                setup = build_simulation(design_path, "cell", analysis)
                jobs = [export_job(setup, job, overwrite=True, fast=True)]
        row["py_warnings"] = sorted({str(w.message)[:300] for w in caught
                                     if "polygon" in str(w.message) or "port" in str(w.message)})
        row["jobs"] = [str(j) for j in jobs]
        checks = [check_job(j) for j in jobs]
        row["check"] = {"errors": [e for c in checks for e in c["errors"]],
                        "warnings": [w for c in checks for w in c["warnings"]],
                        "nets": sum(c["nets"] for c in checks), "objects": sum(c["objects"] for c in checks)}
        meta = json.loads((Path(jobs[0]) / "job.json").read_text(encoding="utf-8"))
        row["ports"] = [(p["kind"], p["name"]) for p in meta.get("ports", [])]
        row["nets"] = meta.get("nets", {})
        row["notes"] = meta.get("notes", [])
    except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
        row["export"] = "failed"
        row["reason"] = _short(e)
        row["traceback"] = traceback.format_exc()[-2000:]
    finally:
        root.removeHandler(tap)
    row["kqc_warnings"] = sorted(set(tap.lines))
    return row


def cmd_audit(out: Path, cells: list[str] | None, analyses: list[str], resume: bool) -> int:
    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.catalog import catalog  # pylint: disable=import-outside-toplevel

    out.mkdir(parents=True, exist_ok=True)
    rows_dir = out / "rows"
    rows_dir.mkdir(exist_ok=True)
    comps = [c for c in catalog(chips=False) if c.cell and (not cells or c.ref in cells or c.name in cells)]
    for comp in comps:
        ports = _ports(comp, dict(QUBIT_PARAMS.get(comp.ref, {})))
        if not _wanted(comp, ports):
            continue
        safe = re.sub(r"[^A-Za-z0-9]+", "_", comp.ref).strip("_").lower()
        row_file = rows_dir / f"{safe}.json"
        if resume and row_file.exists():
            continue
        t0 = time.time()
        base = {"cell": comp.ref, "library": comp.source, "category": comp.category,
                "ports": sorted(ports), "context": None, "build": None, "analyses": {}}
        design_path = None
        kind = "cell"
        for context, data, kind in scratch_designs(comp):
            design_path = out / "designs" / f"{data['name']}.json"
            design_path.parent.mkdir(exist_ok=True)
            design_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
            try:
                build(design_path)
                base["context"], base["build"], base["kind"] = context, "ok", kind
                break
            except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
                base.setdefault("context_failures", []).append(f"{context}: {_short(e)}")
                design_path = None
        if design_path is None:
            base["build"] = "failed"
        else:
            for analysis in analyses:
                job = out / "jobs" / f"{safe}_{analysis}"
                base["analyses"][analysis] = export_case(design_path, kind, analysis, job)
        base["seconds"] = round(time.time() - t0, 1)
        row_file.write_text(json.dumps(base, indent=1, default=str), encoding="utf-8")
        summary = {a: (r["export"], len((r.get("check") or {}).get("errors", [])), len(r["kqc_warnings"]))
                   for a, r in base["analyses"].items()}
        print(f"{comp.ref:32s} {base['build'] or '-':6s} {summary} {base['seconds']}s", flush=True)
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(rows_dir.glob("*.json"))]
    (out / "audit.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    (out / "audit_raw.md").write_text(raw_table(rows, analyses), encoding="utf-8")
    print(f"{len(rows)} cells -> {out / 'audit.json'}")
    return 0


def _cell_status(r: dict | None) -> str:
    if r is None:
        return "–"
    if r["export"] != "ok":
        return f"failed: {r['reason']}"
    c = r.get("check") or {}
    if c.get("errors"):
        return "exported, check failed"
    return "ok"


def raw_table(rows: list[dict], analyses: list[str]) -> str:
    head = ["cell", "library", "category", "context"] + analyses + ["nets disjoint", "junction port polygon", "details"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for row in rows:
        an = row.get("analyses", {})
        errs = [e for r in an.values() for e in ((r.get("check") or {}).get("errors") or [])]
        kqc = [w for r in an.values() for w in r.get("kqc_warnings", []) if "polygon" in w]
        net_bad = [e for e in errs if e.startswith("net") or "touch" in e]
        jj_bad = [e for e in errs if "port" in e] + kqc
        has_jj = "squid_a" in row.get("ports", []) or row.get("kind") == "qubit"
        details = "; ".join(sorted(set(errs + kqc)))[:600] or (row.get("context_failures") or [""])[-1][:300]
        cells = [row["cell"], row["library"], row["category"], row.get("context") or "build failed"]
        cells += [_cell_status(an.get(a)) if row.get("build") == "ok" else "not built" for a in analyses]
        cells += ["–" if not an else ("no" if net_bad else "yes"),
                  "–" if not has_jj else ("missing/bad" if jj_bad else "ok"), details.replace("|", "/")]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check exported job folders")
    c.add_argument("jobs", nargs="+")
    a = sub.add_parser("audit", help="export + check every catalog cell in a scratch design")
    a.add_argument("--out", required=True, type=Path)
    a.add_argument("--cells", default="", help="comma-separated cell refs (default: all)")
    a.add_argument("--analyses", default="q3d_cmatrix,hfss_eigenmode")
    a.add_argument("--resume", action="store_true", help="skip cells already in <out>/rows")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return cmd_check(args.jobs)
    cells = [s.strip() for s in args.cells.split(",") if s.strip()] or None
    return cmd_audit(args.out, cells, [s.strip() for s in args.analyses.split(",") if s.strip()], args.resume)


if __name__ == "__main__":
    sys.exit(main())
