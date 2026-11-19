"""Plugin side of oblique routes and failed routes: snapping to a port's angle, the preview equal to the router, red
failed routes, deleting a route that has no cell."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kplugin" / "python"))

from qcc_kplugin import design_io, geometry  # noqa: E402


def test_constrain_offers_the_port_angle_next_to_45_degrees():
    a = math.radians(-18)
    ray = [((100.0, 0.0), (math.cos(a), math.sin(a)))]
    p = (1000.0, -290.0)  # about 1.5° off the ray
    # without Shift the point is only on the grid (any angle); Shift alone gives 0° / 45° / 90°
    assert geometry.constrain(p, 1.0) == p
    assert geometry.constrain(p, 1.0, [(100.0, 0.0)], True) == (1000.0, 0.0) or geometry.constrain(
        p, 1.0, [(100.0, 0.0)], True)[1] in (0.0, -900.0)
    q = geometry.constrain(p, 1.0, [(100.0, 0.0)], True, ray, 30.0)
    # on the port's axis: (q - origin) is parallel to the ray
    v = (q[0] - 100.0, q[1])
    assert abs(v[0] * math.sin(a) - v[1] * math.cos(a)) < 1e-6 and v[0] > 0
    # far from the ray the 45° / orthogonal choice stays
    far = geometry.constrain((500.0, 400.0), 1.0, [(100.0, 0.0)], True, ray, 30.0)
    assert far == geometry.snap45((100.0, 0.0), (500.0, 400.0), 1.0)


def test_preview_of_an_auto_route_equals_the_routers_oblique_path():
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.design.schema import Route
    from quantcore_circuits.route.router import RouteEnd, plan_route

    def port(x, y, deg):
        return {"pos": (x, y), "dir": (math.cos(math.radians(deg)), math.sin(math.radians(deg)))}

    cases = [(port(0, 0, -18), port(1000 * math.cos(math.radians(-18)), 1000 * math.sin(math.radians(-18)), 162)),
             (port(0, 0, -18), port(1500, -1500, 90)),  # one oblique bend
             (port(2565, 1875, 60), port(2900, 3500, -90)),
             (port(0, 0, 0), port(1000, 800, -90))]  # axis ports: Manhattan, as before
    for s, e in cases:
        mk = lambda q: RouteEnd(pya.DPoint(*q["pos"]), pya.DVector(*q["dir"]), 10, 6)  # noqa: E731
        built = plan_route("P", Route(**{"from": "A.a", "to": "B.a"}), mk(s), mk(e), {"a": 10, "b": 6, "r": 100})
        shown = geometry.route_preview(s["pos"], s["dir"], [], e["pos"], e["dir"], 100.0)
        got = [(p.x, p.y) for p in built.polyline()]
        assert len(got) == len(shown) and all(math.dist(a, b) < 0.02 for a, b in zip(got, shown))


def test_oblique_mids_rejects_hairpins_and_axis_ports():
    assert geometry.oblique_mids((0, 0), (1.0, 0.0), (500, 0), (1.0, 0.0)) is None  # axis ports: Manhattan
    ang = (math.cos(math.radians(60)), math.sin(math.radians(60)))
    assert geometry.oblique_mids((50, 87), ang, (2900, 1600), (0.0, -1.0), 100.0) is None  # the bend would be 150°


def test_delete_route_removes_the_routes_hanging_on_it():
    design = {"routes": {"FL": {"from": "A.a", "to": "B.a"},
                         "R1": {"from": "Q.c", "to": {"hanger": "FL", "s": 10, "length": 300}},
                         "R2": {"from": "Q.d", "to": {"hanger": "R1", "s": 10, "length": 300}},
                         "FLUX": {"from": "P.a", "to": "Q.f"}}}
    assert design_io.delete_route(design, "FL") == ["FL", "R1", "R2"]
    assert list(design["routes"]) == ["FLUX"]
    assert design_io.delete_route(design, "nope") == []


def test_failed_route_in_the_sidecar_has_working_handles():
    # the failed entry is route-shaped: the Route handles list its nodes and insert handles, and editing writes nodes
    f = {"polyline": [[0, 0], [400, 500], [410, 510], [1000, 800]], "waypoints": [[400, 500], [410, 510]],
         "waypoint_index": [1, 2], "waypoint_r": [None, None], "fixed_segments": [], "r": 100, "a": 10, "b": 6}
    route = design_io.editable_route(f)
    wps, inserts = geometry.handle_points(route)
    assert [p for _, p in wps] == [(400, 500), (410, 510)] and [k for k, _ in inserts] == [1, 2, 3]
    design = {"routes": {"R2": {"from": "A.a", "to": "B.a", "nodes": [[400, 500], [410, 510]]}}}
    assert design_io.materialize_nodes(design, "R2", route) == [1, 2]
    design_io.delete_route_node(design, "R2", 1)
    assert design["routes"]["R2"]["nodes"] == [[400, 500]]
    design_io.set_node(design, "R2", 0, at=(420.0, 520.0))
    assert design["routes"]["R2"]["nodes"] == [[420.0, 520.0]]


def test_failure_summary_names_the_route_and_the_reason():
    from qcc_kplugin.session import failure_summary

    text = failure_summary({"R2": "route R2: segment 2 is 39.6 µm but its bends need 43.6 µm"})
    assert text.startswith("Route R2 failed: segment 2 is 39.6") and "drawn in red" in text and "Undo" in text
    assert "and 1 more" in failure_summary({"R2": "route R2: x", "R3": "route R3: y"})
