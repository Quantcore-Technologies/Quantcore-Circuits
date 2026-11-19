"""Parsed simulation results + design → Hamiltonian parameters per instance, comparable to ``design.targets``.

* C-matrix (Q3D / Elmer / Palace electrostatics): Metal LOM per selected qubit. The resonator attached to the cut
  coupler port is modelled as a λ/4 TL with f_r from its routed length (Metal CPW model), unless a measured f_r is
  given (e.g. from an eigenmode run).
* Eigenmodes (HFSS / Palace): linear mode frequencies and Q, assigned to qubits/resonators by nearest target.

Output keys follow ``targets``: ``{"Q1": {"f_q_GHz", "alpha_MHz", ...}, "R1": {"f_GHz", "g_MHz", "chi_MHz"}}``.
"""

from __future__ import annotations

import numpy as np

from quantcore_circuits import track as _track
from quantcore_circuits.design import Design, load_design, split_port_ref


def route_attached_to(design: Design, port_ref: str) -> str | None:
    for name, route in design.routes.items():
        if port_ref in (route.from_, route.to):
            return name
    return None


def resonator_frequency_GHz(design: Design, route: str, guess_GHz: float = 7.0) -> float:
    """λ/4 frequency of ``route`` from its built length and the PDK CPW model (two fixed-point iterations)."""
    from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel

    plan = plan_design(design)
    rp = plan.routes[route]
    length = rp.length
    f = guess_GHz
    for _ in range(3):
        f = cpw_properties(f, rp.params["a"], rp.params["b"], design.pdk)["vp_m_s"] / (4 * length * 1e-6) / 1e9
    return f


def extract(source, results: dict, f_r_GHz: dict[str, float] | None = None) -> dict[str, dict[str, float]]:
    design = load_design(source)
    group = design.sim_groups[results["group"]]
    out: dict[str, dict[str, float]] = {}
    f_r_GHz = dict(f_r_GHz or {})

    if "cmatrix" in results:
        from quantcore_circuits.analysis.lom import lom_transmon_resonator  # pylint: disable=import-outside-toplevel

        labels = results["cmatrix"]["labels"]
        cmat = np.asarray(results["cmatrix"]["matrix"], dtype=float)
        for q in group.select:
            island = f"{q}.island"
            inst = design.instances.get(q)
            if island not in labels or inst is None:
                continue
            from quantcore_circuits.lom.fragment import (  # pylint: disable=import-outside-toplevel
                effective_junction,
                instance_junction,
                missing_junction_message,
            )

            # L at the design flux, as the LOM and the HFSS sheet take it
            ej = instance_junction(q, inst, design.pdk) or effective_junction(inst)
            lj = ej.lj_eff_nH if ej is not None else None
            if lj is None:
                raise ValueError(missing_junction_message(q, inst, ej))
            cj = ej.cj_fF
            couplers = [lab for lab in labels if lab.startswith(f"{q}.") and lab != island]
            for coupler in couplers[:1]:  # one readout resonator per qubit in this version
                route = route_attached_to(design, coupler)
                if route is None:
                    continue
                fr = f_r_GHz.get(route) or resonator_frequency_GHz(design, route)
                res = lom_transmon_resonator(cmat, labels, island, coupler, lj, fr, cj)
                out[q] = {k: res[k] for k in ("f_q_GHz", "alpha_MHz", "EJ_GHz", "EC_GHz", "C_sigma_fF")}
                out[route] = {"f_GHz": res["f_r_GHz"], "g_MHz": res["g_MHz"], "chi_MHz": res["chi_MHz"]}

    if results.get("eigenmodes"):
        modes = sorted(results["eigenmodes"], key=lambda m: m["f_GHz"])
        wanted = []
        for name, tgt in design.targets.items():
            key = "f_q_GHz" if "f_q_GHz" in tgt else ("f_GHz" if "f_GHz" in tgt else None)
            if key and (name in group.select):
                wanted.append((name, key, tgt[key]))
        free = list(modes)
        for name, key, f_target in sorted(wanted, key=lambda w: w[2]):
            if not free:
                break
            best = min(free, key=lambda m: abs(m["f_GHz"] - f_target))
            free.remove(best)
            entry = out.setdefault(name, {})
            entry[key.replace("_GHz", "_eig_GHz")] = best["f_GHz"]
            if best.get("Q") is not None:
                entry["Q"] = best["Q"]
    return out


def compare(targets: dict, extracted: dict) -> list[dict]:
    """Rows of (instance, quantity, target, value, error) for every target that was extracted."""
    rows = []
    for inst, tgt in targets.items():
        got = extracted.get(inst, {})
        for key, value in tgt.items():
            alt = key.replace("_GHz", "_eig_GHz")
            v = got.get(key, got.get(alt))
            rows.append(
                {
                    "instance": inst,
                    "quantity": key,
                    "target": value,
                    "value": v,
                    "error": None if v is None else v - value,
                }
            )
    _track.emit("compare", targets=targets, extracted=extracted)
    return rows


__all__ = ["compare", "extract", "resonator_frequency_GHz", "route_attached_to", "split_port_ref"]
