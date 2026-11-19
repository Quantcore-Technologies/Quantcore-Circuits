"""``qcc watch``: rebuild on change → write OAS → reload in KLayout via klive.

Polling (no extra dependency): ``design.json``/``design.py`` plus any extra files are checked every ``interval``
seconds; a change is rebuilt after ``debounce`` seconds of quiet. A failed build prints the error and leaves the
last good layout in KLayout. KQC library caching keeps rebuilds of unchanged cells cheap, so the loop stays well
under the 2 s target for chip-sized designs.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from pathlib import Path

from quantcore_circuits.live.klive import KliveUnavailable, send_to_klive


def _mtimes(paths: list[Path]) -> tuple:
    out = []
    for p in paths:
        try:
            out.append(p.stat().st_mtime_ns)
        except FileNotFoundError:
            out.append(None)
    return tuple(out)


def rebuild(source: Path, out: Path, klive: bool = True, log: Callable[[str], None] = print,
            chip_overrides: dict | None = None) -> bool:
    from quantcore_circuits.assembly import build, write_layout  # pylint: disable=import-outside-toplevel

    t0 = time.perf_counter()
    try:
        result = build(source, **(chip_overrides or {}))
        write_layout(result, out)
    except Exception as e:  # noqa: BLE001 - report any design/build error and keep the last good layout
        log(f"[qcc watch] build FAILED ({type(e).__name__}): {e}")
        log("".join(traceback.format_exception_only(type(e), e)).strip())
        return False
    t_build = time.perf_counter() - t0
    msg = f"[qcc watch] built {result.design.name} in {t_build:.2f} s -> {out}"
    if klive:
        try:
            reply = send_to_klive(out)
            msg += f" (klive: {reply.get('type', 'sent')})"
        except KliveUnavailable as e:
            msg += f" (klive not reachable: {e})"
    lengths = ", ".join(f"{k}={v:.1f}" for k, v in result.route_lengths().items() if v is not None)
    log(msg + (f"\n            route lengths [µm]: {lengths}" if lengths else ""))
    return True


def watch(
    source: str | Path,
    out: str | Path | None = None,
    extra: list[str | Path] | None = None,
    interval: float = 0.25,
    debounce: float = 0.2,
    klive: bool = True,
    max_builds: int | None = None,
    log: Callable[[str], None] = print,
    chip_overrides: dict | None = None,
) -> None:
    source = Path(source)
    out = Path(out) if out else Path("build") / f"{source.stem}.oas"
    paths = [source] + [Path(p) for p in (extra or [])]
    log(f"[qcc watch] watching {', '.join(map(str, paths))} (Ctrl+C to stop)")
    builds = 0
    rebuild(source, out, klive, log, chip_overrides)
    builds += 1
    if klive and out.exists():
        from quantcore_circuits.live.klayout import gui_enabled, open_klayout  # pylint: disable=C0415
        from quantcore_circuits.live.klive import klive_available  # pylint: disable=import-outside-toplevel

        if not klive_available() and gui_enabled():  # no KLayout (with klive) yet: open one with the layout
            try:
                log(f"[qcc watch] KLayout: {open_klayout(out)}")
            except FileNotFoundError as e:
                log(f"[qcc watch] {e}")
    last = _mtimes(paths)
    try:
        while max_builds is None or builds < max_builds:
            time.sleep(interval)
            now = _mtimes(paths)
            if now == last:
                continue
            time.sleep(debounce)  # let editors finish writing
            last = _mtimes(paths)
            rebuild(source, out, klive, log, chip_overrides)
            builds += 1
    except KeyboardInterrupt:
        log("[qcc watch] stopped")
