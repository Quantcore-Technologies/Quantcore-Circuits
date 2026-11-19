"""Live dashboard (React app in ``reviewer/``, served by :mod:`.server`).

From a notebook::

    dash = qcc.review.connect("examples/q1_r1_feedline.json")   # starts the server (background) + opens the browser
    ...                                                          # every Run/loop step updates it live
    dash.disconnect()                                            # stops the server
"""

from __future__ import annotations

import webbrowser


class Dashboard:
    """Handle on a dashboard server running in this process (see :func:`connect`)."""

    def __init__(self, design, port: int = 8765, run_dir=None):
        self.design, self.port, self.run_dir = design, port, run_dir
        self.server = None
        self.external = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def running(self) -> bool:
        return self.server is not None or self.external

    def connect(self, open_browser: bool = True) -> Dashboard:
        from quantcore_circuits.review.server import serve  # pylint: disable=import-outside-toplevel

        if self.running:
            return self
        try:
            self.server = serve(self.design, port=self.port, open_browser=False, run_dir=self.run_dir, background=True)
        except OSError:
            self.external = True  # something (e.g. `qcc review` in a terminal) already serves this port
        if open_browser:
            webbrowser.open(self.url)
        return self

    def disconnect(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        self.server = None
        self.external = False

    def __repr__(self) -> str:
        state = "external" if self.external else ("running" if self.server else "stopped")
        return f"<Dashboard {self.url} {state}>"


def connect(design, port: int = 8765, open_browser: bool = True, run_dir=None) -> Dashboard:
    return Dashboard(design, port, run_dir).connect(open_browser)
