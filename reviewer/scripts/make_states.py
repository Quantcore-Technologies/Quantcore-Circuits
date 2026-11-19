"""Dashboard states from real runs, and the sample fixture (``reviewer/public/sample-state.json``).

    python reviewer/scripts/make_states.py             # all runs + sample fixture
    python reviewer/scripts/make_states.py two_qubit   # only the 2-qubit run (+ fixture)
    python reviewer/scripts/make_states.py five_qubit  # only the 5-qubit run (re-synthesised from FIVE_Q_TARGETS)
    python reviewer/scripts/make_states.py q1          # only refresh the 1-qubit run's cards

* ``two_qubit`` — ``examples/two_qubit_synth.json`` (two Xmon + λ/4 readout pairs on one feedline, synthesised from
  targets): build → OAS → headless KLayout screenshots → LOM-only analysis (layout estimates, no FEM; one QuTiP
  solve per pair) → feedback (one surrogate per pair → revision 1, built, netlist-checked, screenshot) →
  ``build/two_qubit/state.json``. The fixture is a copy of this state with the screenshots next to it.
* ``five_qubit`` — ``examples/five_qubit_synth.json``: five pairs synthesised from :data:`FIVE_Q_TARGETS` with
  :func:`quantcore_circuits.lom.synthesize.layout_from_targets` (feedline template, 875 µm pitch on the 7.5 mm die),
  then the same LOM-only run as ``two_qubit`` → ``build/five_qubit/state.json``.
* ``q1`` — the notebook's 1-qubit run ``build/q1_r1_code`` (``examples/q1_r1_code.json``, FEM job
  ``build/jobs/q1_r1_feedline_Q1R1_q3d_cmatrix``): re-analysed in place (steps, screenshots, history are kept) so
  its cards / elements follow the current schema; the feedback proposal is recomputed without writing a revision.

No live KLayout pushes; the user's KLayout window is never touched (headless ``klayout.lay`` only).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "reviewer" / "public"

TWO_Q = "examples/two_qubit_synth.json"
FIVE_Q = "examples/five_qubit_synth.json"
ONE_Q = "examples/q1_r1_code.json"
ONE_Q_JOB = "build/jobs/q1_r1_feedline_Q1R1_q3d_cmatrix"

# 5-qubit example (M13): (qubit, f_q GHz, α MHz, resonator, f_r GHz, g MHz). Qubits 200 MHz apart, readouts 150 MHz
# apart (≥ 1.2 GHz detuning from every qubit), g = 80 MHz as in the 2-qubit example.
FIVE_Q_TARGETS = [
    ("Q1", 4.9, -215.0, "R1", 6.90, 80.0),
    ("Q2", 5.1, -215.0, "R2", 7.05, 80.0),
    ("Q3", 5.3, -215.0, "R3", 7.20, 80.0),
    ("Q4", 5.5, -215.0, "R4", 7.35, 80.0),
    ("Q5", 5.7, -215.0, "R5", 7.50, 80.0),
]


def synth_five() -> Path:
    """LOM → layout for :data:`FIVE_Q_TARGETS`, saved to :data:`FIVE_Q` (DRC clean, node-connected netlist).

    The middle flux pad sits where the die frame's device ID goes by default (bottom centre); the frame then puts the
    device ID on the first empty side (here the top, ``device_id_side="auto"``).
    """
    from quantcore_circuits.lom.synthesize import PairTarget, layout_from_targets

    d = layout_from_targets("five_qubit", [PairTarget(*t) for t in FIVE_Q_TARGETS], verbose=False)
    d.show()
    report = d.drc()
    if report.errors or report.warnings:
        raise RuntimeError(f"{FIVE_Q}: DRC not clean: {report}")
    return d.save(FIVE_Q)


def two_qubit() -> Path:
    return lom_only_run(TWO_Q)


def five_qubit() -> Path:
    synth_five()
    return lom_only_run(FIVE_Q)


def lom_only_run(source: str) -> Path:
    from quantcore_circuits import loop
    from quantcore_circuits.assembly import build, write_layout
    from quantcore_circuits.design import load_design
    from quantcore_circuits.live.snapshot import snapshot
    from quantcore_circuits.track import Run

    design = load_design(source)
    run = Run(source, Path("build") / design.name, reset=True)

    run.start("synthesis")
    q = {n: i for n, i in design.instances.items() if i.junction is not None}
    run.done(
        "synthesis",
        " · ".join(
            f"{n} L_J {i.junction.Lj_nH:.3g} nH, cross {i.params.get('cross_length', 0):.4g} µm" for n, i in q.items()
        )
        + f" (from targets, {Path(source).name})",
    )

    run.start("layout")
    t0 = time.perf_counter()
    result = build(source)
    oas = write_layout(result, run.dir / f"{design.name}.oas")
    shots = run.dir / "shots"
    png = snapshot(oas, shots / "chip.png", size=(1400, 1400))
    run.screenshot(png, "Chip", "layout", "Full chip (headless KLayout render)", "headless", "chip")
    for name, inst in q.items():
        x, y = inst.place.at
        box = (x - 560, y - 420, x + 560, y + 700)  # island, claw and the start of the readout meander
        png = snapshot(oas, shots / f"{name.lower()}.png", size=(1100, 1000), box=box)
        run.screenshot(
            png, f"{name} close-up", "layout", f"{name} island, claw and readout (headless)", "headless", name.lower()
        )
    lengths = " · ".join(f"{n} {v:.1f} µm" for n, v in result.route_lengths().items())
    run.done("layout", f"built in {time.perf_counter() - t0:.2f} s · {lengths}", hash=result.hash)

    run.skip("render", "LOM-only run: no FEM project")
    run.skip("simulate", "LOM-only run: layout estimates instead of a C-matrix")
    an = loop.analyse(source, None, run=run, readout=False)
    _, _, revised = loop.feedback(an, run=run, design_source=source)
    png = snapshot(revised, shots / "chip_rev1.png", size=(1400, 1400))
    run.screenshot(
        png, "Chip — revision 1 (proposed)", "feedback", "surrogate prediction; simulate to confirm", "headless"
    )
    return run.path


def one_qubit() -> Path:
    from quantcore_circuits import codesign as cd
    from quantcore_circuits import loop
    from quantcore_circuits.track import Run

    run = Run(ONE_Q, Path("build") / "q1_r1_code")  # keep steps, screenshots, history and log
    fb = next((s for s in run.state["steps"] if s["id"] == "feedback"), {})
    an = loop.analyse(ONE_Q, ONE_Q_JOB, run=run)
    surrogates = cd.surrogates_from_fill(an.filled)  # same proposal as loop.feedback, without writing a revision
    bounds = {**an.model.knobs}
    for s in surrogates:
        bounds.setdefault(s.cg.knob, (s.cg.k0 * 0.4, s.cg.k0 * 2.2))
    measured = {r.param: r.chosen for r in an.rows if r.chosen is not None}  # as loop.feedback: bias-corrected
    prop = cd.propose_all(surrogates, an.model.targets, bounds, anchor=measured)
    if fb.get("status") == "done":
        run.start("feedback")
        run.done("feedback", fb.get("summary", ""))
    loop.update_cards(run, ONE_Q, an, prop)
    return run.path


def fixture(state_path: Path) -> Path:
    """Copy a run state into ``reviewer/public`` with its screenshots under ``sample/``."""
    st = json.loads(state_path.read_text(encoding="utf-8"))
    sample = PUBLIC / "sample"
    sample.mkdir(parents=True, exist_ok=True)
    for old in sample.glob("*.png"):
        old.unlink()
    for shot in st["screenshots"]:
        rel = shot["url"].split("?", 1)[0].removeprefix("/files/")
        src = state_path.parent / rel
        shutil.copyfile(src, sample / src.name)
        shot["url"] = f"sample/{src.name}"
    out = PUBLIC / "sample-state.json"
    out.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main(argv: list[str]) -> None:
    os.chdir(ROOT)
    os.environ.setdefault("QCC_LIVE", "0")
    which = set(argv) or {"two_qubit", "five_qubit", "q1"}
    if "five_qubit" in which:
        print("5-qubit state:", five_qubit())
    if "two_qubit" in which:
        p = two_qubit()
        print("2-qubit state:", p)
        print("fixture:", fixture(p))
    if "q1" in which:
        print("1-qubit state:", one_qubit())


if __name__ == "__main__":
    main(sys.argv[1:])
