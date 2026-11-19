"""A ``qcc sim auto`` run that outlives KLayout (plain Python, no pya: unit-tested outside KLayout).

Simulate starts the run *detached* (own process group, no console window, breaking away from a job object that would
end it with KLayout), with its output in ``<design>.flow/sim_run.log``. ``<design>.flow/sim_run.json`` is the run record:
pid, start time, arguments, the log and the status file ``qcc`` writes, and the state. When the design is opened again
(or KLayout restarts with it) :func:`flow.resume_runs` reads the record: a run that ended meanwhile is imported (its
results are already in the design's run state; ``qcc`` also saved them as ``build/<name>/<name>_<group>_results.json``),
a run still going is watched and imported when it ends.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

RECORD = "sim_run.json"
LOG = "sim_run.log"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
STILL_ACTIVE = 259


def record_path(flow_dir) -> Path:
    return Path(flow_dir) / RECORD


def read_record(flow_dir) -> dict | None:
    try:
        rec = json.loads(record_path(flow_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def write_record(flow_dir, rec: dict) -> None:
    path = record_path(flow_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def launch(cmd, cwd, env, log_path) -> subprocess.Popen:
    """Start ``cmd`` detached from this process: it keeps running when KLayout quits. Output goes to ``log_path``."""
    out = open(log_path, "wb")  # noqa: SIM115  (closed below)
    try:
        kw: dict = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": env, "cwd": cwd}
        if os.name == "nt":
            flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
            try:  # leave the job object KLayout may run in (it would end the run with KLayout) when it allows that
                return subprocess.Popen(cmd, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **kw)  # noqa: S603
            except OSError:
                return subprocess.Popen(cmd, creationflags=flags, **kw)  # noqa: S603
        return subprocess.Popen(cmd, start_new_session=True, **kw)  # noqa: S603
    finally:
        out.close()


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes  # pylint: disable=import-outside-toplevel

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == STILL_ACTIVE
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _status(rec: dict) -> dict:
    try:
        return json.loads(Path(rec["status"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _log_tail(rec: dict) -> str:
    try:
        return Path(rec["log"]).read_text(encoding="utf-8", errors="replace")[-4000:]
    except (OSError, KeyError, TypeError):
        return ""


def outcome(rec: dict) -> str:
    """``running`` while the process lives, else ``done`` / ``failed`` / ``cancelled`` from what ``qcc`` wrote (its status
    file, else the log's "done in" line); a process that vanished without either is ``failed``."""
    if pid_alive(rec.get("pid", 0)):
        return "running"
    state = _status(rec).get("state")
    if state in ("done", "failed", "cancelled"):
        return state
    return "done" if any(ln.startswith("done in") for ln in _log_tail(rec).splitlines()) else "failed"


class PidProc:
    """The ``Popen`` look-alike of a run this KLayout did not start (``poll`` / ``pid`` / ``terminate``)."""

    def __init__(self, rec: dict):
        self.rec = rec
        self.pid = int(rec.get("pid", 0))
        self.returncode = None

    def poll(self):
        if self.returncode is None and outcome(self.rec) != "running":
            self.returncode = 0 if outcome(self.rec) == "done" else 1
        return self.returncode

    def terminate(self):
        if os.name != "nt":
            try:
                os.kill(self.pid, 15)
            except OSError:
                pass

    def wait(self, timeout=None):  # noqa: ARG002
        end = time.time() + (timeout or 0)
        while self.poll() is None and time.time() < end:
            time.sleep(0.1)
        return self.returncode
