"""The sim-group overlay: what a Simulate (or a saved ``sim_groups`` entry) renders, drawn over the layout.

It is a set of KLayout markers on the view, like the other overlays of the plugin: never a fab layer, never in an
export, a PNG of the view made by KLayout's own tools aside. What it shows comes from ``qcc sim preview`` (the library's
``guiflow.preview_groups``, which runs the same ``build_simulation`` as the export, so the box, the ports and the routes
are the ones of the job folder; nothing is written):

* the **box** (purple) with its group, analysis and size;
* the **components** that are selected (green frames), the routes that stay in the simulation (green lines; a grey one
  is only passing through the box, like the feedline that the box cuts) and the other components that reach into
  the box (grey, dashed);
* the **ports**: a junction (red), a 50 ohm edge or pad termination (blue), a cut route's stub port (orange, the stub drawn from the
  component's port).

Two uses: the **Simulate dialog** shows the preview of what will be simulated for the chosen analysis (a temporary
overlay, gone when the dialog closes), and the panel's **Sim groups** tab shows a saved group (it stays until hidden and
follows the design: a rebuild draws it again, a design that changed is previewed again).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pya  # type: ignore

from qcc_kplugin import tools
from qcc_kplugin.session import SESSION, clean_env, log

PURPLE, ORANGE = 0x7B2CBF, 0xF9813A
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
STATE: dict = {
    "overlay": None,  # tools._Overlay of the view it was drawn on
    "data": None,  # the preview shown now
    "spec": None,  # its request (names / analysis / ...), to ask again after a design change
    "pinned": None,  # {"spec", "data"} of the saved group the panel shows (what a closed dialog goes back to)
    "temp": False,  # the shown overlay belongs to the Simulate dialog
    "hash": None,  # the sidecar hash the data was made for
    "job": None,  # the running ``qcc sim preview``
    "timer": None,
    "listening": False,
}


# ---- the request --------------------------------------------------------------------------------------------------
def command(spec: dict) -> list[str]:
    """``qcc sim preview`` arguments of ``spec``: ``names`` (instances / routes), ``analysis``, ``default`` / ``whole``
    (no names), ``group`` (a saved group, its own selection), ``margin``."""
    args = ["sim", "preview", str(SESSION.design_path)]
    if spec.get("group"):
        args += ["--group", spec["group"]]
    elif spec.get("whole"):
        args += ["--whole"]
    elif spec.get("names"):
        args += ["--instances", ",".join(spec["names"])]
    else:
        args += ["--default"]
    if spec.get("analysis"):
        args += ["--analysis", spec["analysis"]]
    if spec.get("margin"):
        args += ["--margin", f"{float(spec['margin']):g}"]
    return args


def request(spec: dict, done=None, temp: bool = False) -> bool:
    """Run ``qcc sim preview`` in the background and draw the result. ``done(data, error)`` follows (``error`` is the
    message of a failed preview, then nothing is drawn). ``temp``: the Simulate dialog's overlay (see :func:`end_temp`).
    A request that is still running is dropped. Returns False without a design."""
    if SESSION.design_path is None or SESSION.design_path.suffix != ".json":
        return False
    cancel()
    fd, path = tempfile.mkstemp(prefix="qcc_simview_", suffix=".json")
    os.close(fd)
    out = open(path, "wb")  # noqa: SIM115  (closed right after the start)
    try:
        proc = subprocess.Popen([SESSION.qcc, *command(spec)], stdout=out, stderr=subprocess.STDOUT,  # noqa: S603
                                env=clean_env(), creationflags=_NO_WINDOW)
    finally:
        out.close()
    STATE["job"] = {"proc": proc, "path": Path(path), "spec": dict(spec), "done": done, "temp": temp,
                    "started": time.time()}
    _start_timer()
    return True


def busy() -> bool:
    return STATE["job"] is not None


def cancel() -> None:
    job = STATE["job"]
    STATE["job"] = None
    if job is not None:
        try:
            job["proc"].kill()
        except OSError:
            pass
        _drop(job)


def _drop(job) -> None:
    try:
        job["path"].unlink()
    except OSError:
        pass


def _start_timer() -> None:
    if STATE["timer"] is not None:
        return
    timer = pya.QTimer(pya.Application.instance().main_window())
    timer.interval = 150
    timer.timeout(poll)
    timer.start()
    STATE["timer"] = timer


def poll() -> None:
    """Collect the finished preview (a timer calls this)."""
    job = STATE["job"]
    if job is None or job["proc"].poll() is None:
        return
    STATE["job"] = None
    data, error = None, None
    try:
        text = job["path"].read_text(encoding="utf-8", errors="replace")  # stdout and stderr: warnings come first
        if job["proc"].returncode == 0:
            data = _loads(text)
        else:
            lines = [ln for ln in text.splitlines() if ln.strip()]
            error = next((ln[len("error:"):].strip() for ln in reversed(lines) if ln.startswith("error:")),
                         lines[-1].strip() if lines else "qcc sim preview failed")
    except (OSError, ValueError) as e:
        error = f"qcc sim preview: {e}"
    _drop(job)
    if data is not None:
        STATE["temp"] = job["temp"]
        show(data, job["spec"], pin=not job["temp"])
    elif error:
        log(f"simview: {error}")
        if job["temp"]:
            end_temp()
        else:
            clear()
    if job["done"] is not None:
        try:
            job["done"](data, error)
        except Exception as e:  # noqa: BLE001  (a timer must not raise)
            log(f"simview: callback failed: {e!r}")


def _loads(text: str):
    from qcc_kplugin import qcache  # pylint: disable=import-outside-toplevel

    return qcache.loads_tolerant(text)


# ---- drawing ------------------------------------------------------------------------------------------------------
def summary(group: dict) -> str:
    """One line for a preview box: the group, the box size and what its ports are."""
    x0, y0, x1, y1 = group["box"]
    kinds = [p["kind"] for p in group.get("ports", [])]
    junction = kinds.count("junction")
    stubs = kinds.count("waveguide")
    edge = len(kinds) - junction - stubs
    ports = ", ".join(f"{n} {what}" for n, what in ((junction, "junction"), (edge, "50 ohm"), (stubs, "cut stub"))
                      if n) or "no ports"
    return f"box {x1 - x0:g} x {y1 - y0:g} um · {', '.join(group.get('select') or [])} · {ports}"


def _overlay():
    view, _ = SESSION.find_view()
    if view is None:
        view = pya.LayoutView.current()
    old = STATE["overlay"]
    if old is not None and (view is None or old.view is not view):
        old.clear()
        STATE["overlay"] = old = None
    if view is None:
        return None
    if old is None:
        old = STATE["overlay"] = tools._Overlay(view)  # pylint: disable=protected-access
    return old


def _inside(bbox, box) -> bool:
    return bbox[0] < box[2] and bbox[2] > box[0] and bbox[1] < box[3] and bbox[3] > box[1]


def draw(data: dict | None) -> int:
    """Draw ``data`` (a ``qcc sim preview`` result) on the design's view; returns the number of markers. ``None`` clears."""
    o = _overlay()
    if o is None:
        return 0
    o.clear()
    if not data:
        return 0
    sidecar = SESSION.data or {}
    insts, routes, ports_at = sidecar.get("instances", {}), sidecar.get("routes", {}), sidecar.get("ports", {})
    for group in data.get("groups", []):
        box = group["box"]
        selected = set(group.get("select") or [])
        o.rect(box, PURPLE, style=0, width=2)
        label = f"sim group {group['name']} · {group.get('analysis') or data.get('analysis')}"
        o.text((box[0] + o.px(6), box[3] + o.px(14)), label, PURPLE)
        for name, inst in insts.items():
            bb = inst.get("bbox")
            if not bb or not _inside(bb, box):
                continue
            if name in selected and not group.get("whole"):
                o.rect(bb, tools.GREEN, style=0, width=2)
            else:
                o.rect(bb, tools.GREY, style=2, width=1)
        for name in group.get("routes", []):
            line = (routes.get(name) or {}).get("polyline")
            if line and len(line) > 1:
                if name in selected:
                    o.path([tuple(q) for q in line], color=tools.GREEN, width=3)
                else:
                    o.path([tuple(q) for q in line], color=tools.GREY, width=1)
        for port in group.get("ports", []):
            at = port.get("at")
            if not at:
                continue
            kind = port["kind"]
            if kind == "junction":
                o.box(tuple(at), 7, tools.RED)
                o.text((at[0] + o.px(10), at[1]), f"junction {port['name']}", tools.RED)
            elif kind == "waveguide":  # the cut route's stub: from the component's port to the stub port
                start = (ports_at.get(port["name"]) or {}).get("pos")
                if start:
                    o.path([tuple(start), tuple(at)], color=ORANGE, width=3)
                o.box(tuple(at), 7, ORANGE)
                o.text((at[0] + o.px(10), at[1]), f"cut stub port {port['name']}", ORANGE)
            else:  # 50 ohm edge port at the box, or a pad termination
                o.box(tuple(at), 7, tools.BLUE)
                if port.get("ground"):
                    o.path([tuple(at), tuple(port["ground"])], color=tools.BLUE, width=2)
                o.text((at[0] + o.px(10), at[1]), f"50 ohm {port['name']}", tools.BLUE)
    return len(o.markers)


def show(data: dict, spec: dict | None = None, pin: bool = False) -> None:
    STATE.update(data=data, spec=spec, hash=(SESSION.data or {}).get("hash"))
    if pin:
        STATE["pinned"] = {"spec": spec, "data": data}
    _listen()
    draw(data)


def clear(unpin: bool = True) -> None:
    """Remove the overlay (and forget the saved group the panel was showing)."""
    cancel()
    STATE.update(data=None, spec=None, temp=False)
    if unpin:
        STATE["pinned"] = None
    draw(None)


def end_temp() -> None:
    """The Simulate dialog closed: back to the saved group the panel shows, or nothing."""
    cancel()
    STATE["temp"] = False
    pinned = STATE["pinned"]
    if pinned:
        STATE.update(data=pinned["data"], spec=pinned["spec"])
        draw(pinned["data"])
    else:
        clear()


def _listen() -> None:
    if not STATE["listening"]:
        SESSION.listeners.append(_on_session)
        STATE["listening"] = True


def _on_session() -> None:
    """After each rebuild: draw again (the layout reloaded); a design that changed is previewed again."""
    data = STATE["data"]
    if not data or STATE["job"] is not None:
        return
    if (SESSION.data or {}).get("hash") != STATE["hash"] and STATE["spec"]:
        request(STATE["spec"], temp=STATE["temp"])
    else:
        draw(data)
