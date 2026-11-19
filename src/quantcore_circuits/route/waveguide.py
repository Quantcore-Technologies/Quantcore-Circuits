"""KQC ``WaveguideComposite`` with a bend radius per corner.

KQC's ``WaveguideComposite`` bends every corner of a straight-waveguide stretch with one radius ``r``; a node's own
``r`` only takes effect on element nodes (tapers, airbridges, ...) and then for the rest of the route. A route with
per-corner radii (``Waypoint.r``) is built with :class:`WaveguideCompositeCorners` instead: its plain nodes may carry
``corner_r`` (µm), the radius of the bend *at that node only*. Where two neighbouring corners differ, the stretch is
split into separate ``WaveguideCoplanar`` pieces in the middle of the straight between them (between the two bend
cuts), so each piece rounds its corners with its own radius. Routes without ``corner_r`` keep the stock KQC class,
so existing designs build exactly as before.

Joins (:func:`joined_nodes`): where a route ends at a cell's port, its gap strips and the cell's etch meet along
one line. Both are snapped to the 1 nm grid on their own, so at an angled port (a ConcentricTransmon coupler at 60°,
a Metal tee at 45°) or a port half a grid step off (an Xmon claw at y = ….4625 µm) they can miss each other by
less than 1 nm. The build then keeps the strip a separate polygon behind a zero-width metal crack, and the fab
export's corner rounding (per polygon) opens the crack into metal slivers (~0.5 µm² each). Such an end is drawn
:data:`JOIN_SHIFT` into the cell, so its strips overlap the cell's etch; the route's port refpoints stay on the
cell's port and the plan's route length is unchanged (the drawn route is 10 nm longer). Ends that already merge are
drawn as before.
"""

from __future__ import annotations

from math import acos, pi, tan

from kqcircuits.elements.waveguide_composite import WaveguideComposite
from kqcircuits.pya_resolver import pya

CORNER_R = "corner_r"  # node parameter: bend radius of this node's corner only
_EPS = 1e-6


def has_corner_radii(nodes) -> bool:
    return any(CORNER_R in (n.params or {}) for n in nodes)


def waveguide_class(nodes):
    """The cell class for a route with these KQC nodes: :class:`WaveguideCompositeCorners` when a node sets its own
    corner radius, else KQC's ``WaveguideComposite``."""
    if has_corner_radii(nodes):
        ensure_registered()
        return WaveguideCompositeCorners
    return WaveguideComposite


def _turn(v1: pya.DVector, v2: pya.DVector) -> float:
    c = v1.sprod(v2) / (v1.length() * v2.length())
    return acos(max(-1.0, min(1.0, c)))


class WaveguideCompositeCorners(WaveguideComposite):
    """``WaveguideComposite`` whose plain nodes may set the bend radius of their own corner (node param
    ``corner_r``)."""

    def _add_waveguide(self, end_index, end_pos=None, end_dir=None):
        start = self._wg_start_idx
        if end_index <= start:
            return super()._add_waveguide(end_index, end_pos, end_dir)
        route_r = self.r
        nodes = self._nodes
        last = end_pos if end_pos is not None else nodes[end_index].position
        pos = [self._wg_start_pos] + [nodes[k].position for k in range(start + 1, end_index)] + [last]
        corners = []  # (j in pos, radius, cut)
        for j in range(1, len(pos) - 1):
            v1, v2 = pos[j] - pos[j - 1], pos[j + 1] - pos[j]
            if v1.length() < _EPS or v2.length() < _EPS:
                continue
            theta = _turn(v1, v2)
            if theta < 1e-9:
                continue
            rad = float(nodes[start + j].params.get(CORNER_R, route_r))
            corners.append((j, rad, rad * tan(min(theta, pi - 1e-9) / 2)))
        split = next((i for i in range(len(corners) - 1) if abs(corners[i][1] - corners[i + 1][1]) > _EPS), None)
        if split is None:  # one radius for the whole stretch
            if corners:
                self.r = corners[0][1]
            try:
                super()._add_waveguide(end_index, end_pos, end_dir)
            finally:
                self.r = route_r
            return None
        (ja, ra, cut_a), (jb, _rb, cut_b) = corners[split], corners[split + 1]
        straight = pos[jb] - pos[ja]
        length = straight.length()
        direction = straight / length
        s_split = cut_a + max(0.0, length - cut_a - cut_b) / 2  # middle of the straight between the two bends
        acc = 0.0
        for j in range(ja + 1, jb + 1):
            seg = (pos[j] - pos[j - 1]).length()
            if abs(acc + seg - s_split) < _EPS and j < jb:  # the split falls on a collinear node: end there
                self.r = ra
                try:
                    super()._add_waveguide(start + j)
                finally:
                    self.r = route_r
                break
            if s_split < acc + seg:
                node = nodes[start + j]
                saved = (node.length_before, node.length_increment)
                node.length_before = node.length_increment = None  # the meander goes on the second half only
                self.r = ra
                try:
                    super()._add_waveguide(start + j, pos[ja] + direction * s_split, direction)
                finally:
                    node.length_before, node.length_increment = saved
                    self.r = route_r
                self._wg_start_idx = start + j - 1  # the next piece runs from the split point to node start + j
                break
            acc += seg
        else:  # numerically no split point (cannot happen for a valid straight): one radius, as KQC would
            return super()._add_waveguide(end_index, end_pos, end_dir)
        return self._add_waveguide(end_index, end_pos, end_dir)


_registered = False


def ensure_registered() -> None:
    """Register :class:`WaveguideCompositeCorners` in KQC's element library (idempotent)."""
    global _registered  # pylint: disable=global-statement
    if _registered:
        return
    from quantcore_circuits.layouts import ensure_loaded, register_pcell_classes  # pylint: disable=C0415

    ensure_loaded()
    register_pcell_classes([WaveguideCompositeCorners])
    _registered = True


JOIN_SHIFT = 0.01  # µm: how far a route end that misses a cell's etch is drawn into the cell


def etch_near(cell: pya.Cell, trans: pya.ICplxTrans, layer: int, box: pya.Box) -> pya.Region:
    """``cell``'s shapes on ``layer`` placed with ``trans``, within ``box`` (parent dbu)."""
    local = box.transformed(trans.inverted())
    return pya.Region(cell.begin_shapes_rec_touching(layer, local)).transformed(trans) & pya.Region(box)


def misses_etch(cell_etch: pya.Region, route_etch: pya.Region, direction: pya.DVector, dbu: float) -> bool:
    """True if a piece of the route's etch neither overlaps nor touches the cell's etch (so the merge keeps it apart)
    although the cell is etched within :data:`JOIN_SHIFT` behind it (``direction`` points along the route): a
    hairline gap. A pin on solid metal, or a join that already merges, gives False."""
    loose = route_etch.not_interacting(cell_etch)
    if loose.is_empty():
        return False
    k = JOIN_SHIFT / dbu
    behind = loose.minkowski_sum(pya.Edge(0, 0, -round(direction.x * k), -round(direction.y * k)))
    return not (behind & cell_etch).is_empty()


def joined_nodes(route_cell: pya.Cell, nodes: list, node_strings: list, origin: pya.DVector, joins: list,
                 placed: dict, layer: int, half_width: float):
    """Nodes for a route whose ends meet a cell's etch across a hairline (see the module docstring), or None.

    ``route_cell`` is the route as built from ``nodes`` (relative to ``origin``), ``node_strings`` the plan's nodes,
    ``joins`` the plan's ``[{"inst", "node": 0 | -1}]``, ``placed`` the chip's instances by name, ``layer`` the etch
    layer and ``half_width`` the route's a/2 + b (µm). Returns ``(nodes, shifts)``: fresh nodes (relative to
    ``origin``) with those ends moved :data:`JOIN_SHIFT` into the cell, and ``{"a" | "b": shift (µm)}`` per moved end.
    """
    from kqcircuits.util.node import Node  # pylint: disable=import-outside-toplevel

    layout = route_cell.layout()
    dbu = layout.dbu
    route_trans = pya.ICplxTrans(pya.Trans(pya.Vector(round(origin.x / dbu), round(origin.y / dbu))))
    moved = {}
    for join in joins:
        inst = placed.get(join["inst"])
        i = int(join["node"])
        if inst is None or len(nodes) < 2:
            continue
        at, nxt = nodes[i].position + origin, nodes[1 if i == 0 else -2].position + origin
        if (nxt - at).length() < _EPS:
            continue
        u = (nxt - at) / (nxt - at).length()  # along the route, away from the cell
        reach = half_width + 2.0
        box = pya.DBox(at.x - reach, at.y - reach, at.x + reach, at.y + reach).to_itype(dbu)
        cell_etch = etch_near(inst.cell, inst.cplx_trans, layer, box)
        route_etch = etch_near(route_cell, route_trans, layer, box)
        if not cell_etch.is_empty() and misses_etch(cell_etch, route_etch, u, dbu):
            moved[i] = u * -JOIN_SHIFT
    if not moved:
        return None
    fresh = Node.nodes_from_string(node_strings)
    for node in fresh:
        node.position = node.position - origin
    for i, shift in moved.items():
        fresh[i].position = fresh[i].position + shift
    return fresh, {("a" if i == 0 else "b"): shift for i, shift in moved.items()}
