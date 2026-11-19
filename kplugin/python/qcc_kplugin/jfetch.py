"""Junction facts from the library, through ``qcc`` (the plugin does not import quantcore_circuits).

* :func:`placement_junction`: the simulation / LOM junction a new component gets when it is placed
  (``qcc design placement-junction CELL --params JSON``): a drawn trilayer junction's PDK value, else the PDK nominal
  SQUID, or None for a component without a junction. It also holds ``drawn`` (the trilayer junction the cell draws).
  The answer is cached by (cell, parameters); :func:`prefetch` starts the call in the background (when a placement is
  armed), so the click that places the component finds it ready.
* :func:`missing_default`: ``qcc design junctions DESIGN --default --json``: the junctions of the default simulation
  subset that have no L_J (the Simulate dialog's pre-check when nothing is selected).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_CACHE: dict[str, dict | None] = {}
_PENDING: dict[str, subprocess.Popen] = {}
_DEFAULT: dict[str, tuple[float, dict]] = {}
TIMEOUT = 60.0


def _qcc_cmd(args: list[str]) -> list[str]:
    from qcc_kplugin.session import SESSION  # pylint: disable=import-outside-toplevel

    return [SESSION.qcc, *[str(a) for a in args]]


def _env() -> dict:
    from qcc_kplugin.session import clean_env  # pylint: disable=import-outside-toplevel

    return clean_env()


def key(cell: str, params: dict | None) -> str:
    return f"{cell}:{json.dumps(params or {}, sort_keys=True, default=str)}"


def _args(cell: str, params: dict | None) -> list[str]:
    return ["design", "placement-junction", cell, "--params", json.dumps(params or {}, default=str)]


def prefetch(cell: str, params: dict | None) -> None:
    """Start the library call for ``cell`` in the background (no-op when cached or already running)."""
    k = key(cell, params)
    if k in _CACHE or k in _PENDING:
        return
    try:
        _PENDING[k] = subprocess.Popen(_qcc_cmd(_args(cell, params)), stdout=subprocess.PIPE,  # noqa: S603
                                       stderr=subprocess.DEVNULL, env=_env(), creationflags=_NO_WINDOW)
    except OSError:
        pass


def _parse(text: str) -> dict | None:
    for line in reversed([ln for ln in text.splitlines() if ln.strip()]):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        return value if isinstance(value, dict) else None
    return None


def placement_junction(cell: str, params: dict | None = None) -> dict | None:
    """``{"Lj_nH", "Cj_fF", "source", "drawn"}`` for ``cell`` placed with ``params``, or None (no junction, or the
    library could not be asked: the plugin then writes nothing). Waits for a prefetch, else asks once (about 1.4 s)."""
    k = key(cell, params)
    if k in _CACHE:
        return _CACHE[k]
    proc = _PENDING.pop(k, None)
    try:
        if proc is None:
            proc = subprocess.Popen(_qcc_cmd(_args(cell, params)), stdout=subprocess.PIPE,  # noqa: S603
                                    stderr=subprocess.DEVNULL, env=_env(), creationflags=_NO_WINDOW)
        out, _ = proc.communicate(timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        if proc is not None:
            proc.kill()
        return None
    value = _parse(out.decode("utf-8", "replace")) if proc.returncode == 0 else None
    if proc.returncode == 0:
        _CACHE[k] = value
    return value


def missing_default(design_path) -> dict[str, str]:
    """``{name: message}`` of the default subset's junctions without an L_J (``qcc design junctions --default``); {}
    when none, or when the library could not be asked. Cached while design.json is unchanged."""
    path = Path(design_path)
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {}
    hit = _DEFAULT.get(str(path))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    try:
        proc = subprocess.run(_qcc_cmd(["design", "junctions", path, "--default", "--json"]),  # noqa: S603
                              capture_output=True, env=_env(), creationflags=_NO_WINDOW, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    data = _parse(proc.stdout.decode("utf-8", "replace")) or {}
    missing = {str(k): str(v) for k, v in (data.get("missing") or {}).items()}
    _DEFAULT[str(path)] = (stamp, missing)
    return missing


# The junction an unset KQC / Metal ``junction_type`` default is drawn as (the PDK trilayer junction). A copy of the
# library's ``assembly.plan._PDK_JUNCTION``, checked by a test.
PDK_JUNCTION = {
    "Manhattan": "Quantcore Squid",
    "Manhattan Single Junction": "Quantcore Junction",
    "QCD1": "Quantcore Squid",
    "Metal": "Quantcore Junction",
}


def drawn_type(set_type: str | None, default_type: str | None, junction_cell: bool = False) -> str | None:
    """The ``junction_type`` a component is drawn with: the instance's own (``set_type``), else the cell's default,
    which the build replaces by the PDK trilayer junction when it is a KQC / Metal one (not for a junction cell)."""
    if set_type is not None:
        return set_type
    return default_type if junction_cell else PDK_JUNCTION.get(default_type, default_type)


def is_trilayer_type(junction_type: str) -> bool:
    """Whether a ``junction_type`` name is a drawn trilayer junction (the PDK gives it a value): the Quantcore,
    "Trilayer ..." and "Squid V0" junction cells. A copy of the library's rule (``trilayer_junction_values``), checked by a test."""
    jt = str(junction_type or "").strip().lower()
    return jt.startswith("quantcore") or "trilayer" in jt or jt == "squid v0"
