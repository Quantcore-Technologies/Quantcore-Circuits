"""Mathematical bridges from simulation results to circuit element values.

1. Maxwell C-matrix → branch capacitances: C_ij = −C_ij(Maxwell) (i ≠ j), C_i0 = Σ_j C_ij(Maxwell).
2. Distributed λ/4 resonator → LC at its open end: C_r = π/(4 ω_r Z0), L_r = 4 Z0/(π ω_r); v_ph and Z0 from Metal's
   CPW formulas on the PDK stack (:func:`quantcore_circuits.analysis.synthesis.cpw_properties`).
3. Junction: Rn ↔ Ic (Ambegaokar–Baratoff at T = 0: Ic·Rn = πΔ/2e) ↔ Lj = Φ0/(2π Ic); area → Rn through the PDK
   specific resistance; SQUID → EJ(Φ) = EJΣ |cos πΦ| √(1 + d² tan² πΦ). The Quantcore trilayer rule
   (:class:`quantcore_circuits.pdk.JunctionProcess`: Δ = 1.4 meV, R_n 40–50 kΩ, f_q 4–8 GHz) sizes junctions:
   :func:`size_junction` (target f_q and C_Σ → E_J, L_J, R_n, area, finger widths), :func:`junction_from_fingers`
   (drawn fingers → R_n, I_c, L_J, E_J, C_J), :func:`fingers_for_lj` (what the junction cells use).
4. Ports: a 50 Ω resistor on feedline nodes (κ in QuCat).
5. Participations → ϕ_zpf: :mod:`quantcore_circuits.analysis.epr`.

Units: fF, nH, Ω, µm, GHz.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

E = 1.602176634e-19
H = 6.62607015e-34
PHI0 = 2.067833848e-15
DELTA_NB_MEV = 1.40  # Nb gap (trilayer Nb/AlOx/Nb junctions); pass delta_meV for Al (≈ 0.18–0.20)


def branch_capacitances(maxwell_fF, labels: list[str], ground: str = "ground") -> dict[tuple[str, str], float]:
    """Maxwell matrix (signal nets only, as Q3D/Elmer/Palace export it) → branch capacitances in fF.

    Keys are ``(net, ground)`` for capacitance to ground and ``(net_i, net_j)`` (i < j in ``labels`` order).
    """
    c = np.asarray(maxwell_fF, dtype=float)
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(labels):
        out[(a, ground)] = float(c[i].sum())
        for j in range(i + 1, len(labels)):
            out[(a, labels[j])] = float(-c[i, j])
    return out


def maxwell_from_branches(branches: dict[tuple[str, str], float], labels: list[str], ground: str = "ground"):
    """Inverse of :func:`branch_capacitances` (for tests and for building Maxwell matrices from a circuit)."""
    n = len(labels)
    idx = {lab: i for i, lab in enumerate(labels)}
    c = np.zeros((n, n))
    for (a, b), v in branches.items():
        if b == ground:
            c[idx[a], idx[a]] += v
        elif a == ground:
            c[idx[b], idx[b]] += v
        else:
            i, j = idx[a], idx[b]
            c[i, i] += v
            c[j, j] += v
            c[i, j] -= v
            c[j, i] -= v
    return c


def quarter_wave_lc(f_r_GHz: float, z0: float = 50.0) -> tuple[float, float]:
    """(C fF, L nH) of a λ/4 resonator near resonance seen from its open end."""
    w = 2 * math.pi * f_r_GHz * 1e9
    c = math.pi / (4 * w * z0)
    return c / 1e-15, 4 * z0 / (math.pi * w) / 1e-9


def tl_resonator(length_um: float, a_um: float, b_um: float, pdk_name: str | None = None, guess_GHz: float = 7.0):
    """λ/4 CPW resonator of ``length_um`` → {f_GHz, Z0_ohm, vp_m_s, eps_eff, C_fF, L_nH, + L_geo/L_k/alpha_k} (fixed
    point on f). The film's kinetic inductance (``pdk.kinetic``, decision #45) is in v_p and Z0: f = f_geo/√(1+L_k/L_geo);
    ``alpha_k`` = L_k/(L_k+L_geo) of the line and ``f_geo_GHz`` the purely geometric frequency are reported."""
    from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import DEFAULT_PDK  # pylint: disable=import-outside-toplevel

    pdk_name = pdk_name or DEFAULT_PDK
    f = guess_GHz
    props = {}
    for _ in range(4):
        props = cpw_properties(f, a_um, b_um, pdk_name)
        f = props["vp_m_s"] / (4 * length_um * 1e-6) / 1e9
    c, ind = quarter_wave_lc(f, props["Z0_ohm"])
    keys = ("Z0_ohm", "vp_m_s", "eps_eff", "L_geo_nH_per_m", "L_k_nH_per_m", "alpha_k")
    return {
        "f_GHz": f,
        **{k: props[k] for k in keys},
        "f_geo_GHz": f * math.sqrt(1.0 + props["L_k_nH_per_m"] / props["L_geo_nH_per_m"]),
        "C_fF": c,
        "L_nH": ind,
    }


def ic_from_rn(rn_ohm: float, delta_meV: float = DELTA_NB_MEV) -> float:
    """Ambegaokar–Baratoff critical current (A) at T = 0."""
    return math.pi * delta_meV * 1e-3 / (2 * rn_ohm)  # πΔ/(2 e Rn), Δ in eV


def rn_from_ic(ic_A: float, delta_meV: float = DELTA_NB_MEV) -> float:
    return math.pi * delta_meV * 1e-3 / (2 * ic_A)


def lj_from_ic(ic_A: float) -> float:
    """Josephson inductance (nH)."""
    return PHI0 / (2 * math.pi * ic_A) / 1e-9


def ic_from_lj(lj_nH: float) -> float:
    return PHI0 / (2 * math.pi * lj_nH * 1e-9)


def rn_from_area(area_um2: float, rn_area_ohm_um2: float) -> float:
    """Normal-state resistance from junction area and the PDK specific resistance Rn·A (Ω·µm²)."""
    return rn_area_ohm_um2 / area_um2


def lj_from_area(area_um2: float, rn_area_ohm_um2: float, delta_meV: float = DELTA_NB_MEV) -> float:
    return lj_from_ic(ic_from_rn(rn_from_area(area_um2, rn_area_ohm_um2), delta_meV))


def area_from_rn(rn_ohm: float, rn_area_ohm_um2: float) -> float:
    """Junction area (µm²) for a normal-state resistance, from the specific resistance Rn·A (Ω·µm²)."""
    return rn_area_ohm_um2 / rn_ohm


def lj_from_rn(rn_ohm: float, delta_meV: float = DELTA_NB_MEV) -> float:
    """Josephson inductance (nH) of a junction of normal-state resistance ``rn_ohm`` (Ambegaokar–Baratoff, T = 0)."""
    return lj_from_ic(ic_from_rn(rn_ohm, delta_meV))


def rn_from_lj(lj_nH: float, delta_meV: float = DELTA_NB_MEV) -> float:
    return rn_from_ic(ic_from_lj(lj_nH), delta_meV)


def ej_from_lj(lj_nH: float) -> float:
    """E_J/h (GHz) = (Φ0/2π)² / L_J / h."""
    return (PHI0 / (2 * math.pi)) ** 2 / (lj_nH * 1e-9) / H / 1e9


def lj_from_ej(ej_GHz: float) -> float:
    return (PHI0 / (2 * math.pi)) ** 2 / (ej_GHz * 1e9 * H) / 1e-9


def ec_from_c(c_fF: float) -> float:
    """E_C/h (GHz) = e² / (2 C) / h."""
    return E**2 / (2 * c_fF * 1e-15) / H / 1e9


def c_from_ec(ec_GHz: float) -> float:
    return E**2 / (2 * ec_GHz * 1e9 * H) / 1e-15


def transmon_f01(ej_GHz: float, ec_GHz: float) -> float:
    """Transmon 0→1 frequency (GHz), asymptotic √(8 E_J E_C) − E_C (E_J/E_C ≫ 1)."""
    return math.sqrt(8 * ej_GHz * ec_GHz) - ec_GHz


def ej_for_f01(f01_GHz: float, ec_GHz: float) -> float:
    """E_J/h (GHz) that gives ``f01_GHz`` at ``ec_GHz`` (inverse of :func:`transmon_f01`)."""
    return (f01_GHz + ec_GHz) ** 2 / (8 * ec_GHz)


def junction_process(pdk=None):
    """The :class:`~quantcore_circuits.pdk.JunctionProcess` of a PDK (name, ``Pdk`` or None = default PDK); a
    ``JunctionProcess`` passes through."""
    from quantcore_circuits.pdk import JunctionProcess, Pdk, get_pdk  # pylint: disable=import-outside-toplevel

    if isinstance(pdk, JunctionProcess):
        return pdk
    if isinstance(pdk, Pdk):
        return pdk.junction
    return get_pdk(pdk).junction if pdk else get_pdk().junction


@dataclass
class JunctionValues:
    """Electrical values of ``n`` identical trilayer cross junctions in parallel (n = 2: a symmetric SQUID at zero
    flux). Per-junction values carry ``_each``; ``rn_kohm``, ``lj_nH``, ``ej_GHz``, ``cj_fF`` are the device totals."""

    straight_um: float
    bent_um: float
    n: int
    area_each_um2: float
    rn_each_kohm: float
    ic_each_nA: float
    rn_kohm: float
    lj_nH: float
    ej_GHz: float
    cj_fF: float
    rn_in_window: bool

    def as_dict(self) -> dict:
        return asdict(self)


def junction_from_fingers(straight_um: float, bent_um: float | None = None, n: int = 1, pdk=None) -> JunctionValues:
    """Drawn cross junction(s) → R_n, I_c, L_J, E_J, C_J on the PDK junction rule (``bent_um`` None or 0: same as
    the straight finger, as the trilayer cells' ``second_finger_width = 0``)."""
    proc = junction_process(pdk)
    bent = bent_um or straight_um
    area = straight_um * bent
    rn = rn_from_area(area, proc.rn_area_ohm_um2)
    ic = ic_from_rn(rn, proc.gap_meV)
    lj_total = lj_from_ic(ic) / n
    lo, hi = proc.rn_target_kohm
    return JunctionValues(
        straight_um=straight_um,
        bent_um=bent,
        n=n,
        area_each_um2=area,
        rn_each_kohm=rn / 1e3,
        ic_each_nA=ic * 1e9,
        rn_kohm=rn / n / 1e3,
        lj_nH=lj_total,
        ej_GHz=ej_from_lj(lj_total),
        cj_fF=proc.cj_fF_per_um2 * area * n,
        rn_in_window=lo <= rn / n / 1e3 <= hi,
    )


def _grid(x: float, step: float) -> float:
    return round(round(x / step) * step, 6) if step > 0 else x


def fingers_for_lj(lj_nH: float, n: int = 1, pdk=None, bent_um: float | None = None) -> tuple[float, float, list[str]]:
    """(straight µm, bent µm, notes) of ``n`` parallel junctions with total L_J ``lj_nH`` on the PDK rule.

    The bent finger stays at ``bent_um`` (default the PDK's ``bent_finger_um``); the straight finger gives the area,
    rounded to ``finger_grid_um``. Below ``finger_range_um[0]`` the straight finger is held at the minimum and the
    bent finger takes the area; above the maximum it is clipped (notes say so)."""
    proc = junction_process(pdk)
    lo, hi = proc.finger_range_um
    bent = bent_um or proc.bent_finger_um
    area = area_from_rn(rn_from_lj(lj_nH * n, proc.gap_meV), proc.rn_area_ohm_um2)
    straight = _grid(area / bent, proc.finger_grid_um)
    notes = []
    if straight < lo:
        straight = lo
        bent = max(lo, _grid(area / lo, proc.finger_grid_um))
        notes.append(f"straight finger at the minimum {lo:g} µm; bent finger {bent:g} µm carries the area")
    elif straight > hi:
        notes.append(f"straight finger {straight:g} µm clipped to the maximum {hi:g} µm (L_J will be higher)")
        straight = hi
    return straight, bent, notes


@dataclass
class JunctionSizing:
    """Result of :func:`size_junction`: the target, the ideal junction, and the junction as drawn (fingers on the
    PDK grid), with window checks (R_n 40–50 kΩ and f_q 4–8 GHz on the default rule)."""

    f_q_GHz: float
    c_sigma_fF: float
    ec_GHz: float
    ej_GHz: float
    lj_nH: float
    rn_kohm: float
    n: int
    drawn: JunctionValues
    f_q_drawn_GHz: float
    rn_in_window: bool
    f_in_window: bool
    notes: list[str] = field(default_factory=list)

    @property
    def finger_width(self) -> float:
        return self.drawn.straight_um

    @property
    def second_finger_width(self) -> float:
        return self.drawn.bent_um

    def junction_params(self) -> dict:
        """Parameters for the trilayer junction cells (``junction_params`` of an Xmon, a ``Quantcore*`` cell)."""
        return {"finger_width": self.drawn.straight_um, "second_finger_width": self.drawn.bent_um}

    def design_junction(self) -> dict:
        """``design.json`` instance ``junction`` values of the drawn junction (L_J total, C_J total)."""
        return {"Lj_nH": round(self.drawn.lj_nH, 4), "Cj_fF": round(self.drawn.cj_fF, 3)}

    def as_dict(self) -> dict:
        return asdict(self)


def size_junction(
    f_q_GHz: float, c_sigma_fF: float, pdk=None, n: int = 1, c_includes_junction: bool = True
) -> JunctionSizing:
    """Size a Quantcore trilayer junction for a transmon frequency.

    ``c_sigma_fF`` is the total shunt capacitance (``c_includes_junction=False``: without the junction's own C_J,
    which is then added from the sized area, iterated to convergence). E_C = e²/2C_Σ, E_J = (f_q + E_C)²/(8 E_C)
    (inverse of the asymptotic transmon f01), L_J = (Φ0/2π)²/E_J; each of the ``n`` parallel junctions (n = 2: a
    symmetric SQUID at zero flux) gets n·L_J → R_n (Ambegaokar–Baratoff, Δ of the PDK) → area = R_n·A / R_n →
    fingers (:func:`fingers_for_lj`). The drawn junction (fingers on the grid) is re-evaluated; ``rn_in_window``
    checks the device R_n (per junction / n) against ``rn_target_kohm`` and ``f_in_window`` the drawn f_q against
    ``f_q_range_GHz``; ``notes`` say what is outside.
    """
    proc = junction_process(pdk)
    c_total = c_sigma_fF
    lj = 0.0
    for _ in range(50 if not c_includes_junction else 1):
        ec = ec_from_c(c_total)
        ej = ej_for_f01(f_q_GHz, ec)
        lj = lj_from_ej(ej)
        if c_includes_junction:
            break
        cj = proc.cj_fF_per_um2 * area_from_rn(rn_from_lj(lj * n, proc.gap_meV), proc.rn_area_ohm_um2) * n
        if abs(c_sigma_fF + cj - c_total) < 1e-9:
            break
        c_total = c_sigma_fF + cj
    ec = ec_from_c(c_total)
    ej = ej_for_f01(f_q_GHz, ec)
    rn_total = rn_from_lj(lj, proc.gap_meV)
    straight, bent, notes = fingers_for_lj(lj, n, proc)
    drawn = junction_from_fingers(straight, bent, n, proc)
    c_drawn = c_total if c_includes_junction else c_sigma_fF + drawn.cj_fF
    f_drawn = transmon_f01(drawn.ej_GHz, ec_from_c(c_drawn))
    lo, hi = proc.rn_target_kohm
    flo, fhi = proc.f_q_range_GHz
    rn_ok = lo <= rn_total / 1e3 <= hi
    f_ok = flo <= f_drawn <= fhi
    if not rn_ok:
        notes.append(
            f"R_n {rn_total / 1e3:.1f} kΩ is outside the process window {lo:g}–{hi:g} kΩ "
            f"(f_q {f_q_GHz:g} GHz with C_Σ {c_total:.1f} fF needs E_J/h {ej:.1f} GHz)"
        )
    if not f_ok:
        notes.append(f"drawn f_q {f_drawn:.2f} GHz is outside {flo:g}–{fhi:g} GHz")
    return JunctionSizing(
        f_q_GHz=f_q_GHz,
        c_sigma_fF=c_total,
        ec_GHz=ec,
        ej_GHz=ej,
        lj_nH=lj,
        rn_kohm=rn_total / 1e3,
        n=n,
        drawn=drawn,
        f_q_drawn_GHz=f_drawn,
        rn_in_window=rn_ok,
        f_in_window=f_ok,
        notes=notes,
    )


def squid_ej(ej_sum_GHz: float, asym: float, flux_phi0: float) -> float:
    """Effective EJ of an asymmetric DC SQUID (d = (EJ1 − EJ2)/(EJ1 + EJ2)) at flux Φ/Φ0."""
    x = math.pi * flux_phi0
    return ej_sum_GHz * abs(math.cos(x)) * math.sqrt(1 + asym**2 * math.tan(x) ** 2)


def stack_capacitance_scale(eps_from: float, eps_to: float) -> float:
    """Approximate rescaling of planar (CPW-like) capacitances between substrates: C ∝ (εr + 1)/2."""
    return (eps_to + 1) / (eps_from + 1)
