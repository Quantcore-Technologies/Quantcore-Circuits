"""Where a qcc AEDT script runs: a new batch process, a new AEDT window, or an AEDT session that is already open.

``aedt=`` (``hfss.render`` / ``hfss.solve_job`` / ``runner.run_job``, the tutorials' ``AEDT_MODE``; default from
``QCC_AEDT_MODE``, else ``"batch"``):

* ``"batch"`` — a new non-graphical AEDT (``ansysedt -ng -RunScriptAndExit``), as before. Nothing to look at, but the
  progress lines (pass, mesh, ΔF / ΔS / ΔC) are printed every ~30 s.
* ``"gui"`` — a new AEDT **window** (``ansysedt -RunScript``, no ``-ng``): you watch the import, the mesh, the
  convergence plots and the results in it, and it stays open after the run (the project is saved). It is started
  detached, so it survives a kernel restart.
* ``"attach"`` — run inside an AEDT 2024 R1+ window that is already open (the newest one, or ``aedt_pid=`` /
  ``QCC_AEDT_PID``); if none is open, as ``"gui"``. The connection uses AEDT's own gRPC client
  (``<AEDT>/PythonFiles/DesktopPlugin/PyDesktopPlugin.py``, shipped with AEDT 2024 R1; no extra Python package) in a
  small helper process, which calls ``oDesktop.RunScriptWithArguments(qcc_solve.py, <sim>.json)`` and then only
  releases the connection: the session, and every project in it (also the new one), stay open. The qcc script never
  quits AEDT, and KQC's ``run_pyepr_t1_estimate.py`` (which does) is never run.

Rules: on a timeout only processes qcc started are killed (the batch AEDT, the ``gui`` window qcc opened, or the
attach helper — never an attached session; its solve then keeps running there). A project of the same job left open
by an earlier attached run is closed in that session before the new run (it would block the save).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from quantcore_circuits.sim_tools.ansys import MIN_VERSION, aedt_version

AEDT_MODES = ("batch", "gui", "attach")
ENV_MODE = "QCC_AEDT_MODE"
ENV_PID = "QCC_AEDT_PID"
ENV_PROGRESS = "QCC_AEDT_PROGRESS"
ATTACH_HELPER = Path(__file__).with_name("aedt_attach.py")
GRPC_PORTS = range(50051, 50101)  # where AEDT's gRPC server listens unless ``-grpcsrv`` says otherwise (as pyaedt)
_ALIASES = {"ng": "batch", "non-graphical": "batch", "nongraphical": "batch", "window": "gui", "new": "gui",
            "graphical": "gui", "connect": "attach", "running": "attach"}

__all__ = [
    "AEDT_MODES",
    "AedtSession",
    "find_sessions",
    "launch_gui",
    "pick_session",
    "progress_interval",
    "resolve_mode",
]


def resolve_mode(aedt: str | None = None, graphical: bool = False) -> str:
    """``aedt`` → one of :data:`AEDT_MODES`; None → ``graphical=True`` means ``"gui"``, else ``QCC_AEDT_MODE``, else
    ``"batch"``."""
    if aedt is None:
        aedt = "gui" if graphical else (os.environ.get(ENV_MODE) or "batch")
    mode = _ALIASES.get(str(aedt).strip().lower(), str(aedt).strip().lower())
    if mode not in AEDT_MODES:
        raise ValueError(f"aedt={aedt!r}: use one of {AEDT_MODES}")
    return mode


def progress_interval(progress: float | None = None) -> float | None:
    """Seconds between progress lines (``progress``, else ``QCC_AEDT_PROGRESS``, else 30); 0 / negative → None."""
    if progress is None:
        try:
            progress = float(os.environ.get(ENV_PROGRESS, "30"))
        except ValueError:
            progress = 30.0
    return float(progress) if progress and progress > 0 else None


# ---- running sessions ---------------------------------------------------------------------------------------------
@dataclass
class AedtSession:
    pid: int
    exe: Path | None
    cmdline: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    created: float | None = None

    @property
    def version(self) -> int | None:
        return aedt_version(self.exe or (self.cmdline[0] if self.cmdline else ""))

    @property
    def graphical(self) -> bool:
        return "-ng" not in [a.lower() for a in self.cmdline]

    @property
    def port(self) -> int | None:
        """The gRPC port: ``-grpcsrv [host:]port`` on the command line, else a listening port in 50051–50100."""
        args = [a.lower() for a in self.cmdline]
        if "-grpcsrv" in args and args.index("-grpcsrv") + 1 < len(args):
            try:
                return int(self.cmdline[args.index("-grpcsrv") + 1].rsplit(":", 1)[-1])
            except ValueError:
                pass
        grpc = sorted(p for p in self.ports if p in GRPC_PORTS)
        return grpc[0] if grpc else None

    @property
    def plugin_dir(self) -> Path | None:
        exe = self.exe or (Path(self.cmdline[0]) if self.cmdline else None)
        return Path(exe).parent / "PythonFiles" / "DesktopPlugin" if exe else None

    def describe(self) -> str:
        v = self.version
        name = f"20{v // 10} R{v % 10}" if v else "?"
        return f"AEDT {name} pid {self.pid} (gRPC port {self.port})"


def parse_netstat(text: str) -> dict[int, list[int]]:
    """``netstat -ano`` (Windows) → {pid: [listening TCP ports]}."""
    out: dict[int, list[int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            try:
                port, pid = int(parts[1].rsplit(":", 1)[1]), int(parts[4])
            except (ValueError, IndexError):
                continue
            out.setdefault(pid, [])
            if port not in out[pid]:
                out[pid].append(port)
    return out


def _processes() -> list[dict]:
    """``ansysedt`` processes: {pid, exe, cmdline, created}. psutil if installed, else CIM (Windows) / ps (POSIX)."""
    try:
        import psutil  # pylint: disable=import-outside-toplevel
    except ImportError:
        psutil = None
    out = []
    if psutil is not None:
        for p in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
            if (p.info.get("name") or "").lower() in ("ansysedt.exe", "ansysedt"):
                out.append({"pid": p.info["pid"], "exe": p.info.get("exe"), "cmdline": p.info.get("cmdline") or [],
                            "created": p.info.get("create_time")})
        return out
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='ansysedt.exe'\" | Select-Object ProcessId,"
              "ExecutablePath,CommandLine,@{n='Created';e={[double]($_.CreationDate.ToUniversalTime() - "
              "[datetime]'1970-01-01').TotalSeconds}} | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=False)
        try:
            rows = json.loads(r.stdout or "[]")
        except ValueError:
            rows = []
        for row in [rows] if isinstance(rows, dict) else rows:
            out.append({"pid": row["ProcessId"], "exe": row.get("ExecutablePath"),
                        "cmdline": _split_cmdline(row.get("CommandLine") or ""), "created": row.get("Created")})
        return out
    r = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, check=False)
    for line in r.stdout.splitlines():
        pid, _, args = line.strip().partition(" ")
        if "ansysedt" in args.split(" ", 1)[0]:
            out.append({"pid": int(pid), "exe": args.split(" ", 1)[0], "cmdline": args.split(), "created": None})
    return out


def _split_cmdline(cmd: str) -> list[str]:
    return [a.strip('"') for a in re.findall(r'"[^"]*"|\S+', cmd)]


def _listening_ports() -> dict[int, list[int]]:
    try:
        import psutil  # pylint: disable=import-outside-toplevel

        out: dict[int, list[int]] = {}
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.pid and c.laddr.port not in out.get(c.pid, []):
                out.setdefault(c.pid, []).append(c.laddr.port)  # IPv4 + IPv6 listeners: once
        return out
    except (ImportError, OSError, RuntimeError):
        pass
    if os.name == "nt":
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, check=False)
        return parse_netstat(r.stdout)
    return {}


def find_sessions(min_version: int = MIN_VERSION) -> list[AedtSession]:
    """AEDT processes of version ≥ ``min_version`` (batch ones too; see :attr:`AedtSession.graphical`), newest first."""
    procs = _processes()
    ports = _listening_ports() if procs else {}
    out = []
    for p in procs:
        s = AedtSession(p["pid"], Path(p["exe"]) if p.get("exe") else None, list(p["cmdline"]),
                        sorted(ports.get(p["pid"], [])), p.get("created"))
        if s.version is None or s.version >= min_version:
            out.append(s)
    return sorted(out, key=lambda s: -(s.created or 0))


def pick_session(sessions: list[AedtSession], pid: int | None = None) -> AedtSession | None:
    """The session to attach to: ``pid`` (or ``QCC_AEDT_PID``) if given, else the newest graphical session with a
    gRPC port. Batch (``-ng``) processes are never picked: they belong to someone's running job."""
    pid = pid or (int(os.environ[ENV_PID]) if os.environ.get(ENV_PID, "").isdigit() else None)
    usable = [s for s in sessions if s.graphical and s.port]
    if pid is not None:
        hit = [s for s in sessions if s.pid == pid]
        if not hit:
            raise LookupError(f"no AEDT process with pid {pid} (running: {[s.pid for s in sessions]})")
        if hit[0] not in usable:
            raise LookupError(f"AEDT pid {pid} cannot be attached to (batch -ng process, or no gRPC port)")
        return hit[0]
    return usable[0] if usable else None


# ---- processes qcc starts -----------------------------------------------------------------------------------------
def gui_command(executable: Path, script: str, sim_json: str) -> list[str]:
    """A new AEDT window that runs ``scripts/<script>`` and stays open (no ``-ng``, ``-RunScript``, not ...AndExit)."""
    return [str(executable), "-RunScript", f"scripts/{script}", "-ScriptArgs", sim_json]


def spawn_detached(args: list[str], cwd: Path, log: Path | None = None) -> subprocess.Popen:
    """Start a GUI process that outlives this one (also a Jupyter kernel restart, which on Windows kills the kernel's
    process tree by parent PID): ``cmd /c start`` leaves no parent link. POSIX: a new session."""
    if os.name != "nt":
        out = log.open("w", encoding="utf-8") if log else subprocess.DEVNULL
        return subprocess.Popen(args, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,  # noqa: S603
                                start_new_session=True, close_fds=True)
    detached, new_group = 0x00000008, 0x00000200
    return subprocess.Popen(["cmd", "/c", "start", "", "/D", str(cwd), *args], cwd=cwd,  # noqa: S603
                            close_fds=True, creationflags=detached | new_group)


def launch_gui(executable: Path, job_dir: Path, script: str, sim_json: str, wait: float = 60.0,
               log: Path | None = None) -> int | None:
    """Open a new AEDT window running ``script`` on ``job_dir``; returns its pid (found by its command line)."""
    before = {s.pid for s in find_sessions(0)}
    t0 = time.time()
    proc = spawn_detached(gui_command(executable, script, sim_json), job_dir, log)
    if os.name != "nt":
        return proc.pid
    while time.time() - t0 < wait:
        for s in find_sessions(0):
            if s.pid not in before and sim_json in s.cmdline and f"scripts/{script}" in s.cmdline:
                return s.pid
        time.sleep(1.0)
    return None


def attach_command(session: AedtSession, script: Path, script_arg: str, project: str) -> list[str]:
    """The helper process (:mod:`.aedt_attach`, standard library only) that runs ``script`` inside ``session``."""
    return [sys.executable, "-I", str(ATTACH_HELPER), "attach", "--port", str(session.port), "--pid",
            str(session.pid), "--plugin", str(session.plugin_dir), "--script", str(script), "--arg", script_arg,
            "--project", project]


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil  # pylint: disable=import-outside-toplevel

        return psutil.pid_exists(pid) and psutil.Process(pid).status() != "zombie"
    except ImportError:
        pass
    except Exception:  # noqa: BLE001  (gone between the two calls)
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
