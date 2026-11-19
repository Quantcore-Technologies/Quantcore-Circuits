"""M5 KLayout plugin: the GUI-free parts (geometry, design.json edits, sidecar) and the GUI-built example."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kplugin" / "python"))

from qcc_kplugin import design_io, geometry  # noqa: E402


def test_route_preview_port_to_port_manhattan():
    pts = geometry.route_preview((0, 0), (0, 1), [], (500, 800), (0, -1), 100)
    assert pts[0] == (0, 0) and pts[1] == (0, 100) and pts[-1] == (500, 800) and pts[-2] == (500, 700)
    for a, b in zip(pts, pts[1:]):  # every segment axis-aligned
        assert abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9


def test_route_preview_turns_instead_of_reversing():
    pts = geometry.route_preview((0, 0), (0, 1), [], (400, -300), None, 100)
    assert pts[:2] == [(0, 0), (0, 100)]
    assert pts[2] == (400, 100)  # turns at the stub end rather than going back down through the port


def test_snap_candidate_needs_compatible_facing_ports():
    moving = {"R1.a": {"pos": [0, 0], "dir": [0, -1], "a": 10, "b": 6}}
    others = {
        "Q1.claw_n": {"pos": [5, 103], "dir": [0, 1], "a": 10, "b": 6},
        "Q1.flux": {"pos": [0, 100], "dir": [0, 1], "a": 4, "b": 6},  # closer but different CPW
    }
    hit = geometry.snap_candidate(moving, others, (0, 100), radius=10)
    assert hit[:2] == ("R1.a", "Q1.claw_n") and hit[2] == pytest.approx((5, 103))
    assert geometry.snap_candidate(moving, others, (300, 0), radius=10) is None


def test_handles_and_insert_index(example_path, tmp_path):
    import quantcore_circuits as qcc

    out = tmp_path / "c.oas"
    qcc.write_layout(qcc.build(example_path), out)
    side = json.loads(out.with_name("c.qcc.json").read_text())
    assert side["design"].endswith("q1_r1_feedline.json") and "Q1.claw_n" in side["ports"]
    flux = side["routes"]["FLUX"]
    wps, inserts = geometry.handle_points(flux)
    # FLUX: pad stub (fixed) → long straight (can take a bend) → taper waypoint → flux port (fixed)
    assert [i for i, _ in wps] == [0] and [k for k, _ in inserts] == [2]
    fl_wps, fl_inserts = geometry.handle_points(side["routes"]["FL"])
    assert fl_wps == [] and [k for k, _ in fl_inserts] == [2]  # the long middle segment can take a bend
    assert flux["waypoint_index"] == [2]
    assert geometry.waypoint_insert_index(flux["waypoint_index"], 2) == 0  # before the taper waypoint
    assert geometry.waypoint_insert_index(flux["waypoint_index"], 3) == 1


def test_path_to_route_and_node_edits():
    ports = {"A.a": {"pos": [0, 0]}, "B.a": {"pos": [1000, 500]}}
    src, dst, nodes = design_io.route_from_path([(2, -3), (0, 300), (1000, 300), (998, 501)], ports, 10)
    assert (src, dst, nodes) == ("A.a", "B.a", [(0, 300), (1000, 300)])
    with pytest.raises(ValueError):
        design_io.route_from_path([(500, 500), (1000, 500)], ports, 10)
    d = design_io.add_route({}, "R1", src, dst, "cpw", nodes=nodes)
    design_io.insert_route_node(d, "R1", 1, (500, 300.00004))
    design_io.move_route_node(d, "R1", 0, (0, 350))
    assert d["routes"]["R1"]["nodes"] == [[0, 350], [500, 300.0], [1000, 300]]
    design_io.delete_route_node(d, "R1", 1)
    design_io.set_route_options(d, "R1", type="meander", length=4000.0)
    assert d["routes"]["R1"] == {
        "from": "A.a",
        "to": "B.a",
        "type": "meander",
        "nodes": [[0, 350], [1000, 300]],
        "length": 4000.0,
    }


def test_waypoint_extras_survive_a_move():
    d = {"routes": {"F": {"from": "a", "to": "b", "nodes": [{"at": [1, 2], "a": 1, "b": 7.5}]}}}
    design_io.move_route_node(d, "F", 0, (5, 6))
    assert d["routes"]["F"]["nodes"][0] == {"at": [5, 6], "a": 1, "b": 7.5}


def test_gui_operations_rebuild_the_example(example_path):
    """M5 acceptance, emulated: the GUI edit operations reproduce the hand-written example (ordering ignored)."""
    ref = json.loads(Path(example_path).read_text(encoding="utf-8"))
    d = {k: ref[k] for k in ("schema", "name", "pdk", "chip", "targets", "sim_groups")}
    pad_f = ref["instances"]["PAD_F"]["params"]
    q1 = ref["instances"]["Q1"]
    # Place component… ×4 (then Move/Snap with R to rotate the edge pads)
    design_io.add_instance(d, "PAD_W", "BondPad", (1125, 3750), 270)
    design_io.add_instance(d, "PAD_E", "BondPad", (6375, 3750), 90)
    design_io.add_instance(d, "PAD_F", "BondPad", (2964.5, 750), 0, pad_f)
    design_io.add_instance(d, "Q1", "Xmon", (2975, 2200), 0, q1["params"])
    d["instances"]["Q1"]["junction"] = q1["junction"]
    d["instances"]["Q1"]["place"] = {"at": [2975, 2200]}
    # Connect tool: PAD_W.a → PAD_E.a; drawn path → FLUX with a taper waypoint; R1 from the route dialog
    design_io.add_route(d, "FL", "PAD_W.a", "PAD_E.a", "cpw")
    d["routes"]["FL"]["airbridges"] = "none"
    design_io.add_route(d, "R1", "Q1.claw_n", ref["routes"]["R1"]["to"], "meander", 4200)
    design_io.add_route(d, "FLUX", "PAD_F.a", "Q1.flux", "cpw", nodes=[(2964.5, 1967.0)])
    d["routes"]["FLUX"].update(a=4, b=6, nodes=ref["routes"]["FLUX"]["nodes"])
    del d["routes"]["FLUX"]["type"]  # cpw is the schema default, as in the hand-written file
    for r in ("FL", "R1"):
        d["routes"][r].pop("type") if d["routes"][r]["type"] == "cpw" else None

    from quantcore_circuits.design import load_design

    a, b = load_design(d).to_json_dict(), load_design(ref).to_json_dict()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_all_plugin_modules_compile():
    import py_compile

    for path in (ROOT / "kplugin" / "python" / "qcc_kplugin").glob("*.py"):
        py_compile.compile(str(path), doraise=True)
    lym = (ROOT / "kplugin" / "pymacros" / "qcc_kplugin.lym").read_text(encoding="utf-8")
    compile(lym.split("<text>", 1)[1].split("</text>", 1)[0], "qcc_kplugin.lym", "exec")


def test_instance_results_reach_the_panel(example_path, tmp_path, monkeypatch):
    """Per-instance results data path: run state (``build/<design>/state.json``) → sidecar ``results`` → panel rows."""
    from quantcore_circuits.assembly import build
    from quantcore_circuits.assembly.sidecar import sidecar_dict
    from quantcore_circuits.design import design_hash, load_design

    design = load_design(example_path)
    monkeypatch.chdir(tmp_path)  # run states live under ./build/<design>/
    result = build(example_path)
    assert sidecar_dict(result)["results"] == {}  # no run yet
    run_dir = tmp_path / "build" / design.name
    run_dir.mkdir(parents=True)
    q, r = next(n for n, i in design.instances.items() if i.junction is not None), next(iter(design.routes))
    elements = [
        {
            "id": q,
            "kind": "qubit",
            "status": "pass",
            "params": [
                {
                    "key": "f_q",
                    "label": "Qubit frequency",
                    "value": 5.1234,
                    "unit": "GHz",
                    "status": "pass",
                    "target": {"value": 5.1, "tol": 0.05},
                    "source": "scqubits",
                },
                {"key": "alpha", "label": "Anharmonicity", "value": -221.0, "unit": "MHz", "status": None},
            ],
        },
        {
            "id": r,
            "kind": "resonator",
            "params": [{"key": "f_r", "label": "Resonator frequency", "value": 7.2, "unit": "GHz"}],
        },
        {"id": "not_in_design", "kind": "coupler", "params": [{"key": "g", "value": 1.0}]},
    ]
    state = {"design": {"hash": design_hash(design)}, "updated": "2026-11-03T00:00:00Z", "elements": elements}
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    side = json.loads(json.dumps(sidecar_dict(result)))  # as the plugin reads it
    assert set(side["results"]) == {q, r}  # elements that are not instances/routes of the design are dropped
    assert side["results"][q]["stale"] is False
    rows = design_io.results_rows(side, q)
    assert rows[0] == (q, "Qubit frequency", "5.123 GHz", "5.1 ± 0.05 · pass")
    assert rows[1] == (q, "Anharmonicity", "-221 MHz", "")
    assert {row[0] for row in design_io.results_rows(side)} == {q, r}
    assert design_io.results_rows(side, "missing") == []

    state["design"]["hash"] = "another-revision"
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    side = sidecar_dict(result)
    assert side["results"][q]["stale"] is True
    assert design_io.results_rows(side, q)[0][3].endswith("(stale)")
    assert sidecar_dict(result, overlays=False)["results"] == {}


def test_new_design_and_hand_built_q1_r1(tmp_path):
    """The GUI path of a hand-made Q1+R1: New design → drop two pads and an Xmon → Connect pad to pad (feedline) →
    Connect the claw to the feedline (a hanger meander). The design.json the plugin writes builds and DRCs clean."""
    from quantcore_circuits.assembly import build
    from quantcore_circuits.assembly.drc import check
    from quantcore_circuits.design import load_design

    d = design_io.new_design("hand_q1r1")
    assert d["chip"]["box"] == [0.0, 0.0, 7500.0, 7500.0] and d["instances"] == {} and d["routes"] == {}
    design_io.add_instance(d, "PAD_W", "BondPad", (1125, 3750), 270)
    design_io.add_instance(d, "PAD_E", "BondPad", (6375, 3750), 90)
    design_io.add_instance(d, "Q1", "Xmon", (2975, 2200), 0, {"claws": ["n"], "junction_type": "Quantcore Squid"})
    design_io.add_route(d, "FL", "PAD_W.a", "PAD_E.a")
    poly = [(1125.0, 3750.0), (1225.0, 3750.0), (6275.0, 3750.0), (6375.0, 3750.0)]
    hit = geometry.route_near({"FL": {"polyline": poly}}, (3125.0, 3745.0), 12.0)
    assert hit == ("FL", 2)
    side = geometry.hanger_side(poly, hit[1], (2975.0, 2454.0))  # the claw is below a west → east line
    assert side == "right"
    design_io.add_route(d, "R1", "Q1.claw_n", design_io.hanger_end("FL", (3125.0, 3745.0), 300, side), "meander", 4200)
    path = tmp_path / "hand_q1r1.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    rep = check(build(load_design(path)))
    assert rep.ok, rep


def test_component_outline_for_the_placement_ghost():
    """`qcc components CELL --outline`: the etched outline (a few polygons, light), bbox and ports in the cell frame."""
    from quantcore_circuits.assembly.plan import pcell_params
    from quantcore_circuits.layouts.registry import element_outline, resolve_cell

    cls = resolve_cell("Xmon")
    g = element_outline(cls, **pcell_params(cls, {"claws": ["n"]}))
    assert g["bbox"][3] > 250 and g["outline"] and sum(len(p) for p in g["outline"]) <= 400
    assert [p["name"] for p in g["ports"]] == ["claw_n"]
    pad = element_outline(resolve_cell("BondPad"), **pcell_params(resolve_cell("BondPad"), {}))
    assert pad["ports"][0]["name"] == "a" and len(pad["outline"]) == 1


def test_instance_parameter_edit():
    """Double-click edit: only values that differ from the cell defaults are stored; rotation goes to place.rot."""
    schema = [{"name": "cross_length", "default": 300}, {"name": "claws", "default": ["n"]},
              {"name": "junction_type", "default": "Trilayer Junction"}]
    values = {"cross_length": design_io.parse_value("350", 300), "claws": design_io.parse_value('["n"]', ["n"]),
              "junction_type": design_io.parse_value("Quantcore Squid", "x")}
    changed = design_io.changed_params(schema, values)
    assert changed == {"cross_length": 350, "junction_type": "Quantcore Squid"}
    d = design_io.new_design("t")
    design_io.add_instance(d, "Q1", "Xmon", (100, 200), 0)
    design_io.set_instance(d, "Q1", changed, 450)
    assert d["instances"]["Q1"]["params"] == changed and d["instances"]["Q1"]["place"]["rot"] == 90.0
    design_io.set_instance(d, "Q1", {}, None)
    assert "params" not in d["instances"]["Q1"] and d["instances"]["Q1"]["place"]["rot"] == 90.0


def test_hanger_follows_moved_component():
    """Moving a qubit moves the hanger coupler of its readout with it (else a 100 µm offset fails to route)."""
    d = design_io.new_design("t")
    design_io.add_instance(d, "Q1", "Xmon", (3000, 2200), 0)
    design_io.add_route(d, "R2", "Q1.claw_n", design_io.hanger_end("FL", (3150, 3750), 300, "right"), "meander", 4200)
    design_io.add_route(d, "FL", "P1.a", "P2.a")
    assert design_io.follow_hangers(d, "Q1", (100.0, -50.0)) == ["R2"]
    assert d["routes"]["R2"]["to"]["near"] == [3250.0, 3700.0]
    assert design_io.follow_hangers(d, "P1", (10.0, 0.0)) == []  # the feedline's own ends: no hanger moves


def test_grid_and_shift_constraints():
    """Grid snapping (KLayout's edit-grid value) and Shift: segments horizontal / vertical, aligned with neighbours."""
    assert geometry.parse_grid("0.5") == 0.5 and geometry.parse_grid("1,1") == 1.0
    assert geometry.parse_grid("") is None and geometry.parse_grid(None) is None
    assert geometry.ortho((0, 0), (100, 30)) == (100, 0) and geometry.ortho((0, 0), (20, -90)) == (0, -90)
    # two generic neighbours: the square corner nearest the point; collinear neighbours: stay on their line
    assert geometry.ortho_between((90, 10), [(0, 0), (100, 100)]) == (100, 0)
    assert geometry.ortho_between((52, 3), [(0, 0), (100, 0)]) == (52, 0)
    # aligned coordinates take the neighbour's exact (off-grid) value; the free one goes to the grid
    assert geometry.constrain((2966.0, 1501.7), 5.0, [(2964.5, 850.0)], shift=True) == (2964.5, 1500.0)
    assert geometry.constrain((2966.0, 1501.7), 5.0, [(2964.5, 850.0)], shift=False) == (2965.0, 1500.0)
    # Shift while drawing (one neighbour): 0° / 45° / 90° …; a diagonal keeps |dx| = |dy| on the grid
    assert geometry.snap45((0, 0), (100, 30)) == (100, 0) and geometry.snap45((0, 0), (-20, -200)) == (0, -200)
    assert geometry.snap45((0, 0), (100, 90), 5.0) == (95.0, 95.0)
    assert geometry.constrain((-210, 190), 10.0, [(0, 0)], shift=True) == (-200.0, 200.0)


def test_connect_commits_the_previewed_corner():
    """The square corner the preview draws is the node a click commits (no oblique segment after the click)."""
    assert geometry.elbow((0, 0), (-1, 0), (-300, -200)) == [(-300, 0)]  # leaves along the port / last segment
    assert geometry.elbow((0, 0), (1, 0), (-300, -200)) == [(0, -200)]  # turns instead of reversing
    assert geometry.elbow((0, 0), None, (300, 100)) == [(300, 0)]  # free start: along the longer axis
    assert geometry.elbow((0, 0), (0, 1), (0, 500)) == []  # aligned: no corner


def test_curvature_handle_round_trip_and_preview():
    prev, p, nxt = (0.0, 0.0), (100.0, 0.0), (100.0, 100.0)
    h = geometry.radius_handle(prev, p, nxt, 50.0)
    assert h == pytest.approx((100 - 50 * (1 - 2 ** -0.5), 50 * (1 - 2 ** -0.5)))  # the middle of the arc
    assert geometry.radius_from_handle(prev, p, nxt, h) == pytest.approx(50.0)
    assert geometry.radius_handle((0, 0), (50, 0), (100, 0), 50.0) is None  # a straight node has no curvature
    pts = geometry.rounded_points([prev, p, nxt], [0, 50, 0])
    assert pts[1] == pytest.approx((50.0, 0.0)) and pts[-2] == pytest.approx((100.0, 50.0))
    assert all(geometry.dist(q, (50.0, 50.0)) == pytest.approx(50.0) for q in pts[1:-1])
    # a collinear node closer to a corner than its bend cut is flagged (KQC cannot build it)
    assert geometry.tight_segments([(0, 0), (700, 0), (800, 0), (800, 500)], [0, 0, 150, 0]) == [2]
    assert geometry.tight_segments([(0, 0), (650, 0), (800, 0), (800, 500)], [0, 0, 150, 0]) == []


def test_free_ends_and_node_edits():
    """Pen-tool route ends and node properties written to design.json."""
    assert design_io.free_end((10, 20)) == {"at": [10, 20], "term": 6.0}
    assert design_io.free_end((10, 20), 180.0, "short") == {"at": [10, 20], "term": 0.0, "dir": 180.0}
    assert geometry.free_end_dir((4500, 5000), (3750, 5000)) == 180.0
    assert geometry.free_end_dir((0, 0), (0, -10)) == 270.0
    with pytest.raises(ValueError):
        design_io.add_route({}, "X", design_io.free_end((0, 0)), design_io.free_end((1, 1)))
    d = design_io.add_route({}, "R", design_io.free_end((0, 0)), design_io.hanger_end("FL", (5, 5), 300), "meander",
                            4200, [(0, 100), (50, 100)])
    design_io.set_node(d, "R", 1, r=150)
    assert d["routes"]["R"]["nodes"] == [[0, 100], {"at": [50, 100], "r": 150}]
    design_io.set_node(d, "R", 1, at=(60, 100), airbridge=True)
    assert d["routes"]["R"]["nodes"][1] == {"at": [60, 100], "r": 150, "airbridge": True}
    assert design_io.node_props(d["routes"]["R"]["nodes"][1]) == {"at": [60, 100], "r": 150, "airbridge": True,
                                                                  "a": None, "b": None}
    design_io.set_node(d, "R", 1, a=1, b=7.5)  # a taper from this node on (the q1_r1 flux line)
    assert d["routes"]["R"]["nodes"][1] == {"at": [60, 100], "r": 150, "airbridge": True, "a": 1, "b": 7.5}
    design_io.set_node(d, "R", 1, r=None, airbridge=False, a=None, b=None)
    assert d["routes"]["R"]["nodes"][1] == [60, 100]  # back to a plain point
    design_io.set_meander_segment(d, "R", 1)
    assert d["routes"]["R"]["meander_segment"] == 1
    design_io.set_meander_segment(d, "R", None)
    assert "meander_segment" not in d["routes"]["R"]


def test_duplicate_and_mirror():
    d = design_io.new_design("t")
    design_io.add_instance(d, "Q1", "Xmon", (100, 200), 90, {"claws": ["n"]})
    d["instances"]["Q1"]["junction"] = {"Lj_nH": 12.0}
    assert design_io.mirror_instance(d, "Q1") is True and d["instances"]["Q1"]["place"]["mirror"] is True
    spec = design_io.duplicate_spec(d, "Q1")
    assert spec == {"cell": "Xmon", "params": {"claws": ["n"]}, "rot": 90.0, "mirror": True,
                    "extra": {"junction": {"Lj_nH": 12.0}}}
    design_io.add_instance(d, "X1", spec["cell"], (500, 200), spec["rot"], spec["params"], spec["mirror"], spec["extra"])
    assert d["instances"]["X1"] == {"cell": "Xmon", "place": {"at": [500, 200], "rot": 90.0, "mirror": True},
                                    "params": {"claws": ["n"]}, "junction": {"Lj_nH": 12.0}}
    assert design_io.mirror_instance(d, "Q1") is False and "mirror" not in d["instances"]["Q1"]["place"]


def test_pen_drawn_resonator_builds_and_drcs(tmp_path):
    """What the pen tool writes for a bare λ/4 (free open end → two nodes → hanger on the feedline), a route ending
    in a free end and a per-corner radius builds and passes the connectivity DRC."""
    from quantcore_circuits.assembly import build
    from quantcore_circuits.assembly.drc import check
    from quantcore_circuits.design import load_design

    d = design_io.new_design("pen")
    design_io.add_instance(d, "PAD_W", "BondPad", (1125, 3750), 270)
    design_io.add_instance(d, "PAD_E", "BondPad", (6375, 3750), 90)
    design_io.add_instance(d, "PAD_N", "BondPad", (3750, 6375), 180)
    design_io.add_route(d, "FL", "PAD_W.a", "PAD_E.a")
    src = design_io.free_end((4510, 2000))
    dst = design_io.hanger_end("FL", (4950, 3751), 300, geometry.hanger_side([(1225, 3750), (6275, 3750)], 1, (4800, 3000)))
    design_io.add_route(d, "R1", src, dst, "meander", 4200, [(4510, 3000), (4800, 3000)])
    design_io.set_node(d, "R1", 1, r=150)
    end = design_io.free_end((4500, 5000), geometry.free_end_dir((4500, 5000), (3750, 5000)))
    design_io.add_route(d, "S", "PAD_N.a", end, nodes=[(3750, 5000)])
    path = tmp_path / "pen.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    result = build(load_design(path))
    assert result.plan.routes["R1"].length == pytest.approx(4200, abs=0.05)
    rep = check(result)
    assert rep.ok, rep


# ---- G3: targets, LOM comparison, flow status ------------------------------------------------------------------
def test_target_keys_by_element_kind():
    assert list(design_io.target_keys("instance", "quantcore:Xmon")) == ["f_q_GHz", "alpha_MHz"]
    assert design_io.target_keys("instance", "BondPad") == {}
    assert design_io.target_keys("instance", "BondPad", {"f_q_GHz": 5.0}) == {"f_q_GHz": "f_q_GHz"}  # existing kept
    assert list(design_io.target_keys("route")) == ["f_GHz", "kappa_MHz", "g_MHz", "chi_MHz"]


def test_parse_and_set_targets_additive():
    assert design_io.parse_targets({"f_q_GHz": " 5.2 ", "alpha_MHz": ""}) == {"f_q_GHz": 5.2}
    with pytest.raises(ValueError, match="f_q_GHz"):
        design_io.parse_targets({"f_q_GHz": "five"})
    d = {"instances": {}, "targets": {"R1": {"f_GHz": 7.0}}}
    assert design_io.set_targets(d, "Q1", {"f_q_GHz": 5.1}) is True
    assert d["targets"] == {"R1": {"f_GHz": 7.0}, "Q1": {"f_q_GHz": 5.1}}  # other elements untouched
    assert design_io.set_targets(d, "Q1", {"f_q_GHz": 5.1}) is False
    design_io.set_targets(d, "Q1", {})
    design_io.set_targets(d, "R1", {})
    assert "targets" not in d


def test_targets_validate_against_the_design_schema(tmp_path):
    from quantcore_circuits.design import load_design

    d = design_io.new_design("t")
    design_io.add_instance(d, "Q1", "Xmon", (1000, 1000), 0)
    design_io.set_targets(d, "Q1", {"f_q_GHz": 5.2, "alpha_MHz": -300.0})
    design_io.set_targets(d, "R1", {"f_GHz": 7.0, "kappa_MHz": 0.4})
    path = tmp_path / "t.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    assert load_design(path).targets["Q1"] == {"f_q_GHz": 5.2, "alpha_MHz": -300.0}


def test_compare_targets_status():
    params = {"Q1.f_q_GHz": 5.21, "Q1.alpha_MHz": -321.0, "R1.f_GHz": 6.0, "R1.chi_MHz": -1.0, "R1.g_MHz": 50.0}
    targets = {"Q1": {"f_q_GHz": 5.2, "alpha_MHz": -320.0}, "R1": {"f_GHz": 7.0, "kappa_MHz": 0.5, "g_MHz": 61.0}}
    rows = {r["key"]: r for r in design_io.compare_targets(params, targets)}
    assert rows["Q1.f_q_GHz"]["status"] == "within tolerance"  # 10 MHz off, tolerance 20 MHz
    assert rows["Q1.f_q_GHz"]["tol"] == 0.02
    assert rows["Q1.alpha_MHz"]["status"] == "within tolerance"
    assert rows["R1.f_GHz"]["status"] == "off"  # 1 GHz off
    assert rows["R1.g_MHz"]["status"] == "off"  # 11 MHz off, tolerance 10 MHz (absolute, as in qcc analyse)
    assert rows["R1.chi_MHz"]["target"] is None and rows["R1.chi_MHz"]["status"] == ""
    assert rows["R1.kappa_MHz"]["status"] == "no value" and rows["R1.kappa_MHz"]["value"] is None


def test_netlist_rows_and_flow_status(tmp_path):
    res = {"branches": {"C_Q1": {"type": "C"}}, "netlist": [
        {"element": "C_Q1", "qucat": "C", "nodes": ["Q1", "gnd"], "value": 64.05, "unit": "fF"},
        {"element": "R1", "qucat": "C‖L", "nodes": ["a", "gnd"], "value": [302.2, 1.49], "unit": "fF, nH"}]}
    rows = design_io.netlist_rows(res)
    assert rows[0] == ("C_Q1", "C", "Q1 – gnd", "64.05 fF") and rows[1][3] == "302.2 fF ‖ 1.49 nH"

    design = tmp_path / "d.json"
    design.write_text("{}", encoding="utf-8")
    assert set(design_io.flow_status(None, None).values()) == {"todo"}
    st = design_io.flow_status(design, {"instances": {"Q1": {}}})
    assert st["design"] == "done" and st["lom"] == "todo" and st["fab"] == "todo"
    (tmp_path / "build" / "d").mkdir(parents=True)
    (tmp_path / "build" / "d" / "lom.json").write_text("{}", encoding="utf-8")
    assert design_io.flow_status(design, None)["lom"] == "done"
    import os, time  # noqa: E401

    later = time.time() + 50
    os.utime(design, (later, later))  # design edited after the LOM run
    assert design_io.flow_status(design, None)["lom"] == "warn"
    (tmp_path / "build" / "d_fab.oas").write_bytes(b"x")
    assert design_io.flow_status(design, None)["fab"] == "warn"  # a mask older than the design
    os.utime(tmp_path / "build" / "d_fab.oas", (later + 1, later + 1))
    assert design_io.flow_status(design, None)["fab"] == "done"


def test_target_tolerances_are_the_librarys():
    """The LOM tab's "within tolerance" is the same rule as qcc analyse (the plugin keeps a copy of DEFAULT_TOL)."""
    from quantcore_circuits.lom.builder import DEFAULT_TOL

    assert design_io.TARGET_TOL == DEFAULT_TOL
    assert design_io.target_tolerance("Q1.chi_MHz", -1.0) == DEFAULT_TOL["chi_MHz"]
    assert design_io.target_tolerance("Q1.T1_us", 50.0) == pytest.approx(0.5)  # not listed: 1 % (as the library)


def test_flow_marks_ignore_sim_groups_and_targets(tmp_path):
    """Writing a sim group (qcc sim auto) or a target does not make LOM / Fab look out of date; a geometry edit does."""
    design = tmp_path / "d.json"
    data = {"name": "dn", "instances": {"Q1": {"cell": "Xmon", "place": {"at": [0, 0]}}}}
    design.write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "build" / "d").mkdir(parents=True)
    (tmp_path / "build" / "d" / "lom.json").write_text("{}", encoding="utf-8")
    (tmp_path / "build" / "d_fab.oas").write_bytes(b"x")
    fp = design_io.design_fingerprint(design)
    design_io.set_mark(design, "lom", fp)
    design_io.set_mark(design, "fab", fp)
    data["sim_groups"] = {"gui_sim": {"select": ["Q1"]}}
    data["targets"] = {"Q1": {"f_q_GHz": 5.0}}
    design.write_text(json.dumps(data), encoding="utf-8")
    st = design_io.flow_status(design, None)
    assert st["lom"] == "done" and st["fab"] == "done"
    data["instances"]["Q1"]["place"]["at"] = [10, 0]
    design.write_text(json.dumps(data), encoding="utf-8")
    st = design_io.flow_status(design, None)
    assert st["lom"] == "warn" and st["fab"] == "warn"
    # simulate: an analysed run (build/<design name>/flow.json); results: values, warn when a target fails
    assert st["simulate"] == "todo"
    (tmp_path / "build" / "dn").mkdir()
    (tmp_path / "build" / "dn" / "flow.json").write_text("{}", encoding="utf-8")
    ok = {"results": {"Q1": {"params": [{"key": "f_q_GHz", "value": 5.0, "status": "pass"}], "stale": False}}}
    assert design_io.flow_status(design, ok)["simulate"] == "done"
    assert design_io.flow_status(design, ok)["results"] == "done"
    ok["results"]["Q1"]["params"][0]["status"] = "fail"
    assert design_io.flow_status(design, ok)["results"] == "warn"
    ok["results"]["Q1"]["stale"] = True
    assert design_io.flow_status(design, ok)["simulate"] == "warn"


def test_session_absorbs_writes_by_qcc(tmp_path, monkeypatch):
    """qcc sim auto writes the sim group into design.json behind the session: no edit is lost, undo keeps the group,
    and an outside geometry edit becomes one undo step."""
    import os
    import time

    from qcc_kplugin import session as sess

    monkeypatch.setattr(sess, "message", lambda *a, **k: None)
    s = sess.Session()
    built = []
    monkeypatch.setattr(s, "_build", lambda: built.append(1))
    design = tmp_path / "d.json"
    design_io.write_design(design, {"name": "d", "instances": {"Q1": {"cell": "Xmon", "place": {"at": [0, 0]}}}})
    s.design_path = design
    s.check_external_edit()  # baseline
    d = design_io.read_design(design)
    d["instances"]["Q1"]["place"]["at"] = [100, 0]
    s.commit(d, "")  # a drawing edit
    on_disk = design_io.read_design(design)  # qcc sim auto writes its group (it re-reads the file first)
    on_disk["sim_groups"] = {"gui_sim": {"select": ["Q1"]}}
    design_io.write_design(design, on_disk)
    os.utime(design, (time.time() + 5, time.time() + 5))
    assert s.check_external_edit() and len(s.history) == 1  # sim groups only: no undo step of their own
    s.undo()  # undoes the drawing edit, keeps the sim group the results belong to
    back = design_io.read_design(design)
    assert back["instances"]["Q1"]["place"]["at"] == [0, 0] and "gui_sim" in back["sim_groups"]
    s.redo()
    assert design_io.read_design(design)["instances"]["Q1"]["place"]["at"] == [100, 0]
    # a geometry edit by someone else: one undo step, and a rebuild
    other = design_io.read_design(design)
    other["instances"]["Q1"]["place"]["at"] = [200, 0]
    design_io.write_design(design, other)
    os.utime(design, (time.time() + 10, time.time() + 10))
    n = len(built)
    assert s.check_external_edit() and len(built) == n + 1
    s.undo()
    assert design_io.read_design(design)["instances"]["Q1"]["place"]["at"] == [100, 0]


def test_circuit_simulate_json_and_png(tmp_path):
    """``qcc circuit simulate --json --png`` (what the LOM tab runs): modes, params, netlist values and a picture."""
    pytest.importorskip("matplotlib")
    pytest.importorskip("qucat")
    from typer.testing import CliRunner

    from quantcore_circuits.cli import app

    ex = ROOT / "examples" / "q1_r1_feedline.json"
    circuit, out, png = tmp_path / "c.circuit.json", tmp_path / "lom.json", tmp_path / "lom.png"
    runner = CliRunner()
    assert runner.invoke(app, ["circuit", "export", str(ex), "-o", str(circuit)]).exit_code == 0
    r = runner.invoke(app, ["circuit", "simulate", str(circuit), "--json", str(out), "--png", str(png)])
    assert r.exit_code == 0, r.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert {m["label"] for m in data["modes"]} >= {"Q1", "R1"}
    assert "Q1.f_q_GHz" in data["params"] and data["netlist"] and data["png"] == str(png)
    assert png.stat().st_size > 5000


def test_every_quantcore_cell_has_a_well_formed_outline_and_schema():
    """The placement ghost / parameter table read these for ANY cell the panel lists: a null port direction once
    crashed the ghost (TwoPadTransmon's SQUID ports). Ports need a position; a direction is a number or None."""
    from quantcore_circuits.assembly.plan import pcell_params
    from quantcore_circuits.layouts.registry import element_outline, element_schema, resolve_cell

    from quantcore_circuits.layouts.catalog import catalog

    names = [c.ref for c in catalog(source="quantcore") if c.cell]
    assert len(names) >= 50
    bad = []
    for name in names:
        cls = resolve_cell(name)
        schema = element_schema(cls)
        if not schema or any(not p.get("name") or "default" not in p for p in schema):
            bad.append((name, "schema"))
        g = element_outline(cls, **pcell_params(cls, {}))
        if len(g["bbox"]) != 4:
            bad.append((name, "bbox"))
        for port in g["ports"]:
            if len(port["at"]) != 2 or not (port.get("dir") is None or isinstance(port["dir"], (int, float))):
                bad.append((name, f"port {port}"))
    assert not bad, bad


# ---- rotation snapping while dragging ------------------------------------------------------------------------------
def _port(x, y, ang, a=10, b=6):
    import math

    return {"pos": (x, y), "dir": (math.cos(math.radians(ang)), math.sin(math.radians(ang))), "a": a, "b": b}


def test_rotation_snap_turns_an_angled_port_to_face_the_target():
    import math

    target = {"T.a": _port(100.0, 0.0, 180.0)}  # faces west
    for pin_angle in (72.0, 144.0, 216.0, 288.0):  # StarQubit pins are 72 degrees apart
        mine = {"S.p": _port(0.0, 0.0, pin_angle)}
        hit = geometry.snap_candidate_rot(mine, target, (95.0, 3.0), 12.0)
        assert hit is not None
        own, tgt, delta, extra = hit
        assert (own, tgt) == ("S.p", "T.a")
        # after the turn the port faces -target.dir and sits on the target
        face = (math.cos(math.radians(pin_angle + extra)), math.sin(math.radians(pin_angle + extra)))
        assert face[0] > 0.9999 and abs(face[1]) < 1e-6
        assert delta == pytest.approx((100.0, 0.0), abs=1e-6)  # the port is at the origin: it lands on the target


def test_rotation_snap_uses_the_turn_about_the_origin_and_the_smallest_turn():
    # a symmetric qubit: four ports on a 100 um radius; all land on the target; the one needing no turn wins
    ports = {f"p{i}": _port(100 * c, 100 * s, ang) for i, (c, s, ang) in enumerate(((1, 0, 0), (0, 1, 90), (-1, 0, 180), (0, -1, 270)))}
    target = {"T.a": _port(500.0, 0.0, 90.0)}  # faces north: wants a port facing south, i.e. p3 (270) with no turn
    hit = geometry.snap_candidate_rot(ports, target, (498.0, 102.0), 15.0, origin=(0.0, 0.0), turn=0.0)
    assert hit is not None and hit[0] == "p3" and hit[3] == 0.0
    assert hit[2] == pytest.approx((500.0, 100.0), abs=1e-6)  # port p3 at (0,-100)+delta = target (500, 0)


def test_rotation_snap_off_keeps_only_ports_that_already_face():
    target = {"T.a": _port(100.0, 0.0, 180.0)}
    assert geometry.snap_candidate_rot({"S.p": _port(0, 0, 72.0)}, target, (100.0, 0.0), 12.0, rotate=False) is None
    hit = geometry.snap_candidate_rot({"S.p": _port(0, 0, 0.0)}, target, (95.0, 0.0), 12.0, rotate=False)
    assert hit is not None and hit[3] == 0.0
    # a different cross-section never snaps
    assert geometry.snap_candidate_rot({"S.p": _port(0, 0, 0.0, a=4)}, target, (100.0, 0.0), 12.0) is None


def test_rotation_snap_respects_the_held_turn():
    # the held component was turned 90 degrees with [ : its port (0 deg in the sidecar) now faces north
    hit = geometry.snap_candidate_rot({"S.p": _port(50.0, 0.0, 0.0)}, {"T.a": _port(0.0, 200.0, 270.0)}, (0.0, 150.0), 10.0,
                                      origin=(0.0, 0.0), turn=90.0)
    assert hit is not None and hit[3] == 0.0  # already facing: no extra turn; port (50,0) -> (0,50) + (0,150) = target


def test_set_place_snap_keeps_mirror():
    design = {"instances": {"A": {"cell": "X", "place": {"at": [0, 0], "rot": 0.0, "mirror": True}}}}
    design_io.set_place_snap(design, "A", "a", "B.a")
    assert design["instances"]["A"]["place"] == {"snap": "A.a", "to": "B.a", "mirror": True}


def test_loads_tolerant_skips_a_warning_line_before_the_json():
    from qcc_kplugin import qcache

    assert qcache.loads_tolerant('{"a": 1}') == {"a": 1}
    assert qcache.loads_tolerant("FutureWarning: update python\n" + '{"bbox": [0, 0, 1, 1], "ports": []}\n') == {
        "bbox": [0, 0, 1, 1], "ports": []}
    assert qcache.loads_tolerant("warning\n[1, 2]\n") == [1, 2]
    with pytest.raises(ValueError):
        qcache.loads_tolerant("no json here")
