"""LOM → layout: qubit/resonator targets (or a ``circuit.json``) → component knobs → a laid-out chip.

1. **Circuit values.** For every transmon + λ/4 readout pair: f_q, α, f_r and g → E_J, E_C, Lj, C_Σ, C_g (LOM synthesis,
   :func:`~quantcore_circuits.analysis.synthesis.synthesize_transmon_readout`).
2. **Knobs.** A surrogate built from the component calibration (Xmon ``cross_length`` → C_island,
   ``claw_length`` → C_g and claw pad; no FEM needed) is inverted with the same QuTiP forward model the co-design
   loop uses, so claw loading of the resonator and the dressed shifts are accounted for (:func:`~quantcore_circuits.
   codesign.propose`).
3. **Layout.** Template ``"feedline"``: bond pads W/E on the chip's mid line, a straight feedline, the qubits below
   it at equal spacing, each with its readout meander hanging off the feedline and a flux line from a bottom pad.
   Built with :class:`~quantcore_circuits.designer.Designer` (``live=True`` shows it being laid out in KLayout).

The result is an ordinary design; simulate it (Q3D/HFSS/Palace), fill the circuit, and the co-design loop takes it
from there.
"""

from __future__ import annotations

from dataclasses import dataclass

from quantcore_circuits.pdk import DEFAULT_PDK


@dataclass
class PairTarget:
    qubit: str
    f_q_GHz: float
    alpha_MHz: float
    resonator: str
    f_r_GHz: float
    g_MHz: float


def pairs_from_circuit(model) -> list[PairTarget]:
    """Transmon + λ/4 pairs and their targets from a :class:`CircuitModel`."""
    out = []
    for rname, b in model.branches.items():
        if b.type != "TLres":
            continue
        cnode = b.nodes[0]
        q = next(
            (
                j.nodes[0]
                for j in model.branches.values()
                if j.type in ("JJ", "SQUID")
                and any(c.type == "C" and set(c.nodes) == {j.nodes[0], cnode} for c in model.branches.values())
            ),
            None,
        )
        t = model.targets
        try:
            out.append(
                PairTarget(
                    q,
                    t[f"{q}.f_q_GHz"].value,
                    t[f"{q}.alpha_MHz"].value,
                    rname,
                    t[f"{rname}.f_GHz"].value,
                    t[f"{rname}.g_MHz"].value,
                )
            )
        except KeyError as e:
            raise ValueError(f"circuit needs targets for {q}/{rname}: missing {e}") from e
    return out


def knobs_for_pair(p: PairTarget, pdk_name: str = DEFAULT_PDK, cj_fF: float = 2.0, a_um=10.0, b_um=6.0) -> dict:
    """Xmon cross/claw, Lj and resonator length that hit ``p`` (calibration surrogate + QuTiP forward model)."""
    from quantcore_circuits.analysis.synthesis import synthesize_transmon_readout  # pylint: disable=C0415
    from quantcore_circuits.codesign import ElementModel, PairSurrogate, propose  # pylint: disable=C0415
    from quantcore_circuits.lom.calibration import _entry  # pylint: disable=import-outside-toplevel

    syn = synthesize_transmon_readout(p.f_q_GHz, p.alpha_MHz, p.f_r_GHz, p.g_MHz, a_um, b_um, pdk_name)
    entry, scale = _entry("Xmon", pdk_name)
    models = {}
    for key, name in (("C_island", "C_island"), ("Cg", "Cg"), ("C_claw", "C_coupler")):
        c = entry[key]
        knob = f"{p.qubit}.{c['knob']}"
        models[name] = ElementModel(name, knob, c["k0"], c["v0"] * scale, c["p"], c["p"])
    s = PairSurrogate(
        p.qubit,
        p.resonator,
        models["C_island"],
        models["Cg"],
        models["C_coupler"],
        syn["Lj_nH"],
        cj_fF,
        syn["resonator_length_um"],
        a_um,
        b_um,
        pdk_name,
    )
    targets = {
        f"{p.qubit}.f_q_GHz": {"value": p.f_q_GHz, "tol": 0.02},
        f"{p.qubit}.alpha_MHz": {"value": p.alpha_MHz, "tol": 10.0},
        f"{p.resonator}.f_GHz": {"value": p.f_r_GHz, "tol": 0.01},
        f"{p.resonator}.g_MHz": {"value": p.g_MHz, "tol": 10.0},
    }
    bounds = {
        f"{p.qubit}.cross_length": (150.0, 600.0),
        f"{p.qubit}.claw_length": (40.0, 260.0),
        f"{p.qubit}.junction.Lj_nH": (3.0, 30.0),
        f"{p.resonator}.length": (2000.0, 9000.0),
    }
    prop = propose(s, targets, bounds)
    return {
        "knobs": prop.knobs,
        "predicted": prop.predicted,
        "residuals": prop.residuals,
        "synthesis": syn,
        "at_bounds": prop.at_bounds,
    }


def layout_from_targets(
    name: str,
    pairs: list[PairTarget],
    box=(0.0, 0.0, 7500.0, 7500.0),
    pdk: str = DEFAULT_PDK,
    live: bool = False,
    template: str = "feedline",
    **designer_kw,
):
    """Lay out ``pairs`` on one feedline (see module docstring). Returns the :class:`Designer`."""
    from quantcore_circuits.designer import Designer  # pylint: disable=import-outside-toplevel

    if template != "feedline":
        raise ValueError(f"unknown template {template!r}")
    x0, y0, x1, y1 = box
    y_fl = (y0 + y1) / 2
    d = Designer(name, box=box, pdk=pdk, chip={"name_chip": name[:6].upper()}, live=live, **designer_kw)
    solved = [knobs_for_pair(p, pdk) for p in pairs]
    with d.batch():
        pw = d.add("PAD_W", "BondPad", at=(x0 + 1125, y_fl), rot=270)
        pe = d.add("PAD_E", "BondPad", at=(x1 - 1125, y_fl), rot=90)
        fl = d.route("FL", pw.a, pe.a, airbridges="none")
    span = (x1 - 1125) - (x0 + 1125)
    for i, (p, sol) in enumerate(zip(pairs, solved)):
        k = sol["knobs"]
        qx = round(x0 + 1125 + span * (i + 1) / (len(pairs) + 1), 1)
        q = d.add(
            p.qubit,
            "Xmon",
            at=(qx, y_fl - 1550),
            cross_length=k[f"{p.qubit}.cross_length"],
            claw_length=k[f"{p.qubit}.claw_length"],
            claws=["n"],
            flux_port=True,
            junction_type="Trilayer Squid",
            junction={"Lj_nH": k[f"{p.qubit}.junction.Lj_nH"], "Cj_fF": 2.0},
        )
        coupler = 300.0
        s = (qx - (x0 + 1125)) + coupler / 2
        d.route(p.resonator, q.claw_n, fl.hanger(s=s, length=coupler, side="right"), meander=k[f"{p.resonator}.length"])
        flux = q.flux.port.pos
        fx = round(qx + flux.x, 4)
        fy = round(y_fl - 1550 + flux.y, 4)
        pf = d.add(
            f"PAD_F{i + 1}" if len(pairs) > 1 else "PAD_F",
            "BondPad",
            at=(fx, y0 + 750),
            a=4,
            b=6,
            pad_width=300,
            pad_height=300,
            pad_gap=150,
            taper_length=300,
        )
        d.route(
            f"FLUX{i + 1}" if len(pairs) > 1 else "FLUX",
            pf.a,
            q.flux,
            a=4,
            b=6,
            nodes=[d.waypoint((fx, round(fy - 57.5, 4)), a=1, b=7.5)],
        )
    d.targets(
        **{p.qubit: {"f_q_GHz": p.f_q_GHz, "alpha_MHz": p.alpha_MHz} for p in pairs},
        **{p.resonator: {"f_GHz": p.f_r_GHz, "g_MHz": p.g_MHz} for p in pairs},
    )
    for p in pairs:
        d.sim_group(f"{p.qubit}{p.resonator}", [p.qubit, p.resonator])
    d.synthesis = solved
    return d


def layout_from_circuit(model, name: str | None = None, **kw):
    """LOM → layout for a :class:`CircuitModel` with transmon + λ/4 pairs and targets."""
    return layout_from_targets(name or model.name.replace("_lom", "") + "_synth", pairs_from_circuit(model), **kw)
