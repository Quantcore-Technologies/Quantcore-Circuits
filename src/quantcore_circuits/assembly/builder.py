"""Build a design into a KQC chip cell and write it out."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from kqcircuits.defaults import default_layers
from kqcircuits.elements.element import get_refpoints
from kqcircuits.pya_resolver import pya
from kqcircuits.util.load_save_layout import save_layout

from quantcore_circuits import track as _track
from quantcore_circuits.assembly.plan import BuildPlan, plan_design
from quantcore_circuits.design import Design, design_hash, load_design
from quantcore_circuits.layouts.chips.design_chip import DesignChip, ensure_registered
from quantcore_circuits.layouts.ports import check_cell


@dataclass
class BuildResult:
    design: Design
    plan: BuildPlan
    layout: pya.Layout
    cell: pya.Cell  # the DesignChip PCell (library proxy)
    top: pya.Cell  # static top cell holding the chip; this is what gets written
    source: Path | None = None  # design file, when built from one

    @property
    def refpoints(self) -> dict[str, pya.DPoint]:
        """Chip-level refpoints, e.g. ``Q1_port_claw_n``, ``FL_port_a`` (instance name prefixes)."""
        return dict(get_refpoints(self.layout.layer(default_layers["refpoints"]), self.cell, pya.DTrans(), 0))

    @property
    def hash(self) -> str:
        return design_hash(self.design)

    def route_lengths(self) -> dict[str, float]:
        return {n: r.length for n, r in self.plan.routes.items()}

    @property
    def failed_routes(self) -> dict:
        """Routes left out of this build (``build(keep_going=True)`` only): ``{name: FailedRoute}``."""
        return self.plan.failed

    def require_complete(self, what: str = "this") -> None:
        """Raise when a route failed (a ``keep_going`` build): ``what`` needs every route."""
        if self.plan.failed:
            from quantcore_circuits.route.router import RoutingError  # pylint: disable=import-outside-toplevel

            raise RoutingError(
                f"{what} refused: " + "; ".join(f.error for f in self.plan.failed.values())
                + " (fix the failed route(s), then build again)"
            )


def build(
    source, layout: pya.Layout | None = None, keep_going: bool = False, last_good: dict | None = None, **chip_overrides
) -> BuildResult:
    """Build ``source`` (path, dict or :class:`Design`) into a ``DesignChip`` cell.

    ``chip_overrides`` replace chip parameters for this build only (e.g. ``with_grid=False`` for simulation).
    ``keep_going`` leaves a route that cannot be built out of the layout instead of raising (it is listed in
    ``result.failed_routes``, with its ``last_good`` geometry when given); the default is strict.
    """
    design = load_design(source)
    ensure_registered()
    layout = layout or pya.Layout()
    plan = plan_design(design, keep_going=keep_going, last_good=last_good)
    params = {**plan.chip_params, **chip_overrides}
    cell = DesignChip.create(layout, plan=plan.to_json(), **params)
    check_cell(cell, f"design {design.name}")
    # KLayout drops top-level library proxies when writing, so (like KQC scripts) wrap the chip in a static top cell
    top = layout.create_cell(design.name)
    top.insert(pya.DCellInstArray(cell.cell_index(), pya.DTrans()))
    path = Path(source) if isinstance(source, (str, Path)) else None
    return BuildResult(design, plan, layout, cell, top, path)


def write_layout(result: BuildResult, path: str | Path, layers=None, sidecar: bool = True) -> Path:
    """Write the chip as static geometry (no PCell context), atomically so a live viewer never reads half a file.

    Also writes ``<name>.qcc.json`` (ports, instances, routes) for the KLayout plugin unless ``sidecar=False``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=path.suffix, dir=path.parent)
    os.close(fd)
    try:
        save_layout(tmp, result.layout, [result.top], layers)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    if result.plan.keep_going:  # the routes that built are the next build's "last good" (see assembly.last_good)
        from quantcore_circuits.assembly import last_good  # pylint: disable=import-outside-toplevel

        last_good.update(last_good.store_path(path), result.plan, previous={
            n: f.last_good for n, f in result.plan.failed.items() if f.last_good})
    if sidecar:
        from quantcore_circuits.assembly.sidecar import write_sidecar  # pylint: disable=import-outside-toplevel

        write_sidecar(result, path)
    _track.emit("layout", result=result, path=path)
    return path


def show(source, path: str | Path | None = None, **chip_overrides) -> BuildResult:
    """Build, write and open in KLayout via klive (the Jupyter equivalent of ``qcc watch``). KLayout is started
    (with the layout) when klive is not listening and raised to the front, unless ``QCC_KLAYOUT_GUI=0``."""
    from quantcore_circuits.live import klayout as kl  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.live.klive import klive_available, send_to_klive  # pylint: disable=C0415

    result = build(source, **chip_overrides)
    path = Path(path) if path else Path("build") / f"{result.design.name}.oas"
    write_layout(result, path)
    if not klive_available() and kl.gui_enabled():
        try:
            kl.open_klayout(path, front=False)
        except FileNotFoundError:  # no KLayout installed: send_to_klive raises KliveUnavailable as before
            pass
    send_to_klive(path)  # KliveUnavailable if klive is still not listening
    if klive_available() and kl.gui_enabled():
        kl.bring_to_front(layout=path)
    return result
