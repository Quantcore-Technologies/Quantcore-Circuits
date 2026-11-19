"""Quantcore layout library: QWri cells re-implemented as KQCircuits Elements with ports.

Folders: ``chips/`` (chip-level cells, ``DesignChip``), ``wafers/`` (wafer/mask layouts and fab export),
``junctions/``, ``qubits/``, ``others/`` (pads, couplers, test structures, ...), ``metal/`` (any Quantum Metal
QComponent as ``cell: "metal:<Class>"``; Metal itself is imported only when such a cell is built).
:mod:`.catalog` lists every usable component (Quantcore, KQC, Metal) with its category.

Every PCell is registered into the KQC library of its base class ("Element Library", "Junction Library", "Qubit
Library", "Chip Library"), so Quantcore junctions are valid ``junction_type`` values for any KQC qubit and Quantcore
elements can be used as KQC ``Node`` elements. Registration does not depend on folder names (unlike KQC's
``SRC_PATHS`` user packages), and it works whether or not KQC libraries were loaded before.

Everything here depends only on KLayout + KQCircuits, so it also loads inside the KLayout GUI (see ``kplugin/``).
"""

import importlib
import inspect
from pathlib import Path

LAYOUTS_PATH = Path(__file__).parent
_FOLDERS = ("others", "junctions", "qubits", "metal", "chips", "wafers")
# KQC library folders, in KQC's library dependency order
_KQC_LIBRARY_PATHS = ("elements", "junctions", "test_structures", "qubits", "chips")


def pcell_classes() -> list:
    """All concrete Quantcore PCell classes (imports every module in the layout folders)."""
    from kqcircuits.elements.element import Element  # pylint: disable=import-outside-toplevel

    classes = []
    for folder in _FOLDERS:
        for path in sorted((LAYOUTS_PATH / folder).rglob("*.py")):
            if path.stem.startswith("_"):
                continue
            rel = path.relative_to(LAYOUTS_PATH).with_suffix("")
            module = importlib.import_module(".".join((__name__,) + rel.parts))
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    obj.__module__ == module.__name__
                    and not name.startswith("_")
                    and issubclass(obj, Element)
                    and obj.build is not Element.build
                ):
                    classes.append(obj)
    return classes


def register_pcell_classes(classes) -> None:
    """Register PCell classes into their (already loaded) KQC libraries."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel
    from kqcircuits.util.library_helper import to_library_name  # pylint: disable=import-outside-toplevel

    touched = set()
    for cls in classes:
        library = pya.Library.library_by_name(cls.LIBRARY_NAME)
        if library is None:
            raise RuntimeError(f"KQC library {cls.LIBRARY_NAME!r} is not loaded; call ensure_loaded() first")
        name = to_library_name(cls.__name__)
        if name not in library.layout().pcell_names():
            library.layout().register_pcell(name, cls())
            touched.add(cls.LIBRARY_NAME)
    for library_name in touched:
        pya.Library.library_by_name(library_name).refresh()


_loaded = False


def ensure_loaded() -> None:
    """Load the KQC libraries and register all Quantcore cells into them (idempotent, cheap after the first call)."""
    global _loaded  # pylint: disable=global-statement
    from kqcircuits.util.library_helper import load_libraries  # pylint: disable=import-outside-toplevel

    for path in _KQC_LIBRARY_PATHS:
        load_libraries(path=path)
    if not _loaded:
        _loaded = True
        from quantcore_circuits.kqc_files import ensure_kqc_data  # pylint: disable=import-outside-toplevel

        ensure_kqc_data()  # KQC's label font: a pip-installed kqcircuits lacks it (qcc kqc-files)
        register_pcell_classes(pcell_classes())


# Re-exports: Quantcore cells and commonly used KQC cells, usable by short name in design.json
from kqcircuits.elements.finger_capacitor_square import FingerCapacitorSquare  # noqa: E402
from kqcircuits.elements.launcher import Launcher  # noqa: E402
from kqcircuits.elements.meander import Meander  # noqa: E402
from kqcircuits.elements.quarter_wave_cpw_resonator import QuarterWaveCpwResonator  # noqa: E402
from kqcircuits.elements.waveguide_composite import WaveguideComposite  # noqa: E402
from kqcircuits.elements.waveguide_coplanar import WaveguideCoplanar  # noqa: E402
from kqcircuits.qubits.double_pads import DoublePads  # noqa: E402
from kqcircuits.qubits.swissmon import Swissmon  # noqa: E402

from quantcore_circuits.layouts.chips.design_chip import DesignChip  # noqa: E402
from quantcore_circuits.layouts.junctions.trilayer import TrilayerJunction, TrilayerSquid  # noqa: E402
from quantcore_circuits.layouts.others.bond_pad import BondPad  # noqa: E402
from quantcore_circuits.layouts.qubits.xmon import Xmon  # noqa: E402

ensure_loaded()

__all__ = [
    "BondPad",
    "DesignChip",
    "DoublePads",
    "FingerCapacitorSquare",
    "Launcher",
    "Meander",
    "QuarterWaveCpwResonator",
    "Swissmon",
    "TrilayerJunction",
    "TrilayerSquid",
    "WaveguideComposite",
    "WaveguideCoplanar",
    "Xmon",
    "ensure_loaded",
    "pcell_classes",
    "register_pcell_classes",
]
