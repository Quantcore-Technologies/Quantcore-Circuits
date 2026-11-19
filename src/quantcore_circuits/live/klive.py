"""Minimal klive client: ask a running KLayout (with the klive Salt package) to open or reload a layout file.

Protocol (verified against klive 0.4.x ``klayout/python/klive_server.py``): TCP on localhost:8082, one JSON object
terminated by a newline. Keys: ``gds`` (absolute path, required), ``keep_position`` (bool; must always be present),
optional ``technology``, ``lyrdb``, ``l2n``, ``markers``. The server replies with a JSON object containing ``type``
(``"open"``/``"reload"``), ``file``, ``version`` and ``klayout_version``.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

KLIVE_PORT = 8082


class KliveUnavailable(ConnectionError):
    """KLayout is not running, or the klive server is not started."""


def send_to_klive(
    path: str | Path,
    keep_position: bool = True,
    lyrdb: str | Path | None = None,
    technology: str | None = None,
    port: int = KLIVE_PORT,
    timeout: float = 2.0,
) -> dict:
    """Open/reload ``path`` in KLayout. Returns the server reply (empty dict if it sent none)."""
    msg = {"gds": str(Path(path).resolve()), "keep_position": bool(keep_position)}
    if lyrdb is not None:
        msg["lyrdb"] = str(Path(lyrdb).resolve())
    if technology is not None:
        msg["technology"] = technology
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            sock.settimeout(timeout)
            try:
                reply = sock.recv(4096)
            except TimeoutError:
                reply = b""
    except OSError as e:
        raise KliveUnavailable(
            f"cannot reach klive on localhost:{port} ({e}). Start KLayout and enable klive (Salt package 'klive')."
        ) from e
    if not reply:
        return {}
    try:
        return json.loads(reply.decode("utf-8"))
    except json.JSONDecodeError:
        return {"raw": reply.decode("utf-8", "replace")}


def klive_available(port: int = KLIVE_PORT, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False
