"""Use Quantum Metal (Apache-2.0) analysis code without vendoring it.

``import qiskit_metal.<anything>`` runs the whole package ``__init__`` (designs, renderers, geopandas: ~10 s). Some
Metal modules only need numpy/scipy, so they are loaded straight from their files in the installed package. The LOM
engine (``lom_core_analysis``) needs the real package and is imported normally, but lazily.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import cache
from pathlib import Path


@cache
def metal_root() -> Path:
    spec = importlib.util.find_spec("qiskit_metal")  # top-level find_spec does not execute the package
    if spec is None or not spec.submodule_search_locations:
        raise ImportError(
            "quantum-metal is not installed "
            "(bash scripts/fetch_other_libs.sh, then pip install -e third_party/qiskit-metal)"
        )
    return Path(list(spec.submodule_search_locations)[0])


@cache
def load_standalone(relpath: str):
    """Load ``qiskit_metal/<relpath>.py`` as an isolated module (only for numpy/scipy-only modules)."""
    path = metal_root() / f"{relpath}.py"
    name = "_qcc_metal_" + relpath.replace("/", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cpw():
    """``qiskit_metal.analyses.em.cpw_calculations`` (guided_wavelength, lumped_cpw)."""
    return load_standalone("analyses/em/cpw_calculations")


def kappa():
    """``qiskit_metal.analyses.em.kappa_calculation`` (kappa_in)."""
    return load_standalone("analyses/em/kappa_calculation")


_compat_applied = False


def apply_scqubits_compat() -> None:
    """Metal's fix for scqubits <= 4.3.1 with qutip >= 5.3 (``csc_array``) and numpy 2 aliases. Idempotent."""
    global _compat_applied  # pylint: disable=global-statement
    if _compat_applied:
        return
    import scqubits  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import

    load_standalone("analyses/quantization/_scqubits_compat").apply()
    _compat_applied = True


def lom_core():
    """``qiskit_metal.analyses.quantization.lom_core_analysis`` (heavy import)."""
    import warnings  # pylint: disable=import-outside-toplevel

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from qiskit_metal.analyses.quantization import lom_core_analysis  # pylint: disable=import-outside-toplevel
    return lom_core_analysis
