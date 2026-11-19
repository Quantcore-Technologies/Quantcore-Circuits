"""Start KLayout from Python when it is not running, so ``qcc.show`` / live designs always have a window to draw in.

``open_klayout()`` launches the KLayout GUI (editor mode) if nothing answers on the klive port, optionally with the
Quantcore KLayout plugin loaded straight from this repository (for users who have not linked it into their Salt
folder yet), with the layout as its argument (so it shows even before klive listens), waits until klive is listening
and brings the window to the front. The executable is found via ``QCC_KLAYOUT`` or the usual install locations
(``%APPDATA%\\KLayout\\klayout_app.exe``, ``%ProgramFiles%\\KLayout``, ``klayout`` on PATH).

Switch: ``QCC_KLAYOUT_GUI`` (``use_gui(True/False)``, the tutorials' ``KLAYOUT_GUI``; default on). Off: a live
design only redraws a KLayout that is already open (klive), and never starts one.

Why the window seemed not to open (2026-11-13): KLayout was started (detached, ``cmd /c start``) but its window came
up *behind* the editor / browser (Windows gives the foreground only to the process that has it), or klive reloaded the
layout in a KLayout window that was open but hidden; and a Designer tried to start KLayout only once, so after the
window was closed a rebuild never reopened it. Now the window is raised (restore + ``SetForegroundWindow`` with the
foreground thread's input attached + a topmost toggle) on the first live build and whenever qcc starts KLayout, and a
closed window is reopened on the next build. KLayout with the KQC Salt package takes ≈ 15–20 s to start; the wait is
60 s (the layout is on the command line, so it opens either way).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from quantcore_circuits.live.klive import klive_available

PLUGIN_LOADER = Path(__file__).resolve().parents[3] / "kplugin" / "load_dev.py"
GUI_ENV = "QCC_KLAYOUT_GUI"
_NAMES = ("klayout_app.exe", "klayout.exe", "klayout_app", "klayout")


def gui_enabled() -> bool:
    """``QCC_KLAYOUT_GUI`` (default on): may qcc start the KLayout window and bring it to the front?"""
    return os.environ.get(GUI_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def use_gui(flag: bool | None = None) -> bool:
    """Set (``True`` / ``False``) or read (``None``) the KLayout-window switch; also seen by subprocesses."""
    if flag is not None:
        os.environ[GUI_ENV] = "1" if flag else "0"
    return gui_enabled()


def find_klayout() -> Path | None:
    explicit = os.environ.get("QCC_KLAYOUT")
    if explicit:
        return Path(explicit)
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("APPDATA"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                candidates += [Path(base) / "KLayout" / "klayout_app.exe", Path(base) / "KLayout" / "klayout.exe"]
    for c in candidates:
        if c.is_file():
            return c
    which = shutil.which("klayout_app") or shutil.which("klayout")
    return Path(which) if which else None


def plugin_installed() -> bool:
    """Whether the Quantcore KLayout plugin is linked into the user's KLayout Salt folder."""
    home = Path(os.environ.get("KLAYOUT_HOME", Path.home() / "KLayout"))
    return (home / "salt" / "quantcore-circuits" / "grain.xml").exists()


def klayout_pids() -> list[int]:
    """PIDs of running KLayout GUI processes (psutil if installed, else ``tasklist`` / ``pgrep``)."""
    try:
        import psutil  # pylint: disable=import-outside-toplevel

        return [p.pid for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").lower() in _NAMES]
    except ImportError:
        pass
    if os.name == "nt":
        out = []
        for name in ("klayout_app.exe", "klayout.exe"):
            r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"], capture_output=True,
                               text=True, check=False)
            out += [int(line.split('","')[1]) for line in r.stdout.splitlines() if line.startswith(f'"{name}"')]
        return out
    r = subprocess.run(["pgrep", "-x", "klayout"], capture_output=True, text=True, check=False)
    return [int(x) for x in r.stdout.split()]


def _spawn_detached(args: list[str], env: dict):
    """Start a process that outlives this one, also when this is a Jupyter kernel being shut down or restarted.

    Kernel shutdown on Windows kills the kernel's process tree by parent PID, so KLayout is started through
    ``cmd /c start`` (cmd exits at once, leaving no parent link to the kernel). On POSIX a new session is enough.
    """
    if os.name != "nt":
        return subprocess.Popen(args, env=env, start_new_session=True, close_fds=True)  # noqa: S603
    detached, new_group = 0x00000008, 0x00000200
    return subprocess.Popen(
        ["cmd", "/c", "start", "", *args],
        env=env,
        close_fds=True,  # noqa: S603
        creationflags=detached | new_group,
    )


# ---- bring the window to the front (Windows; elsewhere a no-op) --------------------------------------------------
def _top_windows(pids: set[int] | None = None, prefix: str = "KLayout") -> list[tuple[int, int, str]]:
    """Visible, unowned top-level windows ``(hwnd, pid, title)`` whose title starts with ``prefix``."""
    if os.name != "nt":
        return []
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    user32 = ctypes.windll.user32
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype = wintypes.HWND
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # GW_OWNER
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if buf.value.startswith(prefix) and (pids is None or pid.value in pids):
            found.append((int(hwnd), int(pid.value), buf.value))
        return True

    user32.EnumWindows(callback, 0)
    return found


def bring_to_front(pid: int | None = None, layout: str | Path | None = None) -> bool:
    """Raise a KLayout window (of ``pid``, else of any KLayout; the one showing ``layout`` first): restore it if
    minimised, give it the foreground, and put it on top. Returns whether a window was found (Windows only)."""
    pids = {pid} if pid else set(klayout_pids())
    wins = _top_windows(pids or None)
    if not wins:
        return False
    if layout is not None:
        name = Path(layout).name
        wins.sort(key=lambda w: name not in w[2])
    hwnd = wins[0][0]
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    for fn, args in (("ShowWindow", [wintypes.HWND, ctypes.c_int]), ("SetForegroundWindow", [wintypes.HWND]),
                     ("BringWindowToTop", [wintypes.HWND]), ("IsIconic", [wintypes.HWND]),
                     ("SetWindowPos", [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_uint]),
                     ("GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
                     ("AttachThreadInput", [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL])):
        getattr(user32, fn).argtypes = args
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)  # SW_RESTORE / SW_SHOW
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    flags = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
    user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)  # HWND_TOPMOST, then back: on top, not pinned
    user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)
    return True


def open_klayout(
    layout: str | Path | None = None, with_plugin: bool = True, timeout: float = 60.0, front: bool = True
) -> dict:
    """Make sure a KLayout GUI with klive is running (start one if needed). Returns what was done.

    ``with_plugin``: if the Quantcore plugin is not installed in Salt, load it from the repo in the new window.
    ``front``: raise the KLayout window (the one qcc started, or the one already open). With ``QCC_KLAYOUT_GUI=0``
    nothing is started.
    """
    if klive_available():
        raised = bring_to_front(layout=layout) if front and gui_enabled() else False
        return {"started": False, "klive": True, "front": raised}
    if not gui_enabled():
        return {"started": False, "klive": False, "hint": f"{GUI_ENV}=0: KLayout is not started from Python"}
    exe = find_klayout()
    if exe is None:
        raise FileNotFoundError("KLayout not found; install it or set QCC_KLAYOUT to klayout_app.exe")
    before = set(klayout_pids())
    args = [str(exe), "-e"]
    if with_plugin and not plugin_installed() and PLUGIN_LOADER.exists():
        args += ["-rm", str(PLUGIN_LOADER)]
    if layout:
        args.append(str(Path(layout).resolve()))
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHONHOME", "PYTHONPATH"))}
    proc = _spawn_detached(args, env)
    t0 = time.time()
    pid = None
    info: dict = {"started": True, "klive": False}
    if before:
        info["note"] = (f"KLayout {sorted(before)} is open but klive is not listening on localhost:8082 (klive Salt "
                        "package missing, or press 'Restart klive' in its toolbar); opened another window")
    while time.time() - t0 < timeout:
        if pid is None:
            new = sorted(set(klayout_pids()) - before)
            pid = new[-1] if new else None
        if klive_available():
            info.update(klive=True, seconds=round(time.time() - t0, 1))
            break
        time.sleep(0.3)
    else:
        proc.poll()
        info["hint"] = "KLayout started but klive is not listening; install the klive Salt package"
    info["pid"] = pid
    if front:
        info["front"] = bring_to_front(pid, layout)
    return info
