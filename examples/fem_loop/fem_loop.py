"""FEM loop milestone (decision #30–#32): one feedline with two hanging resonators, rendered to AEDT 2024 R1, solved
(Q3D C-matrix, eigenmode/EPR, driven S21), read back, then a geometry change and the same again: the values must
move with the geometry.

R1 is a λ/4 resonator shorted at its coupler (the usual readout hanger; κ ≈ 0.1–0.3 MHz, which the driven S21
notch resolves). R2 is a λ/2 resonator open at both ends: a floating conductor, so the Q3D C-matrix measures its
capacitance to ground and its coupling capacitance to the feedline (R1, grounded through its short, is not a Q3D
net). Its κ is ~10 kHz, below the driven sweep's point spacing: the eigenmode gives its frequency.

    python examples/fem_loop/fem_loop.py build            # designs rev0/rev1 + LOM only (seconds)
    python examples/fem_loop/fem_loop.py solve [rev ...]  # + AEDT solves (batch, non-graphical; tens of minutes)
    python examples/fem_loop/fem_loop.py report           # table from whatever results exist

Outputs: ``examples/fem_loop/fem_loop_rev{0,1}.json`` (designs), ``build/jobs/fem_loop_rev*_FL2R_*`` (AEDT jobs:
projects, logs, ``results/results.json``), ``examples/fem_loop/results.json`` + ``results.md`` (the comparison).
The notebook ``fem_loop.ipynb`` shows the same steps and reads these files.

Rev 1 changes three knobs: R1's coupler 250 → 400 µm (its κ must rise), R2 400 µm shorter (its frequency must rise)
and R2's coupler 250 → 400 µm (its coupling capacitance to the feedline must rise).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JOBS = ROOT / "build" / "jobs"
GROUP = "FL2R"
ANALYSES = ("q3d_cmatrix", "eigenmode_epr", "hfss_driven")

TARGETS = {"R1": 7.0, "R2": 7.6}  # GHz
KIND = {"R1": "lambda/4", "R2": "lambda/2"}
REVS = {
    0: {"R1": {"coupler": 250.0, "dl": 0.0}, "R2": {"coupler": 250.0, "dl": 0.0}},
    1: {"R1": {"coupler": 400.0, "dl": 0.0}, "R2": {"coupler": 400.0, "dl": -400.0}},
}


def resonator_length_um(f_GHz: float, kind: str, a: float = 10.0, b: float = 6.0) -> float:
    """λ/4 (or λ/2 = twice that) length for ``f_GHz`` on the PDK CPW, kinetic inductance included."""
    from quantcore_circuits.analysis.synthesis import quarter_wave_length_um  # pylint: disable=C0415

    return quarter_wave_length_um(f_GHz, a, b) * (2 if kind == "lambda/2" else 1)


def design(rev: int):
    """The rev-``rev`` design (Designer), saved as ``fem_loop_rev<rev>.json``."""
    from quantcore_circuits.designer import Designer  # pylint: disable=import-outside-toplevel

    knobs = REVS[rev]
    d = Designer(f"fem_loop_rev{rev}", box=(0, 0, 7500, 7500), chip={"name_chip": f"FL2R{rev}"}, verbose=False)
    d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270, edge="w")  # PDK pad rule: frame.pad_edge (100 µm) from the die edge
    d.add("PAD_E", "BondPad", at=(6375, 3750), rot=90, edge="e")
    fl = d.route("FL", "PAD_W.a", "PAD_E.a", airbridges="none")
    for name, x in (("R1", 2600.0), ("R2", 3900.0)):  # close together: a small simulation box
        k = knobs[name]
        length = resonator_length_um(TARGETS[name], KIND[name]) + k["dl"]
        end = "short" if KIND[name] == "lambda/4" else "open"
        d.route(
            name,
            d.free_end((x, 5600.0 if KIND[name] == "lambda/2" else 4900.0), dir=270, term=6.0),  # open far end
            fl.hanger(near=(x + k["coupler"] / 2, 3700.0), length=k["coupler"], side="left", end=end, ground_gap=6.0),
            meander=length,
            airbridges="none",
        )
    # The group selects the resonators only: the box (their bbox + 300 µm) cuts the feedline, whose two cut ends
    # become the driven ports ("edge"), as in the sim agent's verified Q1R1D run. "keep": the capacitance builds
    # keep the resonators (by default they are cut off at the coupler).
    d.sim_group(
        GROUP,
        ["R1", "R2"],
        margin_um=300.0,
        analyses=ANALYSES,
        ports={"FL": "edge", "R1": "keep", "R2": "keep"},
        settings={
            "q3d_cmatrix": {"percent_error": 1.0},
            # 4 modes: the cut feedline's own (Q ≈ 1) mode takes a slot (first run, 2026-11-04)
            "eigenmode_epr": {"n_modes": 4, "min_frequency": 6.0, "max_delta_f": 0.2, "maximum_passes": 14},
            "hfss_driven": {
                # the sim agent's recipe: without a gap seed the adaptive mesh never refines an off-resonance
                # resonator and the notch falls outside the band (first run: flat S21 in 6.6–7.3 GHz)
                "mesh_size": {"1t1_gap": 10},
                "frequency": 7.3,
                "maximum_passes": 10,
                "minimum_passes": 3,
                "sweep_start": 6.5,  # both resonators: 24 001 points → 79 kHz (κ_R1 ≈ 0.15–0.37 MHz)
                "sweep_end": 8.4,
                "sweep_count": 24001,
                "sweep_type": "fast",
            },
        },
    )
    d.targets(**{n: {"f_GHz": f} for n, f in TARGETS.items()})
    path = d.save(HERE / f"fem_loop_rev{rev}.json")
    return d, path


def lom(path) -> dict:
    """LOM (layout → circuit → QuCat/QuTiP) values of R1 and R2: f_r, κ."""
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.builder import lom_from_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.simulate import simulate  # pylint: disable=import-outside-toplevel

    res = simulate(fill(lom_from_design(path).model, path))
    return {k: v for k, v in res.params.items() if k.split(".")[0] in TARGETS}


def solve(rev: int, analyses=ANALYSES, aedt: str | None = None) -> dict:
    """Render + solve each analysis of rev ``rev`` in AEDT the ``aedt`` way: ``"batch"`` (default) its own
    non-graphical AEDT; ``"gui"`` a new AEDT window, left open; ``"attach"`` the AEDT window that is open."""
    from quantcore_circuits.sim_tools.hfss import render  # pylint: disable=import-outside-toplevel

    _, path = design(rev)
    out = {}
    for analysis in analyses:
        job = JOBS / f"fem_loop_rev{rev}_{GROUP}_{analysis}"
        t0 = time.time()
        r = render(path, GROUP, analysis, job_dir=job, solve=True, timeout=3 * 3600, aedt=aedt)
        out[analysis] = {"job": str(job), "ok": bool(r.ok), "seconds": round(time.time() - t0, 1)}
        print(f"rev{rev} {analysis}: ok={r.ok} in {out[analysis]['seconds']} s → {job}", flush=True)
    return out


def fem(rev: int) -> dict:
    """FEM values read back from the solved jobs of rev ``rev`` (whatever exists)."""
    out = {}
    for analysis in ANALYSES:
        f = JOBS / f"fem_loop_rev{rev}_{GROUP}_{analysis}" / "results" / "results.json"
        if f.exists():
            out[analysis] = json.loads(f.read_text(encoding="utf-8"))
    return out


def summary(rev: int) -> dict:
    """Comparable numbers per resonator: LOM f/κ; eigenmode f, κ = f/Q (the cut feedline is terminated in 50 Ω, so
    Q is the external Q); driven notch f, κ_ext; Q3D Maxwell matrix (FL and the floating λ/2 R2)."""
    _, path = design(rev)
    lom_vals = lom(path)
    res = fem(rev)
    row: dict = {"rev": rev, "knobs": REVS[rev], "resonators": {}}
    eig = (res.get("eigenmode_epr") or {}).get("eigenmodes") or []
    real = [m for m in eig if m.get("Q", 0) > 100]  # drop the cut feedline's own (Q ≈ 1) modes
    notches = list(((res.get("hfss_driven") or {}).get("sparams") or {}).get("notch", {}).values())
    for name in TARGETS:
        f_lom = lom_vals.get(f"{name}.f_GHz")
        r = {"lom": {"f_GHz": f_lom, "kappa_MHz": lom_vals.get(f"{name}.kappa_MHz")}}
        if real and f_lom:
            m = min(real, key=lambda m: abs(m["f_GHz"] - f_lom))
            r["eigenmode"] = {"f_GHz": m["f_GHz"], "Q": m["Q"], "kappa_MHz": m["f_GHz"] / m["Q"] * 1e3}
        if notches and f_lom:
            n = min(notches, key=lambda n: abs(n["f0_GHz"] - f_lom))
            r["driven"] = {k: n[k] for k in ("f0_GHz", "kappa_ext_MHz", "kappa_MHz", "Q_internal", "residual_rms")}
        row["resonators"][name] = r
    cm = (res.get("q3d_cmatrix") or {}).get("cmatrix")
    if cm:
        # R2 is the only floating conductor and has no port, so AEDT's Net2 comes back as "floating_2" (the job's net
        # map only knows ported nets); name it here
        floating = [x for x in cm["labels"] if x.startswith("floating")]
        labels = [("R2" if x in floating and len(floating) == 1 else x) for x in cm["labels"]]
        row["q3d"] = {"labels": labels, "maxwell_fF": cm["matrix"]}
    conv = {a: (res.get(a) or {}).get("convergence", {}).get("converged") for a in ANALYSES if res.get(a)}
    row["converged"] = conv
    return row


def _fmt(x, nd=4) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def report(rows: list[dict]) -> str:
    """Markdown comparison of the revisions: each value, its change rev0 → rev1, LOM vs FEM."""
    r0, r1 = rows[0], rows[-1]
    head = ["| resonator | quantity | source | rev 0 | rev 1 | change |", "|---|---|---|---|---|---|"]
    lines = list(head)
    for name in TARGETS:
        for qty, key_lom, src_keys in (
            ("f (GHz)", "f_GHz", (("eigenmode", "f_GHz"), ("driven", "f0_GHz"))),
            ("κ_ext/2π (MHz)", "kappa_MHz", (("eigenmode", "kappa_MHz"), ("driven", "kappa_ext_MHz"))),
        ):
            names = {"eigenmode": "FEM eigenmode", "driven": "FEM driven S21"}
            sources = [("LOM", ("lom", key_lom))] + [(names[s], (s, k)) for s, k in src_keys]
            for label, (src, k) in sources:
                a = (r0["resonators"][name].get(src) or {}).get(k)
                b = (r1["resonators"][name].get(src) or {}).get(k)
                change = (
                    "—" if a is None or b is None else (f"{b - a:+.4f}" if qty.startswith("f") else f"×{b / a:.2f}")
                )
                lines.append(f"| {name} | {qty} | {label} | {_fmt(a)} | {_fmt(b)} | {change} |")
    if r0.get("q3d") and r1.get("q3d"):
        m0, m1 = r0["q3d"]["maxwell_fF"], r1["q3d"]["maxwell_fF"]
        labels = r0["q3d"]["labels"]
        for i in range(len(labels)):
            for j in range(i + 1):
                what = f"C[{labels[i]}]" if i == j else f"C[{labels[i]}, {labels[j]}]"
                a, b = m0[i][j], m1[i][j]
                lines.append(f"| Q3D | {what} (fF, Maxwell) | FEM Q3D | {a:.3f} | {b:.3f} | {b - a:+.3f} |")
    lines.append("")
    lines.append(f"Converged: rev 0 {r0.get('converged')}, rev 1 {r1.get('converged')} (decision #30: accepted as is).")
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else "build"
    if cmd == "build":
        for rev in REVS:
            d, path = design(rev)
            print(path, lom(path))
    elif cmd == "solve":
        revs = [int(a) for a in argv[2:]] or list(REVS)
        for rev in revs:
            solve(rev)
        cmd = "report"
    if cmd == "report":
        rows = [summary(rev) for rev in REVS]
        (HERE / "results.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        (HERE / "results.md").write_text(report(rows) + "\n", encoding="utf-8")
        print(report(rows))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    main(sys.argv)
