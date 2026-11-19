"""Parameter cards, chip elements and the process summary for the dashboard (``State.sections`` / ``cards`` /
``summary`` / ``elements``).

Every number the loop produces gets a card: what it is, its value (chosen estimator / FEM / estimate), where it
comes from (dependency chips pointing at the card they come from), the target or design value, the estimator range
and the formula. Cards are organised by chip **element** so a chip with any number of qubits reads the same way:

* ``elements`` — one entry per qubit, readout resonator, bus, coupler, feedline and port, with its key parameters
  (value / unit / status / target, the card that explains it) and its links (which resonator reads which qubit, which
  feedline it hangs off, which pad biases it). The dashboard's chip overview table is built from this list.
* every card carries ``element`` (``"Q1"``, ``"R1"``, … or ``"chip"`` for process / simulation / jobs / feedback);
  coupling cards also carry ``partner`` (element ``"Q1"``, partner ``"R1"``), so they show under that pair.

Works on LOM-only analyses (layout estimates, no FEM job) and on FEM-filled ones, for N transmon–resonator pairs.
"""

from __future__ import annotations

import math

CHIP = "chip"


def _fmt(v, unit=""):
    if v is None:
        return "–"
    if isinstance(v, str):
        return v
    a = abs(v)
    s = f"{v:.4g}" if a < 1e4 else f"{v:,.0f}"
    return f"{s} {unit}".strip()


class _Cards:
    def __init__(self):
        self.cards: list[dict] = []
        self.sections: list[dict] = []
        self.n = 0
        self.ids: set[str] = set()

    def section(self, ident, letter, title, subtitle=""):
        if ident not in {s["id"] for s in self.sections}:
            self.sections.append({"id": ident, "letter": letter, "title": title, "subtitle": subtitle})

    def card(self, section, element, title, symbol, value, unit, *, ident, partner=None, **kw) -> str:
        """Add a card; returns its id (use it as a ``from`` reference)."""
        self.n += 1
        if ident in self.ids:
            ident = f"{ident}#{self.n}"
        self.ids.add(ident)
        self.cards.append(
            {
                "id": ident,
                "section": section,
                "element": element,
                **({"partner": partner} if partner else {}),
                "index": self.n,
                "title": title,
                "symbol": symbol,
                "value": None if value is None or not _isfinite(value) else float(value),
                "unit": unit,
                **{k: v for k, v in kw.items() if v is not None},
            }
        )
        return ident


def _row(rows, param):
    return next((r for r in rows if r.param == param), None)


def _range(r):
    if r is None or not r.values:
        return None
    vs = [v for v in r.values.values() if v is not None]
    return [min(vs), max(vs)] if len(vs) > 1 else None


def _target(r):
    return {"value": r.target, "tol": r.tol} if r is not None and r.target is not None else None


def _status(r):
    return (
        r.status
        if r is not None and r.status in ("pass", "fail")
        else ("warn" if r is not None and r.flagged else None)
    )


def _chosen(r):
    return r.chosen if r is not None else None


def _param(key, label, symbol, value, unit, row=None, card=None, of=None, source=None, status=None) -> dict:
    """One ``ElementParam``: a column of the chip overview table."""
    out = {
        "key": key,
        "label": label,
        "symbol": symbol,
        "value": None if value is None or not _isfinite(value) else float(value),
        "unit": unit,
    }
    if row is not None:
        if row.target is not None:
            out["target"] = {"value": row.target, "tol": row.tol}
        status = status or _status(row)
        source = source or row.chosen_by
    if status:
        out["status"] = status
    if source:
        out["source"] = source
    if card:
        out["card"] = card
    if of:
        out["of"] = of
    return out


def _worst(params) -> str | None:
    st = {p.get("status") for p in params}
    return next((s for s in ("fail", "warn", "pass") if s in st), None)


class _Topology:
    """Who is who in the circuit model: qubits, readout resonators, buses, couplers, feedlines, ports, flux lines."""

    def __init__(self, design, model, plan):
        self.model, self.design = model, design
        gnd = model.ground
        br = model.branches
        self.qubit_junction: dict[str, str] = {}
        for name, b in br.items():
            if b.type in ("JJ", "SQUID"):
                q = b.nodes[0] if b.nodes[1] == gnd else b.nodes[1]
                self.qubit_junction.setdefault(q, name)
        self.qubits = list(self.qubit_junction)
        cap = [(n, b) for n, b in br.items() if b.type == "C"]

        def qubits_at(node):
            return [q for q in self.qubits if any(set(b.nodes) == {q, node} for _, b in cap)]

        self.resonators: dict[str, dict] = {}  # TLres name → {"node", "qubits", "feedline", "hanger", "kind"}
        for name, b in br.items():
            if b.type != "TLres":
                continue
            node = b.nodes[0] if b.nodes[1] == gnd else b.nodes[1]
            hanger = next((h for h, x in br.items() if x.type == "HANGER" and node in x.nodes), None)
            fl = None
            if hanger:
                hb = br[hanger].nodes
                fl = hb[1] if hb[0] == node else hb[0]
            qs = qubits_at(node)
            kind = "bus" if len(qs) >= 2 else "resonator"
            self.resonators[name] = {"node": node, "qubits": qs, "feedline": fl, "hanger": hanger, "kind": kind}
        self.couplers = {
            n: list(b.nodes) for n, b in cap if b.nodes[0] in self.qubits and b.nodes[1] in self.qubits
        }  # direct island–island capacitances
        fls = [r["feedline"] for r in self.resonators.values() if r["feedline"]]
        fls += [b.nodes[0] for n, b in br.items() if b.type == "R" and b.nodes[1] == gnd]
        self.feedlines = [n for n in dict.fromkeys(fls) if n and n != gnd]
        # ports: pads at the ends of feedline routes and of flux / control lines (from the design's routes)
        self.ports: dict[str, dict] = {}  # pad instance → {"role", "to", "line", "length_um"}
        self.flux: dict[str, str] = {}  # qubit → pad
        for rname, route in design.routes.items():
            ends = [e for e in (route.from_, route.to) if isinstance(e, str)]
            insts = [e.split(".", 1) for e in ends]
            length = plan.routes[rname].length if rname in plan.routes else None
            if rname in self.feedlines:
                for inst, _ in insts:
                    self.ports[inst] = {"role": "feedline", "to": rname, "line": rname, "length_um": length}
                continue
            qubit_end = next(((i, p) for i, p in insts if i in self.qubits and "flux" in p), None)
            if qubit_end and len(insts) == 2:
                pad = next(i for i, p in insts if (i, p) != qubit_end)
                self.ports[pad] = {"role": "flux", "to": qubit_end[0], "line": rname, "length_um": length}
                self.flux[qubit_end[0]] = pad
        self.fl_ports = {
            fl: [p for p, v in self.ports.items() if v["role"] == "feedline" and v["to"] == fl] for fl in self.feedlines
        }
        self.feedline_length = {fl: plan.routes[fl].length if fl in plan.routes else None for fl in self.feedlines}


def build(design, an, proposal=None, jobs=None) -> dict:
    """``{"sections", "cards", "summary", "elements"}`` from an :class:`~quantcore_circuits.loop.Analysis`."""
    from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.analysis.transmon import transmon_spectrum  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.bridges import ic_from_lj, rn_from_ic, squid_ej  # pylint: disable=C0415
    from quantcore_circuits.circuit.fill import two_node_model  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.hamiltonian import purcell_t1_us  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.loop import pair_plot_id  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    pdk = get_pdk(design.pdk)
    st = pdk.stack
    rows = an.rows
    filled = an.filled
    c = _Cards()
    fem = filled.cmatrix is not None
    origin = f"FEM · {filled.job}" if fem else "layout estimates (no FEM yet)"
    # the analysis' own plan when it is of this design (loop.analyse planned it already), else plan it here
    plan = getattr(an, "plan", None)
    if plan is None or getattr(plan, "design", None) is None or plan.design.to_json_dict() != design.to_json_dict():
        plan = plan_design(design)
    topo = _Topology(design, an.model, plan)
    pairs = filled.pairs

    f_ref = next((design.targets.get(p.resonator, {}).get("f_GHz") for p in pairs), None) or 7.0
    cpw = cpw_properties(f_ref, pdk.cpw_a, pdk.cpw_b, design.pdk)
    summary = [
        {
            "id": "process",
            "index": "0",
            "title": "Process and CPW",
            "items": [
                {"label": "Substrate", "value": f"{st.substrate_material} {st.substrate_height:g} µm"},
                {"label": "Permittivity", "symbol": "\\varepsilon_r", "value": st.substrate_permittivity},
                {"label": "Effective permittivity", "symbol": "\\varepsilon_{eff}", "value": round(cpw["eps_eff"], 4)},
                {"label": "Impedance", "symbol": "Z_0", "value": round(cpw["Z0_ohm"], 2), "unit": "Ω"},
                {"label": f"CPW λ/4 at {f_ref:g} GHz", "value": round(cpw["lambda_um"] / 4 / 1e3, 4), "unit": "mm"},
                {"label": "CPW centre / gap", "value": f"{pdk.cpw_a:g} / {pdk.cpw_b:g} µm"},
                {"label": "Values from", "value": origin},
            ],
        }
    ]

    # ---- chip: process and CPW ------------------------------------------------------------------------------------
    c.section("process", "0", "Process and CPW", f"{design.pdk} · values from {origin}")
    c.card(
        "process",
        CHIP,
        "Substrate",
        "\\varepsilon_r",
        st.substrate_permittivity,
        "",
        ident="chip.substrate",
        sub=[
            {"symbol": "h", "value": st.substrate_height, "unit": "µm"},
            {"symbol": "\\varepsilon_{eff}", "value": cpw["eps_eff"], "unit": ""},
        ],
        source="pdk",
        description=f"{st.substrate_material}; ε_eff of the CPW from conformal mapping.",
        formula="\\varepsilon_{eff} \\approx (\\varepsilon_r + 1)/2",
    )
    i_cpw = c.card(
        "process",
        CHIP,
        "CPW line",
        "Z_0",
        cpw["Z0_ohm"],
        "Ω",
        ident="chip.cpw",
        sub=[
            {"symbol": "a", "value": pdk.cpw_a, "unit": "µm"},
            {"symbol": "b", "value": pdk.cpw_b, "unit": "µm"},
            {"symbol": "v_p/c", "value": cpw["vp_m_s"] / 2.998e8, "unit": ""},
        ],
        source="pdk",
        description="PDK default centre width a and gap b.",
        formula="Z_0 = \\frac{30\\pi}{\\sqrt{\\varepsilon_{eff}}} \\frac{K(k')}{K(k)},\\; k = a/(a+2b)",
    )
    c.card(
        "process",
        CHIP,
        f"Quarter wave at {f_ref:g} GHz",
        "\\lambda/4",
        cpw["lambda_um"] / 4,
        "µm",
        ident="chip.lambda4",
        source="pdk",
        **{"from": [{"label": "v_p", "value": _fmt(cpw["vp_m_s"] / 1e8, "×10⁸ m/s"), "ref": i_cpw}]},
        formula="\\lambda/4 = v_p / 4f",
        description="Reference length of a λ/4 CPW resonator on this stack.",
    )

    # FEM net → simulation self-capacitance card id (filled in below, referenced from the pair cards)
    sim_self = {lab: f"sim.self.{lab}" for lab in (filled.cmatrix or {}).get("labels", [])} if fem else {}

    # ---- per transmon–resonator pair -----------------------------------------------------------------------------
    elements: dict[str, dict] = {}
    done_qubits: set[str] = set()
    for p in pairs:
        q, r = p.qubit, p.resonator
        pr = f"{q}{r}"
        tn = two_node_model(p)
        fq, al = _row(rows, f"{q}.f_q_GHz"), _row(rows, f"{q}.alpha_MHz")
        fr, gg, chi = _row(rows, f"{r}.f_GHz"), _row(rows, f"{r}.g_MHz"), _row(rows, f"{r}.chi_MHz")
        jname = topo.qubit_junction.get(q, f"J_{q}")
        syn = filled.values[jname].design if jname in filled.values else None
        cq = filled.values.get(f"C_{q}")
        cnode = topo.resonators.get(r, {}).get("node")
        cgv = next((v for v in filled.values.values() if v.type == "C" and set(v.nodes) == {q, cnode}), None)
        cgv = cgv or next((v for n, v in filled.values.items() if n.startswith(f"Cg_{q}_")), None)
        tlv = filled.values.get(r)
        hv = filled.values.get(f"K_{r}")
        res = an.pair_results.get(q) if getattr(an, "pair_results", None) else None
        res = res if res and res["resonator"] == r else None  # QuTiP solved this qubit with this resonator
        id_cs, id_j, id_cg, id_cpw_r = f"{q}.csigma", f"{q}.junction", f"{pr}.cg", f"{r}.cpw"

        if q not in done_qubits:
            done_qubits.add(q)
            inst = design.instances.get(q)
            jtype = (inst.params.get("junction_type") if inst else None) or ("SQUID" if p.squid else "JJ")
            c.section(f"qubit_{q}", "A", f"Qubit {q}", "Capacitance first, then the junction and the frequency plan.")
            c.card(
                f"qubit_{q}",
                q,
                "Qubit capacitance",
                "C_\\Sigma",
                tn["C_sigma_fF"],
                "fF",
                ident=id_cs,
                sub=[
                    {"symbol": "E_C/h", "value": tn["EC_GHz"] * 1e3, "unit": "MHz"},
                    {"symbol": "C_{island}", "value": cq.value if cq else None, "unit": "fF"},
                ],
                design=(cq.design + (cgv.design or 0) + p.cj_fF) if cq and cq.design and cgv else None,
                source=(cq.origin if cq else None),
                **{
                    "from": [
                        {
                            "label": "C_island",
                            "value": _fmt(cq.value if cq else None, "fF"),
                            "ref": sim_self.get(p.labels[0]),
                        },
                        {"label": "C_g", "value": _fmt(p.cg_fF, "fF"), "ref": id_cg},
                        {"label": "C_J", "value": _fmt(p.cj_fF, "fF"), "ref": id_j},
                    ]
                },
                formula="E_C = e^2 / 2C_\\Sigma",
                description="Total island capacitance including the loaded coupler; sets E_C and the anharmonicity.",
            )
            ic = ic_from_lj(p.lj_nH)
            c.card(
                f"qubit_{q}",
                q,
                "Junction",
                "L_J",
                p.lj_nH,
                "nH",
                ident=id_j,
                sub=[
                    {"symbol": "E_J/h", "value": tn["EJ_GHz"], "unit": "GHz"},
                    {"symbol": "I_c", "value": ic * 1e9, "unit": "nA"},
                    {"symbol": "R_n", "value": rn_from_ic(ic), "unit": "Ω"},
                ],
                design=syn,
                source="design.json",
                **{"from": [{"label": "junction", "value": f"{jtype} · design.json"}]},
                formula="E_J = (\\Phi_0 / 2\\pi)^2 / L_J,\\; I_c R_n = \\pi\\Delta_{Nb}/2e",
                description="Total Josephson inductance at zero flux; R_n from Ambegaokar–Baratoff with Δ_Nb.",
            )
            c.card(
                f"qubit_{q}",
                q,
                "Qubit frequency",
                "f_{01}",
                _chosen(fq),
                "GHz",
                ident=f"{q}.f01",
                target=_target(fq),
                range=_range(fq),
                source=fq.chosen_by if fq else None,
                status=_status(fq),
                **{
                    "from": [
                        {"label": "E_J", "value": _fmt(tn["EJ_GHz"], "GHz"), "ref": id_j},
                        {"label": "E_C", "value": _fmt(tn["EC_GHz"] * 1e3, "MHz"), "ref": id_cs},
                    ]
                },
                formula="f_{01} \\approx \\sqrt{8E_JE_C} - E_C",
                plot=pair_plot_id("levels", q, an) if res and res["dressed"] else None,
                description="Dressed 0→1 transition; the range is the spread over the estimators.",
            )
            c.card(
                f"qubit_{q}",
                q,
                "Anharmonicity",
                "\\alpha/2\\pi",
                _chosen(al),
                "MHz",
                ident=f"{q}.alpha",
                target=_target(al),
                range=_range(al),
                source=al.chosen_by if al else None,
                status=_status(al),
                **{"from": [{"label": "E_C", "value": _fmt(tn["EC_GHz"] * 1e3, "MHz"), "ref": id_cs}]},
                formula="\\alpha \\approx -E_C",
                description="E₁₂ − E₀₁; mostly set by C_Σ.",
            )
            f0, _ = transmon_spectrum(tn["EJ_GHz"], tn["EC_GHz"], 0.0)
            f5, _ = transmon_spectrum(tn["EJ_GHz"], tn["EC_GHz"], 0.5)
            c.card(
                f"qubit_{q}",
                q,
                "Transmon regime",
                "E_J/E_C",
                tn["EJ_GHz"] / tn["EC_GHz"],
                "",
                ident=f"{q}.ejec",
                sub=[{"symbol": "\\epsilon_{01}", "value": abs(f0 - f5) * 1e6, "unit": "kHz"}],
                formula="\\epsilon_{01} = |f_{01}(n_g{=}0) - f_{01}(n_g{=}\\tfrac12)|",
                description="Charge dispersion of the 0→1 line; E_J/E_C ≳ 50 keeps it small.",
            )
            if p.squid:
                ej_sum = tn["EJ_GHz"] * p.ej_sum_ratio  # E_J at zero flux (tn is at the design flux)
                fmin, _ = transmon_spectrum(max(squid_ej(ej_sum, p.asym, 0.45), 1e-6), tn["EC_GHz"])
                pad = topo.flux.get(q)
                c.card(
                    f"qubit_{q}",
                    q,
                    "Flux tuning",
                    "f_{max}",
                    f0,
                    "GHz",
                    ident=f"{q}.flux",
                    sub=[{"symbol": "f(\\pm0.45\\Phi_0)", "value": fmin, "unit": "GHz"}],
                    plot=pair_plot_id("flux", q, an) if res and res["flux"] else None,
                    formula="E_J(\\Phi) = E_{J\\Sigma}|\\cos \\pi\\Phi/\\Phi_0|",
                    **({"from": [_flux_ref(topo, pad)]} if pad else {}),
                    description="Symmetric SQUID; flux line from the bias pad.",
                )

        c.section(f"res_{r}", "B", f"Readout resonator {r}", "λ/4 meander hanging off the feedline.")
        id_len = c.card(
            f"res_{r}",
            r,
            "Resonator length",
            "\\ell",
            tlv.estimate if tlv else None,
            "µm",
            ident=f"{r}.length",
            design=tlv.design if tlv else None,
            source="layout",
            **{"from": [{"label": "route", "value": f"{r} meander"}]},
            description="Routed length, tuned exactly by the meander.",
        )
        c.card(
            f"res_{r}",
            r,
            "Resonator frequency",
            "f_r",
            _chosen(fr),
            "GHz",
            ident=f"{r}.f_r",
            target=_target(fr),
            range=_range(fr),
            source=fr.chosen_by if fr else None,
            status=_status(fr),
            sub=[
                {"symbol": "f_{\\lambda/4}", "value": p.f_r_GHz, "unit": "GHz"},
                {"symbol": "f_{loaded}", "value": tn["f_r_loaded_GHz"], "unit": "GHz"},
            ],
            **{
                "from": [
                    {"label": "ℓ", "value": _fmt(tlv.estimate if tlv else None, "µm"), "ref": id_len},
                    {"label": "C_claw", "value": _fmt(p.c_coupler_fF, "fF"), "ref": sim_self.get(p.labels[1])},
                ]
            },
            formula="f_{\\lambda/4} = v_p / 4\\ell",
            plot=pair_plot_id("readout", q, an) if res and res["readout"] else None,
            description="Dressed resonator frequency; the claw capacitance pulls the bare λ/4 down.",
        )
        cr = tn["C_r_fF"]
        c.card(
            f"res_{r}",
            r,
            "CPW line",
            "Z_0",
            p.z0_ohm,
            "Ω",
            ident=id_cpw_r,
            sub=[
                {"symbol": "C_r", "value": cr, "unit": "fF"},
                {"symbol": "L_r", "value": tn["L_r_nH"], "unit": "nH"},
                {"symbol": "v_p/c", "value": (tlv.extra.get("vp_m_s", 0) / 2.998e8) if tlv else None, "unit": ""},
            ],
            formula="C_r = \\pi/4\\omega_r Z_0,\\; L_r = 4Z_0/\\pi\\omega_r",
            description="λ/4 seen from its open end as a parallel LC.",
        )
        kap = hv.value if hv else None
        fqv, frv, gv = _chosen(fq), _chosen(fr), _chosen(gg)
        t1 = purcell_t1_us(fqv, frv, gv, kap) if kap and fqv and frv and gv else None
        if kap:
            c.card(
                f"res_{r}",
                r,
                "Linewidth",
                "\\kappa/2\\pi",
                kap,
                "MHz",
                ident=f"{r}.kappa",
                sub=[
                    {"symbol": "Q_{ext}", "value": (frv or p.f_r_GHz) * 1e3 / kap, "unit": ""},
                    {"symbol": "T_1^{Purcell}", "value": t1, "unit": "µs"},
                ],
                source=hv.origin,
                status="info",
                **{
                    "from": [
                        {
                            "label": "hanger",
                            "value": f"{hv.extra.get('coupling_length_um', 0):g} µm · "
                            f"gap {hv.extra.get('ground_gap_um', 0):g} µm",
                            "ref": p.feedline,
                        }
                    ]
                },
                formula="Q_{ext} = \\pi / 2k^2\\sin^2\\beta l_c",
                description="Coupled-line estimate (calibrate k from a driven simulation).",
            )

        c.section(f"coupling_{pr}", "C", f"Coupling {q}–{r}", "Claw capacitance, exchange coupling, dispersive shift.")
        c.card(
            f"coupling_{pr}",
            q,
            "Coupling capacitance",
            "C_g",
            p.cg_fF,
            "fF",
            ident=id_cg,
            partner=r,
            design=cgv.design if cgv else None,
            source=cgv.origin if cgv else None,
            sub=[{"symbol": "\\beta = C_g/C_\\Sigma", "value": p.cg_fF / tn["C_sigma_fF"], "unit": ""}],
            description="Island ↔ claw capacitance (C-matrix off-diagonal).",
        )
        g_val = gv if gg else tn["g_MHz"]
        c.card(
            f"coupling_{pr}",
            q,
            "Coupling",
            "g/2\\pi",
            g_val,
            "MHz",
            ident=f"{pr}.g",
            partner=r,
            target=_target(gg),
            range=_range(gg),
            source=gg.chosen_by if gg else "2-node",
            status=_status(gg),
            **{
                "from": [
                    {"label": "C_g", "value": _fmt(p.cg_fF, "fF"), "ref": id_cg},
                    {"label": "C_r", "value": _fmt(cr, "fF"), "ref": id_cpw_r},
                ]
            },
            formula="\\hbar g = 2e\\beta V_{zpf}\\langle 1|\\hat n|0\\rangle",
            description="Exchange coupling of the qubit to the resonator.",
        )
        ro = res["readout"] if res else None
        c.card(
            f"coupling_{pr}",
            q,
            "Dispersive shift",
            "\\chi/2\\pi",
            _chosen(chi),
            "MHz",
            ident=f"{pr}.chi",
            partner=r,
            range=_range(chi),
            source=chi.chosen_by if chi else None,
            status="warn" if chi and chi.flagged else None,
            sub=[
                {"symbol": "\\chi_{readout}", "value": ro["chi_readout_MHz"] if ro else None, "unit": "MHz"},
                {"symbol": "\\chi/\\kappa", "value": (chi.chosen / kap) if chi and kap else None, "unit": ""},
            ],
            formula="\\chi = E_{11} - E_{10} - E_{01} + E_{00}",
            plot=pair_plot_id("readout", q, an) if ro else None,
            description="Full resonator shift between qubit |g⟩ and |e⟩"
            + ("; QuTiP readout simulation cross-checks it." if ro else "."),
        )
        delta = fqv - frv if fqv is not None and frv is not None else None
        if delta is not None:
            c.card(
                f"coupling_{pr}",
                q,
                "Detuning",
                "\\Delta/2\\pi",
                delta,
                "GHz",
                ident=f"{pr}.delta",
                partner=r,
                sub=[{"symbol": "g/\\Delta", "value": (g_val / 1e3) / abs(delta) if delta else None, "unit": ""}],
                description="Qubit–resonator detuning; g/Δ ≪ 1 for the dispersive regime.",
            )

        # elements: the qubit row carries its readout's values (one row per qubit in the overview)
        qe = elements.setdefault(q, _element(q, "qubit", q, _qubit_subtitle(design, q, p.squid)))
        if not qe["params"]:
            qe["params"] = [
                _param("f_q", "Qubit frequency", "f_{01}", fqv, "GHz", fq, f"{q}.f01"),
                _param("alpha", "Anharmonicity", "\\alpha/2\\pi", _chosen(al), "MHz", al, f"{q}.alpha"),
                _param("EJ_EC", "Transmon regime", "E_J/E_C", tn["EJ_GHz"] / tn["EC_GHz"], "", card=f"{q}.ejec"),
                _param("E_C", "Charging energy", "E_C/h", tn["EC_GHz"] * 1e3, "MHz", card=id_cs),
                _param("f_r", "Readout frequency", "f_r", frv, "GHz", fr, f"{r}.f_r", of=r),
                _param("g", "Coupling", "g/2\\pi", g_val, "MHz", gg, f"{pr}.g", of=r),
                _param("chi", "Dispersive shift", "\\chi/2\\pi", _chosen(chi), "MHz", chi, f"{pr}.chi", of=r),
                _param("kappa", "Linewidth", "\\kappa/2\\pi", kap, "MHz", card=f"{r}.kappa" if kap else None, of=r),
                _param("delta", "Detuning", "\\Delta/2\\pi", delta, "GHz", card=f"{pr}.delta", of=r),
                _param("T1_purcell", "Purcell limit", "T_1^{P}", t1, "µs", card=f"{r}.kappa" if kap else None, of=r),
            ]
        qe["links"].append({"to": r, "role": "readout"})
        if q in topo.flux and not any(x["role"] == "flux" for x in qe["links"]):
            qe["links"].append({"to": topo.flux[q], "role": "flux", "label": topo.ports[topo.flux[q]]["line"]})
        re_ = elements.setdefault(
            r, _element(r, "resonator", r, f"λ/4 · hanger on {p.feedline}" if p.feedline else "λ/4")
        )
        re_["params"] = [
            _param("f_r", "Resonator frequency", "f_r", frv, "GHz", fr, f"{r}.f_r"),
            _param("length", "Length", "\\ell", tlv.estimate if tlv else None, "µm", card=f"{r}.length"),
            _param("kappa", "Linewidth", "\\kappa/2\\pi", kap, "MHz", card=f"{r}.kappa" if kap else None),
            _param(
                "Q_ext",
                "External Q",
                "Q_{ext}",
                (frv or p.f_r_GHz) * 1e3 / kap if kap else None,
                "",
                card=f"{r}.kappa" if kap else None,
            ),
            _param("Z0", "Impedance", "Z_0", p.z0_ohm, "Ω", card=id_cpw_r),
        ]
        re_["links"] = [{"to": q, "role": "readout"}] + ([{"to": p.feedline, "role": "feedline"}] if p.feedline else [])

    # ---- qubits without a readout pair, buses, direct couplers --------------------------------------------------
    for q in topo.qubits:
        if q in done_qubits:
            continue
        jv = filled.values.get(topo.qubit_junction[q])
        fq, al = _row(rows, f"{q}.f_q_GHz"), _row(rows, f"{q}.alpha_MHz")
        c.section(f"qubit_{q}", "A", f"Qubit {q}", "No λ/4 readout found in the circuit.")
        c.card(
            f"qubit_{q}",
            q,
            "Junction",
            "L_J",
            jv.value if jv else None,
            "nH",
            ident=f"{q}.junction",
            design=jv.design if jv else None,
            source="design.json",
        )
        for key, row, title, sym, unit in (
            ("f01", fq, "Qubit frequency", "f_{01}", "GHz"),
            ("alpha", al, "Anharmonicity", "\\alpha/2\\pi", "MHz"),
        ):
            if row is not None:
                c.card(
                    f"qubit_{q}",
                    q,
                    title,
                    sym,
                    row.chosen,
                    unit,
                    ident=f"{q}.{key}",
                    target=_target(row),
                    range=_range(row),
                    source=row.chosen_by,
                    status=_status(row),
                )
        e = elements.setdefault(
            q, _element(q, "qubit", q, _qubit_subtitle(design, q, jv is not None and jv.type == "SQUID"))
        )
        e["params"] = [
            _param("f_q", "Qubit frequency", "f_{01}", _chosen(fq), "GHz", fq, f"{q}.f01" if fq else None),
            _param("alpha", "Anharmonicity", "\\alpha/2\\pi", _chosen(al), "MHz", al, f"{q}.alpha" if al else None),
        ]
        if q in topo.flux:
            e["links"].append({"to": topo.flux[q], "role": "flux", "label": topo.ports[topo.flux[q]]["line"]})

    for rname, info in topo.resonators.items():
        if rname in elements:
            continue
        tlv = filled.values.get(rname)
        f_bus = tlv.extra.get("f_GHz") if tlv else None
        kind = info["kind"]
        sec = f"{'bus' if kind == 'bus' else 'res'}_{rname}"
        c.section(sec, "B", f"{'Bus' if kind == 'bus' else 'Resonator'} {rname}", " – ".join(info["qubits"]))
        c.card(sec, rname, "Resonator length", "\\ell", tlv.estimate if tlv else None, "µm", ident=f"{rname}.length")
        c.card(
            sec,
            rname,
            "Bare frequency",
            "f",
            f_bus,
            "GHz",
            ident=f"{rname}.f",
            source="layout",
            description=f"{tlv.extra.get('kind', '')} from the routed length." if tlv else None,
        )
        e = elements.setdefault(rname, _element(rname, kind, rname, tlv.extra.get("kind", "") if tlv else ""))
        e["params"] = [
            _param("f_r", "Bare frequency", "f", f_bus, "GHz", card=f"{rname}.f"),
            _param("length", "Length", "\\ell", tlv.estimate if tlv else None, "µm", card=f"{rname}.length"),
        ]
        e["links"] = [{"to": q, "role": "coupling"} for q in info["qubits"]]
        e["links"] += [{"to": info["feedline"], "role": "feedline"}] if info["feedline"] else []
        for q in info["qubits"]:
            if q in elements:
                elements[q]["links"].append({"to": rname, "role": "coupling"})

    for cname, (qa, qb) in topo.couplers.items():
        v = filled.values.get(cname)
        c.section(f"coupler_{cname}", "C", f"Coupler {qa}–{qb}", "Direct island–island capacitance.")
        c.card(
            f"coupler_{cname}",
            cname,
            "Coupling capacitance",
            "C_c",
            v.value if v else None,
            "fF",
            ident=f"{cname}.C",
            design=v.design if v else None,
            source=v.origin if v else None,
        )
        e = elements.setdefault(cname, _element(cname, "coupler", f"{qa}–{qb}", "capacitive"))
        e["params"] = [_param("C", "Capacitance", "C_c", v.value if v else None, "fF", card=f"{cname}.C")]
        e["links"] = [{"to": qa, "role": "coupling"}, {"to": qb, "role": "coupling"}]
        for q in (qa, qb):
            if q in elements:
                elements[q]["links"].append({"to": cname, "role": "coupling"})

    for fl in topo.feedlines:
        on = [r for r, i in topo.resonators.items() if i["feedline"] == fl]
        fl_ports = topo.fl_ports.get(fl, [])
        e = elements.setdefault(fl, _element(fl, "feedline", fl, f"{len(on)} resonator{'s' if len(on) != 1 else ''}"))
        e["params"] = [
            _param("Z0", "Impedance", "Z_0", cpw["Z0_ohm"], "Ω", card="chip.cpw"),
            _param("length", "Length", "\\ell", topo.feedline_length.get(fl), "µm"),
            _param("n_res", "Resonators", "n_r", len(on), ""),
        ]
        e["links"] = [{"to": r, "role": "readout"} for r in on] + [{"to": pt, "role": "port"} for pt in fl_ports]
    for pad, info in topo.ports.items():
        if pad in elements:
            continue
        e = elements.setdefault(
            pad, _element(pad, "port", pad, f"{'flux bias' if info['role'] == 'flux' else 'feedline port'}")
        )
        flux = info["role"] == "flux"
        e["params"] = [_param("length", "Line length", "\\ell", info["length_um"], "µm")] if flux else []
        e["links"] = [{"to": info["to"], "role": info["role"], "label": info["line"]}]

    # ---- chip: simulation, jobs, feedback ------------------------------------------------------------------------
    if fem:
        cm = filled.cmatrix
        c.section("simulation", "D", "Simulation", f"{filled.job}")
        labels, m = cm["labels"], cm["matrix"]
        for i, li in enumerate(labels):
            c.card(
                "simulation",
                CHIP,
                f"Self capacitance {li}",
                f"C_{{{i + 1}{i + 1}}}",
                m[i][i],
                "fF",
                ident=sim_self[li],
                **{"from": [{"label": "net", "value": li, "ref": _net_element(li, elements)}]},
                description="Maxwell diagonal (total to all others).",
            )
        mutual = [(i, j) for i in range(len(labels)) for j in range(i + 1, len(labels))]
        mutual.sort(key=lambda ij: -abs(m[ij[0]][ij[1]]))
        for i, j in sorted(mutual[:24]):
            c.card(
                "simulation",
                CHIP,
                f"Mutual {labels[i]} ↔ {labels[j]}",
                f"C_{{{i + 1}{j + 1}}}",
                -m[i][j],
                "fF",
                ident=f"sim.mutual.{labels[i]}.{labels[j]}",
                description="Branch capacitance between the two nets (−Maxwell off-diagonal).",
            )
        notes = list(filled.notes)
        if len(mutual) > 24:
            notes.append(f"{len(mutual) - 24} smaller mutual capacitances: see the C-matrix in the Simulation tab")
        if notes:
            c.cards[-1].setdefault("notes", []).extend(notes)
    if jobs:
        c.section("jobs", "J", "Simulation jobs", "Exported, rendered and solved jobs.")
    for job in jobs or []:
        c.card(
            "jobs",
            CHIP,
            job["name"],
            job["analysis"],
            None,
            "",
            ident=f"job.{job['name']}",
            status="pass" if job.get("hasResults") else "info",
            **{"from": [{"label": "status", "value": job["status"]}, {"label": "solver", "value": job["solver"]}]},
            description=f"group {job['group']}" + (f" · {job['project']}" if job.get("project") else ""),
        )
    if proposal is not None:
        c.section("feedback", "E", "Feedback", "Next design revision from the surrogate (prediction until simulated).")
        for k, v in proposal.knobs.items():
            old = proposal.start_knobs.get(k)
            unit = "nH" if k.endswith("Lj_nH") else "µm"
            owner = k.split(".", 1)[0]
            c.card(
                "feedback",
                CHIP,
                k,
                k.split(".")[-1].replace("_", "\\_"),
                v,
                unit,
                ident=f"fb.{k}",
                sub=[{"symbol": "now", "value": old, "unit": unit}],
                status="warn" if k in proposal.at_bounds else None,
                **({"from": [{"label": "element", "value": "", "ref": owner}]} if owner in elements else {}),
                description=(
                    "at its bound — widen it or add a knob"
                    if k in proposal.at_bounds
                    else f"{100 * (v - old) / old:+.1f} % vs now"
                    if old
                    else ""
                ),
            )
        n_t = len(proposal.residuals) if getattr(proposal, "residuals", None) else None
        c.card(
            "feedback",
            CHIP,
            "Predicted residual",
            "\\lVert r \\rVert",
            proposal.objective,
            "tol",
            ident="fb.residual",
            description="Norm of (predicted − target)/tol"
            + (f" over the {n_t} targets" if n_t else "")
            + " after this revision.",
        )

    for e in elements.values():
        e["status"] = _worst(e["params"])
    return {"sections": c.sections, "cards": c.cards, "summary": summary, "elements": _ordered(elements)}


def _flux_ref(topo, pad) -> dict:
    line = topo.ports[pad]
    length = f" · {line['length_um']:.4g} µm" if line.get("length_um") else ""
    return {"label": "flux line", "value": f"{line['line']}{length}", "ref": pad}


def _element(ident, kind, label, subtitle="") -> dict:
    return {"id": ident, "kind": kind, "label": label, "subtitle": subtitle, "params": [], "links": []}


def _qubit_subtitle(design, q, squid) -> str:
    inst = design.instances.get(q)
    cell = inst.cell.rsplit(".", 1)[-1] if inst else "transmon"
    jt = (inst.params.get("junction_type") if inst else None) or ("SQUID" if squid else "JJ")
    return f"{cell} · {jt}"


def _net_element(net: str, elements: dict) -> str | None:
    """FEM net → element id ("Q1.island" → "Q1"; a claw → its readout resonator), for the self-capacitance chips."""
    head = net.split(".", 1)[0]
    if net.endswith(".island") or net == head:
        return head if head in elements else None
    readout = next((x["to"] for x in elements.get(head, {}).get("links", []) if x["role"] == "readout"), None)
    return readout or (head if head in elements else None)


_KIND_ORDER = {"qubit": 0, "resonator": 1, "bus": 2, "coupler": 3, "feedline": 4, "port": 5}


def _natural(s: str):
    import re  # pylint: disable=import-outside-toplevel

    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def _ordered(elements: dict) -> list[dict]:
    return sorted(elements.values(), key=lambda e: (_KIND_ORDER.get(e["kind"], 9), _natural(e["id"])))


def _isfinite(v) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)
