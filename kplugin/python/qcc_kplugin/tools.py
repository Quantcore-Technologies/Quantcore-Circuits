"""Interactive KLayout tools (toolbar modes) for editing a qcc design in place.

Structure follows KQC's ``kqcircuits/util/edit_node_plugin.py`` (GPL-3.0): a ``pya.PluginFactory`` registers each mode
and creates one ``pya.Plugin`` per view; overlays are ``pya.Marker`` objects sized in screen pixels. Unlike KQC's
node editor these tools never change the layout: every action edits ``design.json`` through
:mod:`qcc_kplugin.design_io` and the session rebuilds it.

* **qcc Connect** — pen tool: start on a port or on empty canvas (a free end), click nodes, finish on a port, on a
  line (a hanger coupler) or on the last node again (a free end) → route dialog (cpw / meander + length, bend
  radius, free-end termination). Clicks snap to KLayout's editor grid; without a modifier each click adds a square
  corner (Manhattan), Shift makes the segment 0° / 45° / 90° or along the start port's own angle when it faces an
  angle, Ctrl places the node as clicked: any angle, one oblique straight. The rubber band shows the route with its
  corners bent to the radius as you move (and the oblique straight the router draws between ports that face an angle).
* **qcc Route handles** — every route shows its nodes (filled squares: click to select and pick up, click to drop;
  right-click deletes) and an insert handle on each free straight segment (hollow square). Nodes move to any angle
  on the grid; Shift snaps to 0° / 45° / 90° or an angled port's axis. A route the last build left out (failed) is
  drawn in red with the same handles. A selected corner shows a curvature handle that sets that corner's own bend
  radius. Double-click a node for its properties, a route for
  its options (type, length, radius, meander segment).
* **qcc Move/Snap** — drag an instance; a port that comes within the capture radius of a compatible port (same CPW,
  facing) snaps, and the placement is stored as ``place.snap``. Otherwise the new ``place.at`` is grid-rounded.
  ``[`` / ``]`` rotate by 90° while dragging; a port near a compatible one also turns the component to face it
  (any angle: StarQubit pins, ConcentricTransmon couplers), unless Ctrl is held. A pending component (double-click in
  the panel, Duplicate) follows the mouse and snaps the same way; the next click drops it.
"""

from __future__ import annotations

from pathlib import Path

import pya  # type: ignore

from qcc_kplugin import design_io, design_ops, dialogs, geometry, joins
from qcc_kplugin.session import SESSION, guard_error, log, message, ok_cancel, report_error

RED, BLUE, GREEN, GREY = 0xDA0037, 0x185ADB, 0x206A5D, 0x888888
# component ref -> catalog class ("qubit", "resonator", ...), filled by the panel from qcc components --details
CATEGORY: dict = {}
JOIN = {"mode": "hang"}  # how Connect ends a route clicked on a line: "hang" (a coupler beside it) or "merge" (a T)


def toggle_join() -> None:
    """Quantcore menu (Ctrl+Shift+J): a route that ends on a line hangs beside it (a hanger coupler) or merges into it (a
    T-junction); the dialog can still change it per route."""
    import time  # pylint: disable=import-outside-toplevel

    now = time.monotonic()
    if now - JOIN.get("at", -1.0) < 0.15:  # the menu shortcut and the tool's own key handler: one press, one switch
        return
    JOIN["at"] = now
    JOIN["mode"] = "merge" if JOIN["mode"] == "hang" else "hang"
    message("Connect on a line: " + ("merge into it (T-junction)" if JOIN["mode"] == "merge"
                                     else "hang beside it (hanger coupler)") + "  ·  Ctrl+Shift+J switches", 6)
    for tool in ACTIVE:
        if isinstance(tool, ConnectTool) and tool.active:
            tool.redraw()

LEFT = pya.ButtonState.LeftButton
RIGHT = pya.ButtonState.RightButton
SHIFT = pya.ButtonState.ShiftKey
CTRL = pya.ButtonState.ControlKey


def _dp(p) -> pya.DPoint:
    return pya.DPoint(p[0], p[1])


def _xy(p: pya.DPoint) -> tuple[float, float]:
    return (p.x, p.y)


def rounded_path(points, width: float, r: float) -> pya.DPath:
    """Sharp polyline → path with every corner bent to radius ``r`` (what KQC does when it builds the route)."""
    path = pya.DPath([_dp(p) for p in points], width)
    if len(points) > 2 and r > 0:
        path = path.round_corners(r, 64, 0.001)
    return path


class _Overlay:
    """A set of markers on one view, rebuilt from scratch on every update."""

    def __init__(self, view):
        self.view = view
        self.markers = []

    def clear(self):
        for m in self.markers:
            m._destroy()  # pylint: disable=protected-access
        self.markers = []

    def px(self, n: float) -> float:
        return n / self.view.viewport_trans().mag

    def box(self, p, size_px=6, color=BLUE, filled=True, width=1):
        s = self.px(size_px)
        m = pya.Marker(self.view)
        m.set(pya.DBox(p[0] - s, p[1] - s, p[0] + s, p[1] + s))
        m.color = color
        m.frame_color = color
        m.line_width = width
        m.vertex_size = 0
        m.dither_pattern = 0 if filled else 1  # stipple 0 = solid, 1 = hollow
        self.markers.append(m)
        return m

    def rect(self, bbox, color=GREY, style=2, width=1):
        m = pya.Marker(self.view)
        m.set(pya.DBox(*bbox))
        m.color = color
        m.frame_color = color
        m.line_style = style
        m.line_width = width
        m.vertex_size = 0
        m.dither_pattern = 1
        self.markers.append(m)
        return m

    def path(self, points, width_um=0.0, color=BLUE, width=1, style=0, r=0.0):
        m = pya.Marker(self.view)
        m.set(rounded_path(points, width_um, r) if width_um or r else pya.DPath([_dp(p) for p in points], 0))
        m.color = color
        m.frame_color = color
        m.line_width = width
        m.line_style = style
        m.vertex_size = 0
        m.dither_pattern = 1
        self.markers.append(m)
        return m

    def arrow(self, port: dict, color=BLUE):
        pos = tuple(port["pos"])
        if not port.get("dir"):
            self.box(pos, 4, color)
            return
        d = tuple(port["dir"])
        tip = geometry.add(pos, geometry.mul(d, self.px(18)))
        self.path([pos, tip], color=color, width=2)
        self.box(pos, 4, color)

    def text(self, p, s, color=BLUE):
        m = pya.Marker(self.view)
        m.set(pya.DText(s, pya.DTrans(pya.DVector(p[0], p[1]))))
        m.color = color
        m.frame_color = color
        m.vertex_size = 0
        self.markers.append(m)
        return m


_GUARDED = ("activated", "deactivated", "update", "mouse_moved_event", "mouse_click_event",
            "mouse_double_click_event", "mouse_button_pressed_event", "mouse_button_released_event", "key_event")


def _guarded(fn, label: str):
    """Wrap a KLayout event handler: an exception is logged + shown in the status bar, never raised into KLayout
    (which would open a "Script Error" dialog from inside a mouse event). Returns False (event not consumed)."""
    import functools  # pylint: disable=import-outside-toplevel

    @functools.wraps(fn)
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            guard_error(label)
            return False

    run.__qcc_guarded__ = True
    return run


class _Tool(pya.Plugin):
    name = "qcc"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for attr in _GUARDED:
            fn = cls.__dict__.get(attr)
            if callable(fn) and not getattr(fn, "__qcc_guarded__", False):
                setattr(cls, attr, _guarded(fn, f"{cls.__name__}.{attr}"))

    def __init__(self, manager, view):  # pylint: disable=super-init-not-called  (as KQC's EditNodePlugin)
        self.manager = manager
        self.view_ = view
        self.overlay = _Overlay(view)
        self.active = False
        self.mouse = (0.0, 0.0)
        self.shift = False  # Shift held at the last mouse event: segments 0° / 45° / 90° / a port's angle
        self.free = False  # Ctrl held: any angle, nodes only on the grid

    # helpers
    @property
    def data(self) -> dict:
        return SESSION.data or {}

    def capture(self) -> float:
        return self.overlay.px(SESSION.capture_px)

    def ports(self) -> dict:
        return self.data.get("ports", {})

    def all_routes(self) -> dict:
        """The built routes and the failed ones (``failed`` set: the path the design asks for, in route form)."""
        failed = {n: {**f, "failed": True} for n, f in (self.data.get("failed_routes") or {}).items()}
        return {**self.data.get("routes", {}), **failed}

    def port_near(self, p, exclude=()) -> str | None:
        pts = {n: tuple(v["pos"]) for n, v in self.ports().items() if n not in exclude}
        return geometry.nearest(pts, p, self.capture())

    def snap(self, p):
        return geometry.snap_grid(p, SESSION.grid)

    def cursor(self, p, color=RED):
        """The snapped point a click would use: a small cross."""
        o, s = self.overlay, self.overlay.px(6)
        o.path([(p[0] - s, p[1]), (p[0] + s, p[1])], color=color, width=1)
        o.path([(p[0], p[1] - s), (p[0], p[1] + s)], color=color, width=1)

    def draw_drc(self):
        """Mark connectivity-DRC issues (dangling ports, crossings, ...) from the sidecar."""
        o = self.overlay
        for issue in self.data.get("drc", []):
            color = RED if issue.get("severity") == "error" else 0xF9813A
            for w in issue.get("where", [])[:1]:
                p = tuple(w)
                s = o.px(7)
                o.path([(p[0] - s, p[1] - s), (p[0] + s, p[1] + s)], color=color, width=2)
                o.path([(p[0] - s, p[1] + s), (p[0] + s, p[1] - s)], color=color, width=2)
                o.text((p[0] + s, p[1] + s), issue.get("rule", ""), color)

    def lom_node(self, port: str) -> str:
        return self.data.get("lom", {}).get("port_nodes", {}).get(port, "")

    def activated(self):
        self.active = True
        ACTIVE[:] = [self]
        if not SESSION.attach_view(self.view_):
            message("qcc: open a qcc-built layout first (Quantcore > Open design...)")
        SESSION.listeners.append(self.redraw)
        self.redraw()

    def deactivated(self):
        self.active = False
        if self.redraw in SESSION.listeners:
            SESSION.listeners.remove(self.redraw)
        self.reset()
        self.overlay.clear()

    def reset(self):
        pass

    def redraw(self):
        pass

    def update(self):  # called by KLayout when the viewport changes: keep marker sizes constant in pixels
        if self.active:
            self.redraw()

    def mouse_moved_event(self, p, buttons, prio):
        self.mouse = _xy(p)
        self.shift = bool(buttons & SHIFT)
        self.free = bool(buttons & CTRL)
        return False


for _attr in _GUARDED:  # the base class's own handlers too
    _fn = _Tool.__dict__.get(_attr)
    if callable(_fn) and not getattr(_fn, "__qcc_guarded__", False):
        setattr(_Tool, _attr, _guarded(_fn, f"_Tool.{_attr}"))


# ---- Connect (pen tool) ------------------------------------------------------------------------------------------
class ConnectTool(_Tool):
    """Pen-tool routing. Start on a port, or on empty canvas (a free end); every canvas click adds a node; finish on
    a port, on a line (a hanger coupler on it), or by clicking the last node again (a free end there). Clicks snap
    to the grid. Without Shift a segment turns once with a square corner (the preview shows it and the click commits
    it, so the built route is what was previewed); with Shift it goes straight at 0° / 45° / 90° / …. Right-click
    removes the last click (or cancels)."""

    def reset(self):
        self.start = None  # port name
        self.start_free = None  # (x, y) of a free start
        self.waypoints = []
        self.clicks = []  # nodes added by each click (a click can add a square corner and its node)

    def __init__(self, manager, view):
        super().__init__(manager, view)
        self.reset()

    @property
    def started(self) -> bool:
        return self.start is not None or self.start_free is not None

    def keep_state(self):
        """The route in progress, to carry it over a layout reload (a rebuild that lands while the user is drawing
        switches the tool off and on again, which would otherwise drop the clicks made so far)."""
        if not self.started:
            return None
        return {"start": self.start, "start_free": self.start_free, "waypoints": list(self.waypoints),
                "clicks": list(self.clicks)}

    def restore_state(self, state) -> None:
        """Take back a :meth:`keep_state` after the reload; dropped when its start port is gone."""
        if not state or (state["start"] is not None and state["start"] not in self.ports()):
            return
        self.start, self.start_free = state["start"], state["start_free"]
        self.waypoints, self.clicks = list(state["waypoints"]), list(state["clicks"])
        self.redraw()

    def stub(self) -> float:
        return float(self.data.get("pdk", {}).get("turn_radius", 100.0))

    def start_point(self):
        """(position, outward direction or None) of the route start."""
        if self.start_free is not None:
            return self.start_free, None
        sp = self.ports()[self.start]
        return tuple(sp["pos"]), (tuple(sp["dir"]) if sp.get("dir") else None)

    def anchor(self):
        """The previous point of the route (what Shift aligns the next segment with): the last node, the free start,
        or the end of the start port's stub."""
        if self.waypoints:
            return self.waypoints[-1]
        pos, d = self.start_point()
        return pos if d is None else geometry.add(pos, geometry.mul(d, self.stub()))

    def rays(self) -> list:
        """The axis of the start port when it faces an angle (a StarQubit pin, a ConcentricTransmon coupler): offered
        by Shift next to 0° / 45° / 90°, so a node can sit exactly on the port's own direction."""
        if self.start is None:
            return []
        pos, d = self.start_point()
        return [] if d is None or geometry.is_axis(d) else [(pos, d)]

    def anchor_dir(self):
        """Direction of the segment arriving at the anchor: the next square corner leaves along it."""
        if not self.waypoints:
            return self.start_point()[1]
        prev = self.waypoints[-2] if len(self.waypoints) > 1 else self.anchor_before(None)
        d = geometry.sub(self.waypoints[-1], prev)
        return d if geometry.norm(d) > geometry.EPS else None

    def segment_to(self, q):
        """Nodes a click at ``q`` (already on the grid / Shift-snapped) adds: the square corner the preview shows,
        then ``q``; with Shift just ``q`` (a straight 0° / 45° / 90° / port-angle segment), with Ctrl just ``q`` at the
        clicked point (any angle)."""
        if geometry.dist(q, self.anchor()) < geometry.EPS:
            return []
        return [q] if self.shift or self.free else geometry.elbow(self.anchor(), self.anchor_dir(), q) + [q]

    def port_corner(self, end_port: str):
        """Square corner into the stub of ``end_port`` after the user's nodes (none without nodes: the router turns
        by itself then, as before; none with Shift or Ctrl: straight into the stub)."""
        ep = self.ports()[end_port]
        if not self.waypoints or self.shift or self.free or not ep.get("dir"):
            return []
        tail = geometry.add(tuple(ep["pos"]), geometry.mul(tuple(ep["dir"]), self.stub()))
        return geometry.elbow(self.anchor(), self.anchor_dir(), tail)

    def node_point(self, p):
        """A canvas click / hover at ``p`` → the node it places (grid; Shift: 0° / 45° / 90° or the start port's angle;
        Ctrl: the grid point, any angle)."""
        return geometry.constrain(p, SESSION.grid, [self.anchor()] if self.started else [],
                                  self.shift and not self.free, self.rays() if self.started else [], self.capture())

    def target(self, p):
        """What a click at ``p`` does: ("start-port", name) / ("start-free", pt) before the start; then ("port",
        name) / ("finish-free", pt) / ("line", (route, seg)) / ("node", pt). A port near the click always wins, so
        port → port routing behaves as before."""
        if not self.started:
            name = self.port_near(p)
            return ("start-port", name) if name else ("start-free", self.node_point(p))
        name = self.port_near(p, exclude=(self.start,) if self.start else ())
        if name:
            return ("port", name)
        if self.waypoints and geometry.dist(p, self.waypoints[-1]) <= self.capture():
            return ("finish-free", self.waypoints[-1])
        host = self.route_near(p)
        if host is not None:
            return ("line", host)
        return ("node", self.node_point(p))

    def redraw(self):
        o = self.overlay
        o.clear()
        self.draw_drc()
        kind, what = self.target(self.mouse)
        hover = what if kind in ("start-port", "port") else None
        for name, port in self.ports().items():
            o.arrow(port, RED if name in (self.start, hover) else BLUE)
        if not self.started:
            if hover:
                node = self.lom_node(hover)
                o.text(self.mouse, f"{hover}  [node {node}]" if node else hover, RED)
            else:
                self.cursor(what)
                o.text(what, "click: start a free end here (or click a port)", GREY)
            return
        start, start_dir = self.start_point()
        if self.start is not None and start_dir is None:
            o.text(self.mouse, f"{self.start} has no direction; pick another port", RED)
            return
        wps = list(self.waypoints)
        end_dir = None
        if kind == "port":
            ep = self.ports()[what]
            end, end_dir = tuple(ep["pos"]), (tuple(ep["dir"]) if ep.get("dir") else None)
            wps += self.port_corner(what)
            label = f"→ {what}"
        elif kind == "finish-free":
            end, wps = wps[-1], wps[:-1]
            label = "click: end here (free end)"
        elif kind == "line":
            pts_h = [tuple(q) for q in self.data["routes"][what[0]]["polyline"]]
            if not geometry.is_axis(geometry.unit(geometry.sub(pts_h[what[1]], pts_h[what[1] - 1]))):
                end = self.mouse
                label = f"{what[0]} is oblique here: a coupler needs a horizontal or vertical straight"
            elif JOIN["mode"] == "merge":
                end = joins.arclength(pts_h, self.mouse)[2]
                label = f"merge into {what[0]} here (T-junction)  [Ctrl+Shift+J: hang instead]"
            else:
                end = self.mouse
                label = f"hang from {what[0]} here  [Ctrl+Shift+J: merge instead]"
        else:
            end = what
            wps += self.segment_to(what)
            label = "click: node · click the last node again: free end · port or line: finish"
            self.cursor(what)
        pts = geometry.route_preview(start, start_dir, wps, end, end_dir, self.stub())
        sp = self.ports().get(self.start, {}) if self.start else {}
        a, b = sp.get("a", 10.0), sp.get("b", 6.0)
        o.path(pts, color=GREY, style=2)
        o.path(pts, width_um=a + 2 * b, color=RED, r=self.stub())
        if self.start_free is not None:
            o.box(self.start_free, 5, RED, filled=False, width=2)
        for w in self.waypoints:
            o.box(w, 4, RED)
        o.text(self.mouse, f"{self.start or 'free end'} {label}" + (
            "  [Ctrl: any angle]" if self.free else "  [Shift: 0/45/90° or the port's angle]" if self.shift else ""), RED)

    def mouse_moved_event(self, p, buttons, prio):
        super().mouse_moved_event(p, buttons, prio)
        if prio and self.active:
            self.redraw()
        return False

    def mouse_click_event(self, p, buttons, prio):
        if not (prio and self.active):
            return False
        self.shift = bool(buttons & SHIFT)
        self.free = bool(buttons & CTRL)
        here = _xy(p)
        if buttons & RIGHT:  # remove the last node, or cancel
            if self.waypoints:
                self.undo_click()
            else:
                self.reset()
            self.redraw()
            return True
        if not buttons & LEFT:
            return False
        kind, what = self.target(here)
        try:
            if kind == "start-port":
                self.start = what
            elif kind == "start-free":
                self.start_free = what
                message("free end: click nodes, then a port, a line, or the last node again (right-click: undo node)", 6)
            elif kind == "node":
                added = self.segment_to(what)
                self.waypoints += added
                if added:
                    self.clicks.append(len(added))
            elif kind == "port":
                self.finish(what)
            elif kind == "finish-free":
                self.finish_free()
            elif kind == "line":
                self.finish_hanger(what, here)
        except Exception:  # noqa: BLE001
            self.reset()
            report_error("the route")
        self.redraw()
        return True

    def key_event(self, key, buttons):
        if not self.active:
            return False
        if key == pya.KeyCode.Escape:
            self.reset()
            self.redraw()
            return True
        if key == pya.KeyCode.Backspace and self.waypoints:
            self.undo_click()
            self.redraw()
            return True
        return False

    def undo_click(self):
        """Remove the nodes the last click added (a square corner goes with its node)."""
        n = self.clicks.pop() if self.clicks else 1
        del self.waypoints[-n:]

    def route_near(self, p):
        """(route, segment) under ``p`` (capture radius), not a route starting at the start port."""
        routes = self.data.get("routes", {})
        mine = tuple(n for n, r in routes.items() if self.start and self.start in (r.get("from"), r.get("to")))
        return geometry.route_near(routes, p, self.capture(), exclude=mine)

    def route_r(self, value):
        """The route's ``r`` for design.json: None when the dialog still holds the PDK turn radius it was preset
        with, so the route keeps following the PDK (a changed value is written)."""
        pdk_r = self.data.get("pdk", {}).get("turn_radius")
        if value is not None and pdk_r is not None and abs(float(value) - float(pdk_r)) < 1e-9:
            return None
        return value

    def _src(self, free_kind: str, gap: float):
        """The route's ``from``: the start port, or the free start (open/short)."""
        if self.start is not None:
            return self.start
        return design_io.free_end(self.start_free, None, free_kind, gap)

    def pdk_ab_if_wide(self):
        """The PDK CPW (a, b) when the start port is no CPW end (a reference plane much wider than the PDK line, e.g.
        a Gatemon ``readout`` island edge, a = 150 µm): a route would otherwise take that width. (None, None) else."""
        pdk = self.data.get("pdk", {})
        pa, pb = pdk.get("cpw_a"), pdk.get("cpw_b")
        sp = self.ports().get(self.start, {}) if self.start else {}
        if pa and pb and sp and (float(sp.get("a", pa)) > 3 * float(pa) or float(sp.get("b", pb)) > 3 * float(pb)):
            return float(pa), float(pb)
        return None, None

    def finish_hanger(self, host, here):
        """End the route on route ``host[0]`` at the clicked point: as a hanger coupler beside it (a λ/4 readout on a
        feedline: meander from a claw or from a free open end, short end on the line), or merged into it with a T
        (the join mode, Ctrl+Shift+J; the dialog's checkbox decides)."""
        rname, seg = host
        poly = self.data["routes"][rname]["polyline"]
        if not geometry.is_axis(geometry.unit(geometry.sub(tuple(poly[seg]), tuple(poly[seg - 1])))):
            message(f"{rname}: this straight is oblique; a coupler (hanger or T-junction) sits on a horizontal or "
                    "vertical straight. Click another straight of the line.", 8)
            return
        toward = self.waypoints[-1] if self.waypoints else self.start_point()[0]
        side = geometry.hanger_side(poly, seg, toward)
        design = SESSION.design()
        a0, b0 = self.pdk_ab_if_wide()
        opts = hanger_dialog(design_io.unique_name(design, "R"), rname, side, self.data.get("pdk", {}).get("turn_radius"),
                             free_start=self.start_free is not None, merge=JOIN["mode"] == "merge", a=a0, b=b0,
                             wide_port=self.start if a0 is not None else None)
        if opts is not None and opts.get("merge"):
            self.finish_merge(design, rname, poly, here, opts)
        elif opts is not None:
            dst = design_io.hanger_end(rname, here, opts["coupler"], opts["side"], opts["end"], opts["gap"],
                                       opts.get("direction", "forward"), opts.get("coupler_gap"),
                                       opts.get("line_gap"))
            src = self._src(opts.get("free", "open"), opts.get("free_gap", 6.0))
            design_io.add_route(design, opts["name"], src, dst, opts["kind"], opts["length"], self.waypoints,
                                self.route_r(opts["r"]), opts.get("a"), opts.get("b"))
            SESSION.commit(design, f"route {opts['name']}: {self.start or 'free end'} → hanger on {rname} "
                                   f"({opts['kind']}, {opts['coupler']:g} µm, {opts['side']})")
        self.reset()

    def finish_merge(self, design, rname, poly, here, opts):
        """Split line ``rname`` at ``here`` with a T (KQC ``WaveguideCoplanarSplitter``) whose stem faces the dialog's
        side and end the route on the stem: a capacitor or a resonator galvanically on the line, not beside it."""
        host = self.data["routes"][rname]
        r_host = float(host.get("r") or self.stub())
        pdk = self.data.get("pdk", {})
        tee_params = {k: float(host[k]) for k in ("a", "b")
                      if host.get(k) is not None and abs(float(host[k]) - float(pdk.get(f"cpw_{k}", -1))) > 1e-9}
        try:
            out = joins.merge(design, rname, poly, here, opts["side"], r_host, tee_params)
        except ValueError as e:
            message(str(e), 8)
            return
        src = self._src(opts.get("free", "open"), opts.get("free_gap", 6.0))
        nodes = list(self.waypoints)
        if nodes and not self.shift and not self.free:  # square corner into the stem's stub, as into any port
            tail = geometry.add(out["stem_pos"], geometry.mul(out["stem_dir"], self.stub()))
            nodes += geometry.elbow(self.anchor(), self.anchor_dir(), tail)
        design_io.add_route(design, opts["name"], src, out["stem"], opts["kind"], opts["length"], nodes,
                            self.route_r(opts["r"]), opts.get("a"), opts.get("b"))
        SESSION.commit(design, f"route {opts['name']}: {self.start or 'free end'} → merged into {rname} with "
                               f"{out['tee']} ({rname} split into {rname} + {out['second']})")

    def finish(self, end):
        design = SESSION.design()
        a0, b0 = self.pdk_ab_if_wide()
        opts = route_dialog(design_io.unique_name(design, "R"), "cpw", None, self.data.get("pdk", {}).get("turn_radius"),
                            free_ends=["start"] if self.start_free is not None else [], a=a0, b=b0)
        if opts is not None:
            src = self._src(opts.get("free_start", "open"), opts.get("free_gap", 6.0))
            nodes = self.waypoints + self.port_corner(end)
            design_io.add_route(design, opts["name"], src, end, opts["kind"], opts["length"], nodes,
                                self.route_r(opts["r"]), opts.get("a"), opts.get("b"))
            SESSION.commit(design, f"route {opts['name']}: {self.start or 'free end'} → {end} ({opts['kind']})")
        self.reset()

    def finish_free(self):
        """The last node clicked again: the route ends there in a free end pointing back along the last segment."""
        if self.start is None:
            message("a route needs a port or a line at one end: finish on a port or on a line", 6)
            return
        end = self.waypoints[-1]
        nodes = self.waypoints[:-1]
        toward = nodes[-1] if nodes else self.anchor_before(end)
        design = SESSION.design()
        opts = route_dialog(design_io.unique_name(design, "R"), "cpw", None, self.data.get("pdk", {}).get("turn_radius"),
                            free_ends=["end"])
        if opts is not None:
            dst = design_io.free_end(end, geometry.free_end_dir(end, toward), opts.get("free_end", "open"),
                                     opts.get("free_gap", 6.0))
            design_io.add_route(design, opts["name"], self.start, dst, opts["kind"], opts["length"], nodes,
                                self.route_r(opts["r"]), opts.get("a"), opts.get("b"))
            SESSION.commit(design, f"route {opts['name']}: {self.start} → free end ({opts['kind']})")
        self.reset()

    def anchor_before(self, end):
        pos, d = self.start_point()
        return pos if d is None else geometry.add(pos, geometry.mul(d, self.stub()))


MERGE_TEXT = "Merge into {host} (T-junction) instead of hanging beside it"
SEGMENT_TEXT = "Meander on straight"
MEANDER_SIDES = ("left of the travel (+1)", "right of the travel (-1)")


def _num(v) -> str:
    """A number for a line edit without losing digits (``:g`` keeps 6: 3965.944 would read back as 3965.94)."""
    return format(float(v), ".12g")


C_UM_PER_NS = 299792.458  # speed of light, µm / ns


def substrate_eps() -> float:
    """εr of the open design's substrate (Chip settings; the PDK's by default), from the sidecar."""
    try:
        return float(((SESSION.data or {}).get("pdk") or {}).get("substrate_eps_r") or 10.25)
    except Exception:  # noqa: BLE001
        return 10.25


def length_hint(text: str, eps_r: float | None = None) -> str:
    """Bare λ/4 frequency of a CPW of this length on the design's substrate: f = c / (4 L √ε_eff), ε_eff = (εr + 1) / 2
    (a thick substrate; a claw or a hanger coupler loads it a few % to ~10 % lower: Q1 + R1, 4200 µm: 7.5 GHz bare,
    6.65 GHz in its LOM). The thickness does not matter at these widths; the loss tangent sets Q, not f."""
    eps_r = substrate_eps() if eps_r is None else float(eps_r)
    v = C_UM_PER_NS / ((eps_r + 1) / 2) ** 0.5  # µm / ns
    try:
        length = float(text)
    except ValueError:
        length = 0.0
    seven = v / (4 * 7.0)
    if length <= 0:
        return f"λ/4 at 7 GHz ≈ {seven:.0f} µm (εr {eps_r:g})"
    return (f"≈ {v / (4 * length):.2f} GHz bare λ/4 on εr {eps_r:g} (a coupler pulls it lower) · 7 GHz ≈ "
            f"{seven:.0f} µm")


def _free_rows(dialog, form, label: str):
    """Rows for one free end: open/short and the open gap."""
    e_end = pya.QComboBox(dialog)
    e_end.addItems(["open", "short"])
    e_gap = pya.QLineEdit("6", dialog)
    form.addRow(f"Free end ({label})", e_end)
    form.addRow(f"Open gap µm ({label})", e_gap)
    return e_end, e_gap


def route_dialog(name, kind, length, r, title="qcc route", free_ends=(), segment=None, segments=None,
                 targets=None, a=None, b=None, join=None, hanger=None, meander=None, lom_of=None, error=None,
                 last_good=None):
    """Route options → dict ``{name, kind, length, r, a, b}`` (+ ``free_<end>``/``free_gap`` for each free end,
    ``segment`` for the meander segment, ``merge`` when ``join`` is given) or None. ``length`` is only used for
    meanders; ``a`` / ``b`` (CPW width and gap, empty = taken from the ports) are written only when set. ``join`` =
    ``(line, merged)`` for a route that ends on a line: the checkbox merges it into the line with a T (checked) or
    hangs it beside the line (unchecked). ``hanger`` (the route's hanger end) adds its coupler rows → ``out["hanger"]``
    with the edited ``length``, ``side``, ``end``, ``ground_gap``, ``open_gap``, ``direction``. ``meander``
    (``{"meanders", "meander_direction"}`` of an existing route) adds the meander's turn count and first-turn side →
    ``out["meanders"]`` (-1 = automatic) and ``out["meander_direction"]`` (1 / -1). ``error`` (a route the last build
    left out) shows why at the top, with ``last_good`` (its last good length) and a "Delete this route" box →
    ``out["delete"]``."""
    dialog = pya.QDialog(pya.Application.instance().main_window())
    dialog.windowTitle = title
    form = dialogs.Rows(dialog)  # rows in one or two columns; the dialog scrolls and fits the screen
    e_delete = None
    if error:
        why = pya.QLabel("This route failed to build and is not in the layout:\n" + error + (
            f"\nIts last good route ({last_good['length']:.1f} µm) stands in for it in the LOM." if last_good
            and isinstance(last_good.get("length"), (int, float)) else
            "\nNo earlier good route is stored: the LOM and the fab export need it fixed."), dialog)
        why.wordWrap = True
        why.styleSheet = "color: #b00020"
        form.addRow(why)
        e_delete = pya.QCheckBox("Delete this route", dialog)
        form.addRow(e_delete)
        form.section()
    e_name = pya.QLineEdit(name, dialog)
    e_kind = pya.QComboBox(dialog)
    e_kind.addItems(["cpw", "meander"])
    e_kind.currentText = kind
    e_len = pya.QLineEdit("" if length is None else _num(length), dialog)
    hint = pya.QLabel(length_hint(e_len.text), dialog)
    try:
        e_len.textChanged(lambda t: setattr(hint, "text", length_hint(t)))
    except Exception:  # noqa: BLE001
        pass
    e_r = pya.QLineEdit("" if r is None else _num(r), dialog)
    form.addRow("Name", e_name)
    form.addRow("Type", e_kind)
    form.addRow("Length µm (meander)", e_len)
    form.addRow("", hint)
    form.addRow("Bend radius µm", e_r)
    e_a, e_b = _ab_rows(dialog, form, a, b)
    e_seg = None
    seg_keys = [None]
    if segments is not None:  # [(segment, length µm, clicked)] of the free straights (stubs / couplers left out)
        e_seg = pya.QComboBox(dialog)
        longest = max(segments, key=lambda t: t[1])[0] if segments else None
        e_seg.addItem("automatic: the longest free straight" + (f" (now {longest})" if longest else ""))
        for k, length, clicked in segments:
            e_seg.addItem(f"{k} · {length:.0f} µm" + ("  (where you double-clicked)" if clicked else ""))
            seg_keys.append(k)
        if segment in seg_keys:
            e_seg.currentIndex = seg_keys.index(segment)
        e_seg.toolTip = ("Which straight of the route holds the meander. Segments count from the route's start; port "
                         "stubs and the hanger coupler are not offered. Ctrl+Shift+M in Route handles puts it on the "
                         "straight under the cursor.")
        form.addRow(SEGMENT_TEXT, e_seg)
    e_turns = e_mdir = None
    if meander is not None:
        e_turns = pya.QLineEdit("" if int(meander.get("meanders", -1)) < 0 else str(meander["meanders"]), dialog)
        e_turns.toolTip = "Number of meander periods; empty = as many as the length needs on the straight (KQC)"
        e_mdir = pya.QComboBox(dialog)
        e_mdir.addItems(MEANDER_SIDES)
        e_mdir.currentText = MEANDER_SIDES[0] if int(meander.get("meander_direction", 1)) == 1 else MEANDER_SIDES[1]
        e_mdir.toolTip = "Which side of the straight the meander's first turn goes to (flips the meander over)"
        form.addRow("Meander turns (empty = automatic)", e_turns)
        form.addRow("Meander first turn", e_mdir)
    frees = {end: _free_rows(dialog, form, end) for end in free_ends}
    hrows = None
    if hanger is not None:
        hrows = {
            "length": pya.QLineEdit(_num(hanger.get("length", 300)), dialog),
            "side": pya.QComboBox(dialog), "end": pya.QComboBox(dialog),
            "ground_gap": pya.QLineEdit(_num(hanger.get("ground_gap", 6.0)), dialog),
            "open_gap": pya.QLineEdit(_num(hanger.get("open_gap", 6.0)), dialog),
            "direction": pya.QComboBox(dialog),
        }
        hrows["side"].addItems(["left", "right"])
        hrows["side"].currentText = hanger.get("side", "left")
        hrows["end"].addItems(["short", "open"])
        hrows["end"].currentText = hanger.get("end", "short")
        hrows["direction"].addItems(["forward", "backward"])
        hrows["direction"].currentText = hanger.get("direction", "forward")
        host = hanger.get("hanger", "the line")
        form.section(HANGER_TITLE.format(host=host))
        form.addRow(f"Coupler length on {host} µm", hrows["length"])
        form.addRow("Side of the line", hrows["side"])
        form.addRow("Coupler end (short = λ/4)", hrows["end"])
        form.addRow("Ground strip µm", hrows["ground_gap"])
        form.addRow("Open gap µm (open end)", hrows["open_gap"])
        hrows["coupler_gap"], hrows["line_gap"] = _facing_gap_rows(dialog, form, host, hanger.get("coupler_gap"),
                                                                  hanger.get("line_gap"))
        form.addRow("Direction (forward = ends downstream)", hrows["direction"])
    e_merge = None
    if join is not None:
        e_merge = pya.QCheckBox(MERGE_TEXT.format(host=join[0]), dialog)
        e_merge.checked = bool(join[1])
        e_merge.toolTip = ("Checked: a T-junction splits the line and the route ends on its stem. Unchecked: the "
                           "route ends in a hanger coupler beside the line (300 µm, short end; double-click the "
                           "route again to change it).")
        form.addRow(e_merge)
    editor = None
    if targets is not None:  # a resonator: f_r, kappa, ... targets (the section is only offered by the caller)
        form.section()
        holder = pya.QVBoxLayout()
        form.addRow(holder)
        editor = TargetsEditor(dialog, holder, design_io.target_keys("route", "", targets), targets)
    if lom_of:
        form.section()
        holder2 = pya.QVBoxLayout()
        form.addRow(holder2)
        lom_section(dialog, holder2, lom_of)
    dialog.qcc_rows = form  # tests
    dialogs.fit(dialog, form.build(), ok_cancel(dialog))
    if not dialog.exec_():
        return None
    try:
        k = e_kind.currentText
        length = float(e_len.text) if e_len.text.strip() else None
        if k == "meander" and not length:
            raise ValueError("A meander needs a length.")
        if e_delete is not None and e_delete.checked:
            return {"delete": True}
        out = {"name": e_name.text.strip(), "kind": k, "length": length,
               "r": float(e_r.text) if e_r.text.strip() else None, **_ab_values(e_a, e_b)}
        if editor is not None:
            out["targets"] = editor.values()
        if e_seg is not None:
            out["segment"] = seg_keys[e_seg.currentIndex] if 0 <= e_seg.currentIndex < len(seg_keys) else None
        if e_merge is not None:
            out["merge"] = bool(e_merge.checked)
        if e_turns is not None:
            out["meanders"] = int(e_turns.text) if e_turns.text.strip() else -1
            out["meander_direction"] = 1 if e_mdir.currentText == MEANDER_SIDES[0] else -1
        if hrows is not None:
            out["hanger"] = {"length": float(hrows["length"].text), "side": hrows["side"].currentText,
                             "end": hrows["end"].currentText, "ground_gap": float(hrows["ground_gap"].text),
                             "open_gap": float(hrows["open_gap"].text), "direction": hrows["direction"].currentText,
                             **_facing_gap_values(hrows["coupler_gap"], hrows["line_gap"])}
        for end, (e_end, e_gap) in frees.items():
            out[f"free_{end}"] = e_end.currentText
            out["free_gap"] = float(e_gap.text)
        return out
    except ValueError as e:
        pya.MessageBox.warning("qcc route", str(e), pya.MessageBox.Ok)
        return None


HANGER_TITLE = "Hanger coupler beside {host}"
FACING_GAP_TEXT = "Coupler: this route's gap facing the line µm (empty = its b)"
LINE_GAP_TEXT = "Coupler: {host}'s gap facing this route µm (empty = {host}'s b)"


def _facing_gap_rows(dialog, form, host, coupler_gap, line_gap):
    """Rows for the two gaps that face each other along a hanger coupler (empty = the CPW's own gap ``b``)."""
    e_c = pya.QLineEdit("" if coupler_gap is None else _num(coupler_gap), dialog)
    e_l = pya.QLineEdit("" if line_gap is None else _num(line_gap), dialog)
    e_c.toolTip = (f"Along the coupler only: this route's gap on the side that faces {host} (between its centre line and "
                   f"the ground strip). Empty = this route's own gap b. Narrower facing gaps bring the two centre lines "
                   f"closer by what they save: stronger coupling at the same ground strip.")
    e_l.toolTip = (f"Along the coupler only: {host}'s gap on the side that faces this route. Empty = {host}'s own gap "
                   f"b. {host} keeps its gap everywhere else, and both outer gaps keep theirs.")
    form.addRow(FACING_GAP_TEXT, e_c)
    form.addRow(LINE_GAP_TEXT.format(host=host), e_l)
    return e_c, e_l


def _facing_gap_values(e_c, e_l) -> dict:
    return {"coupler_gap": float(e_c.text) if e_c.text.strip() else None,
            "line_gap": float(e_l.text) if e_l.text.strip() else None}


def _ab_rows(dialog, form, a, b):
    """Rows for the CPW width a and gap b of a route (empty = from the ports)."""
    e_a = pya.QLineEdit("" if a is None else _num(a), dialog)
    e_b = pya.QLineEdit("" if b is None else _num(b), dialog)
    e_a.toolTip = e_b.toolTip = ("This route's centre line width a and its gap b on both sides, over its whole "
                                 "length. Empty = the CPW of the start port; set both to give the route its own.")
    form.addRow("Line width a µm (this route; empty = the ports')", e_a)
    form.addRow("Line gap b µm (this route, both sides; empty = the ports')", e_b)
    return e_a, e_b


def _ab_values(e_a, e_b) -> dict:
    out = {}
    if e_a.text.strip():
        out["a"] = float(e_a.text)
    if e_b.text.strip():
        out["b"] = float(e_b.text)
    return out


def hanger_dialog(name, host, side, r, free_start=False, merge=False, a=None, b=None, wide_port=None):
    """Options of a route ending on line ``host`` → dict ``{name, kind, length, r, coupler, side, end, gap, merge}``
    (+ ``free``/``free_gap`` for a free start) or None. ``merge`` presets the checkbox that merges the route into the
    line with a T instead of hanging it beside the line (the coupler fields are then unused); ``a`` / ``b`` preset the
    line's own width / gap (``wide_port``: the start port that is no CPW end, named in a note)."""
    dialog = pya.QDialog(pya.Application.instance().main_window())
    dialog.windowTitle = f"qcc route: hang from {host}"
    form = dialogs.Rows(dialog)  # rows in one or two columns; the dialog scrolls and fits the screen
    e_name = pya.QLineEdit(name, dialog)
    e_kind = pya.QComboBox(dialog)
    e_kind.addItems(["meander", "cpw"])
    e_len = pya.QLineEdit("4200", dialog)
    e_len.toolTip = "Total resonator length (µm), coupler included"
    hint = pya.QLabel(length_hint(e_len.text), dialog)
    try:
        e_len.textChanged(lambda t: setattr(hint, "text", length_hint(t)))
    except Exception:  # noqa: BLE001
        pass
    e_r = pya.QLineEdit("" if r is None else _num(r), dialog)
    e_cpl = pya.QLineEdit("300", dialog)
    e_side = pya.QComboBox(dialog)
    e_side.addItems(["left", "right"])
    e_side.currentText = side
    e_end = pya.QComboBox(dialog)
    e_end.addItems(["short", "open"])
    e_gap = pya.QLineEdit("6", dialog)
    e_dir = pya.QComboBox(dialog)
    e_dir.addItems(["forward", "backward"])
    e_dir.toolTip = ("Which end of the coupler the route terminates at: forward = downstream along the line "
                     "(the way the line runs from its first to its last port)")
    e_merge = pya.QCheckBox(MERGE_TEXT.format(host=host), dialog)
    e_merge.checked = bool(merge)
    e_merge.toolTip = ("Checked: the line is split here by a T-junction (WaveguideCoplanarSplitter) and this route "
                       "ends on its stem, galvanically on the line (e.g. a finger capacitor to a feedline). "
                       "Unchecked: a hanger coupler runs beside the line. Ctrl+Shift+J switches the default.")
    form.addRow(e_merge)
    if merge:  # a merged route is mostly a short line to a capacitor; a hanger mostly a λ/4 meander
        e_kind.currentText = "cpw"
    try:
        e_merge.toggled(lambda on: setattr(e_kind, "currentText", "cpw" if on else "meander"))
    except Exception:  # noqa: BLE001
        pass
    form.addRow("Name", e_name)
    form.addRow("Type", e_kind)
    form.addRow("Meander length µm", e_len)
    form.addRow("", hint)
    form.addRow("Bend radius µm", e_r)
    e_a, e_b = _ab_rows(dialog, form, a, b)
    if wide_port:
        note = pya.QLabel(f"{wide_port} is no CPW end (wider than the PDK line): the width / gap above are the PDK "
                          "line's. Empty = the port's.", dialog)
        note.wordWrap = True
        form.addRow("", note)
    form.section(HANGER_TITLE.format(host=host))
    form.addRow(f"Coupler length on {host} µm", e_cpl)
    form.addRow("Side of the line (preset: where you came from)", e_side)
    form.addRow("Coupler end (short = λ/4)", e_end)
    form.addRow("Ground strip µm", e_gap)
    e_cgap, e_lgap = _facing_gap_rows(dialog, form, host, None, None)
    form.addRow("Direction (forward = ends downstream)", e_dir)
    if free_start:
        form.section()
    free = _free_rows(dialog, form, "start") if free_start else None
    dialog.qcc_rows = form  # tests
    dialogs.fit(dialog, form.build(), ok_cancel(dialog))
    if not dialog.exec_():
        return None
    try:
        k = e_kind.currentText
        length = float(e_len.text) if e_len.text.strip() else None
        if k == "meander" and not length:
            raise ValueError("a meander needs a length")
        out = {"name": e_name.text.strip(), "kind": k, "length": length,
               "r": float(e_r.text) if e_r.text.strip() else None, "coupler": float(e_cpl.text),
               "side": e_side.currentText, "end": e_end.currentText, "gap": float(e_gap.text),
               "direction": e_dir.currentText, "merge": bool(e_merge.checked), **_ab_values(e_a, e_b),
               **_facing_gap_values(e_cgap, e_lgap)}
        if free is not None:
            out["free"], out["free_gap"] = free[0].currentText, float(free[1].text)
        return out
    except ValueError as e:
        pya.MessageBox.warning("qcc route", str(e), pya.MessageBox.Ok)
        return None


def node_dialog(route: str, index: int, props: dict, route_r: float):
    """Node ``index`` of ``route``: x, y, bend radius of its corner (empty = the route's), airbridge, and the line
    width / gap from this node on (a taper; empty = as before the node) → dict or None."""
    dialog = pya.QDialog(pya.Application.instance().main_window())
    dialog.windowTitle = f"qcc node {route}[{index}]"
    form = pya.QFormLayout(dialog)
    e_x = pya.QLineEdit(_num(props['at'][0]), dialog)
    e_y = pya.QLineEdit(_num(props['at'][1]), dialog)
    e_r = pya.QLineEdit("" if props.get("r") is None else _num(props['r']), dialog)
    e_r.toolTip = f"Bend radius of this corner only; empty = the route radius ({route_r:g} µm)"
    e_ab = pya.QCheckBox("airbridge at this node", dialog)
    e_ab.checked = bool(props.get("airbridge"))
    e_a = pya.QLineEdit("" if props.get("a") is None else _num(props["a"]), dialog)
    e_b = pya.QLineEdit("" if props.get("b") is None else _num(props["b"]), dialog)
    e_a.toolTip = e_b.toolTip = "From this node to the end the line tapers to this width / gap; empty = unchanged"
    form.addRow("x µm", e_x)
    form.addRow("y µm", e_y)
    form.addRow(f"Corner radius µm (route: {route_r:g})", e_r)
    form.addRow("", e_ab)
    form.addRow("Taper: line width a µm from here (empty = unchanged)", e_a)
    form.addRow("Taper: line gap b µm from here (empty = unchanged)", e_b)
    form.addRow(ok_cancel(dialog))
    if not dialog.exec_():
        return None
    try:
        return {"at": (float(e_x.text), float(e_y.text)), "r": float(e_r.text) if e_r.text.strip() else None,
                "airbridge": bool(e_ab.checked), "a": float(e_a.text) if e_a.text.strip() else None,
                "b": float(e_b.text) if e_b.text.strip() else None}
    except ValueError as e:
        pya.MessageBox.warning("qcc node", str(e), pya.MessageBox.Ok)
        return None


# ---- Route handles (node editing) ----------------------------------------------------------------------------------
class RouteEditTool(_Tool):
    """Pen-tool node editing. Click a node (filled square) to select it and pick it up, move, click to drop it (grid,
    any angle; Shift aligns it with its neighbours at 0° / 45° / 90° or on an angled port's axis, Ctrl = no
    alignment). A route the last build left out is drawn in red with its handles: edit its nodes, double-click it for
    its options, or press Delete on its line to delete the route. A selected corner shows its curvature handle (green, on the arc): pick it,
    move, drop to set that corner's bend radius. Hollow squares insert a node. Right-click a node deletes it."""

    def reset(self):
        self.drag = None  # (route, "move" | "insert" | "radius", index)

    def __init__(self, manager, view):
        super().__init__(manager, view)
        self.selected = None  # (route, node index)
        self.reset()

    # ---- geometry of the sidecar routes
    def routes(self) -> dict:
        """The sidecar routes with every corner as a node: the router's own corners (a route drawn without clicks,
        corners the router added) are listed next to the user's nodes, so each gets a handle; the first edit of such
        a corner writes them all to design.json (:func:`design_io.materialize_nodes`)."""
        data = self.data or {}
        cache = getattr(self, "_routes_cache", None)
        if cache is not None and cache[0] is data:
            return cache[1]
        out = {name: design_io.editable_route(r) for name, r in self.all_routes().items()}
        self._routes_cache = (data, out)
        return out

    def route(self, rname) -> dict:
        return self.routes().get(rname, {})

    def radii(self, route: dict) -> list:
        """Bend radius of each polyline point (the route's, or a waypoint's own)."""
        pts = route.get("polyline") or []
        out = [float(route.get("r") or 0.0)] * len(pts)
        for i, rr in enumerate(route.get("waypoint_r") or []):
            idx = (route.get("waypoint_index") or [])
            if rr is not None and i < len(idx):
                out[idx[i]] = float(rr)
        return out

    def corner(self, rname, i):
        """(prev, pos, next, radius, polyline index) of node ``i`` of ``rname``, or None."""
        route = self.route(rname)
        idx = route.get("waypoint_index") or []
        pts = [tuple(q) for q in route.get("polyline") or []]
        if i >= len(idx) or not 0 < idx[i] < len(pts) - 1:
            return None
        k = idx[i]
        return pts[k - 1], pts[k], pts[k + 1], self.radii(route)[k], k

    def radius_handle(self):
        if not self.selected:
            return None
        c = self.corner(*self.selected)
        return None if c is None else geometry.radius_handle(c[0], c[1], c[2], c[3])

    def handles(self):
        out = []  # (route, kind, index, pos)
        for rname, route in self.routes().items():
            wps, inserts = geometry.handle_points(route)
            out += [(rname, "move", i, p) for i, p in wps]
            out += [(rname, "insert", k, p) for k, p in inserts]
        h = self.radius_handle()
        if h is not None:
            out.append((self.selected[0], "radius", self.selected[1], h))
        return out

    def handle_near(self, p):
        best, hit = self.capture(), None
        for h in self.handles():
            d = geometry.dist(p, h[3])
            if d <= best:
                best, hit = d, h
        return hit

    def neighbours(self, route: dict, kind: str, index: int):
        pts = [tuple(q) for q in route["polyline"]]
        if kind == "move":
            k = route["waypoint_index"][index]
            return [pts[k - 1] if k > 0 else None, pts[k + 1] if k + 1 < len(pts) else None]
        return [pts[index - 1], pts[index]]

    def drag_point(self, p):
        rname, kind, i = self.drag
        route = self.route(rname)
        return geometry.constrain(p, SESSION.grid, self.neighbours(route, kind, i), self.shift and not self.free,
                                  self.port_rays(route), self.capture())

    @staticmethod
    def port_rays(route: dict) -> list:
        """Axes of the end stubs that face an angle (a StarQubit pin, a ConcentricTransmon coupler): Shift offers them
        next to 0° / 45° / 90°. Failed routes have no stubs."""
        pts = [tuple(q) for q in route.get("polyline") or []]
        fixed = set(route.get("fixed_segments") or [])
        rays = []
        if len(pts) > 2 and 1 in fixed:
            rays.append((pts[1], geometry.sub(pts[1], pts[0])))
        if len(pts) > 2 and len(pts) - 1 in fixed:
            rays.append((pts[-2], geometry.sub(pts[-2], pts[-1])))
        return [(o, d) for o, d in rays if not geometry.is_axis(geometry.unit(d)) and geometry.unit(d) is not None]

    def drag_radius(self, p) -> float | None:
        c = self.corner(self.drag[0], self.drag[2])
        if c is None:
            return None
        rad = geometry.radius_from_handle(c[0], c[1], c[2], p)
        if rad is None:
            return None
        g = SESSION.grid
        return max(g, round(rad / g) * g) if g > 0 else rad

    def preview(self, route: dict, kind: str, index: int, pos):
        """(points, radii) of ``route`` with the dragged handle at ``pos`` (a radius for kind "radius")."""
        pts = [tuple(q) for q in route["polyline"]]
        radii = self.radii(route)
        if kind == "move":
            pts[route["waypoint_index"][index]] = pos
        elif kind == "radius":
            radii[route["waypoint_index"][index]] = pos
        else:
            pts.insert(index, pos)
            radii.insert(index, float(route.get("r") or 0.0))
        return pts, radii

    def redraw(self):
        o = self.overlay
        o.clear()
        self.draw_drc()
        routes = self.routes()
        if self.selected and (self.selected[0] not in routes
                              or self.selected[1] >= len(routes[self.selected[0]].get("waypoints", []))):
            self.selected = None
        if SESSION.last_error:
            box = self.data.get("chip_box", [0, 0, 0, 0])
            o.text((box[0] + 50, box[3] + 50),
                   (SESSION.last_error if SESSION.failed_routes else f"build failed: {SESSION.last_error}")[:160], RED)
        for rname, route in routes.items():
            pts = [tuple(q) for q in route["polyline"]]
            if route.get("failed"):  # the last good path and the label are the red overlay's (draw_failed)
                o.path(pts, color=RED, style=2, width=2)
                continue
            o.path(pts, color=GREY, style=2)
            mid = pts[len(pts) // 2]
            length = route.get("length")
            tag = f"{rname} · {route['type']}" + (f" · {length:.1f} µm" if length else "")
            o.text(mid, tag, GREY)
        for rname, kind, index, p in self.handles():
            if kind == "radius":
                c = self.corner(rname, index)
                o.path([c[1], p], color=GREEN, style=2)
                o.box(p, 5, GREEN, filled=False, width=2)
                o.text(p, f"r {c[3]:g}", GREEN)
            elif (rname, index) == self.selected and kind == "move":
                o.box(p, 7, GREEN, filled=True)
            else:
                o.box(p, 5, BLUE, filled=kind == "move")
        if self.drag:
            rname, kind, i = self.drag
            route = routes[rname]
            if kind == "radius":
                value = self.drag_radius(self.mouse)
                if value is None:
                    return
                pts, radii = self.preview(route, kind, i, value)
                c = self.corner(rname, i)
                h = geometry.radius_handle(c[0], c[1], c[2], value)
                if h is not None:
                    o.box(h, 6, RED, filled=False, width=2)
                o.text(self.mouse, f"{rname}[{i}] corner r = {value:g} µm (click to set)", RED)
            else:
                pos = self.drag_point(self.mouse)
                pts, radii = self.preview(route, kind, i, pos)
                self.cursor(pos)
                o.text(self.mouse, f"({pos[0]:g}, {pos[1]:g})" + (
                    "  [Ctrl: any angle]" if self.free else "  [Shift: aligned]" if self.shift else ""), RED)
            o.path(geometry.rounded_points(pts, radii), width_um=route["a"] + 2 * route["b"], color=RED)
            tight = geometry.tight_segments(pts, radii)
            if tight:
                k = tight[0]
                o.text(geometry.mul(geometry.add(pts[k - 1], pts[k]), 0.5),
                       f"segment {k} too short for its bends", RED)

    def mouse_click_event(self, p, buttons, prio):
        """Click a handle to pick it up, move, click again to drop it there. Right-click a node deletes it;
        right-click while moving cancels."""
        if not (prio and self.active):
            return False
        self.shift = bool(buttons & SHIFT)
        self.free = bool(buttons & CTRL)
        try:
            if self.drag and buttons & RIGHT:
                self.reset()
                self.redraw()
                return True
            if self.drag and buttons & LEFT:
                self.drop(_xy(p))
                return True
            h = self.handle_near(_xy(p))
            if h is None:
                if buttons & LEFT and self.selected:
                    self.selected = None
                    self.redraw()
                return False
            rname, kind, i, _ = h
            if buttons & RIGHT and kind == "move":
                delete_node(rname, i)
                return True
            if buttons & LEFT:
                if kind == "move":
                    self.selected = (rname, i)
                self.drag = (rname, kind, i)
                what = {"move": "move the node", "insert": "place the new node", "radius": "set the corner radius"}
                message(f"{rname}: {what[kind]}, click to drop it (Shift: 0/45/90° or the port's angle, Ctrl: any "
                        "angle; right-click cancels)", 4)
                self.redraw()
                return True
        except Exception:  # noqa: BLE001
            self.reset()
            report_error("editing the route")
        return False

    def mouse_moved_event(self, p, buttons, prio):
        super().mouse_moved_event(p, buttons, prio)
        if prio and self.active and self.drag:
            self.redraw()
            return True
        return False

    def drop(self, here):
        rname, kind, i = self.drag
        design = SESSION.design()
        route = self.route(rname)
        if kind == "radius":
            value = self.drag_radius(here)
            self.drag = None
            if value is None:
                return
            same = abs(value - float(route.get("r") or 0.0)) < 1e-9
            design_io.materialize_nodes(design, rname, route)
            design_io.set_node(design, rname, i, r=None if same else value)
            SESSION.commit(design, f"{rname}: corner {i} radius {value:g} µm")
            self.redraw()
            return
        pos = self.drag_point(here)
        self.drag = None
        if kind == "move":
            old = tuple(route["waypoints"][i])
            if geometry.dist(old, pos) < 1e-6:  # a click without a move: only selects
                self.redraw()
                return
            design_io.materialize_nodes(design, rname, route)
            design_io.set_node(design, rname, i, at=pos)
        else:
            # the router's own corners become nodes first, so the route keeps the shape the preview showed
            design_io.materialize_nodes(design, rname, route)
            index = geometry.waypoint_insert_index(route.get("waypoint_index", []), i)
            design_io.insert_route_node(design, rname, index, pos)
            self.selected = (rname, index)
        SESSION.commit(design, f"{rname}: node at ({pos[0]:g}, {pos[1]:g})")
        self.redraw()

    def mouse_double_click_event(self, p, buttons, prio):
        """Double-click a node: its properties (x, y, corner radius, airbridge); elsewhere on a route: the route's
        options (type, length, radius, meander segment)."""
        if not (prio and self.active):
            return False
        self.reset()
        here = _xy(p)
        try:
            h = self.handle_near(here)
            if h is not None and h[1] in ("move", "radius"):
                self.selected = (h[0], h[2])
                node_properties()
                return True
            best, hit, seg = self.capture(), None, None
            for rname, route in self.routes().items():
                d, k = geometry.dist_point_polyline(here, [tuple(q) for q in route["polyline"]])
                if d <= best:
                    best, hit, seg = d, rname, k
            if hit is None:
                return False
            edit_route_options(hit, seg)
        except Exception:  # noqa: BLE001
            report_error("editing the route")
        return True

    def key_event(self, key, buttons):
        if not self.active:
            return False
        if key in (pya.KeyCode.Delete, pya.KeyCode.Backspace):
            h = self.handle_near(self.mouse)
            if h and h[1] == "move":
                delete_node(h[0], h[2])
                return True
            if h is None:  # a failed route has no cell to select and delete: Delete on its line removes it
                near = geometry.route_near({n: r for n, r in self.routes().items() if r.get("failed")}, self.mouse,
                                           self.capture())
                if near is not None:
                    delete_route(near[0])
                    return True
        if key == pya.KeyCode.Escape and self.drag:
            self.reset()
            self.redraw()
            return True
        return False


def _route_tool():
    tool = ACTIVE[0] if ACTIVE else None
    return tool if isinstance(tool, RouteEditTool) and tool.active else None


def delete_node(rname: str, index: int) -> None:
    """Delete node ``index`` of ``rname`` as Route handles shows it (the router's own corners count as nodes: they
    are written to design.json first, then the one is removed)."""
    tool = _route_tool()
    design = SESSION.design()
    built = tool.route(rname) if tool is not None else design_io.editable_route(
        (SESSION.data or {}).get("routes", {}).get(rname, {}))
    if tool is not None:
        tool.selected = None
        tool.reset()
    design_io.materialize_nodes(design, rname, built)
    nodes = design.get("routes", {}).get(rname, {}).get("nodes") or []
    if not 0 <= index < len(nodes):
        message(f"{rname}: node {index} is gone (the route changed); click the node again", 6)
        if tool is not None:
            tool.redraw()
        return
    design = design_io.delete_route_node(design, rname, index)
    SESSION.commit(design, f"{rname}: removed node {index}")


def delete_route(rname: str) -> None:
    """Delete route ``rname`` (and the routes hanging on it) from design.json: a failed route has no cell, so KLayout's
    own Delete cannot reach it."""
    design = SESSION.design()
    gone = design_io.delete_route(design, rname)
    if not gone:
        message(f"{rname} is not a route of this design", 6)
        return
    tool = _route_tool()
    if tool is not None:
        tool.selected = None
        tool.reset()
    SESSION.commit(design, f"deleted route {', '.join(gone)}")


def delete_selected_node() -> None:
    """Quantcore menu: delete the node selected in *Route handles*."""
    tool = _route_tool()
    if tool is None or not tool.selected:
        message("Route handles: click a node first, then Delete node", 4)
        return
    delete_node(*tool.selected)


def node_properties() -> None:
    """Quantcore menu: x, y, corner radius and airbridge of the node selected in *Route handles*."""
    tool = _route_tool()
    if tool is None or not tool.selected:
        message("Route handles: click a node first, then Node properties", 4)
        return
    rname, i = tool.selected
    design = SESSION.design()
    design_io.materialize_nodes(design, rname, tool.route(rname))
    nodes = design["routes"].get(rname, {}).get("nodes") or []
    if not 0 <= i < len(nodes):
        tool.selected = None
        message(f"{rname}: node {i} is gone (the route changed); click the node again", 6)
        return
    node = nodes[i]
    route_r = float(tool.route(rname).get("r") or 0.0)
    out = node_dialog(rname, i, design_io.node_props(node), route_r)
    if out is None:
        return
    design_io.set_node(design, rname, i, **out)
    SESSION.commit(design, f"{rname}: node {i} at ({out['at'][0]:g}, {out['at'][1]:g})"
                           + (f", corner r {out['r']:g}" if out["r"] is not None else "")
                           + (f", taper a {out['a']:g}" if out.get("a") is not None else "")
                           + (f", taper b {out['b']:g}" if out.get("b") is not None else ""))


def edit_route_options(rname: str, segment: int | None = None) -> None:
    """The route dialog for an existing route (type, length, radius, meander segment)."""
    design = SESSION.design()
    r = design["routes"][rname]
    seg = r.get("meander_segment")
    failed = (SESSION.data.get("failed_routes") or {}).get(rname)
    built = SESSION.data.get("routes", {}).get(rname) or failed or {}
    pts = [tuple(q) for q in built.get("polyline") or []]
    fixed = set(built.get("fixed_segments") or [])
    segments = [(k, geometry.dist(pts[k - 1], pts[k]), k == segment) for k in range(1, len(pts)) if k not in fixed]
    current = design.get("targets", {}).get(rname, {})
    join = None
    tee = joins.tee_of(design, rname)
    if isinstance(r.get("to"), dict) and r["to"].get("hanger"):
        join = (r["to"]["hanger"], False)
    elif tee is not None:
        try:
            join = (joins._halves(design, tee)[0], True)  # noqa: SLF001
        except ValueError:
            join = None
    opts = route_dialog(rname, r.get("type", "cpw"), r.get("length"), r.get("r"), f"qcc route {rname}",
                        segment=seg, segments=segments if r.get("type") == "meander" and not failed else None,
                        targets=current,  # always offered: a resonator can be a plain cpw route
                        a=r.get("a"), b=r.get("b"), join=join,
                        hanger=r["to"] if isinstance(r.get("to"), dict) and r["to"].get("hanger") else None,
                        meander={"meanders": r.get("meanders", -1), "meander_direction": r.get("meander_direction", 1)},
                        lom_of=rname, error=failed.get("error") if failed else None,
                        last_good=(failed or {}).get("last_good"))
    if opts is None:
        return
    if opts.get("delete"):
        delete_route(rname)
        return
    if opts.get("hanger") and isinstance(r.get("to"), dict) and not opts.get("merge"):
        end = r["to"]
        for k, v in opts["hanger"].items():
            default = {"direction": "forward", "open_gap": 6.0}.get(k)
            if v is None:
                end.pop(k, None)  # coupler_gap / line_gap emptied: the CPW's own gap
            elif v == default and k not in end:
                continue  # the schema's default: not written
            else:
                end[k] = v
    joined = ""
    if join is not None and opts.get("merge") is not None and opts["merge"] != join[1]:
        def polyline_of(name):
            return SESSION.data.get("routes", {}).get(name, {}).get("polyline") or []
        try:
            if opts["merge"]:
                host = SESSION.data.get("routes", {}).get(join[0], {})
                r_host = float(host.get("r") or SESSION.data.get("pdk", {}).get("turn_radius") or 100.0)
                joined = f", merged into {join[0]} with {joins.hanger_to_merge(design, rname, polyline_of, r_host)}"
            else:
                joined = f", hangs from {joins.merge_to_hanger(design, rname, polyline_of)} (T removed)"
        except ValueError as e:
            message(f"route {rname}: {e}", 8)
            return
    design_io.set_route_options(design, rname, type=opts["kind"], length=opts["length"], r=opts["r"],
                                a=opts.get("a"), b=opts.get("b"))
    if "targets" in opts:
        design_io.set_targets(design, rname, opts["targets"])
    if opts["kind"] == "meander":
        design_io.set_meander_segment(design, rname, opts.get("segment"))
        if "meanders" in opts:  # the schema defaults (-1 automatic, +1) are not written
            design_io.set_route_options(design, rname, meanders=None if opts["meanders"] < 0 else opts["meanders"],
                                        meander_direction=None if opts["meander_direction"] == 1 else -1)
    name = opts["name"]
    if name and name != rname:
        try:
            design_ops.rename_route(design, rname, name)  # hanger ends, targets, couplings and sim groups follow
        except ValueError as e:
            message(f"route {rname}: {e}", 8)
            name = rname
    SESSION.commit(design, f"route {name}: {opts['kind']}" + (f", {opts['length']:g} µm" if opts["length"] else "")
                   + joined)


def meander_here() -> None:
    """Quantcore menu: put the meander of the route under the cursor on the segment under the cursor (Route
    handles)."""
    tool = _route_tool()
    if tool is None:
        message("switch to Route handles, point at a straight of a meander route, then Meander here", 4)
        return
    best, hit = tool.capture() * 2, None
    for rname, route in tool.data.get("routes", {}).items():
        d, k = geometry.dist_point_polyline(tool.mouse, [tuple(q) for q in route["polyline"]])
        if d <= best:
            best, hit = d, (rname, k)
    if hit is None:
        message("Meander here: point at a segment of a meander route first", 4)
        return
    rname, seg = hit
    route = tool.route(rname)
    if route.get("type") != "meander":
        message(f"{rname} is not a meander (double-click it to change its type)", 4)
        return
    if seg in set(route.get("fixed_segments", [])):
        message(f"{rname}: segment {seg} is a port stub or coupler; pick a free straight", 4)
        return
    design = design_io.set_meander_segment(SESSION.design(), rname, seg)
    SESSION.commit(design, f"{rname}: meander on segment {seg}")


# ---- Move / snap / place -----------------------------------------------------------------------------------------
PENDING_PLACE: dict = {}  # {"cell", "params", "rot", "ghost"} set by arm_place (panel double-click / Place component…)
_GHOSTS: dict = {}  # (cell, params JSON) → outline from `qcc components CELL --outline`


def snap_text(hit, rot: float) -> str:
    """The label of a port snap while dragging: which ports, and the turn the snap added."""
    extra = hit[3]
    return f"snap {hit[0]} -> {hit[1]}" + (f", turn {extra:+.1f}° (rot {rot % 360.0:.1f}°)" if extra else "")


def ghost(cell: str, params: dict) -> dict | None:
    """The component's outline, bbox and ports in its own frame (cached; one `qcc` call, ~1.5 s, per cell+params)."""
    import json  # pylint: disable=import-outside-toplevel
    import subprocess  # pylint: disable=import-outside-toplevel

    from qcc_kplugin import qcache  # pylint: disable=import-outside-toplevel
    from qcc_kplugin.session import clean_env  # pylint: disable=import-outside-toplevel

    key = (cell, json.dumps(params, sort_keys=True))
    if key not in _GHOSTS:
        cached = qcache.get(qcache.outline_key(*key))
        if cached is not None:
            _GHOSTS[key] = cached
    if key not in _GHOSTS:
        proc = subprocess.run(  # noqa: S603
            [SESSION.qcc, "components", cell, "--outline", "--params", key[1]],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=clean_env(),
            creationflags=0x08000000,
        )
        try:
            _GHOSTS[key] = qcache.loads_tolerant(proc.stdout) if proc.returncode == 0 else None
        except ValueError:
            _GHOSTS[key] = None
        if _GHOSTS[key] is None:
            log(f"no outline for {cell} {key[1]}: {(proc.stderr or proc.stdout)[-400:]}")
        else:
            qcache.put(qcache.outline_key(*key), _GHOSTS[key])
    return _GHOSTS[key]


def ghost_cached(cell: str, params: dict) -> bool:
    import json  # pylint: disable=import-outside-toplevel

    from qcc_kplugin import qcache  # pylint: disable=import-outside-toplevel

    key = (cell, json.dumps(params, sort_keys=True))
    return _GHOSTS.get(key) is not None or qcache.get(qcache.outline_key(*key)) is not None


def ghost_async(cell: str, params: dict, done=None) -> None:
    """Load the outline in the background (``done(outline or None)`` afterwards; at once when it is cached)."""
    import json  # pylint: disable=import-outside-toplevel

    from qcc_kplugin import qcache  # pylint: disable=import-outside-toplevel

    pj = json.dumps(params, sort_keys=True)

    def got(data):
        if data is not None:
            _GHOSTS[(cell, pj)] = data
        if done is not None:
            done(data)

    qcache.fetch(qcache.outline_key(cell, pj), ["components", cell, "--outline", "--params", pj], got)


ROTATE_HINT = "[ ] rotate 90°"
ACTIVE: list = []  # the qcc tool currently active in the view (for menu actions that must redraw it)


def rotate(step: float) -> None:
    """Rotate the component being placed (or the instance being dragged) by ``step`` degrees: the Quantcore menu's
    [ / ] actions, so the keys work wherever the keyboard focus is (e.g. still in the panel after a double-click)."""
    tool = ACTIVE[0] if ACTIVE else None
    if PENDING_PLACE:
        PENDING_PLACE["rot"] = (PENDING_PLACE.get("rot", 0.0) + step) % 360.0
        message(f"{PENDING_PLACE['cell']}: {PENDING_PLACE['rot']:g}°", 2)
    elif tool is not None and getattr(tool, "drag", None):
        tool.drag["rot"] = (tool.drag["rot"] + step) % 360.0
        message(f"{tool.drag['inst']}: {tool.drag['rot']:g}° (applied on release)", 2)
    else:
        message("nothing to rotate: double-click a component in the panel first", 3)
        return
    if tool is not None and tool.active:
        tool.redraw()
ROTATE_KEYS = {ord("["): 90.0, ord("]"): -90.0}  # KLayout keeps R for its ruler
_SCHEMAS: dict = {}


def schema(cell: str) -> list[dict]:
    """The cell's editable parameters and defaults (`qcc components CELL --schema`, cached)."""
    import subprocess  # pylint: disable=import-outside-toplevel

    from qcc_kplugin import qcache  # pylint: disable=import-outside-toplevel
    from qcc_kplugin.session import clean_env  # pylint: disable=import-outside-toplevel

    if cell not in _SCHEMAS and qcache.get(qcache.schema_key(cell)):
        _SCHEMAS[cell] = qcache.get(qcache.schema_key(cell))
    if cell not in _SCHEMAS:
        proc = subprocess.run(  # noqa: S603
            [SESSION.qcc, "components", cell, "--schema"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=clean_env(),
            creationflags=0x08000000,
        )
        try:
            _SCHEMAS[cell] = qcache.loads_tolerant(proc.stdout) if proc.returncode == 0 else []
        except ValueError:
            _SCHEMAS[cell] = []
        if not _SCHEMAS[cell]:
            log(f"no parameters for {cell}: {(proc.stderr or proc.stdout)[-400:]}")
        else:
            qcache.put(qcache.schema_key(cell), _SCHEMAS[cell])
    return _SCHEMAS[cell]


def schema_async(cell: str, done) -> None:
    """``done(rows)`` with the cell's parameters, loaded in the background (at once when cached)."""
    from qcc_kplugin import qcache  # pylint: disable=import-outside-toplevel

    def got(data):
        if data:
            _SCHEMAS[cell] = data
        done(data or [])

    qcache.fetch(qcache.schema_key(cell), ["components", cell, "--schema"], got)


def fill_table(table, rows: list[dict], values: dict, cell: str | None = None) -> None:
    """Two-column parameter table (name, value); ``values`` override the defaults; hover shows the description (and,
    with ``cell``, the PDK junction an unset KQC ``junction_type`` default is drawn as)."""
    import json  # pylint: disable=import-outside-toplevel

    table.setRowCount(len(rows))
    for i, p in enumerate(rows):
        v = values.get(p["name"], p["default"])
        name = pya.QTableWidgetItem(p["name"] + (f" ({p['unit']})" if p.get("unit") else ""))
        name.flags = pya.Qt.ItemIsEnabled
        value = pya.QTableWidgetItem(v if isinstance(v, str) else json.dumps(v))
        choices = ", ".join(map(str, p.get("choices") or []))
        tip = p.get("description", "") + (f"\nchoices: {choices}" if choices else "")
        if p["name"] == "junction_type" and p["name"] not in values and cell and CATEGORY.get(cell) != "junction":
            from qcc_kplugin import jfetch  # pylint: disable=import-outside-toplevel

            drawn = jfetch.PDK_JUNCTION.get(str(v))
            if drawn:  # the build draws an unset KQC / Metal default as the PDK trilayer junction
                tip += f"\nleft unset, {v} is drawn as {drawn} (the PDK junction); set it to draw {v} itself"
        name.toolTip = tip
        value.toolTip = tip
        table.setItem(i, 0, name)
        table.setItem(i, 1, value)
    table.resizeColumnsToContents()


def table_values(table, rows: list[dict]) -> dict:
    out = {}
    for i, p in enumerate(rows):
        item = table.item(i, 1)
        if item is not None:
            out[p["name"]] = design_io.parse_value(item.text, p["default"], p["name"])
    return out


def size_note(cell: str, g: dict | None) -> str:
    """"" when the outline fits on the chip, else a status-bar sentence: a wafer-level or frame cell (WaferMap75,
    BoundaryBox, AlignmentMarkers) is not a component to drop on a chip, and the user should know before it builds."""
    box = (SESSION.data or {}).get("chip_box")
    if not g or not g.get("bbox") or not box:
        return ""
    w, h = g["bbox"][2] - g["bbox"][0], g["bbox"][3] - g["bbox"][1]
    cw, ch = box[2] - box[0], box[3] - box[1]
    if w <= cw and h <= ch:
        return ""
    return (f"{cell} is {w:g} x {h:g} um, larger than the chip ({cw:g} x {ch:g} um): a wafer-level / frame cell, "
            "not a component. It is placed as asked; undo if that was a mistake")


def may_have_junction(cell: str, params: dict | None = None) -> bool:
    """Whether a placed ``cell`` can carry a junction (a qubit, or a cell with a ``junction_type`` parameter): then the
    placement asks the library for its simulation value (:func:`fix_placed_junction`)."""
    try:
        return CATEGORY.get(cell) == "qubit" or "junction_type" in (params or {}) or any(
            p["name"] == "junction_type" for p in schema(cell))
    except Exception:  # noqa: BLE001
        return False


def fix_placed_junction(design: dict, name: str) -> str | None:
    """Placing a qubit fixes its junction at design time: ``junction = {Lj_nH, Cj_fF}`` goes into design.json (a drawn
    trilayer junction's PDK value, else the PDK nominal SQUID, both from the library), unless the instance already has
    one (a duplicate keeps its source's). Returns the status-bar note, or None."""
    from qcc_kplugin import jfetch  # pylint: disable=import-outside-toplevel

    entry = design["instances"][name]
    if entry.get("junction") is not None or not may_have_junction(entry["cell"], entry.get("params")):
        return None
    try:
        values = jfetch.placement_junction(entry["cell"], entry.get("params") or {})
    except Exception:  # noqa: BLE001  (placing never fails over a value)
        report_error(f"junction value of {name}")
        return None
    return design_ops.fix_junction_at_placement(design, name, values)


def arm_place(cell: str, params: dict, rot: float = 0.0, mirror: bool = False, extra: dict | None = None) -> None:
    """Next click in *Move/Snap* drops ``cell``; its outline follows the mouse; [ and ] rotate it by 90°.
    ``rot``/``mirror``/``extra`` (entry keys such as ``junction``) come from a duplicated component."""
    PENDING_PLACE.clear()
    if not SESSION.ensure_design():
        pya.MessageBox.info("Quantcore", "Open or create a design first: Quantcore > New design... or Open design...",
                            pya.MessageBox.Ok)
        return
    PENDING_PLACE.update({"cell": cell, "params": params, "rot": rot, "mirror": mirror, "extra": extra or {},
                          "ghost": ghost(cell, params)})
    if not (extra or {}).get("junction") and may_have_junction(cell, params):  # ready by the time of the click
        from qcc_kplugin import jfetch  # pylint: disable=import-outside-toplevel

        jfetch.prefetch(cell, params)
    pya.MainWindow.instance().menu().action("@toolbar.qcc_snap").trigger()
    try:  # keys ([ ], Esc) go to the layout, not to the panel list that was double-clicked
        view = pya.LayoutView.current()
        if view is not None:
            view.widget().setFocus()
    except Exception:  # noqa: BLE001
        pass
    note = size_note(cell, PENDING_PLACE["ghost"])
    message(f"click in the layout to place {cell}; {ROTATE_HINT}, right-click cancels" + (f". NOTE: {note}" if note else ""),
            10 if note else 6)


class TargetsEditor:
    """The optional "Targets" rows of an edit dialog: one line edit per key (empty = no target). The values go to
    ``design.json`` ``targets[element]`` (see :func:`design_io.set_targets`)."""

    def __init__(self, dialog, layout, keys: dict, current: dict):
        self.edits = {}
        layout.addWidget(pya.QLabel("Targets (optional, compared with the LOM values; empty = none)", dialog))
        form = pya.QFormLayout()
        for key, desc in keys.items():
            e = pya.QLineEdit("" if key not in current else f"{current[key]:g}", dialog)
            e.toolTip = desc
            e.objectName = f"qcc_target_{key}"
            form.addRow(key, e)
            self.edits[key] = e
        layout.addLayout(form)

    def values(self) -> dict:
        return design_io.parse_targets({k: e.text for k, e in self.edits.items()})


def lom_section(dialog, layout, element: str) -> None:
    """Read-only rows: the element's circuit as the last build's LOM sees it (C to ground and couplings, L_J / C_J,
    the resonator line, the hanger κ); Run LOM uses these, a simulation replaces the C values."""
    rows = design_io.lom_rows(SESSION.data or {}, element)
    if not rows:
        return
    layout.addWidget(pya.QLabel("Circuit (LOM estimate from the last build; Run LOM / Simulate refine it)", dialog))
    form = pya.QFormLayout()
    for bname, kind, text in rows:
        label = pya.QLabel(text, dialog)
        label.toolTip = f"{bname}: {kind}"
        form.addRow(f"{bname} ({kind})", label)
    layout.addLayout(form)


JUNCTION_TITLE = "Junction (simulation and LOM only, not drawn, not in the fab mask)"


def squid_l_eff(lj0_nh: float, flux_phi0: float = 0.0, asym: float = 0.0) -> float:
    """L of a DC SQUID at flux Φ/Φ0 with asymmetry d: L_J0 / √(cos² πΦ + d² sin² πΦ) (the library's
    ``lom.fragment.squid_l_eff``; raises at Φ = ½ with d = 0)."""
    import math  # pylint: disable=import-outside-toplevel

    x = math.pi * float(flux_phi0)
    den = math.cos(x) ** 2 + float(asym) ** 2 * math.sin(x) ** 2
    if den < 1e-24:
        raise ValueError(f"a symmetric SQUID (d = {asym:g}) at Φ = {flux_phi0:g} Φ0 has no finite L_J: move the "
                         "flux off ½ or set the asymmetry d")
    return float(lj0_nh) / math.sqrt(den)


def junction_info(name: str) -> dict | None:
    """The build sidecar's ``instances.<name>.junction`` (kind, Lj0_nH, Cj_fF, flux_phi0, asym, Lj_eff_nH, source,
    maybe error), None for a component without a junction or before the first build."""
    return (((SESSION.data or {}).get("instances") or {}).get(name) or {}).get("junction")


def drawn_junction_value(entry: dict, info: dict | None) -> dict | None:
    """What the cell's drawn trilayer junction gives (``{"Lj_nH", "Cj_fF", "source"}``, PDK rule), or None. The sidecar
    has it when the design holds no value of its own (``source`` "drawn ..."); with a design value, and a cell whose
    ``junction_type`` is a trilayer junction, the library is asked (``qcc design placement-junction``)."""
    from qcc_kplugin import jfetch  # pylint: disable=import-outside-toplevel

    if info and str(info.get("source") or "").startswith("drawn") and info.get("Lj0_nH") is not None:
        return {"Lj_nH": float(info["Lj0_nH"]), "Cj_fF": float(info.get("Cj_fF") or 0.0),
                "source": str(info["source"])}
    jt = (entry.get("params") or {}).get("junction_type")
    if jt is None:  # unset: the cell's default, a KQC one drawn as the PDK trilayer junction
        jt = jfetch.drawn_type(None, next((p.get("default") for p in schema(entry["cell"])
                                           if p["name"] == "junction_type"), None),
                               CATEGORY.get(entry["cell"]) == "junction")
    if jt is None or not jfetch.is_trilayer_type(jt):
        return None
    found = jfetch.placement_junction(entry["cell"], entry.get("params") or {})
    return (found or {}).get("drawn")


class JunctionRows:
    """The junction section of the component dialog: L_J, I_c, R_n and C_J (L_J = Φ0/2πI_c, I_c·R_n = πΔ/2e with the
    PDK's Δ: typing any one fills the other two), for a SQUID the flux Φ/Φ0 and the asymmetry d, then read-only: the
    L at this bias (L_J0 / √(cos² πΦ + d² sin² πΦ), live), where the value comes from, and the junction the cell draws
    (PDK rule). These are simulation and LOM values, fixed per component: the drawn junction is for fab only.

    ``junction``: design.json's ``junction``. ``info``: the sidecar's entry (kind, source, ``error``). ``drawn``: the
    drawn trilayer junction's values. With no design value but a drawn junction, its values are the fields'
    placeholders ("PDK, drawn junction") and nothing is written unless the user types."""

    def __init__(self, dialog, form, junction: dict | None, info: dict | None = None, drawn: dict | None = None):
        junction = junction if isinstance(junction, dict) else {}
        info = info or {}
        self.gap = float(((SESSION.data or {}).get("pdk") or {}).get("junction_gap_meV") or 1.4)
        lj, cj = junction.get("Lj_nH"), junction.get("Cj_fF")
        self.multi = isinstance(lj, list) or isinstance(cj, list)
        self.squid = info.get("kind") == "SQUID" or "flux_phi0" in junction or "asym" in junction
        self.drawn = drawn
        self._edited = False
        self.pdk = None  # (L_J0, C_J or None) a drawn junction gives, used while the design has no L_J of its own
        if not self.multi and lj is None:
            src = drawn or (info if str(info.get("source") or "").startswith("drawn") else None)
            lj0 = None if src is None else src.get("Lj_nH", src.get("Lj0_nH"))
            if lj0 is not None:
                self.pdk = (float(lj0), None if cj is not None else float(src.get("Cj_fF") or 0.0))
        self.l_title = pya.QLabel(JUNCTION_TITLE, dialog)
        form.addRow(self.l_title)
        trip = design_io.junction_triplet(self.gap, lj_nh=None if self.multi else lj)
        self.e = {k: pya.QLineEdit("" if trip[k] is None else format(trip[k], ".5g"), dialog)
                  for k in ("Lj_nH", "Ic_nA", "Rn_kohm")}
        if not self.multi and lj is not None:
            self.e["Lj_nH"].text = _num(lj)  # the stored value exactly (OK without an edit changes nothing)
        self.e_cj = pya.QLineEdit("" if cj is None or self.multi else _num(cj), dialog)
        self.e_flux = pya.QLineEdit("" if not junction.get("flux_phi0") else _num(junction["flux_phi0"]), dialog)
        self.e_asym = pya.QLineEdit("" if not junction.get("asym") else _num(junction["asym"]), dialog)
        labels = {"Lj_nH": "Junction L_J nH" + (" (L_J0, zero flux)" if self.squid else ""),
                  "Ic_nA": "Junction I_c nA", "Rn_kohm": "Junction R_n kΩ"}
        for k, e in self.e.items():
            e.toolTip = (f"L_J = Φ0/2πI_c, I_c·R_n = πΔ/2e (Δ {self.gap:g} meV, the PDK's); type one, the others "
                         "follow. A SQUID: L_J0, its value at zero flux. Empty = none")
            e.enabled = not self.multi
            form.addRow(labels[k], e)
            try:
                e.textEdited(lambda text, key=k: self._follow(key, text))
            except Exception:  # noqa: BLE001
                pass
        self.e_cj.enabled = not self.multi
        self.e_cj.toolTip = "Junction capacitance in fF (a simulation value). Empty = none"
        form.addRow("Junction C_J fF", self.e_cj)
        self._placeholders()
        if self.squid:
            self.e_flux.toolTip = "Flux through the SQUID loop in Φ0 (0 = the sweet spot). Empty = 0"
            self.e_asym.toolTip = "SQUID asymmetry d = (I1 - I2)/(I1 + I2). Empty = 0 (symmetric)"
            for e in (self.e_flux, self.e_asym):
                e.enabled = not self.multi
            form.addRow("SQUID flux Φ/Φ0", self.e_flux)
            form.addRow("SQUID asymmetry d", self.e_asym)
            for e in (self.e_flux, self.e_asym):
                try:
                    e.textEdited(lambda _t: self._edit())
                except Exception:  # noqa: BLE001
                    pass
        self.l_eff = pya.QLabel("", dialog)
        self.l_src = pya.QLabel("", dialog)
        self.l_err = pya.QLabel(str(info.get("error") or ""), dialog)
        self.l_err.wordWrap = True
        try:
            self.l_err.setStyleSheet("color: #c0392b")
        except Exception:  # noqa: BLE001
            pass
        self.l_eff.toolTip = "Read-only: L_J at this flux (the value the LOM and the eigenmode / driven runs use)"
        form.addRow("L at this bias nH" if self.squid else "L used nH", self.l_eff)
        form.addRow("Source", self.l_src)
        form.addRow("", self.l_err)
        self.l_drawn = None
        if drawn is not None:
            self.l_drawn = pya.QLabel(
                f"L_J {drawn['Lj_nH']:.5g} nH, C_J {float(drawn.get('Cj_fF') or 0):.4g} fF  "
                f"({drawn.get('source', 'PDK rule')}); for fab only, not a simulation value", dialog)
            self.l_drawn.wordWrap = True
            form.addRow("Drawn junction (PDK)", self.l_drawn)
        if self.multi:
            form.addRow("", pya.QLabel("several junctions (lists): edit them in design.json", dialog))
        self.refresh()

    # ---- placeholders (the drawn junction's PDK value) --------------------------------------------------------
    def _placeholders(self):
        if self.pdk is None:
            return
        trip = design_io.junction_triplet(self.gap, lj_nh=self.pdk[0])
        for k, e in self.e.items():
            self._hint(e, format(trip[k], ".5g"))
        if self.pdk[1] is not None:
            self._hint(self.e_cj, _num(self.pdk[1]))

    @staticmethod
    def _hint(edit, text: str):
        try:
            edit.placeholderText = f"{text} (PDK, drawn junction)"
        except Exception:  # noqa: BLE001
            pass

    # ---- live L at this bias ----------------------------------------------------------------------------------
    @staticmethod
    def _float(edit, default=None):
        text = edit.text.strip()
        return default if not text else float(text)

    def lj0(self):
        """L_J0 in use: the typed / stored value, else the drawn junction's PDK value, else None."""
        try:
            typed = self._float(self.e["Lj_nH"])
        except ValueError:
            return None
        if typed is not None:
            return typed
        return None if self.pdk is None else self.pdk[0]

    def source_text(self) -> str:
        if self.e["Lj_nH"].text.strip():
            return "design (the value in this dialog / design.json)"
        if self.pdk is not None:
            return "drawn junction, PDK rule (nothing is written unless you type a value)"
        return "none: no L_J (the LOM and eigenmode / driven runs need one)"

    def refresh(self):
        """Recompute the read-only rows from the fields."""
        lj0, err, text = self.lj0(), "", "none"
        if lj0 is not None and lj0 > 0:
            try:
                eff = lj0
                if self.squid:
                    eff = squid_l_eff(lj0, self._float(self.e_flux, 0.0), self._float(self.e_asym, 0.0))
                text = format(eff, ".5g")
            except ValueError as e:
                err = str(e)
        self.l_eff.text = text
        self.l_src.text = self.source_text()
        if err or self._edited:  # until the first edit the sidecar's own message stays
            self.l_err.text = err

    def _edit(self):
        self._edited = True
        self.refresh()

    def _follow(self, key, text):
        try:
            value = float(text) if text.strip() else None
            trip = design_io.junction_triplet(self.gap, **{{"Lj_nH": "lj_nh", "Ic_nA": "ic_na", "Rn_kohm": "rn_kohm"}[key]: value})
        except (ValueError, ZeroDivisionError):
            self._edit()
            return
        for k, e in self.e.items():
            if k != key:
                e.text = "" if trip[k] is None else format(trip[k], ".5g")
        self._edit()

    def values(self):
        """``(Lj_nH or None, Cj_fF or None, flux_phi0, asym)`` (flux and asym ``design_ops.KEEP`` for a component that
        is not a SQUID), or None for a multi-junction qubit (left as it is)."""
        if self.multi:
            return None
        lj = float(self.e["Lj_nH"].text) if self.e["Lj_nH"].text.strip() else None
        cj = float(self.e_cj.text) if self.e_cj.text.strip() else None
        if not self.squid:
            return lj, cj, design_ops.KEEP, design_ops.KEEP
        return lj, cj, self._float(self.e_flux, 0.0), self._float(self.e_asym, 0.0)


def _table_height(table) -> int:
    """The height that shows every row of ``table`` (its header included), for the dialog's first size."""
    v = dialogs._v  # pylint: disable=protected-access
    try:
        table.resizeRowsToContents()
        header = int(v(v(v(table.horizontalHeader).sizeHint).height))
        rows = sum(int(table.rowHeight(i)) for i in range(int(v(table.rowCount))))
        return header + rows + 2 * int(v(table.frameWidth)) + 4
    except Exception:  # noqa: BLE001
        return 300


def _hint_h(layout) -> int:
    return dialogs._hint(layout)[1]  # pylint: disable=protected-access


def edit_instance_dialog(name: str, entry: dict, targets: dict | None = None):
    """Dialog: the placed instance's parameters (its values over the cell defaults), rotation and, for components
    that can have them (qubits), targets. ``targets`` is the element's current ``design.json`` targets (None: no
    targets section). Returns ``(changed params, rotation or None, targets or None, position or None, junction or
    None)`` (None targets: section not shown; None position: unchanged or snapped; junction ``(Lj_nH, Cj_fF, flux, asym)``
    for a qubit) or None when cancelled."""
    rows = schema(entry["cell"])
    place = entry.get("place", {})
    snapped = "snap" in place
    dialog = pya.QDialog(pya.Application.instance().main_window())
    dialog.windowTitle = f"{name} ({entry['cell']})"
    left = pya.QVBoxLayout()  # position and parameters; the right column: targets, junction, circuit
    lay = pya.QVBoxLayout()
    form = pya.QFormLayout()
    e_rot = pya.QLineEdit("" if snapped else f"{place.get('rot', 0.0):g}", dialog)
    e_rot.enabled = not snapped
    e_rot.toolTip = "Rotation in degrees (counter-clockwise); a snapped instance takes the rotation of its snap"
    at0 = place.get("at") if not snapped else None
    e_x = pya.QLineEdit("" if at0 is None else _num(at0[0]), dialog)
    e_y = pya.QLineEdit("" if at0 is None else _num(at0[1]), dialog)
    for e in (e_x, e_y):
        e.enabled = at0 is not None
        e.toolTip = ("Position of the component's origin in µm (exact); a snapped instance sits on its snap port"
                     if at0 is not None else "Snapped to a port: move it with Move/Snap")
    form.addRow("x µm", e_x)
    form.addRow("y µm", e_y)
    form.addRow("rotation (°)", e_rot)
    left.addLayout(form)
    table = pya.QTableWidget(0, 2, dialog)
    table.setHorizontalHeaderLabels(["parameter", "value"])
    fill_table(table, rows, entry.get("params", {}), entry["cell"])
    table.setMinimumSize(380, 240)  # it scrolls; the dialog gives it the height the screen has
    left.addWidget(table, 1)
    keys = (design_io.target_keys("instance", entry["cell"], targets, CATEGORY.get(entry["cell"]))
            if targets is not None else {})
    editor = TargetsEditor(dialog, lay, keys, targets or {}) if keys else None
    jrows = None
    if CATEGORY.get(entry["cell"]) == "qubit" or "junction" in entry or any(p["name"] == "junction_type" for p in rows):
        jform = pya.QFormLayout()
        info = junction_info(name)
        jrows = JunctionRows(dialog, jform, entry.get("junction"), info, drawn_junction_value(entry, info))
        lay.addLayout(jform)
    lom_section(dialog, lay, name)
    dialog.targets_editor = editor  # for tests
    dialog.junction_rows = jrows  # for tests
    dialog.param_table, dialog.param_rows = table, rows  # for tests
    if lay.count() == 0:  # nothing for the right column: the parameters take the width
        body = pya.QWidget(dialog)
        body.setLayout(left)
    else:
        lay.addStretch(1)
        body = dialogs.side_by_side(dialog, left, lay)
    dialog.qcc_body = body  # tests
    dialogs.fit(dialog, body, ok_cancel(dialog), want=(0, _table_height(table) + _hint_h(form) + 60))
    if not dialog.exec_():
        return None
    try:
        new_targets = editor.values() if editor is not None else None
        junction = jrows.values() if jrows is not None else None
    except ValueError as e:
        pya.MessageBox.warning("qcc", str(e), pya.MessageBox.Ok)
        return None
    params = design_io.changed_params(rows, table_values(table, rows))
    known = {p["name"] for p in rows}
    extra = {k: v for k, v in entry.get("params", {}).items() if k not in known}  # e.g. junction_params kept as is
    rot = float(e_rot.text) if not snapped and e_rot.text.strip() else None
    at = None
    if at0 is not None and e_x.text.strip() and e_y.text.strip():
        try:
            xy = (float(e_x.text), float(e_y.text))
        except ValueError as e:
            pya.MessageBox.warning("qcc", f"position: {e}", pya.MessageBox.Ok)
            return None
        if abs(xy[0] - float(at0[0])) > 1e-9 or abs(xy[1] - float(at0[1])) > 1e-9:
            at = xy
    return {**extra, **params}, rot, new_targets, at, junction


def apply_instance_edit(design: dict, name: str, out) -> str:
    """Write the result of :func:`edit_instance_dialog` into ``design`` and describe it."""
    params, rot, new_targets = out[:3]
    at = out[3] if len(out) > 3 else None
    design_io.set_instance(design, name, params, rot)
    what = f"{name}: parameters {params or 'defaults'}" + (f", rot {rot:g}" if rot is not None else "")
    if at is not None:
        design["instances"][name].setdefault("place", {})["at"] = [float(at[0]), float(at[1])]
        what += f", at ({at[0]:g}, {at[1]:g})"
    if new_targets is not None and design_io.set_targets(design, name, new_targets):
        what += f", targets {new_targets or 'none'}"
    junction = out[4] if len(out) > 4 else None
    if junction is not None and design_ops.set_junction(design, name, *junction):
        what += f", junction {design['instances'][name].get('junction') or 'removed'}"
    return what


def _rot(p, deg: float):
    import math  # pylint: disable=import-outside-toplevel

    c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (p[0] * c - p[1] * s_, p[0] * s_ + p[1] * c)


class SnapTool(_Tool):
    def reset(self):
        self.drag = None  # {"inst", "origin", "rot"}
        self.hit = None

    def __init__(self, manager, view):
        super().__init__(manager, view)
        self.reset()

    def instance_at(self, p):
        for name, inst in self.data.get("instances", {}).items():
            b = inst.get("bbox")
            if b and b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]:
                return name
        return None

    def own_ports(self, inst) -> dict:
        return {n: v for n, v in self.ports().items() if n.split(".", 1)[0] == inst}

    def other_ports(self, inst) -> dict:
        return {n: v for n, v in self.ports().items() if n.split(".", 1)[0] != inst}

    def redraw(self):
        o = self.overlay
        o.clear()
        self.draw_drc()
        for inst in self.data.get("instances", {}).values():
            if inst.get("bbox"):
                o.rect(inst["bbox"], GREY)
        if PENDING_PLACE:
            c, s = self.snap(self.mouse), o.px(14)
            rot = PENDING_PLACE.get("rot", 0.0)
            g = PENDING_PLACE.get("ghost") or {}
            pend = self.pending_snap(c)
            if pend:  # a port is near a compatible one: the component turns to face it and sits on it
                c, rot = pend[2], rot + pend[3]

            mirror = PENDING_PLACE.get("mirror", False)

            def to_chip(q):
                r = _rot((q[0], -q[1]) if mirror else q, rot)
                return (c[0] + r[0], c[1] + r[1])

            for poly in g.get("outline", []):  # the component's etched outline, as it will be placed
                pts = [to_chip(q) for q in poly]
                o.path(pts + pts[:1], color=RED, width=2)
            if g.get("bbox"):
                x0, y0, x1, y1 = g["bbox"]
                pts = [to_chip(q) for q in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
                o.path(pts + pts[:1], color=GREY, width=1, style=2)
            for port in g.get("ports", []):  # its ports, pointing the way they will point
                ang = port.get("dir")  # None: a directionless port (e.g. a SQUID terminal): drawn as a box
                d = None if ang is None else _rot((1.0, 0.0), (-1 if mirror else 1) * ang + rot)
                o.arrow({"pos": to_chip(tuple(port["at"])), "dir": d}, BLUE)
                o.text(to_chip(tuple(port["at"])), port["name"], BLUE)
            o.path([(c[0] - s, c[1]), (c[0] + s, c[1])], color=RED, width=1)
            o.path([(c[0], c[1] - s), (c[0], c[1] + s)], color=RED, width=1)
            if pend:
                target = self.ports()[pend[1]]
                o.box(tuple(target["pos"]), 9, GREEN, filled=False, width=2)
                o.text(tuple(target["pos"]), snap_text(pend, rot), GREEN)
            o.text((c[0] + s, c[1] + s), f"{PENDING_PLACE['cell']} {rot:g}°: click to drop, {ROTATE_HINT}, Ctrl: no "
                   "rotation snap, right-click cancels", RED)
            return
        if not self.drag:
            hover = self.instance_at(self.mouse)
            if hover:
                o.rect(self.data["instances"][hover]["bbox"], BLUE, style=0, width=2)
            return
        inst = self.drag["inst"]
        delta = geometry.sub(self.mouse, self.drag["origin"])
        at = tuple(self.data["instances"][inst]["trans"]["at"])
        turn = (self.drag["rot"] - self.data["instances"][inst]["trans"]["rot"]) % 360.0
        self.hit = geometry.snap_candidate_rot(self.own_ports(inst), self.other_ports(inst), delta, self.capture(), at,
                                               turn, rotate=not self.free)
        extra = 0.0
        if self.hit:
            delta, extra = self.hit[2], self.hit[3]
        else:
            delta = geometry.sub(self.snap(geometry.add(self.drag["at"], delta)), self.drag["at"])
        turn = (turn + extra) % 360.0  # shown turn: the held one plus the snap's
        b = self.data["instances"][inst]["bbox"]
        if 1e-9 < turn < 360.0 - 1e-9:  # turned while held or by the snap: the bbox turned about the instance origin
            corners = [_rot((x - at[0], y - at[1]), turn) for x, y in ((b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]))]
            pts = [(at[0] + cx + delta[0], at[1] + cy + delta[1]) for cx, cy in corners]
            o.path(pts + pts[:1], color=RED, width=2)
        else:
            o.rect([b[0] + delta[0], b[1] + delta[1], b[2] + delta[0], b[3] + delta[1]], RED, style=0, width=2)
        g = self.drag.get("outline") or {}
        mirror = bool(self.data["instances"][inst]["trans"].get("mirror"))
        for poly in g.get("outline", []):  # the component's etched outline, as it will lie
            pts = []
            for q in poly:
                r = _rot((q[0], -q[1]) if mirror else q, self.drag["rot"] + extra)
                pts.append((at[0] + delta[0] + r[0], at[1] + delta[1] + r[1]))
            o.path(pts + pts[:1], color=RED, width=1)
        for port in self.own_ports(inst).values():  # the ports as they will point: turned about the origin
            rel = _rot((port["pos"][0] - at[0], port["pos"][1] - at[1]), turn)
            d = port.get("dir")
            o.arrow({**port, "pos": (at[0] + rel[0] + delta[0], at[1] + rel[1] + delta[1]),
                     "dir": _rot(tuple(d), turn) if d else d}, RED)
        if self.hit:
            target = self.ports()[self.hit[1]]
            o.box(tuple(target["pos"]), 9, GREEN, filled=False, width=2)
            o.text(tuple(target["pos"]), snap_text(self.hit, self.drag["rot"] + extra), GREEN)
        else:
            o.text(self.mouse, f"{inst} at ({self.drag['at'][0] + delta[0]:g}, {self.drag['at'][1] + delta[1]:g})", RED)

    def load_outline(self, inst):
        """The held instance's etched outline for the preview (background query, cached; the bbox shows until it
        arrives, and when the instance's parameters cannot be read)."""
        drag = self.drag
        try:
            entry = SESSION.design()["instances"][inst]
            ghost_async(entry["cell"], entry.get("params") or {},
                        lambda g: drag.__setitem__("outline", g) if g and self.drag is drag else None)
        except Exception:  # noqa: BLE001  (the preview only loses the outline)
            pass

    def pending_snap(self, c):
        """``(own port, target port, corrected position, extra turn)`` for the component being placed with its origin
        at ``c`` (it follows the mouse like a held instance: a port near a compatible one snaps, turning to face it;
        Ctrl: only ports that already face each other), or None."""
        g = PENDING_PLACE.get("ghost") or {}
        rot, mirror = PENDING_PLACE.get("rot", 0.0), PENDING_PLACE.get("mirror", False)
        mine = {}
        for port in g.get("ports", []):
            if port.get("dir") is None:
                continue
            q = tuple(port["at"])
            mine[port["name"]] = {"pos": _rot((q[0], -q[1]) if mirror else q, rot),
                                  "dir": _rot((1.0, 0.0), (-1 if mirror else 1) * port["dir"] + rot),
                                  "a": port.get("a"), "b": port.get("b")}
        return geometry.snap_candidate_rot(mine, self.ports(), c, self.capture(), rotate=not self.free)

    def mouse_moved_event(self, p, buttons, prio):
        super().mouse_moved_event(p, buttons, prio)
        if prio and self.active:
            self.redraw()
            return bool(self.drag)
        return False

    def _drop(self, p, how: str) -> bool:
        """Place the pending component at ``p`` (from a press or a click, whichever KLayout delivers)."""
        here = _xy(p)
        log(f"place ({how}) at {here}: {PENDING_PLACE.get('cell')}")
        try:
            self.place(self.snap(here))
        except Exception:  # noqa: BLE001
            PENDING_PLACE.clear()
            report_error("placing the component")
        return True

    def mouse_click_event(self, p, buttons, prio):  # KQC's proven path (edit_node_plugin uses only click events)
        if PENDING_PLACE:
            log(f"click event prio={prio} active={self.active} buttons={buttons}")
        if prio and self.active and buttons & RIGHT and (PENDING_PLACE or self.drag):  # right-click cancels
            PENDING_PLACE.clear()
            self.reset()
            self.redraw()
            return True
        if PENDING_PLACE and prio and self.active and buttons & LEFT:
            return self._drop(p, "click")
        if not (prio and self.active and buttons & LEFT):
            return False
        here = _xy(p)
        try:
            if self.drag:
                self.mouse = here
                self.drop_instance()
                return True
            inst = self.instance_at(here)
            if inst is None:
                return False
            at = tuple(self.data["instances"][inst]["trans"]["at"])
            self.drag = {"inst": inst, "origin": here, "at": at, "rot": self.data["instances"][inst]["trans"]["rot"],
                         "outline": None}
            self.load_outline(inst)
            message(f"{inst}: move it, [ ] rotate, click to drop (right-click cancels)", 4)
            self.redraw()
        except Exception:  # noqa: BLE001
            self.reset()
            report_error("moving the component")
        return True

    def drop_instance(self):
        self.redraw()  # final snap decision
        inst, design = self.drag["inst"], SESSION.design()
        if self.hit:
            own, target, _, extra = self.hit
            design_io.set_place_snap(design, inst, own.split(".", 1)[1], target)
            what = f"{inst}: snapped {own} → {target}" + (f", turned {extra:+.1f}°" if extra else "")
        else:
            delta = geometry.sub(self.mouse, self.drag["origin"])
            at = self.snap(geometry.add(self.drag["at"], delta))
            old = design["instances"][inst].get("place", {}).get("at") or self.drag["at"]
            design_io.set_place_at(design, inst, at, self.drag["rot"])
            design_io.follow_hangers(design, inst, (at[0] - old[0], at[1] - old[1]))
            what = f"{inst}: at ({at[0]:g}, {at[1]:g}) rot {self.drag['rot']:g}"
        self.reset()
        SESSION.commit(design, what)

    def key_event(self, key, buttons):
        if not self.active:
            return False
        if self.drag and key in (pya.KeyCode.Escape,):
            self.reset()
            self.redraw()
            return True
        if PENDING_PLACE and key == pya.KeyCode.Escape:
            PENDING_PLACE.clear()
            self.redraw()
            return True
        if PENDING_PLACE and key in ROTATE_KEYS:
            PENDING_PLACE["rot"] = (PENDING_PLACE.get("rot", 0.0) + ROTATE_KEYS[key]) % 360.0
            self.redraw()
            return True
        if self.drag and key in ROTATE_KEYS:
            self.drag["rot"] = (self.drag["rot"] + ROTATE_KEYS[key]) % 360.0
            message(f"{self.drag['inst']}: rot {self.drag['rot']:g} (applied on release)")
            return True
        return False

    def mouse_double_click_event(self, p, buttons, prio):
        """Double-click a placed component: edit its parameters and rotation (written to design.json, rebuilt)."""
        if not (prio and self.active) or PENDING_PLACE:
            return False
        inst = self.instance_at(_xy(p))
        log(f"double-click at {_xy(p)}: {inst}")
        if inst is None:
            hit = geometry.route_near(self.all_routes(), _xy(p), self.capture())
            if hit is None:
                return False
            try:  # a route (a meander, a hanger, a line): its dialog, as a double-click in Route handles
                edit_route_options(hit[0])
            except Exception:  # noqa: BLE001
                report_error(f"editing route {hit[0]}")
            return True
        try:
            design = SESSION.design()
            out = edit_instance_dialog(inst, design["instances"][inst], design.get("targets", {}).get(inst, {}))
            if out is not None:
                SESSION.commit(design, apply_instance_edit(design, inst, out))
        except Exception:  # noqa: BLE001
            report_error(f"editing {inst}")
        return True

    def place(self, at):
        design = SESSION.design()
        cell = PENDING_PLACE["cell"]
        base = "".join(c for c in cell if c.isupper())[:3] or "X"
        name = design_io.unique_name(design, base)
        rot = PENDING_PLACE.get("rot", 0.0)
        pend = self.pending_snap(at)
        if pend:  # on a compatible port: the placement is the snap (the build solves the turn, as the preview showed)
            at, rot = pend[2], (rot + pend[3]) % 360.0
        design_io.add_instance(design, name, cell, at, rot, PENDING_PLACE.get("params") or None,
                               PENDING_PLACE.get("mirror", False), PENDING_PLACE.get("extra"))
        if pend:
            design_io.set_place_snap(design, name, pend[0], pend[1])
        note = size_note(cell, PENDING_PLACE.get("ghost"))
        PENDING_PLACE.clear()
        jnote = fix_placed_junction(design, name)  # the same undo step as the placement
        SESSION.commit(design, f"placed {name} ({cell}) at ({at[0]:g}, {at[1]:g}) rot {rot:g}"
                       + (f", snapped {pend[0]} → {pend[1]}" if pend else "")
                       + (f", junction {design['instances'][name]['junction']}" if jnote else ""))
        if jnote:
            message(jnote, 12)
        if note:
            message(f"NOTE: {note}", 12)


# ---- failed routes: red, whatever tool is active -------------------------------------------------------------------
FAILED = {"overlay": None}


def draw_failed(o, name: str, f: dict) -> None:
    """One failed route in red: its last good path (the route as it last built, wide) when there is one, and the path
    the design asks for now (its ends and nodes, dashed), with the name and the reason."""
    last = (f.get("last_good") or {}).get("polyline") or []
    a, b = float(f.get("a") or 10.0), float(f.get("b") or 6.0)
    if len(last) > 1:
        o.path([tuple(q) for q in last], width_um=a + 2 * b, color=RED, r=float(f.get("r") or 0.0))
    now = [tuple(q) for q in f.get("polyline") or []]
    if len(now) > 1:
        o.path(now, color=RED, style=2, width=2)
    at = now[len(now) // 2] if now else (tuple(last[len(last) // 2]) if last else None)
    if at is not None:
        why = str(f.get("error", ""))
        why = why[len(f"route {name}: "):] if why.startswith(f"route {name}: ") else why
        o.text(at, f"{name} FAILED: {why[:90]}" + ("  (last good route shown)" if last else ""), RED)


def refresh_failed_overlay() -> None:
    """Red markers for the routes the last build left out, on the design's view (a listener of the session: it runs
    after every sidecar change, so the marks follow each build and vanish when the route builds again)."""
    view, _ = SESSION.find_view()
    old = FAILED["overlay"]
    if old is not None and (view is None or old.view is not view):
        old.clear()
        FAILED["overlay"] = old = None
    if view is None:
        return
    if old is None:
        old = FAILED["overlay"] = _Overlay(view)
    old.clear()
    for name, f in ((SESSION.data or {}).get("failed_routes") or {}).items():
        draw_failed(old, name, f)


# ---- factories ---------------------------------------------------------------------------------------------------
ICONS = Path(__file__).resolve().parents[2] / "icons"  # kplugin/icons/<name>.png (32×32 or 64×64, transparent)


def icon(name: str) -> str | None:
    path = ICONS / f"{name}.png"
    return str(path) if path.exists() else None


class _Factory(pya.PluginFactory):
    tool_cls = None

    def __init__(self, ident, title, priority, tip=""):  # pylint: disable=super-init-not-called  (as KQC)
        self.has_tool_entry = True
        path = icon(ident)
        if path:
            self.register(priority, ident, title, path)
        else:
            self.register(priority, ident, title)
        action = pya.MainWindow.instance().menu().action(f"@toolbar.{ident}")
        if action and tip:
            action.tool_tip = tip

    def create_plugin(self, manager, _root, view):
        tool = self.tool_cls(manager, view)
        INSTANCES.append(tool)
        return tool


class ConnectFactory(_Factory):
    tool_cls = ConnectTool


class RouteEditFactory(_Factory):
    tool_cls = RouteEditTool


class SnapFactory(_Factory):
    tool_cls = SnapTool


FACTORIES = []
INSTANCES = []  # created tools (one per view and mode); used by scripted GUI tests


def register_tools():
    if FACTORIES:
        return
    if refresh_failed_overlay not in SESSION.listeners:
        SESSION.listeners.append(refresh_failed_overlay)
    FACTORIES.append(
        ConnectFactory("qcc_connect", "Connect", 2000,
                       "Pen tool: click a port or the canvas, click nodes, end on a port, a line or the last node")
    )
    FACTORIES.append(
        RouteEditFactory("qcc_route_edit", "Route handles", 2001,
                         "Click a node to move it; green handle: corner radius; hollow: insert; right-click: delete")
    )
    FACTORIES.append(SnapFactory("qcc_snap", "Move/Snap", 2002, "Drag an instance; ports snap to compatible ports"))
