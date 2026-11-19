"""Helper process for ``aedt="attach"``: run one qcc AEDT script inside an AEDT session that is already open.

Run by path (``python -I aedt_attach.py attach --port P --pid N --plugin DIR --script S --arg A --project NAME``),
standard library only, so it starts in a moment and a crash here never touches the notebook kernel. It connects with
AEDT's own gRPC client (``<AEDT>/PythonFiles/DesktopPlugin/PyDesktopPlugin.py``, shipped with AEDT 2024 R1), checks
that the port belongs to the expected AEDT process, closes an earlier copy of *this job's* project if one is open (it
would block the save), calls ``oDesktop.RunScriptWithArguments(script, arg)`` (blocks until the script returns) and
then only releases the connection. It never calls ``QuitApplication`` / ``ScriptEnv.Shutdown``: the session and all
its projects stay open. ``probe`` only connects and lists the open projects.
"""

from __future__ import annotations

import argparse
import sys
import time


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="qcc-aedt-attach")
    ap.add_argument("cmd", choices=["attach", "probe"])
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--script", default="")
    ap.add_argument("--arg", default="")
    ap.add_argument("--project", default="")
    a = ap.parse_args(argv)

    def say(msg):
        print(f"[qcc attach] {msg}", flush=True)

    sys.path.insert(0, a.plugin)
    try:
        import PyDesktopPlugin  # noqa: PLC0415  (AEDT's gRPC client)
    except Exception as e:  # noqa: BLE001
        say(f"cannot load AEDT's PyDesktopPlugin from {a.plugin}: {type(e).__name__}: {e}")
        return 4
    try:
        app = PyDesktopPlugin.CreateAedtApplication("", a.port, False, False)  # connect; never a new session
        desk = app.GetAppDesktop()
        pid = int(desk.GetProcessID())
        projects = [str(p) for p in desk.GetProjectList()]
        say(f"connected to AEDT {desk.GetVersion()} pid {pid} on port {a.port}; open projects {projects}")
        if a.pid and pid != a.pid:
            say(f"port {a.port} belongs to pid {pid}, not {a.pid}: nothing run")
            return 3
        if a.cmd == "probe":
            return 0
        if a.project and a.project in projects:
            desk.CloseProject(a.project)
            say(f"closed the earlier copy of {a.project} (this job's own project; it is re-run now)")
        say(f"running {a.script} {a.arg}")
        t0 = time.time()
        desk.RunScriptWithArguments(a.script, a.arg)
        say(f"script returned after {time.time() - t0:.1f} s; the session and its projects stay open")
        return 0
    except Exception as e:  # noqa: BLE001
        say(f"{type(e).__name__}: {e}")
        return 2
    finally:
        PyDesktopPlugin.Release()  # drops this connection only


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
