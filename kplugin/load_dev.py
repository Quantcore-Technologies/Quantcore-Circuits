# Load the Quantcore KLayout plugin straight from this repository (same code the Salt autorun macro runs):
#   klayout_app.exe -e -rm kplugin/load_dev.py
# Used by quantcore_circuits.live.klayout.open_klayout() when the plugin is not linked into the Salt folder yet.
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "python"))
_lym = (HERE / "pymacros" / "qcc_kplugin.lym").read_text(encoding="utf-8")
_code = _lym.split("<text>", 1)[1].split("</text>", 1)[0]
exec(_code.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&"))  # noqa: S102
