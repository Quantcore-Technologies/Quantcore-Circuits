"""The component-docs generator reads the same ports as the library (positions, names)."""

import importlib.util
import math
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_component_docs.py"


def _gen():
    spec = importlib.util.spec_from_file_location("make_component_docs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("ref", ["Xmon", "BondPad", "TwoPadTransmon"])
def test_generator_ports_equal_library(ref):
    gen = _gen()
    (c,) = gen.doc_cells([ref])
    _layout, _cell, ports, err = gen.build_default(c)
    assert not err
    lib = c.ports_of()
    assert set(ports) == set(lib)
    for name, p in ports.items():
        assert math.isclose(p.pos.x, lib[name].pos.x, abs_tol=1e-6)
        assert math.isclose(p.pos.y, lib[name].pos.y, abs_tol=1e-6)
    text = gen.page(c, {"ports": ports, "error": "", "frag": None, "has_lom": False, "lom_error": "",
                        "schema": gen.schema_rows(c)}, {}, {})
    for name in ports:
        assert f"| `{name}` |" in text
