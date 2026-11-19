"""Parametric-amplifier models for the amplifier design notebooks (agent ``amplifiers``): numpy / scipy only.

* **Linear networks** — ABCD matrices over a frequency axis (``series``, ``shunt``, ``cascade``, ``s_params``), the
  Bloch exponent of a periodic unit (``bloch``: cosh γ = (A + D)/2), ladders of JJ / KI cells (``jj_cell``,
  ``ki_cell``), a SQUID-terminated λ/4 CPW resonator (``cpw_jpa_s11``) and the resonance / linewidth of a reflection
  (``resonance``: f0 at the steepest phase, κ/2π = 4 / max|dφ/df|, a lossless one-port).
* **Resonant paramps** — the linearised single-mode Langevin equation in the pump frame (``paramp_reflection``):
  ȧ = −(κ/2 + iδ0) a − i g a† + √κ_e a_in, a_out = √κ_e a − a_in. Flux pumping (Yamamoto 2008; QPDK
  ``vacask_cpw_parametric_amplifier``): ω0(t) = ω0 + δω cos ω_p t → g = δω/2, threshold δω = κ, peak gain
  ((1 + r²)/(1 − r²))², r = δω/κ (Roy & Devoret 2016). Kerr (current) pumping (Eichler & Wallraff 2014; twpa-sim
  ``twpa.jpa``): pump photons n from n[(κ/2)² + (Δ − K n)²] = κ_e Φ_in, then δ0 = ω0 − ω_p + 2Kn, g = K n.
* **Travelling-wave gain** — coupled-mode equations with an undepleted pump for a line whose inductance is
  L(I) = L0 (1 + ε I + ξ I²) (Chaudhuri, Gao & Irwin 2015; Malnou et al. 2021; O'Brien et al. 2014):
  4WM (ω_s + ω_i = 2ω_p): SPM α_p = k_p ξ I_p²/8, XPM α_{s,i} = k_{s,i} ξ I_p²/4, coupling γ_{s,i} = k_{s,i} ξ I_p²/8,
  Δβ = (2k_p − k_s − k_i) + 2α_p − α_s − α_i; 3WM (ω_s + ω_i = ω_p): γ_{s,i} = k_{s,i} ε I_p/4,
  Δβ = (k_p − k_s − k_i) + α_p − α_s − α_i; G = 1 + (γ_s γ_i / g²) sinh²(g N), g² = γ_s γ_i − (Δβ/2)² (k per cell,
  N cells). A JJ line has ξ = 1/(2 I_c²) (QPDK: the pump's own inductance × (1 + x/8), the signal's × (1 + x/4),
  x = (I_p/I_c)²); a KI line ε = 2 I_dc/(I*² + I_dc²), ξ = 1/(I*² + I_dc²) on its kinetic share α_k.

These are first-order models: they explain trends and reproduce the sources' headline numbers, they are not a
harmonic-balance solution (JosephsonCircuits.jl / VACASK are not in this environment).
"""

from __future__ import annotations

import math

import numpy as np

PHI0 = 2.067833848e-15  # Wb
H_PLANCK = 6.62607015e-34


def lj_from_ic(ic_A: float) -> float:
    """Josephson inductance L_J = Φ0 / (2π I_c), H."""
    return PHI0 / (2 * math.pi * ic_A)


def ic_from_lj(lj_H: float) -> float:
    return PHI0 / (2 * math.pi * lj_H)


def squid_ls(ls0, flux_phi0, asym: float = 0.0):
    """L_s(Φ) of a DC SQUID (no loop inductance): L_s0 / √(cos² πΦ + d² sin² πΦ)."""
    x = np.pi * np.asarray(flux_phi0, dtype=float)
    return ls0 / np.sqrt(np.cos(x) ** 2 + asym**2 * np.sin(x) ** 2)


# ---- ABCD networks ---------------------------------------------------------------------------------------------------
def series(z) -> np.ndarray:
    z = np.atleast_1d(np.asarray(z, dtype=complex))
    m = np.zeros(z.shape + (2, 2), dtype=complex)
    m[..., 0, 0] = m[..., 1, 1] = 1
    m[..., 0, 1] = z
    return m


def shunt(y) -> np.ndarray:
    y = np.atleast_1d(np.asarray(y, dtype=complex))
    m = np.zeros(y.shape + (2, 2), dtype=complex)
    m[..., 0, 0] = m[..., 1, 1] = 1
    m[..., 1, 0] = y
    return m


def cascade(*mats) -> np.ndarray:
    out = mats[0]
    for m in mats[1:]:
        out = out @ m
    return out


def power(m: np.ndarray, n: int) -> np.ndarray:
    """``m`` (…, 2, 2) to the n-th power per frequency (repeated squaring)."""
    out = np.broadcast_to(np.eye(2, dtype=complex), m.shape).copy()
    base = m.copy()
    while n:
        if n & 1:
            out = out @ base
        base = base @ base
        n >>= 1
    return out


def s_params(abcd: np.ndarray, z0: float = 50.0) -> tuple[np.ndarray, np.ndarray]:
    """(S11, S21) of a two-port between z0 ports."""
    a, b, c, d = abcd[..., 0, 0], abcd[..., 0, 1], abcd[..., 1, 0], abcd[..., 1, 1]
    den = a + b / z0 + c * z0 + d
    return (a + b / z0 - c * z0 - d) / den, 2 / den


def bloch(unit: np.ndarray) -> np.ndarray:
    """Complex Bloch exponent γ of a periodic unit: cosh γ = (A + D)/2 (Re γ: attenuation, Im γ: phase per unit),
    branch with Im γ ≥ 0, unwrapped along the frequency axis."""
    g = np.arccosh((unit[..., 0, 0] + unit[..., 1, 1]) / 2)
    g = np.where(g.imag < 0, -g, g)
    return g


def unwrap_bloch(phase) -> np.ndarray:
    """Unfold a Bloch phase per unit (``bloch(unit).imag``, folded into [0, π]) along an increasing frequency axis:
    after each Bragg stop band the folded phase runs back from π to 0 (or 0 to π); the true phase keeps increasing
    (2mπ ± φ, the smallest candidate not below the previous value). Needed for long units (a KI-TWPA supercell of 54
    cells passes the zone edge inside the band)."""
    phase = np.asarray(phase, dtype=float)
    out = np.empty_like(phase)
    prev = 0.0
    two_pi = 2 * np.pi
    for i, p in enumerate(phase):
        m = np.floor(prev / two_pi)
        cands = [two_pi * (m + j) + s * p for j in (0, 1, 2) for s in (1, -1)]
        prev = min(c for c in cands if c >= prev - 1e-9)
        out[i] = prev
    return out


def char_impedance(unit: np.ndarray) -> np.ndarray:
    """Bloch impedance of a symmetric unit: √(B/C)."""
    return np.sqrt(unit[..., 0, 1] / unit[..., 1, 0])


# ---- ladders --------------------------------------------------------------------------------------------------------
def jj_cell(f, lj_H, cj_F, cg_F, resonator: tuple[float, float, float] | None = None) -> np.ndarray:
    """Symmetric JTWPA unit cell: half shunt — series (L_J ∥ C_J) — half shunt. ``resonator`` = (C_c, L_r, C_r):
    the shunt gains C_c in series with L_r ∥ C_r (O'Brien 2014 resonant phase matching)."""
    w = 2 * np.pi * np.asarray(f, dtype=float)
    z_j = 1j * w * lj_H / (1 - w**2 * lj_H * cj_F)
    y = 1j * w * cg_F
    if resonator is not None:
        cc, lr, cr = resonator
        z_r = 1j * w * lr / (1 - w**2 * lr * cr)
        y = y + 1 / (1 / (1j * w * cc) + z_r)
    return cascade(shunt(y / 2), series(z_j), shunt(y / 2))


def jtwpa_unit(f, lj_H, cj_F, cg_F, every: int = 0, resonator=None, cg_loaded_F=None) -> np.ndarray:
    """One repeat unit of a (resonator-loaded) JJ chain: ``every`` cells with the resonator on the last (or one
    plain cell when ``every`` is 0)."""
    if not every or resonator is None:
        return jj_cell(f, lj_H, cj_F, cg_F)
    plain = jj_cell(f, lj_H, cj_F, cg_F)
    loaded = jj_cell(f, lj_H, cj_F, cg_F if cg_loaded_F is None else cg_loaded_F, resonator)
    return cascade(*([plain] * (every - 1)), loaded)


def ki_cell(f, l_H, c_F, l_stub_H: float = 0.0) -> np.ndarray:
    """KI-TWPA cell (twpa-sim ``Cell``, shunt-series): two finger capacitors C/2 to ground, each through its
    stub inductance, then the series spine inductance."""
    w = 2 * np.pi * np.asarray(f, dtype=float)
    yf = 1 / (1j * w * l_stub_H + 1 / (1j * w * c_F / 2))
    return cascade(shunt(yf), series(1j * w * l_H), shunt(yf))  # symmetric: one finger each side of the spine


def ki_supercell(f, l_H, c_u_F, c_l_F, unloaded: int, loaded: int, stub_u_H=0.0, stub_l_H=0.0) -> np.ndarray:
    """twpa-sim supercell: unloaded/2 plain cells, ``loaded`` cells with the shorter fingers, unloaded/2 plain."""
    u = ki_cell(f, l_H, c_u_F, stub_u_H)
    lo = ki_cell(f, l_H, c_l_F, stub_l_H)
    half = power(u, unloaded // 2)
    return cascade(half, power(lo, loaded), half)


# ---- SQUID-terminated λ/4 JPA ---------------------------------------------------------------------------------------
def cpw_jpa_s11(
    f, cc_F, z0_ohm, vp_m_s, length_um, ls_H, z_port: float = 50.0, loss_tangent: float = 0.0, eps_fill: float = 1.0
):
    """Reflection of port — C_c — λ/4 CPW (Z0, v_p, ``length_um``) — L_s to ground (the SQUID), exact TL formula.
    ``loss_tangent`` adds dielectric loss (α = β tanδ / 2 · ``eps_fill``)."""
    w = 2 * np.pi * np.asarray(f, dtype=float)
    beta = w / vp_m_s * (1 - 0.5j * loss_tangent * eps_fill)
    t = np.tan(beta * length_um * 1e-6)
    zl = 1j * w * ls_H
    zin = z0_ohm * (zl + 1j * z0_ohm * t) / (z0_ohm + 1j * zl * t) + 1 / (1j * w * cc_F)
    return (zin - z_port) / (zin + z_port)


def resonance(f, s) -> tuple[float, float]:
    """(f0 Hz, κ/2π Hz) of a one-port resonance in a reflection trace: the steepest phase and 4 / max|dφ/df|
    (exact for a lossless reflection resonator; overcoupled traces stay close)."""
    f = np.asarray(f, dtype=float)
    phi = np.unwrap(np.angle(np.asarray(s)))
    slope = np.abs(np.gradient(phi, f))
    i = int(np.argmax(slope))
    return float(f[i]), float(4.0 / slope[i])


# ---- single-mode paramps --------------------------------------------------------------------------------------------
def paramp_reflection(omega, kappa_e, kappa_i, delta0, g):
    """(S_ss, S_si): signal reflection and idler conversion at offset ``omega`` (rad/s) from the pump frame of a
    single-mode paramp with detuning ``delta0`` and pump coupling ``g`` (rad/s)."""
    omega = np.asarray(omega, dtype=float)
    k = kappa_e + kappa_i
    m11 = k / 2 + 1j * (delta0 - omega)
    m22 = k / 2 - 1j * (delta0 + omega)
    m12, m21 = 1j * g, -1j * np.conj(g)
    det = m11 * m22 - m12 * m21
    return kappa_e * m22 / det - 1, kappa_e * (-m12) / det


def flux_pumped_gain(detuning_Hz, kappa_Hz, r, kappa_i_Hz: float = 0.0):
    """Phase-preserving gain |S_ss|² vs signal detuning from f_p/2 (pump at 2 f0), pump ratio r = δω/κ."""
    k = 2 * np.pi * kappa_Hz
    ki = 2 * np.pi * kappa_i_Hz
    s, _ = paramp_reflection(2 * np.pi * np.asarray(detuning_Hz), k - ki, ki, 0.0, r * k / 2)
    return np.abs(s) ** 2


def flux_pumped_peak_gain(r):
    r = np.asarray(r, dtype=float)
    return ((1 + r**2) / (1 - r**2)) ** 2


def kerr_pump_photons(delta_p, kerr, kappa_e, kappa_i, flux_in) -> list[tuple[float, bool]]:
    """Intracavity pump photons n (all non-negative roots) for pump detuning Δ = ω_p − ω0, self-Kerr K (rad/s,
    negative for a junction), incident photon flux Φ_in (1/s); each with its linear stability."""
    k = kappa_e + kappa_i
    roots = np.roots([kerr**2, -2 * delta_p * kerr, delta_p**2 + k**2 / 4, -kappa_e * flux_in])
    out = []
    for n in sorted(float(r.real) for r in roots if abs(r.imag) < 1e-6 * max(abs(r), 1) and r.real >= 0):
        d0 = -delta_p + 2 * kerr * n
        stable = (abs(kerr * n) ** 2 - d0**2) < k**2 / 4
        out.append((n, bool(stable)))
    return out


def kerr_gain(omega, delta_p, kerr, kappa_e, kappa_i, n):
    """|S_ss|² of a Kerr paramp at pump photon number n (pump frame)."""
    s, _ = paramp_reflection(omega, kappa_e, kappa_i, -delta_p + 2 * kerr * n, kerr * n)
    return np.abs(s) ** 2


# ---- travelling-wave gain (coupled modes, undepleted pump) ----------------------------------------------------------
def cme_gain(k_s, k_i, k_p, n_cells: float, ip_A: float, xi: float = 0.0, eps: float = 0.0, mode: str = "4wm"):
    """Signal power gain of a TWPA of ``n_cells`` cells (k in rad/cell), pump amplitude ``ip_A``; returns
    (G, Δβ per cell, g per cell). See the module docstring for the coefficients."""
    k_s, k_i = np.asarray(k_s, dtype=float), np.asarray(k_i, dtype=float)
    a_p = k_p * xi * ip_A**2 / 8
    a_s, a_i = k_s * xi * ip_A**2 / 4, k_i * xi * ip_A**2 / 4
    if mode == "4wm":
        gs, gi = k_s * xi * ip_A**2 / 8, k_i * xi * ip_A**2 / 8
        dbeta = (2 * k_p - k_s - k_i) + 2 * a_p - a_s - a_i
    elif mode == "3wm":
        gs, gi = k_s * eps * ip_A / 4, k_i * eps * ip_A / 4
        dbeta = (k_p - k_s - k_i) + a_p - a_s - a_i
    else:
        raise ValueError(f"mode must be '4wm' or '3wm', got {mode!r}")
    g2 = gs * gi - (dbeta / 2) ** 2
    g = np.sqrt(g2.astype(complex))
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(np.abs(g2) > 1e-30, gs * gi / g2, 0.0)
        gain = 1 + ratio * np.sinh(g * n_cells) ** 2
        gain = np.where(np.abs(g2) > 1e-30, gain, 1 + gs * gi * n_cells**2)
    return np.real(gain), dbeta, np.real(g)


def ki_nonlinearity(i_star_A: float, i_dc_A: float = 0.0, alpha_k: float = 1.0, kerr_factor: float = 1.0):
    """(ε, ξ) of a KI line, twpa-sim ``Bias``: ε = 2 I_dc/(I*² + I_dc²), ξ = kerr/(I*² + I_dc²), times the kinetic
    share α_k of the line inductance (only L_k is current-dependent)."""
    d = i_star_A**2 + i_dc_A**2
    return alpha_k * 2 * i_dc_A / d, alpha_k * kerr_factor / d


def db(x):
    return 10 * np.log10(np.asarray(x, dtype=float))
