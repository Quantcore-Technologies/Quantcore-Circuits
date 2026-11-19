import type { ParamCard, Section, State, SummaryGroup } from "@contract/state";
import { fmt } from "@/lib/format";
import { GREY, PALETTE, PASS, SIGNAL, WARN } from "@/lib/palette";

export type CardStatus = NonNullable<ParamCard["status"]>;

export const STATUS_COLOUR: Record<CardStatus, string | null> = { fail: SIGNAL, pass: PASS, warn: WARN, info: null };
export const STATUS_LABEL: Record<CardStatus, string | null> = { fail: "Fail", pass: "Pass", warn: "Check", info: null };

/** "01", "02", … (three digits from 100 on). */
export const cardNumber = (index: number) => String(index).padStart(2, "0");
export const cardDomId = (index: number) => `pcard-${cardNumber(index)}`;
export const sectionDomId = (id: string) => `psec-${id}`;

export type SourceKind = "fem" | "estimate" | "design" | "estimator";

/** Colour family of a card's source: FEM and estimators blue, rough estimates orange, design inputs grey. */
export function sourceKind(source: string | undefined): SourceKind | null {
  if (!source) return null;
  const s = source.trim().toLowerCase();
  if (/^fem\b/.test(s)) return "fem";
  if (/^estimate\b/.test(s)) return "estimate";
  if (/^(design|design\.json|layout|lom|synthesis|pdk)\b/.test(s)) return "design";
  return "estimator";
}

export const SOURCE_COLOUR: Record<SourceKind, string> = { fem: PALETTE[0], estimator: PALETTE[0], estimate: PALETTE[1], design: GREY };

/** Word-like sub/superscripts are labels, not products of variables: C_{island} → C_{\mathrm{island}} (ISO 80000-2). */
export const uprightScripts = (tex: string) => tex.replace(/([_^])\{([A-Za-z]{2,})\}/g, "$1{\\mathrm{$2}}");

/**
 * A card/summary symbol is KaTeX, but the backend sometimes sends plain identifiers ("hfss_eigenmode", "cross\_length",
 * "now") that KaTeX would set as a product of italic letters. Those are shown as text; "f_max" style subscripts get braces.
 */
export function symbolMarkup(symbol: string): { kind: "tex" | "text"; value: string } {
  const s = symbol.trim();
  if (/^[A-Za-z][A-Za-z0-9]*(?:\\_[A-Za-z0-9]+)+$/.test(s)) return { kind: "text", value: s.replace(/\\_/g, "_") };
  const ident = /^([A-Za-z][A-Za-z0-9]*)((?:_[A-Za-z0-9]+)+)$/.exec(s);
  if (ident) {
    const parts = ident[2].slice(1).split("_");
    if (ident[1].length === 1 && parts.length === 1) return { kind: "tex", value: uprightScripts(`${ident[1]}_{${parts[0]}}`) };
    return { kind: "text", value: s };
  }
  if (/^[A-Za-z]{3,}$/.test(s)) return { kind: "text", value: s };
  return { kind: "tex", value: uprightScripts(s) };
}

export interface CardGroup {
  section: Section;
  cards: ParamCard[];
}

const byIndex = (a: ParamCard, b: ParamCard) => a.index - b.index;

/** Cards grouped by section, in section order; cards of unknown sections go to a trailing "Other" group. */
export function groupCards(sections: Section[], cards: ParamCard[]): CardGroup[] {
  const known = new Set(sections.map((s) => s.id));
  const out: CardGroup[] = [];
  const seen = new Set<string>();
  for (const s of sections) {
    if (seen.has(s.id)) continue;
    seen.add(s.id);
    const list = cards.filter((c) => c.section === s.id).sort(byIndex);
    if (list.length) out.push({ section: s, cards: list });
  }
  const orphans = cards.filter((c) => !known.has(c.section)).sort(byIndex);
  if (orphans.length) out.push({ section: { id: "__other", letter: "", title: "Other parameters" }, cards: orphans });
  return out;
}

/** Older states have no cards: derive a minimal set from the targets and the Hamiltonian terms. */
function derivedCards(state: State): { sections: Section[]; cards: ParamCard[] } {
  const sections: Section[] = [];
  const cards: ParamCard[] = [];
  let i = 0;
  if (state.targets.length) {
    sections.push({ id: "__targets", letter: "A", title: "Targets", subtitle: "Current best estimate against each design target." });
    for (const t of state.targets) {
      cards.push({
        id: `__t_${t.key}`,
        section: "__targets",
        index: ++i,
        title: t.label,
        symbol: t.symbol,
        value: t.value,
        unit: t.unit,
        target: Number.isFinite(t.target) ? { value: t.target, tol: t.tol } : null,
        source: t.source,
        status: t.status === "unknown" ? undefined : t.status,
      });
    }
  }
  const terms = state.hamiltonian?.terms ?? [];
  if (terms.length) {
    sections.push({ id: "__hamiltonian", letter: sections.length ? "B" : "A", title: "Hamiltonian", subtitle: state.hamiltonian?.model });
    for (const term of terms) {
      cards.push({ id: `__h_${i}`, section: "__hamiltonian", index: ++i, title: term.label, symbol: term.symbol, value: term.value, unit: term.unit, source: state.hamiltonian?.solver });
    }
  }
  return { sections, cards };
}

export function cardsFor(state: State): { sections: Section[]; cards: ParamCard[]; derived: boolean } {
  if (state.cards.length) return { sections: state.sections, cards: state.cards, derived: false };
  return { ...derivedCards(state), derived: true };
}

/** Older states have no summary: show the design facts from the header instead. */
export function summaryFor(state: State): SummaryGroup[] {
  if (state.summary.length) return state.summary;
  const d = state.design;
  const [x0, y0, x1, y1] = d.chipBox;
  const chip = Number.isFinite(x1 - x0) && Number.isFinite(y1 - y0) ? `${fmt((x1 - x0) / 1000, 3)} × ${fmt((y1 - y0) / 1000, 3)} mm` : null;
  return [
    {
      id: "__design",
      index: "0",
      title: "Design",
      items: [
        { label: "PDK", value: d.pdk || null },
        { label: "Substrate", value: d.stack.substrate ? `${d.stack.substrate} ${fmt(d.stack.thickness_um)} µm` : null },
        { label: "Permittivity", symbol: "\\varepsilon_r", value: Number.isFinite(d.stack.epsR) ? d.stack.epsR : null },
        { label: "Chip", value: chip },
        { label: "Instances", value: Number.isFinite(d.instances) ? d.instances : null },
        { label: "Routes", value: Number.isFinite(d.routes) ? d.routes : null },
      ],
    },
  ];
}
