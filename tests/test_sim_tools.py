import math
import json

import pytest

from quantcore_circuits.sim_tools import build_simulation, export_job, read_job
from quantcore_circuits.sim_tools.builder import grounded_routes
from quantcore_circuits.sim_tools.runner import launcher_command, queue_status, serve, submit


def test_q3d_cuts_resonator_and_adds_coupler_port(example_path):
    s = build_simulation(example_path, "Q1R1", "q3d_cmatrix")
    assert [(p.kind, p.name) for p in s.ports] == [("junction", "Q1.junction"), ("waveguide", "Q1.claw_n")]
    exc = {k: v["excitation"] for k, v in s.simulation.get_simulation_data()["layers"].items() if "excitation" in v}
    assert sorted(exc.values()) == [0, 1, 2]  # ground, island, claw


def test_flux_line_is_grounded(example_path):
    from quantcore_circuits.design import load_design

    assert grounded_routes(load_design(example_path)) == {"R1", "FLUX"}


def test_eigenmode_keeps_resonator_and_sets_lj(example_path, tmp_path):
    s = build_simulation(example_path, "Q1R1", "hfss_eigenmode")
    # the junction, plus the feedline terminated in 50 Ω where it leaves the box on either side (κ from the mode Q)
    assert [(p.kind, p.name) for p in s.ports] == [
        ("junction", "Q1.junction"),
        ("edge_lumped", "FL"),
        ("edge_lumped", "FL"),
    ]
    box, data = s.box, s.simulation.get_port_data()
    for pd in data[1:]:
        assert pd["type"] == "InternalPort" and pd["resistance"] == pytest.approx(50.0) and not pd.get("junction")
        x, y = pd["signal_location"][:2]
        assert min(abs(x - box.left), abs(x - box.right)) == pytest.approx(1.0)  # 1 µm inside the box edge
        assert y == pytest.approx(3750.0)  # on the feedline centre line
    port = data[0]
    assert (
        port["junction"] and port["inductance"] == pytest.approx(12e-9) and port["capacitance"] == pytest.approx(2e-15)
    )
    job = export_job(s, tmp_path / "eig")
    meta = read_job(job)
    assert meta["analysis"] == "hfss_eigenmode" and meta["solver"] == "ansys" and meta["design_hash"]
    sim_json = json.loads((job / f"{s.simulation.name}.json").read_text())
    assert sim_json["ansys_tool"] == "eigenmode" and sim_json["analysis_setup"]["n_modes"] == 2
    bat = (job / "simulation.bat").read_text()
    # qcc_solve.py in a separate non-graphical AEDT (KQC's import_and_simulate.py ran with the GUI)
    assert "-RunScriptAndExit" in bat and "qcc_solve.py" in bat and " -ng " in bat


def test_eigenmode_edge_port_terminates_a_cut_grounded_readout(example_dict):
    """A qubit-only eigenmode group: the box cuts the qubit's λ/4 readout (grounded at its hanger short). By default a
    grounded line gets no port; ``ports={"R1": "edge"}`` terminates it in 50 Ω where it leaves the box (the readout
    "cut short"), as for any other line. Q3D is unchanged (a grounded line is never a C-matrix net)."""
    from quantcore_circuits.design import load_design

    data = dict(example_dict)
    data["sim_groups"] = {
        "Q1": {"select": ["Q1"], "margin_um": 150, "analyses": ["eigenmode_epr"]},
        "Q1e": {"select": ["Q1"], "margin_um": 150, "analyses": ["eigenmode_epr"], "ports": {"R1": "edge"}},
    }
    design = load_design(data)
    plain = [(p.kind, p.name) for p in build_simulation(design, "Q1", "eigenmode_epr").ports]
    cut = [(p.kind, p.name) for p in build_simulation(design, "Q1e", "eigenmode_epr").ports]
    assert ("edge_lumped", "R1") not in plain and ("junction", "Q1.junction") in plain
    assert ("edge_lumped", "R1") in cut and set(plain) <= set(cut)
    assert not any(name == "FLUX" for _, name in cut)  # other grounded lines keep the default
    q3d = [(p.kind, p.name) for p in build_simulation(design, "Q1e", "q3d_cmatrix").ports]
    assert not any(name == "R1" and kind.startswith("edge") for kind, name in q3d)


def test_ansys_executable_override(example_path, tmp_path, monkeypatch):
    fake = tmp_path / "ansysedt.exe"
    fake.write_text("")
    monkeypatch.setenv("QCC_ANSYS_EXECUTABLE", str(fake))
    job = export_job(build_simulation(example_path, "Q1R1", "q3d_cmatrix"), tmp_path / "q3d")
    assert str(fake) in (job / "simulation.bat").read_text()


def test_elmer_export(example_path, tmp_path):
    job = export_job(build_simulation(example_path, "Q1R1", "elmer_cap"), tmp_path / "elmer")
    assert read_job(job)["solver"] == "elmer" and (job / "scripts" / "run.py").exists()


@pytest.mark.slow
def test_palace_cap_prepare(example_path, tmp_path):
    pytest.importorskip("gmsh")
    from quantcore_circuits.sim_tools.palace import prepare

    job = export_job(
        build_simulation(example_path, "Q1R1", "palace_cap"), tmp_path / "pal", mesh_global_max=300.0, mesh_edge=20.0
    )
    cfg = json.loads(prepare(job).read_text())
    assert cfg["Problem"]["Type"] == "Electrostatic" and cfg["Model"]["L0"] == 1e-6
    assert [t["Index"] for t in cfg["Boundaries"]["Terminal"]] == [1, 2]
    perms = sorted(m["Permittivity"] for m in cfg["Domains"]["Materials"])
    assert perms == [1.0, 10.25]  # vacuum, sapphire
    msh = next(job.glob("*.msh"))
    assert msh.read_text(errors="replace").splitlines()[1].startswith("2.2")


def test_palace_config_eigenmode_lumped_port():
    from quantcore_circuits.sim_tools.palace import palace_config

    sim = {
        "material_dict": {"silicon": {"permittivity": 11.45}},
        "layers": {"substrate_1": {"material": "silicon"}, "vacuum": {"material": "vacuum"}},
        "ports": [
            {
                "number": 1,
                "junction": True,
                "inductance": 12e-9,
                "capacitance": 2e-15,
                "signal_location": [0, 10, 0],
                "ground_location": [0, 2, 0],
            }
        ],
    }
    physical = {
        "substrate_1": (3, 1),
        "vacuum": (3, 2),
        "excitation_0_boundary": (2, 3),
        "excitation_1_boundary": (2, 4),
        "domain_boundary": (2, 5),
        "port_1": (2, 6),
    }
    cfg = palace_config(sim, physical, {"problem": "Eigenmode", "order": 2, "n_modes": 2, "target_GHz": 3.0}, "m.msh")
    lp = cfg["Boundaries"]["LumpedPort"][0]
    assert lp == {"Index": 1, "Attributes": [6], "Direction": "+Y", "L": 12e-9, "C": 2e-15}
    assert cfg["Boundaries"]["PEC"]["Attributes"] == [3, 4, 5]


def test_queue_roundtrip(example_path, tmp_path, monkeypatch):
    job = export_job(build_simulation(example_path, "Q1R1", "q3d_cmatrix"), tmp_path / "job")
    queued = submit(job, tmp_path / "queue")
    assert read_job(queued)["status"] == "queued"
    import quantcore_circuits.sim_tools.runner as runner

    monkeypatch.setattr(
        runner, "launcher_command", lambda d: ["cmd", "/c", "exit 0"] if __import__("os").name == "nt" else ["true"]
    )
    serve(tmp_path / "queue", once=True, log=lambda *_: None)
    status = queue_status(tmp_path / "queue")
    assert status["failed"] == ["job"]  # solver "ran" but produced no results
    cmd = launcher_command(job)
    assert cmd[0].endswith(("ansysedt", "ansysedt.exe")) and cmd[1] == "-ng" and "scripts/qcc_solve.py" in cmd


def test_cmatrix_nets_follow_kqc_conductors(example_path):
    """Both feedline pads share one conductor: KQC gives it one excitation, so there is no PAD_E net. The flux line
    ends in its short to ground at the Xmon's ``flux`` port (``qcc_shorted_ports``), so PAD_F is ground, not a net.
    (Before the taper fit, the FLUX route's narrowing taper ran 42.5 µm past the port and its etch cut that short,
    which made PAD_F a floating net.)"""
    s = build_simulation(example_path, "chip", "q3d_cmatrix")
    assert s.nets == {1: "Q1.island", 2: "PAD_W.pad"}


def test_floating_transmon_gets_two_island_nets(tmp_path):
    from quantcore_circuits.analysis.results import net_labels
    from quantcore_circuits.designer import Designer

    d = Designer("t_float", box=(0, 0, 7500, 4500), verbose=False)
    d.add("Q1", "DoublePads", at=(3000, 1800), junction={"Lj_nH": 12.0, "Cj_fF": 2.0})
    d.sim_group("Q1", ["Q1"], analyses=["q3d_cmatrix"])
    s = build_simulation(d.save(tmp_path / "f.json"), "Q1", "q3d_cmatrix")
    assert [p.floating for p in s.simulation.ports] == [True]  # the far island is not forced to ground
    assert s.nets == {1: "Q1.island1", 2: "Q1.island2"}
    job = export_job(s, tmp_path / "job")
    assert net_labels(read_job(job), 2) == ["Q1.island1", "Q1.island2"]


def test_wrapped_metal_qubit_keeps_its_junction_in_a_sim_group(tmp_path):
    """``metal:<Class>`` qubits have no ``junction_type``: the sim design must not set it (it raised before)."""
    from quantcore_circuits.designer import Designer

    d = Designer("metal_q_sim", box=(0, 0, 3000, 3000), chip={"die_frame": False}, verbose=False)
    d.add("Q1", "metal:TransmonCross", at=(1500, 1500), junction={"Lj_nH": 10, "Cj_fF": 2})
    d.sim_group("Q1", ["Q1"], analyses=["q3d_cmatrix"])
    s = build_simulation(d.save(tmp_path / "metal_q_sim.json"), "Q1", "q3d_cmatrix")
    assert [(p.kind, p.name, p.excitation) for p in s.ports] == [("junction", "Q1.junction", "Q1.island")]
    assert s.nets == {1: "Q1.island"}


def _design_sim_cases():
    """(design json, group, analysis) for every saved example design (``examples/**/*.json``, schema qcc/0.1)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    cases = []
    for path in sorted((root / "examples").rglob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict) or not str(raw.get("schema", "")).startswith(("qcc/", "qcd/")):
            continue
        for group in raw.get("sim_groups") or {}:
            for analysis in ("q3d_cmatrix", "eigenmode_epr", "elmer_cap", "palace_cap", "palace_eig"):
                rel = path.relative_to(root).as_posix()
                cases.append(pytest.param(path, group, analysis, id=f"{rel}::{group}::{analysis}"))
    return cases


@pytest.mark.slow
@pytest.mark.parametrize(("path", "group", "analysis"), _design_sim_cases())
def test_every_design_sim_group_exports(path, group, analysis, tmp_path):
    """M6: every sim group of every example design exports every analysis (no solve): ports, and named C-matrix nets."""
    s = build_simulation(path, group, analysis)
    job = export_job(s, tmp_path / "job")
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    assert meta["ports"], f"{group}/{analysis}: no ports"
    numbers = {p["number"] for p in meta["ports"]}
    assert all(int(k) in numbers or v for k, v in meta["nets"].items())
    assert all(meta["nets"].values()), f"unnamed nets {meta['nets']}"
    if analysis in ("q3d_cmatrix", "elmer_cap", "palace_cap"):
        assert meta["nets"], f"{group}/{analysis}: no C-matrix nets"


def test_junction_window_is_dropped_for_simulation(example_dict, tmp_path):
    """The fab junction window (metal across the junction gap) would short island to ground in FEM: not simulated."""
    from quantcore_circuits.design import Design

    example_dict["instances"]["Q1"]["params"]["junction_window"] = [30, 27, -3]
    path = tmp_path / "w.json"
    path.write_text(json.dumps(Design.model_validate(example_dict).to_json_dict()), encoding="utf-8")
    s = build_simulation(path, "Q1R1", "q3d_cmatrix")
    assert [(p.kind, p.name) for p in s.ports][0] == ("junction", "Q1.junction")
    assert s.nets.get(1) == "Q1.island"


def test_floating_claw_is_named_by_proximity():
    """A component-port probe that lands in ground (a claw tail joined to a grounded resonator) names the nearest
    still-unnamed conductor (the floating claw body), so ``fill`` can still match the claw coupling."""
    from types import SimpleNamespace

    from kqcircuits.pya_resolver import pya
    from kqcircuits.simulations.simulation import get_simulation_layer_by_name

    from quantcore_circuits.sim_tools.builder import net_names

    layout = pya.Layout()
    cell = layout.create_cell("sim")
    layers = {}
    for k, box in ((1, pya.DBox(0, 0, 100, 100)), (2, pya.DBox(150, 0, 170, 100))):  # island, floating claw body
        name = f"1t1_signal_{k}"
        layers[name] = {"excitation": k}
        cell.shapes(layout.layer(get_simulation_layer_by_name(name))).insert(box.to_itype(layout.dbu))
    sim = SimpleNamespace(layers=layers, cell=cell, layout=layout)
    island_probe = [("Q1.island", pya.DPoint(50, 50))]
    claw_tail_in_ground = [("Q1.claw_n", pya.DPoint(200, 50))]  # 30 µm beyond the claw body, in ground
    assert net_names(sim, island_probe, claw_tail_in_ground) == {1: "Q1.island", 2: "Q1.claw_n"}
    assert net_names(sim, island_probe, claw_tail_in_ground, reach=10.0) == {1: "Q1.island"}  # too far: unnamed


def test_chip03_claws_are_galvanic_after_the_tail_fix():
    """chip_03 after decision #8: the resonator tail is joined galvanically into the claw (no separate
    claw conductor), so the Q1R1 C-matrix has the island net only (the claw is part of the grounded resonator)."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "examples" / "designs" / "legacy" / "chip_03_trilayer.json"
    if not path.exists():
        pytest.skip("legacy design not present")
    s = build_simulation(path, "Q1R1", "q3d_cmatrix")
    assert sorted(s.nets.values()) == ["Q1.island"]


def test_cut_routes_take_their_couplings_with_them(example_dict, tmp_path):
    """A capacitance cut removes the selected routes; a coupling naming one must not break the derived design."""
    from quantcore_circuits.design import Design

    example_dict.setdefault("couplings", {})["K"] = {"between": ["Q1", "R1"], "type": "C", "value": 1.0}
    path = tmp_path / "k.json"
    path.write_text(json.dumps(Design.model_validate(example_dict).to_json_dict()), encoding="utf-8")
    s = build_simulation(path, "Q1R1", "q3d_cmatrix")  # R1 is cut (raised a validation error before)
    assert [(p.kind, p.name) for p in s.ports] == [("junction", "Q1.junction"), ("waveguide", "Q1.claw_n")]


def test_sim_group_ports_keep_a_route(example_path, tmp_path):
    """``Designer.sim_group(..., ports={"R1": "keep"})``: the capacitance job keeps R1 whole (no stub at the claw)."""
    import shutil

    from quantcore_circuits.designer import Designer

    d = Designer.load(shutil.copy(example_path, tmp_path / "d.json"), verbose=False)
    d.sim_group("KEEP", ["Q1", "R1"], analyses=["q3d_cmatrix"], ports={"R1": "keep"}, settings={"percent_error": 1})
    assert d.data["sim_groups"]["KEEP"]["ports"] == {"R1": "keep"}
    path = d.save(tmp_path / "keep.json")
    kinds = [p.kind for p in build_simulation(path, "KEEP", "q3d_cmatrix").ports]
    assert "waveguide" not in kinds and kinds[0] == "junction"
    cut = [p.kind for p in build_simulation(path, "Q1R1", "q3d_cmatrix").ports]
    assert "waveguide" in cut  # the default group still cuts R1 and puts a stub on the claw


def test_star_qubit_islands_are_named():
    """metal:StarQubit ends its junction line inside an etched slot: the island nets are still named (m54)."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "examples" / "designs" / "metal" / "m54_wallraff_cell.json"
    if not path.exists():
        pytest.skip("design not present")
    s = build_simulation(path, "cell", "q3d_cmatrix")
    assert {"D5.island", "Z3.island"} <= set(s.nets.values())


def _write_s2p(path, f0=7.2, qc=2.0e4, qi=2.0e5, phi=0.1, fmt="MA"):
    import numpy as np

    f = np.linspace(f0 - 0.004, f0 + 0.004, 801)
    ql = 1 / (1 / qi + np.cos(phi) / qc)
    s21 = 0.9 * np.exp(0.3j) * (1 - (ql / qc) * np.exp(1j * phi) / (1 + 2j * ql * (f / f0 - 1)))
    s11 = 1 - s21
    lines = ["! synthetic hanger", f"# GHz S {fmt} R 50"]
    for k, fk in enumerate(f):
        row = [fk]
        for v in (s11[k], s21[k], s21[k], s11[k]):  # S11 S21 S12 S22
            row += [abs(v), float(np.degrees(np.angle(v)))] if fmt == "MA" else [v.real, v.imag]
        lines.append(" ".join(f"{x:.12g}" for x in row))
    path.write_text("\n".join(lines) + "\n")
    return f0, qc / np.cos(phi), ql


def test_driven_job_exports_and_s21_gives_kappa(example_path, tmp_path):
    """hfss_driven: a hanger group exports a 2-port driven job; a solved S21 (KQC *_SMatrix.s2p) fits to κ."""
    import pytest

    from quantcore_circuits.analysis.results import collect_results, fit_notch, parse_touchstone
    from quantcore_circuits.design import load_design, save_design
    from quantcore_circuits.design.schema import SimGroup

    design = load_design(example_path)
    design.sim_groups["R1FL"] = SimGroup(select=["R1", "FL", "Q1"], analyses=["hfss_driven"])
    src = save_design(design, tmp_path / "d.json")
    s = build_simulation(src, "R1FL", "hfss_driven")
    assert [p.kind for p in s.ports].count("junction") == 1 and len(s.ports) >= 3  # Lj + both feedline ends
    job = export_job(s, tmp_path / "job")
    sim_json = json.loads((job / f"{s.simulation.name}.json").read_text())
    assert sim_json["ansys_tool"] == "hfss" and sim_json["analysis_setup"]["sweep_enabled"]

    f0, qc, ql = _write_s2p(job / f"{s.simulation.name}_SMatrix.s2p")
    f, S, z0 = parse_touchstone(job / f"{s.simulation.name}_SMatrix.s2p")
    assert S.shape == (801, 2, 2) and z0 == 50.0
    fit = fit_notch(f, S[:, 1, 0])
    assert fit["f0_GHz"] == pytest.approx(f0, rel=1e-7)
    assert fit["Q_coupling"] == pytest.approx(qc, rel=1e-3) and fit["Q_loaded"] == pytest.approx(ql, rel=1e-3)
    assert fit["kappa_ext_MHz"] == pytest.approx(f0 / qc * 1e3, rel=1e-3)
    res = collect_results(job)
    assert res["sparams"]["notch"]["S21"]["Q_coupling"] == pytest.approx(qc, rel=1e-3)
    _write_s2p(tmp_path / "ri.s2p", fmt="RI")
    assert parse_touchstone(tmp_path / "ri.s2p")[1][:, 1, 0] == pytest.approx(S[:, 1, 0], rel=1e-9)


def _sim_layer_shapes(setup, part: str) -> int:
    layout = setup.simulation.layout
    return sum(
        cell.shapes(layout.layer(info)).size()
        for info in layout.layer_infos()
        if part in (info.name or "")
        for cell in layout.each_cell()
    )


def test_simulation_export_never_cheeses_and_airbridges_are_optional(example_dict, tmp_path):
    """Design rule: no ground-grid cheese in any FEM export; airbridges dropped by default, kept on request."""
    from quantcore_circuits.design import save_design
    from quantcore_circuits.design.schema import Design

    d = example_dict
    d["chip"]["params"]["with_grid"] = True  # a fab-cheesed chip
    d["routes"]["FL"]["airbridges"] = "auto"  # strap bridges on the feedline (crosses the Q1R1 eigenmode box)
    d["sim_groups"]["Q1R1"]["analyses"] = ["q3d_cmatrix", "eigenmode_epr"]
    d["sim_groups"]["Q1R1_ab"] = {**d["sim_groups"]["Q1R1"], "settings": {"airbridges": True, "maximum_passes": 7}}
    src = save_design(Design.model_validate(d), tmp_path / "d.json")

    dropped = build_simulation(src, "Q1R1", "eigenmode_epr")
    assert dropped.geometry["airbridges"] == "dropped" and dropped.geometry["airbridge_shapes"] > 0
    assert _sim_layer_shapes(dropped, "airbridge") == 0
    assert not [k for k in dropped.simulation.layers if "airbridge" in k]
    kept = build_simulation(src, "Q1R1", "eigenmode_epr", airbridges=True)
    assert kept.geometry["airbridges"] == "kept" and _sim_layer_shapes(kept, "airbridge") > 0
    assert {"1t1_airbridge_pads", "1t1_airbridge_flyover"} <= set(kept.simulation.layers)  # PEC pads and bridges
    for s in (dropped, kept, build_simulation(src, "chip", "q3d_cmatrix")):
        assert _sim_layer_shapes(s, "ground_grid") - _sim_layer_shapes(s, "ground_grid_avoidance") == 0
    # fab-only processing (ground grid, PDK cheese band, corner rounding) never reaches the FEM geometry: inside the box
    # the etch region equals a plain uncheesed build except at the junction, which becomes the "Sim" port
    import klayout.db as kdb

    from quantcore_circuits.assembly import build

    def etch(layout, cell):
        idx = next(i for i in layout.layer_indexes() if (layout.get_info(i).name or "") == "1t1_base_metal_gap_wo_grid")
        return kdb.Region(cell.begin_shapes_rec(idx)).merged()

    lay = dropped.simulation.layout
    box = kdb.Region(dropped.box.to_itype(lay.dbu))
    plain = build(src, with_grid=False)
    diff = ((etch(lay, dropped.simulation.cell) & box) ^ (etch(plain.layout, plain.cell) & box)).merged()
    assert diff.area() * lay.dbu**2 < 200  # 92 µm² here: the SQUID → simulation junction
    assert diff.bbox().to_dtype(lay.dbu).enlarged(1, 1).contains(kdb.DPoint(2975, 2050))
    group = build_simulation(src, "Q1R1_ab", "eigenmode_epr")  # the group's settings keep them
    assert group.geometry["airbridges"] == "kept"
    job = export_job(group, tmp_path / "job")
    meta = read_job(job)
    assert meta["geometry"]["airbridges"] == "kept" and meta["settings"]["maximum_passes"] == 7
    assert "airbridges" not in meta["settings"]  # a builder option, not a solver setting


def test_crossing_airbridges_dropped_are_noted(tmp_path):
    from quantcore_circuits.designer import Designer

    d = Designer("t_cross", box=(0, 0, 7500, 4500), verbose=False)
    d.add("PAD_A", "BondPad", at=(1500, 2250), rot=270)
    d.add("PAD_B", "BondPad", at=(6000, 2250), rot=90)
    d.route("L", "PAD_A.a", "PAD_B.a", nodes=[{"at": (3750, 2250), "airbridge": True}])
    d.sim_group("L", ["L"], analyses=["q3d_cmatrix"], ports={"L": "keep"})
    s = build_simulation(d.save(tmp_path / "c.json"), "L", "q3d_cmatrix")
    assert any("crossing airbridges dropped on L" in n for n in s.notes)
    assert not build_simulation(tmp_path / "c.json", "L", "q3d_cmatrix", airbridges=True).notes


def test_fem_fast_loosens_criteria_and_caps_passes(example_path, tmp_path, monkeypatch):
    """``FEM_FAST`` (chain-verify, 2026-11-13): whole-chip test runs. Criteria at least the fast values, pass counts
    at most, mesh seeds coarsened, sweeps capped; recorded in job.json. A full solve's settings count as tighter."""
    from quantcore_circuits.sim_tools import export as ex

    drv = ex.fast_settings("hfss_driven", {"max_delta_s": 0.02, "maximum_passes": 10, "minimum_passes": 3,
                                           "mesh_size": {"1t1_gap": 10}, "sweep_count": 24001, "frequency": 7.0})
    assert drv["max_delta_s"] == 0.05 and drv["maximum_passes"] == 6 and drv["minimum_passes"] == 1
    assert drv["mesh_size"] == {"1t1_gap": 30.0} and drv["sweep_count"] == ex.FAST_SWEEP_POINTS
    assert drv["frequency"] == 7.0
    eig = ex.fast_settings("eigenmode_epr", {"max_delta_f": 2.5, "maximum_passes": 5, "n_modes": 3})
    assert (eig["max_delta_f"], eig["maximum_passes"], eig["n_modes"]) == (2.5, 3, 3)  # looser ΔF kept
    assert eig["mesh_size"] == ex.FAST_MESH_SEED["eigenmode_epr"]  # unseeded early passes miss the qubit
    isl = ex.fast_settings("eigenmode_epr", {"max_delta_f": 0.1}, islands=[1])["mesh_size"]
    assert isl == {**ex.FAST_MESH_SEED["eigenmode_epr"], "*_signal_1": ex.FAST_ISLAND_SEED}
    eig_job = read_job(export_job(build_simulation(example_path, "Q1R1", "eigenmode_epr"), tmp_path / "eig", fast=True))
    assert eig_job["settings"]["mesh_size"]["*_signal_1"] == ex.FAST_ISLAND_SEED  # net 1 = Q1.island (the junction)
    assert eig_job["nets"]["1"] == "Q1.island"
    assert ex.fast_settings("elmer_cap", {"p_element_order": 3}) == {"p_element_order": 3}
    assert "mesh_size" not in ex.fast_settings("q3d_cmatrix", {"percent_error": 0.5})

    monkeypatch.delenv("QCC_FEM_FAST", raising=False)
    ex.set_fem_fast(None)
    full = read_job(export_job(build_simulation(example_path, "Q1R1", "q3d_cmatrix"), tmp_path / "full"))
    assert full["settings"]["percent_error"] == 0.5 and "fem_fast" not in full
    monkeypatch.setenv("QCC_FEM_FAST", "1")
    fast = read_job(export_job(build_simulation(example_path, "Q1R1", "q3d_cmatrix"), tmp_path / "fast"))
    assert fast["fem_fast"] is True and fast["settings"]["percent_error"] == 2.0
    assert fast["settings"]["maximum_passes"] == 8
    ex.set_fem_fast(False)  # the process switch wins over the environment
    try:
        assert "fem_fast" not in read_job(export_job(build_simulation(example_path, "Q1R1", "q3d_cmatrix"),
                                                     tmp_path / "off"))
    finally:
        ex.set_fem_fast(None)
    assert ex.tighter_or_equal(full["settings"], fast["settings"])
    assert not ex.tighter_or_equal(fast["settings"], full["settings"])
    assert not ex.tighter_or_equal({**full["settings"], "n_modes": 2}, {**fast["settings"], "n_modes": 3})


def test_an_unseeded_kept_result_does_not_stand_in_for_a_seeded_fast_run():
    from quantcore_circuits.sim_tools.export import fast_settings, tighter_or_equal

    old = {"max_delta_f": 1.0, "maximum_passes": 3, "minimum_passes": 1, "minimum_converged_passes": 1, "n_modes": 3}
    new = fast_settings("eigenmode_epr", old)
    assert "mesh_size" in new and not tighter_or_equal(old, new)
    assert tighter_or_equal({**old, "max_delta_f": 0.1, "maximum_passes": 17, "mesh_size": {"1t1_gap": 10}}, new)


def test_narrow_junction_port():
    """A junction port spanning whole island / ground edges (chip 12's TransmonCrossFL: 50 µm / 435 µm, a skewed
    sheet) becomes a 10 µm rectangle on the junction line; short KQC lead edges (Xmon, 8 µm) are kept; a port with no
    edge (diagonal StarQubit line) gets one."""
    from quantcore_circuits.sim_tools.builder import narrow_junction_port

    skewed = {"junction": True, "signal_location": [3500.0, 5970.0, 0.0], "ground_location": [3500.0, 5990.0, 0.0],
              "signal_edge": [[3475.0, 5970.0, 0.0], [3525.0, 5970.0, 0.0]],
              "ground_edge": [[3545.0, 5990.0, 0.0], [3110.0, 5990.0, 0.0]], "polygon": [[0, 0, 0]] * 4}
    p = narrow_junction_port(skewed)
    xs = sorted(round(v[0], 6) for v in p["polygon"])
    ys = sorted(round(v[1], 6) for v in p["polygon"])
    assert xs == [3495.0, 3495.0, 3505.0, 3505.0] and ys == [5970.0, 5970.0, 5990.0, 5990.0]
    short = {"junction": True, "signal_location": [0.0, 8.0, 0.0], "ground_location": [0.0, 0.0, 0.0],
             "signal_edge": [[-4.0, 8.0, 0.0], [4.0, 8.0, 0.0]], "ground_edge": [[4.0, 0.0, 0.0], [-4.0, 0.0, 0.0]],
             "polygon": "kqc"}
    assert narrow_junction_port(short)["polygon"] == "kqc"
    diag = {"junction": True, "signal_location": [0.0, 0.0, 0.0], "ground_location": [10.0, 10.0, 0.0]}
    p = narrow_junction_port(diag)
    assert len(p["polygon"]) == 4 and abs(math.dist(*[v[:2] for v in p["signal_edge"]]) - 10.0) < 1e-9
