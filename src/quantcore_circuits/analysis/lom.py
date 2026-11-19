"""Lumped-oscillator model (Quantum Metal LOM 2.0, ``lom_core_analysis``) from a simulated capacitance matrix.

Input is the Maxwell capacitance matrix of the signal nets (as Q3D/Elmer/Palace export it, ground excluded) with
net labels from the job's port table. The ground row/column Metal expects is reconstructed from row sums.
"""

from __future__ import annotations

import numpy as np

from quantcore_circuits.analysis._metal import lom_core


def maxwell_with_ground(cmatrix: np.ndarray, labels: list[str], ground: str = "ground"):
    """Append the ground node to a signal-only Maxwell matrix. Returns a DataFrame in the input units."""
    import pandas as pd  # pylint: disable=import-outside-toplevel

    c = np.asarray(cmatrix, dtype=float)
    to_ground = c.sum(axis=1)  # Maxwell matrix rows sum to the capacitance to ground
    n = len(labels)
    full = np.zeros((n + 1, n + 1))
    full[:n, :n] = c
    full[:n, n] = full[n, :n] = -to_ground
    full[n, n] = to_ground.sum()
    names = list(labels) + [ground]
    return pd.DataFrame(full, index=names, columns=names)


def lom_transmon_resonator(
    cmatrix_fF: np.ndarray,
    labels: list[str],
    island: str,
    coupler: str,
    lj_nH: float,
    f_r_GHz: float,
    cj_fF: float = 0.0,
    z0: float = 50.0,
    vp: float | None = None,
    other_end_shorted: bool = True,
    resonator_levels: int = 5,
) -> dict:
    """Grounded transmon (``island``–ground junction) coupled through ``coupler`` to a λ/4 TL resonator.

    ``f_r_GHz`` is the bare resonator frequency (Metal's TL_RESONATOR takes it as given). ``vp`` defaults to Metal's
    CPW model when ``None``. Returns f_q, f_r (GHz), α, χ, g (MHz), EJ, EC (GHz) in qcc conventions.
    """
    lom = lom_core()
    cap = maxwell_with_ground(cmatrix_fF, labels)
    cell = lom.Cell(
        {
            "cap_mat": cap,
            "ind_dict": {(island, "ground"): lj_nH},
            "jj_dict": {(island, "ground"): "j1"},
            "cj_dict": {(island, "ground"): cj_fF},
        }
    )
    q_opts = {"f_res": f_r_GHz, "Z0": z0, "other_end_shorted": other_end_shorted, "truncated_dim": resonator_levels}
    if vp is not None:
        q_opts["vp"] = vp
    qubit = lom.Subsystem(name="qubit", sys_type="TRANSMON", nodes=["j1"])
    res = lom.Subsystem(name="readout", sys_type="TL_RESONATOR", nodes=[coupler], q_opts=q_opts)
    system = lom.CompositeSystem(subsystems=[qubit, res], cells=[cell], grd_node="ground", nodes_force_keep=[coupler])
    hs = system.add_interaction()
    out = system.hamiltonian_results(hs, print_info=False)
    chi = out["chi_in_MHz"].to_dataframe()
    gs = system.compute_gs().to_dataframe()
    hp = qubit.h_params.get("j1", qubit.h_params)
    ec_GHz = float(hp["EC"]) / 1e3
    from quantcore_circuits.analysis.transmon import c_from_ec  # pylint: disable=import-outside-toplevel

    return {
        "f_q_GHz": float(out["fQ_in_Ghz"]["qubit"]),
        "f_r_GHz": float(out["fQ_in_Ghz"]["readout"]),
        "alpha_MHz": float(chi.loc["qubit", "qubit"]),
        "chi_MHz": float(chi.loc["qubit", "readout"]),
        "g_MHz": float(abs(gs.loc["j1", coupler])),
        "EJ_GHz": float(hp["EJ"]) / 1e3,
        "EC_GHz": ec_GHz,
        "C_sigma_fF": c_from_ec(ec_GHz),  # effective (loaded) qubit capacitance
    }
