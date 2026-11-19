"""Cache and background loading of the slow ``qcc components …`` queries (list, parameters, outline).

Each call starts Python and imports the library (~1.4 s). Called synchronously from the panel that froze KLayout, so:

* results are cached in memory and in one JSON file in the temp folder (so the next KLayout start is instant too);
* the cache is valid for one *library key*: the ``qcc`` path and time, and the newest modification time under
  ``src/quantcore_circuits/layouts`` when the plugin runs from the repository. A library change refreshes everything;
* :func:`fetch` runs a query in a subprocess polled from a timer and calls ``done(data)`` when it is there, at once
  when the result is cached. ``data`` is ``None`` when ``qcc`` failed.

Names used by the panel: ``list:<source>``, ``schema:<cell>``, ``outline:<cell>:<params JSON>``, plus the bulk
``schemas:quantcore`` that fills every ``schema:<cell>`` in one call (prefetch).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CACHE_FILE = Path(tempfile.gettempdir()) / "qcc_kplugin_cache.json"
LAYOUTS = Path(__file__).resolve().parents[3] / "src" / "quantcore_circuits" / "layouts"
_MEM: dict = {}
_STATE = {"key": None, "key_at": 0.0, "loaded": False}
PENDING: dict[str, dict] = {}  # name → {"proc", "path", "callbacks", "started", "bulk"}
_TIMER: list = []


def _qcc() -> str:
    from qcc_kplugin.session import SESSION  # pylint: disable=import-outside-toplevel

    return SESSION.qcc


def library_key() -> str:
    """qcc path + its mtime + newest mtime of the library sources (re-evaluated at most every 2 s)."""
    now = time.time()
    if _STATE["key"] is not None and now - _STATE["key_at"] < 2.0:
        return _STATE["key"]
    qcc = _qcc()
    parts = [qcc]
    try:
        parts.append(str(os.stat(qcc).st_mtime_ns))
    except OSError:
        pass
    newest = 0
    try:
        for dirpath, _dirs, files in os.walk(LAYOUTS):
            for f in files:
                if f.endswith(".py"):
                    newest = max(newest, os.stat(os.path.join(dirpath, f)).st_mtime_ns)
    except OSError:
        pass
    parts.append(str(newest))
    _STATE["key"], _STATE["key_at"] = "|".join(parts), now
    return _STATE["key"]


def _load() -> None:
    """Read the disk cache once; a file from another library key is dropped."""
    key = library_key()
    if _MEM.get("__key__") not in (None, key):
        _MEM.clear()
        _STATE["loaded"] = False
    if _STATE["loaded"]:
        return
    _STATE["loaded"] = True
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if data.get("key") == key:
            _MEM.update(data.get("items", {}))
    except (OSError, ValueError):
        pass
    _MEM["__key__"] = key


def _save() -> None:
    try:
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": library_key(), "items": {k: v for k, v in _MEM.items() if k != "__key__"}}),
                       encoding="utf-8")
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


def get(name: str):
    """The cached value of ``name`` (None when absent or from another library version)."""
    _load()
    return _MEM.get(name)


def put(name: str, value, save: bool = True) -> None:
    _load()
    _MEM[name] = value
    if save:
        _save()


def clear() -> None:
    """Forget everything (the panel's Refresh list)."""
    _MEM.clear()
    _STATE.update({"key": None, "loaded": True})
    _MEM["__key__"] = library_key()
    try:
        CACHE_FILE.unlink()
    except OSError:
        pass


def _store_bulk(data) -> None:
    for cell, rec in (data or {}).items():
        if isinstance(rec, dict) and isinstance(rec.get("schema"), list):
            _MEM[f"schema:{cell}"] = rec["schema"]


def fetch(name: str, args: list[str], done=None, bulk: bool = False) -> None:
    """``done(data)`` with the JSON of ``qcc *args`` — at once when ``name`` is cached, else after the background run."""
    cached = None if bulk else get(name)
    if cached is not None:
        if done is not None:
            done(cached)
        return
    if name in PENDING:
        if done is not None:
            PENDING[name]["callbacks"].append(done)
        return
    fd, path = tempfile.mkstemp(prefix="qcc_cache_", suffix=".json")
    os.close(fd)
    out = open(path, "wb")  # noqa: SIM115  (closed right after the start)
    try:
        proc = subprocess.Popen([_qcc(), *args], stdout=out, stderr=subprocess.DEVNULL,  # noqa: S603
                                env=_env(), creationflags=_NO_WINDOW)
    finally:
        out.close()
    PENDING[name] = {"proc": proc, "path": Path(path), "callbacks": [done] if done is not None else [],
                     "started": time.time(), "bulk": bulk}
    _start_timer()


def _env() -> dict:
    from qcc_kplugin.session import clean_env  # pylint: disable=import-outside-toplevel

    return clean_env()


def _start_timer() -> None:
    if _TIMER:
        return
    try:
        import pya  # type: ignore  # pylint: disable=import-outside-toplevel

        timer = pya.QTimer(pya.Application.instance().main_window())
    except Exception:  # noqa: BLE001  (no GUI: tests call poll() themselves)
        return
    timer.interval = 120
    timer.timeout(poll)
    timer.start()
    _TIMER.append(timer)


def loads_tolerant(text: str):
    """``json.loads`` for what a ``qcc`` call printed. Some Quantum Metal calls print a warning line on stdout before the
    JSON (``FutureWarning: ...``): then the JSON is the last line that starts with ``{`` or ``[``."""
    try:
        return json.loads(text)
    except ValueError:
        for line in reversed(text.strip().splitlines()):
            if line[:1] in "{[":
                return json.loads(line)
        raise


def poll() -> bool:
    """Collect the finished queries and call their callbacks; True while something still runs."""
    for name in list(PENDING):
        job = PENDING[name]
        if job["proc"].poll() is None:
            continue
        del PENDING[name]
        data = None
        try:
            if job["proc"].returncode == 0:
                data = loads_tolerant(job["path"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        try:
            job["path"].unlink()
        except OSError:
            pass
        if data is not None:
            if job["bulk"]:
                _store_bulk(data)
                put(name, True)
            else:
                put(name, data)
        for cb in job["callbacks"]:
            try:
                cb(data)
            except Exception:  # noqa: BLE001  (a timer must not raise)
                import traceback  # pylint: disable=import-outside-toplevel

                from qcc_kplugin.session import log  # pylint: disable=import-outside-toplevel

                log(f"ERROR in a cache callback ({name})\n{traceback.format_exc()}")
    return bool(PENDING)


def wait(timeout: float = 60.0) -> None:
    """Block until nothing is pending (tests only)."""
    end = time.time() + timeout
    while poll() and time.time() < end:
        time.sleep(0.02)


def schema_key(cell: str) -> str:
    return f"schema:{cell}"


def outline_key(cell: str, params_json: str) -> str:
    return f"outline:{cell}:{params_json}"
