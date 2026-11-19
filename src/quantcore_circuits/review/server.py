"""Live dashboard backend: serves the React app (``reviewer/`` → ``review/static``) and the run state.

API (contract: ``reviewer/contract/state.ts``):

- ``GET  /api/state``   — ``build/<design>/state.json`` (a fresh state is created from the design if missing)
- ``GET  /api/events``  — Server-Sent Events: ``event: state`` whenever ``state.json`` changes, a ping every 15 s
- ``GET  /files/<p>``   — files inside the run directory (screenshots under ``shots/``)
- ``POST /api/rebuild`` — rebuild the layout, write the OAS (+ klive if KLayout is open), headless screenshot, update
  the *Layout* step

Standard library only; binds to localhost.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

STATIC = Path(__file__).parent / "static"


def rebuild_layout(run, design_source) -> dict:
    """Build → OAS (+ sidecar) → klive (if available) → headless KLayout screenshot → state."""
    from quantcore_circuits.assembly import build, write_layout  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.live import klive_available, send_to_klive  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.live.snapshot import snapshot  # pylint: disable=import-outside-toplevel

    run.start("layout")
    t0 = time.perf_counter()
    try:
        result = build(design_source)
    except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
        run.fail("layout", f"{type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    out = Path("build") / f"{result.design.name}.oas"
    write_layout(result, out)
    if klive_available():
        send_to_klive(out)
    png = snapshot(out, run.dir / "shots" / "chip.png", size=(1400, 1400))
    run.screenshot(png, "Chip", "layout", "Full chip (headless KLayout render)", "headless", "chip")
    lengths = ", ".join(f"{n} {v:.1f} µm" for n, v in result.route_lengths().items())
    run.done("layout", f"built in {time.perf_counter() - t0:.2f} s · {lengths}", hash=result.hash)
    return {"ok": True}


def waiting_state(root: Path) -> dict:
    """What the dashboard shows before any run exists (follow mode): an empty state that says what to do."""
    from quantcore_circuits.track import Run  # pylint: disable=import-outside-toplevel

    st = Run._empty()  # noqa: SLF001
    st["design"] = {
        "name": "waiting for a run",
        "path": "",
        "hash": "",
        "pdk": "",
        "stack": {"substrate": "", "epsR": 0, "thickness_um": 0},
        "chipBox": [0, 0, 1000, 1000],
        "instances": 0,
        "routes": 0,
    }
    st["log"] = [
        {
            "t": st["updated"],
            "level": "info",
            "msg": f"No run under {root}/ yet. In the notebook: from quantcore_circuits import track; "
            "track.start('name')  (or set QCC_TRACK=1)",
        }
    ]
    return st


def live_run_dir(root: Path, run: str | None = None) -> Path | None:
    """The run directory to show: ``root/<run>`` if named, else the one ``root/_live.json`` points at (the run that
    saw the latest tracked event), else the most recently updated ``root/*/state.json``."""
    if run:
        return root / run
    try:
        ptr = json.loads((root / "_live.json").read_text(encoding="utf-8"))
        d = root / ptr["run"]
        if (d / "state.json").exists():
            return d
    except (OSError, ValueError, KeyError):
        pass
    states = sorted(root.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return states[0].parent if states else None


def make_handler(run_dir, design_source, root: Path | None = None):
    """``run_dir``: a Path (one run) or a callable returning the current run directory (or None): follow mode."""
    from quantcore_circuits.track import Run  # pylint: disable=import-outside-toplevel

    lock = threading.Lock()
    follow = callable(run_dir)

    def cur_dir() -> Path | None:
        return run_dir() if follow else run_dir

    def cur_state() -> Path | None:
        d = cur_dir()
        return d / "state.json" if d is not None else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code=200):
            self._send(json.dumps(data).encode("utf-8"), "application/json; charset=utf-8", code)

        def _file(self, path: Path):
            if not path.is_file():
                return self._send(b"not found", "text/plain", 404)
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return self._send(path.read_bytes(), ctype)

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last, last_ping = None, time.time()
            try:
                while True:
                    sp = cur_state()
                    m = (str(sp), sp.stat().st_mtime) if sp is not None and sp.exists() else None
                    if m != last:
                        last = m
                        self.wfile.write(f"event: state\ndata: {json.dumps({'updated': m})}\n\n".encode())
                        self.wfile.flush()
                    elif time.time() - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = time.time()
                    time.sleep(0.3)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def do_GET(self):  # noqa: N802
            path = unquote(urlparse(self.path).path)
            if path == "/api/state":
                sp = cur_state()
                if sp is None or (not sp.exists() and design_source is None):
                    return self._json(waiting_state(root or Path("build")))
                if not sp.exists():
                    with lock:
                        Run(design_source, cur_dir())
                return self._send(sp.read_bytes(), "application/json; charset=utf-8")
            if path == "/api/events":
                return self._events()
            if path.startswith("/files/"):
                base = cur_dir()
                if base is None:
                    return self._send(b"not found", "text/plain", 404)
                target = (base / path[len("/files/") :]).resolve()
                if base.resolve() not in target.parents:
                    return self._send(b"forbidden", "text/plain", 403)
                return self._file(target)
            rel = path.lstrip("/") or "index.html"
            target = (STATIC / rel).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                target = STATIC / "index.html"
            return self._file(target)

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path == "/api/rebuild":
                src, d = design_source, cur_dir()
                if follow:  # the design file of the run being shown
                    sp = cur_state()
                    path = json.loads(sp.read_text(encoding="utf-8")).get("design", {}).get("path") if sp else None
                    src = path if path and Path(path).exists() else None
                if src is None or d is None:
                    return self._json({"ok": False, "error": "this run has no design file to rebuild"})
                with lock:
                    return self._json(rebuild_layout(Run(src, d), src))
            return self._json({"ok": False, "error": "unknown endpoint"}, 404)

    return Handler


def serve(
    design, port: int = 8765, open_browser: bool = True, run_dir: str | Path | None = None, background: bool = False
):
    """Serve the dashboard for ``design`` on http://127.0.0.1:``port``. ``background=True`` returns the server
    (running in a daemon thread) instead of blocking, for use from Jupyter."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.track import run_dir_for  # pylint: disable=import-outside-toplevel

    name = load_design(design).name
    run_dir = Path(run_dir) if run_dir else run_dir_for(name)
    run_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(run_dir, design))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"qcc dashboard: {url}  (design {name}, run dir {run_dir})")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    if background:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return None


def serve_live(
    root: str | Path | None = None,
    run: str | None = None,
    port: int = 8765,
    open_browser: bool = True,
    background: bool = False,
):
    """Serve the dashboard in follow mode: it shows the run named ``run``, or (default) whichever run saw the latest
    tracked event (``<root>/_live.json``, written by :func:`quantcore_circuits.track.start`), switching by itself
    when a notebook moves on to another design. Same API as :func:`serve`."""
    from quantcore_circuits.track import default_root  # pylint: disable=import-outside-toplevel

    root = Path(root) if root is not None else default_root()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(lambda: live_run_dir(root, run), None, root))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"qcc dashboard: {url}  (following {'run ' + run if run else 'the latest run'} under {root}/)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    if background:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return None
