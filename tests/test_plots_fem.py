"""Convergence / S21-fit / EPR plots and their dashboard specs, on the kept FEM results (Agg backend, no display)."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

from quantcore_circuits import plots as P  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FEM = REPO / "examples" / "tutorials" / "fem"
EIG = FEM / "t04_two_qubit_ALL_eigenmode_epr"
DRV = FEM / "t04_two_qubit_ALL_hfss_driven"
Q3D = FEM / "t04_two_qubit_PAIR_q3d_cmatrix"
S2P = REPO / "tests" / "data" / "aedt_2024r1" / "hfss_driven"


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def _spec_ok(spec):
    assert {"id", "title", "tab", "kind"} <= set(spec)
    json.dumps(spec)  # plain data for state.json
    if spec["kind"] == "xy":
        for s in spec["series"]:
            assert len(s["x"]) == len(s["y"]) > 0


def test_convergence_data_from_dict_folder_and_text():
    d = P.convergence_data(EIG)
    assert d["criterion"] == "Max Delta Freq. %" and d["passes"] == [1, 2, 3] and d["converged"] is False
    assert d["delta"][0] is None and set(d["mode_GHz"]) == {"1", "2", "3", "4", "5"}
    txt = next((REPO / "tests" / "data").rglob("*_project_convergence.txt"), None)
    if txt is not None:
        assert P.convergence_data(txt)["passes"]
    assert P.convergence_data({"analysis": "x"}) is None


def test_plot_convergence_single_ax_and_figure():
    ax = P.plot_convergence(EIG / "results" / "results.json", ax=plt.subplots()[1])
    assert ax.get_yscale() == "log" and len(ax.lines) >= 2  # data + criterion line
    assert len(ax.child_axes) == 1  # the secondary tets axis
    ax2 = P.plot_convergence(EIG)
    assert len(ax2.figure.axes) == 3  # pass, mesh, mode frequencies
    ax3 = P.plot_convergence({"eig": EIG, "q3d": Q3D, "drv": DRV})  # different criteria: delta / target
    assert "target" in ax3.get_ylabel() and ax3.get_legend() is not None


def test_plot_s21_fit_model_only_and_with_trace():
    ax = P.plot_s21_fit(DRV)  # fit only: the trace is not kept
    assert "fit only" in ax.get_title() and len(ax.figure.axes) == 2  # two notches
    ax = P.plot_s21_fit(S2P)  # a job folder with the raw s2p: trace read, notch fitted
    labels = [ln.get_label() for ln in ax.get_lines()]
    assert "data" in labels and "notch fit" in labels
    assert "fit only" not in ax.get_title()


def test_plot_epr_and_specs():
    from quantcore_circuits.analysis import epr_lumped as L

    res = L.epr_from_job(EIG)
    ax = P.plot_epr(res)
    assert len(ax.figure.axes) >= 3  # bars, chi, colour bar
    ax1 = P.plot_epr(res, ax=plt.subplots()[1])
    assert len(ax1.patches) > 0
    sp = P.epr_specs(res)
    assert [s["kind"] for s in sp] == ["bar", "heatmap"]
    for s in sp:
        _spec_ok(s)
        P.plot_spec(s)  # the dashboard spec draws in matplotlib too


def test_fem_specs_for_the_dashboard():
    jobs = [json.loads((d / "results" / "results.json").read_text(encoding="utf-8")) for d in (Q3D, EIG, DRV)]
    specs = P.fem_specs([{"group": "ALL", "results": r} for r in jobs])
    ids = [s["id"] for s in specs]
    assert len(ids) == len(set(ids))
    assert any(i.startswith("conv_") and i.endswith("_mesh") for i in ids)
    assert any(i.endswith("_modes") for i in ids) and any(i.startswith("s21_") for i in ids) and "epr_p" in ids
    for s in specs:
        _spec_ok(s)
        assert s["tab"] == "plots"
        P.plot_spec(s)
    assert P.fem_specs([]) == [] and P.fem_specs([{"results": {}}]) == []
