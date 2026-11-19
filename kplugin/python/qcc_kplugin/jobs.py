"""Background ``qcc`` subprocesses for the GUI: run one command or a chain, show progress in the status bar, never
block KLayout's UI thread and never open a modal dialog from the timer (errors go to the status bar and the log).

``run(steps, label, done)`` starts ``steps`` (a list of argument lists for ``qcc``) one after the other; ``done(ok,
output)`` is called from the polling timer when the last step ended or one failed. QuCat on a large netlist can take
minutes: the UI stays usable meanwhile, and the status bar shows the elapsed time.

A job stops by itself: when a step fails (the rest are skipped, ``done(False, output)``), or after ``timeout`` seconds
(the process is killed, ``timed_out`` is set and ``done(False, output)`` gets a "stopped" line). ``progress(job)``, when
given, is called on every poll while the job runs (``live_text()`` is the output so far, also of the running step).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pya  # type: ignore

from qcc_kplugin.session import SESSION, clean_env, log, message

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
RUNNING: list[Job] = []  # keeps the jobs (and their timers) alive until they finish


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a ``qcc`` process and its children (``qcc.exe`` is a launcher that starts python.exe)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False,  # noqa: S603,S607
                       creationflags=_NO_WINDOW)
    else:
        proc.kill()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        pass


class Job:
    def __init__(self, steps, label, done, cwd=None, timeout=None, progress=None):
        self.steps = [list(map(str, s)) for s in steps]
        self.label = label
        self.done = done
        self.cwd = cwd
        self.index = -1
        self.proc: subprocess.Popen | None = None
        self.log_path: Path | None = None
        self.output = ""
        self.started = time.time()
        self.finished = False
        self.ok = False
        self.timeout = timeout
        self.timed_out = False
        self.cancelled = False
        self.progress = progress
        self.timer = pya.QTimer(pya.Application.instance().main_window())
        self.timer.interval = 400
        self.timer.timeout(self.poll)

    def elapsed(self) -> float:
        return time.time() - self.started

    def start(self) -> Job:
        RUNNING.append(self)
        self._next()
        self.timer.start()
        return self

    def _next(self) -> bool:
        self.index += 1
        if self.index >= len(self.steps):
            return False
        args = self.steps[self.index]
        fd, name = tempfile.mkstemp(prefix="qcc_job_", suffix=".log")
        os.close(fd)
        self.log_path = Path(name)
        out = open(name, "wb")  # noqa: SIM115  (closed in poll once the process ended)
        try:
            self.proc = subprocess.Popen(  # noqa: S603
                [SESSION.qcc, *args], stdout=out, stderr=subprocess.STDOUT, env=clean_env(),
                creationflags=_NO_WINDOW, cwd=self.cwd,
            )
        finally:
            out.close()
        log(f"job {self.label} step {self.index + 1}/{len(self.steps)}: {' '.join(args)[:200]}")
        return True

    def live_text(self) -> str:
        """The output so far: the finished steps and what the running step has written."""
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace") if self.log_path else ""
        except OSError:
            text = ""
        return self.output + (text if not self.finished else "")

    def poll(self) -> None:
        if self.finished or self.proc is None:
            return
        rc = self.proc.poll()
        if rc is None and self.timeout is not None and self.elapsed() > self.timeout:
            kill_tree(self.proc)  # a QuCat solve that never ends (or a hung process): stop it, report it
            self.timed_out = True
            self.output = self.live_text() + (f"\nstopped: no result after {self.timeout / 60:.0f} min (the time limit "
                                              "in Quantcore > Settings)\n")
            self._drop_log()
            self._finish(False)
            return
        if rc is None:
            step = f" (step {self.index + 1}/{len(self.steps)})" if len(self.steps) > 1 else ""
            message(f"{self.label}: running{step}, {self.elapsed():.0f} s…", 2, log_it=False)
            if self.progress is not None:
                try:
                    self.progress(self)
                except Exception as e:  # noqa: BLE001  (a progress display must not stop the job)
                    log(f"{self.label}: progress display: {e!r}")
            return
        text = self.log_path.read_text(encoding="utf-8", errors="replace") if self.log_path else ""
        self.output += text
        self._drop_log()  # the step's output is kept in self.output (and the log on failure): no temp files pile up
        if rc == 0 and self._next():
            return
        self._finish(rc == 0)

    def _drop_log(self) -> None:
        """Remove the step's temp log (a subclass that keeps its log overrides this)."""
        try:
            self.log_path.unlink()
        except (OSError, AttributeError):
            pass

    def cancel(self) -> None:
        """Stop the job: kill the ``qcc`` process (tree) of the running step, skip the rest, drop its log. ``done`` is
        called with ``(False, "cancelled")`` and ``job.cancelled`` set, so the caller can restore what it showed."""
        if self.finished:
            return
        self.cancelled = True
        if self.proc is not None:
            kill_tree(self.proc)
        self._drop_log()
        self.output = "cancelled" + chr(10)
        self._finish(False)

    def _finish(self, ok: bool) -> None:
        self.finished = True
        self.ok = ok
        self.timer.stop()
        if self in RUNNING:
            RUNNING.remove(self)
        message(f"{self.label}: {'stopped' if self.cancelled else 'done' if ok else 'failed'} ({self.elapsed():.0f} s)")
        try:
            self.done(ok, self.output)
        except Exception:  # noqa: BLE001  (no dialog from a timer: log it)
            import traceback  # pylint: disable=import-outside-toplevel

            log(f"ERROR in the '{self.label}' completion handler\n{traceback.format_exc()}")
            message(f"{self.label}: could not show the result, see {Path(tempfile.gettempdir()) / 'qcc_kplugin.log'}")

    def wait(self, timeout: float = 600.0) -> bool:
        """Block until finished (tests only; the GUI never calls this)."""
        end = time.time() + timeout
        while not self.finished and time.time() < end:
            pya.QApplication.processEvents()
            self.poll()
            time.sleep(0.05)
        return self.ok


def run(steps, label, done, cwd=None, timeout=None, progress=None) -> Job:
    return Job(steps, label, done, cwd, timeout, progress).start()


def busy(label_prefix: str) -> bool:
    return any(j.label.startswith(label_prefix) and not j.finished for j in RUNNING)
