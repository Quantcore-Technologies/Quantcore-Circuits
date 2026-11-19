"""Quantcore concentric transmon with the PDK trilayer junction.

A copy of KQC ``ConcentricTransmon`` (same islands, couplers, drive port, parameters, ports and LOM): only the
junction differs. ``junction_type`` offers the Quantcore trilayer cells and defaults to ``"Quantcore Squid"`` (the PDK
nominal SQUID, L_J 6.73 nH, C_J 15 fF); ``junction_params`` (JSON dict, as on the Xmon) is passed to that cell, e.g.
``{"lj_nH": 8}``. The fingers (2/0, 4/0), spacer (50/0) and gradient (51-53/0) land where KQC's SQUID lands.
"""

import json

from kqcircuits.junctions import junction_type_choices
from kqcircuits.qubits.concentric_transmon import ConcentricTransmon
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.qubits.xmon import _junction_params


class TrilayerConcentricTransmon(ConcentricTransmon):
    """Concentric transmon (KQC geometry) shunted by a Quantcore trilayer junction / SQUID."""

    qcc_category = "qubit"

    junction_type = Param(
        pdt.TypeString,
        "Junction Type",
        "Quantcore Squid",
        choices=junction_type_choices
        + ["Trilayer Junction", "Trilayer Squid", "Quantcore Junction", "Quantcore Squid"],
    )
    junction_params = Param(pdt.TypeString, "Junction cell parameters (JSON dict)", "{}")

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        """design.json params → PCell params: ``junction_params`` dict → JSON. Unknown parameters raise."""
        params = dict(params)
        unknown = sorted(set(params) - set(cls.get_schema()))
        if unknown:
            raise ValueError(f"TrilayerConcentricTransmon: unknown parameter(s) {unknown}")
        jp = params.get("junction_params")
        if isinstance(jp, dict):
            params["junction_params"] = json.dumps(jp, sort_keys=True)
        elif isinstance(jp, str):
            _junction_params(jp)  # validate
        return params

    def produce_squid(self, transf, only_arms=False, **parameters):
        """The base ``produce_squid`` with ``junction_params`` passed to the junction cell."""
        return super().produce_squid(transf, only_arms, **{**_junction_params(self.junction_params), **parameters})

    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):
        """The KQC ConcentricTransmon model; without ``junction.Lj_nH`` in the design the junction takes the drawn
        trilayer junction's L_J / C_J on the PDK rule."""
        from quantcore_circuits.lom.fragment import cell_params, drawn_junction  # pylint: disable=C0415
        from quantcore_circuits.lom.kqc_models import concentric_lom  # pylint: disable=C0415

        frag = concentric_lom(name, inst, pdk)
        drawn = drawn_junction(cell_params(inst))
        for el in frag.elements:
            if el.name == f"J_{name}" and el.value.get("Lj_nH") is None and drawn is not None:
                lj, cj, source = drawn
                el.value.update({"Lj_nH": lj, "Cj_fF": cj, "source": source})
                frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 3), round(lj * 1.5, 3))
                frag.notes = [n for n in frag.notes if "no junction.Lj_nH" not in n]
        return frag
