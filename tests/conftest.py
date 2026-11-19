import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "q1_r1_feedline.json"


def have(*modules) -> bool:
    return all(importlib.util.find_spec(m) is not None for m in modules)


@pytest.fixture
def example_path() -> Path:
    return EXAMPLE


@pytest.fixture
def example_dict() -> dict:
    return copy.deepcopy(json.loads(EXAMPLE.read_text(encoding="utf-8")))


AEDT_DATA = ROOT / "tests" / "data" / "aedt_2024r1"


def have_aedt_fixtures() -> bool:
    """The AEDT projects and result folders under ``tests/data/aedt_2024r1`` are kept in a dev checkout only (not in
    git: every AEDT edition writes its own, and the notebooks make them)."""
    return any(AEDT_DATA.rglob("*.aedt")) and any(AEDT_DATA.rglob("*.aedtresults"))


def pytest_collection_modifyitems(config, items):
    skip_analysis = pytest.mark.skip(reason="analysis stack (quantum-metal, scqubits, qutip, ...) not installed")
    skip_fixture = pytest.mark.skip(reason="local AEDT project fixtures not present (dev checkout only)")
    fixtures = None
    for item in items:
        if "analysis" in item.keywords and not have("qiskit_metal", "scqubits", "qutip", "pyEPR"):
            item.add_marker(skip_analysis)
        if "aedt_fixture" in item.keywords:
            if fixtures is None:
                fixtures = have_aedt_fixtures()
            if not fixtures:
                item.add_marker(skip_fixture)
