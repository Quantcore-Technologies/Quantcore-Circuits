"""A Metal cell's options written as ``params.options`` (a dict, or the JSON text of the PCell form: what the KLayout
plugin's parameter table writes) must give the same LOM and design checks as the flat form the notebooks write."""

import json

from quantcore_circuits.design import Design
from quantcore_circuits.layouts.metal import flat_options
from quantcore_circuits.lom.metal_models import _opts

OPTS = {"connection_pads": {"a": {"connector_type": "0", "claw_length": "150um"}}, "cross_length": "220um"}


def test_flat_options_merges_dict_and_json_text_and_flat_keys_win():
    assert flat_options({"options": OPTS, "a": 10}) == {**OPTS, "a": 10}
    assert flat_options({"options": json.dumps(OPTS)}) == OPTS
    assert flat_options({"options": "", "x": 1}) == {"x": 1}
    assert flat_options({"options": {"cross_length": "1um"}, "cross_length": "2um"}) == {"cross_length": "2um"}
    assert flat_options(None) == {}


def _design(params):
    return Design.model_validate({
        "name": "t", "pdk": "quantcore_nb_sapphire_v1",
        "chip": {"box": [0, 0, 7500, 7500]},
        "instances": {"Q": {"cell": "metal:TransmonCross", "params": params, "place": {"at": [3000, 3000]}}},
    })


def test_lom_reads_the_options_form_like_the_flat_form():
    flat = _opts(_design(dict(OPTS)).instances["Q"])
    nested = _opts(_design({"options": dict(OPTS)}).instances["Q"])
    text = _opts(_design({"options": json.dumps(OPTS)}).instances["Q"])
    assert flat.raw == nested.raw == text.raw
    assert flat.pads == nested.pads == text.pads and "a" in flat.pads
