"""M11–M13: surrogate, co-design loop, dashboard state + server, plot helpers."""

import json
import urllib.request
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "q1_r1_feedline.json"


def test_power_law_surrogate_refits_exponent():
    from quantcore_circuits.codesign import ElementModel

    m = ElementModel("C", "x", 300.0, 60.0, p=1.0)
    m.add(300.0, 60.0)
    assert m.predict(330.0) == pytest.approx(66.0)  # prior exponent
    m.add(400.0, 60.0 * (400 / 300) ** 0.8)
    assert m.p == pytest.approx(0.8) and m.invert(m.predict(350.0)) == pytest.approx(350.0)


def _truth_evaluator():
    """Synthetic 'FEM': the real capacitances scale with exponents the surrogate does not know (0.85, 1.15, 0.7)."""
    from quantcore_circuits.circuit.bridges import tl_resonator
    from quantcore_circuits.circuit.fill import FilledCircuit, TransmonReadout
    from quantcore_circuits.optimise import get_knob

    def evaluate(design):
        cross = float(get_knob(design, "Q1.cross_length"))
        claw = float(get_knob(design, "Q1.claw_length"))
        lj = float(get_knob(design, "Q1.junction.Lj_nH"))
        length = float(get_knob(design, "R1.length"))
        c_i, cg, cc = 64.0 * (cross / 300) ** 0.85, 3.2 * (claw / 100) ** 1.15, 76.0 * (claw / 100) ** 0.7
        maxwell = np.array([[c_i + cg, -cg], [-cg, cc + cg]])
        tl = tl_resonator(length, 10, 6, design.pdk)
        pair = TransmonReadout("Q1", "R1", ["Q1.island", "Q1.claw_n"], maxwell, lj, 2.0, tl["f_GHz"], tl["Z0_ohm"])
        return FilledCircuit(None, design, {}, None, [pair])

    return evaluate


@pytest.mark.slow
@pytest.mark.analysis
def test_codesign_loop_converges(tmp_path):
    """M12 acceptance (emulated FEM): from the example (f_q 120 MHz high, α 100 MHz off, f_r 400 MHz low, g −35 %)
    every target is inside tolerance within ≤ 5 FEM iterations."""
    from quantcore_circuits import codesign
    from quantcore_circuits.circuit.derive import circuit_from_design

    model = circuit_from_design(EXAMPLE, "Q1R1")
    bounds = {**model.knobs, "Q1.claw_length": (40.0, 220.0)}
    assert bounds["Q1.cross_length"] == (150.0, 540.0)
    steps = codesign.run(
        EXAMPLE, _truth_evaluator(), codesign.copy_targets(model.targets), max_iter=5, run_dir=tmp_path, bounds=bounds
    )
    assert steps[0].objective > 5
    assert all(abs(r) <= 1 for r in steps[-1].residuals.values()), steps[-1].residuals
    assert set(steps[-1].residuals) == {"Q1.f_q_GHz", "Q1.alpha_MHz", "R1.f_GHz", "R1.g_MHz"}
    assert len(steps) - 1 <= 5
    assert Path(steps[0].revision).exists()


def test_follow_ports_moves_taper_waypoint():
    from quantcore_circuits import codesign

    d = codesign.apply(EXAMPLE, {"Q1.cross_length": 400.0})
    y = d.routes["FLUX"].nodes[0].at[1]
    assert y == pytest.approx(1967.0 - 50.0)  # the flux port moved 50 µm down; the taper went with it
    assert (
        codesign.apply(EXAMPLE, {"Q1.cross_length": 400.0}, follow_ports=False).routes["FLUX"].nodes[0].at[1] == 1967.0
    )


def test_run_state_contract(tmp_path):
    from quantcore_circuits.track import STEPS, Run

    run = Run(EXAMPLE, tmp_path / "run", reset=True)
    run.start("layout")
    run.done("layout", "built", hash="abc")
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    run.screenshot(png, "Chip", "layout", source="gui", ident="chip")
    run.plot(
        {
            "id": "p",
            "title": "t",
            "tab": "plots",
            "kind": "xy",
            "series": [{"name": "a", "x": [0], "y": [np.float64(1)]}],
        }
    )
    run.iteration({"iteration": 0, "objective": 3.0, "residuals": {}, "knobs": {}, "accepted": True})
    st = json.loads(run.path.read_text(encoding="utf-8"))
    contract = (ROOT / "reviewer" / "contract" / "state.ts").read_text(encoding="utf-8")
    top = contract.split("export interface State {", 1)[1].split("}", 1)[0]
    keys = {line.split(":")[0].strip() for line in top.splitlines() if ":" in line}
    assert keys == set(st)  # every State field present, nothing extra
    assert [s["id"] for s in st["steps"]] == [i for i, _ in STEPS]
    assert st["currentStep"] == "layout" and st["steps"][1]["status"] == "done"
    assert st["screenshots"][0]["url"].startswith("/files/shots/chip.png") and st["plots"][0]["series"][0]["y"] == [1.0]
    assert st["design"]["stack"] == {"substrate": "sapphire", "epsR": 10.25, "thickness_um": 650.0}


def test_dashboard_server_endpoints(tmp_path):
    from quantcore_circuits.review.server import serve
    from quantcore_circuits.track import Run

    run = Run(EXAMPLE, tmp_path / "run", reset=True)
    (run.dir / "shots").mkdir()
    (run.dir / "shots" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    server = serve(EXAMPLE, port=0, open_browser=False, run_dir=run.dir, background=True)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        state = json.loads(urllib.request.urlopen(f"{base}/api/state", timeout=5).read())
        assert state["schema"] == "qcc-state/0.1" and state["design"]["name"] == "q1_r1_feedline"
        assert urllib.request.urlopen(f"{base}/files/shots/a.png?v=1", timeout=5).headers["Content-Type"] == "image/png"
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{base}/files/../state.json", timeout=5)
        events = urllib.request.urlopen(f"{base}/api/events", timeout=5)
        assert events.headers["Content-Type"] == "text/event-stream"
        assert events.readline().startswith(b"event: state")
        events.close()
        html = urllib.request.urlopen(f"{base}/", timeout=5).read()
        assert b'<div id="root">' in html or b"id=root" in html or b"root" in html
    finally:
        server.shutdown()


def test_plot_helpers_follow_guidelines(tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    from quantcore_circuits import plots

    plots.use_style(usetex=False)
    import matplotlib.pyplot as plt

    assert plt.rcParams["xtick.direction"] == "in" and plt.rcParams["axes.prop_cycle"].by_key()["color"] == plots.COLORS
    fig, ax = plots.figure("two", 1, 2)
    assert tuple(fig.get_size_inches()) == (6.0, 2.5) and plt.rcParams["font.size"] == 11  # tier 2
    specs = [
        plots.xy_spec(
            "a",
            "A",
            "plots",
            [{"name": "f_q", "x": [0, 1], "y": [1, 2]}],
            "Flux Φ/Φ0",
            "f (GHz)",
            [{"axis": "y", "value": 1.5, "label": "target"}],
        ),
        plots.levels_spec("b", "B", "hamiltonian", [{"label": "|g,0⟩", "energy": 0}, {"label": "|e,0⟩", "energy": 5}]),
    ]
    for a, s in zip(ax, specs):
        plots.plot_spec(s, a)
    out = plots.save(fig, tmp_path / "fig")
    assert [p.suffix for p in out] == [".pdf", ".png"] and all(p.stat().st_size > 1000 for p in out)
    assert plots.tex("f_q") == "$f_{q}$" and plots.tex("metal_lom") == "metal_lom"


def test_multi_qubit_analysis_and_feedback_cover_every_pair(tmp_path):
    """Two qubit–resonator pairs: QuTiP per pair (per-pair plots linked from cards) and one surrogate per pair."""
    from quantcore_circuits import loop
    from quantcore_circuits.track import Run

    src = "examples/two_qubit_synth.json"
    run = Run(src, tmp_path / "run", reset=True)
    an = loop.analyse(src, None, run=run, readout=False)
    assert list(an.pair_results) == ["Q1", "Q2"]
    assert {"Q2.f_q_GHz", "R2.chi_MHz"} <= set(an.estimates["qutip"])
    plots = {p["id"] for p in an.plots}
    assert {"levels", "levels_Q2", "flux_Q2"} <= plots
    linked = {c["plot"] for c in run.state["cards"] if c.get("plot")}
    assert "levels_Q2" in linked and linked <= plots
    prop, _, result = loop.feedback(an, run=run, design_source=src)
    assert {"Q1.claw_length", "Q2.claw_length", "R2.length"} <= set(prop.knobs)
    assert all(abs(r) <= 1 for r in prop.residuals.values()) and len(prop.residuals) == 8
