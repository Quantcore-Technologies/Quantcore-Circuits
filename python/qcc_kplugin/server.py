"""Command server on localhost:8083 so notebooks / ``qcc`` can ask the GUI for things klive cannot do.

One JSON object per line, one JSON reply per request (same framing as klive on 8082):

* ``{"cmd": "screenshot", "path": "...png", "width": 1600, "height": 1200, "box": [x0, y0, x1, y1]?,
  "layout": "...oas"?}`` — save the current view (or ``box``, µm) as PNG with the GUI's own layer colours; with
  ``layout`` that file is first opened (or reloaded if already open); ``lyp`` (layer properties file) and ``hide``
  (layer-name fragments) restyle the view first → ``{"ok": true, "path": ...}``
* ``{"cmd": "status"}`` → ``{"ok": true, "design": ..., "layout": ..., "watching": bool, "klayout": version}``
* ``{"cmd": "open", "design": "path/design.json"}`` → open the design in the session (build + load)
"""

from __future__ import annotations

import json

import pya  # type: ignore

from qcc_kplugin.session import SESSION

PORT = 8083


def _show_layout(path: str):
    from pathlib import Path  # pylint: disable=import-outside-toplevel

    target = Path(path).resolve()
    window = pya.MainWindow.instance()
    for i in range(window.views()):
        view = window.view(i)
        for j in range(view.cellviews()):
            fn = view.cellview(j).filename()
            if fn and Path(fn).resolve() == target:
                window.current_view_index = i
                view.reload_layout(j)
                return view
    window.load_layout(str(target), 1)
    view = pya.LayoutView.current()
    view.max_hier()
    view.zoom_fit()
    return view


def _style(view, lyp: str | None, hide: list[str]) -> None:
    """Layer properties file (e.g. KQC's ``default_layer_props.lyp``) and hidden helper layers, as in the headless
    renders, so GUI and headless screenshots look alike."""
    if lyp:
        view.load_layer_props(lyp, True)
        view.add_missing_layers()
    hidden = [h.replace("_", " ").lower() for h in hide]
    it = view.begin_layers()
    while not it.at_end():
        node = it.current()
        label = f"{node.name} {node.source}".replace("_", " ").lower()
        if any(h in label for h in hidden):
            node.visible = False
        it.next()


def _screenshot(req: dict) -> dict:
    view = _show_layout(req["layout"]) if req.get("layout") else pya.LayoutView.current()
    if view is None:
        return {"ok": False, "error": "no layout view open"}
    if req.get("lyp") or req.get("hide"):
        _style(view, req.get("lyp"), req.get("hide", []))
    box = req.get("box")
    if box:
        view.zoom_box(pya.DBox(*box))
    elif req.get("fit", True):
        view.zoom_fit()
    w, h = int(req.get("width", 1600)), int(req.get("height", 1200))
    view.save_image_with_options(req["path"], w, h, 0, int(req.get("oversampling", 2)), 0, pya.DBox(), False)
    return {"ok": True, "path": req["path"]}


def handle(req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "screenshot":
        return _screenshot(req)
    if cmd == "status":
        return {
            "ok": True,
            "design": str(SESSION.design_path) if SESSION.design_path else None,
            "layout": str(SESSION.layout_path) if SESSION.layout_path else None,
            "watching": SESSION.watching(),
            "klayout": pya.__version__,
        }
    if cmd == "open":
        SESSION.open(req["design"])
        SESSION._reload_after = 0.0  # pylint: disable=protected-access  (load as soon as the layout exists)
        SESSION._build()  # pylint: disable=protected-access
        return {"ok": True}
    return {"ok": False, "error": f"unknown command {cmd!r}"}


class CommandServer(pya.QTcpServer):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.listen(pya.QHostAddress.new_special(pya.QHostAddress.LocalHost), PORT)
        self.newConnection(self._on_connection)
        print(f"[qcc] command server {'listening on' if self.isListening() else 'FAILED to listen on'} :{PORT}")

    def _on_connection(self):
        conn = self.nextPendingConnection()
        try:
            while conn.isOpen() and conn.state() == pya.QTcpSocket.ConnectedState:
                if conn.canReadLine():
                    line = conn.readLine()
                    try:
                        reply = handle(json.loads(line))
                    except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
                        reply = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                    conn.write((json.dumps(reply) + "\n").encode("utf-8"))
                    conn.flush()
                    break
                conn.waitForReadyRead(200)
        finally:
            conn.disconnectFromHost()


SERVER = []


def start_server():
    if not SERVER:
        SERVER.append(CommandServer(pya.Application.instance().main_window()))
