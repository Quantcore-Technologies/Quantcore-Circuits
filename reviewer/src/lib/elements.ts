import type { ChipElement, ElementKind, ElementLink, ElementParam, ParamCard, Section, State } from "@contract/state";
import type { CardStatus } from "@/lib/cards";

/** Pseudo element for chip-level cards (process, simulation, jobs, feedback). */
export const CHIP = "chip";

export const KIND_ORDER: ElementKind[] = ["qubit", "resonator", "bus", "coupler", "feedline", "port"];
export const KIND_LABEL: Record<ElementKind, { one: string; many: string }> = {
  qubit: { one: "Qubit", many: "Qubits" },
  resonator: { one: "Resonator", many: "Resonators" },
  bus: { one: "Bus", many: "Buses" },
  coupler: { one: "Coupler", many: "Couplers" },
  feedline: { one: "Feedline", many: "Feedlines" },
  port: { one: "Port", many: "Ports" },
};

/** Column header for a link role, seen from an element of `kind`. */
export function roleLabel(kind: ElementKind, role: ElementLink["role"]): string {
  if (role === "readout") return kind === "qubit" ? "Readout" : kind === "feedline" ? "Resonators" : "Reads";
  if (role === "feedline") return "Feedline";
  if (role === "flux") return kind === "port" ? "Biases" : "Flux";
  if (role === "port") return "Ports";
  if (role === "drive") return "Drive";
  return "Coupled to";
}

export const naturalCompare = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

const STATUS_RANK: Record<CardStatus, number> = { fail: 3, warn: 2, pass: 1, info: 0 };

export function worstStatus(list: (CardStatus | null | undefined)[]): CardStatus | null {
  let best: CardStatus | null = null;
  for (const s of list) if (s && s !== "info" && (!best || STATUS_RANK[s] > STATUS_RANK[best])) best = s;
  return best;
}

// ---- older states (no `elements`, cards without `element`) -----------------------------------------------------

const QUBIT_QTY = new Set(["f_q_GHz", "alpha_MHz", "EJ_GHz", "EC_GHz"]);

/** Element of a card from its section id (states written before cards carried `element`). */
function elementFromSection(section: string, known: Set<string>): { element: string; partner?: string } {
  const m = /^(?:qubit|res|bus|coupler)_(.+)$/.exec(section);
  if (m) return { element: m[1] };
  const c = /^coupling_(.+)$/.exec(section);
  if (c) {
    for (const k of known) if (c[1].startsWith(k) && known.has(c[1].slice(k.length))) return { element: k, partner: c[1].slice(k.length) };
  }
  return { element: CHIP };
}

function derivedElements(state: State): ChipElement[] {
  const byId = new Map<string, ChipElement>();
  const get = (id: string, kind: ElementKind) => {
    let e = byId.get(id);
    if (!e) byId.set(id, (e = { id, kind, label: id, params: [], links: [] }));
    return e;
  };
  for (const s of state.sections) {
    const q = /^qubit_(.+)$/.exec(s.id);
    if (q) get(q[1], "qubit");
    const r = /^res_(.+)$/.exec(s.id);
    if (r) get(r[1], "resonator");
  }
  for (const t of state.targets) {
    const [inst, qty] = t.key.split(".", 2);
    if (!inst || !qty) continue;
    const e = get(inst, QUBIT_QTY.has(qty) ? "qubit" : "resonator");
    const p: ElementParam = {
      key: qty.replace(/_(GHz|MHz)$/, ""),
      label: t.label,
      symbol: t.symbol,
      value: t.value,
      unit: t.unit,
      status: t.status === "unknown" ? null : t.status,
      target: Number.isFinite(t.target) ? { value: t.target, tol: t.tol } : null,
      source: t.source,
    };
    e.params.push(p);
  }
  const known = new Set(byId.keys());
  for (const s of state.sections) {
    const { element, partner } = elementFromSection(s.id, known);
    if (partner && byId.has(element) && byId.has(partner)) {
      byId.get(element)!.links.push({ to: partner, role: "readout" });
      byId.get(partner)!.links.push({ to: element, role: "readout" });
    }
  }
  for (const e of byId.values()) e.status = worstStatus(e.params.map((p) => p.status));
  return sortElements([...byId.values()]);
}

export function sortElements(list: ChipElement[]): ChipElement[] {
  return [...list].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || naturalCompare(a.id, b.id));
}

export interface ElementModel {
  elements: ChipElement[];
  byId: Map<string, ChipElement>;
  /** Element (and partner) of every card id. */
  owner: Map<string, { element: string; partner?: string }>;
  derived: boolean;
}

export function elementModel(state: State, cards: ParamCard[]): ElementModel {
  const derived = state.elements.length === 0;
  const elements = derived ? derivedElements(state) : state.elements;
  const byId = new Map(elements.map((e) => [e.id, e]));
  const known = new Set(byId.keys());
  const owner = new Map<string, { element: string; partner?: string }>();
  for (const c of cards) {
    const o = c.element ? { element: c.element, partner: c.partner } : elementFromSection(c.section, known);
    owner.set(c.id, o.element === CHIP || known.has(o.element) ? o : { element: CHIP });
  }
  return { elements, byId, owner, derived };
}

export interface CardBlock {
  key: string;
  section: Section;
  cards: ParamCard[];
  /** Two-element block (coupling Q1–R1): always gets its own small heading. */
  pair: boolean;
}

/** The cards shown when `element` is selected: its own sections, then the pair sections it takes part in. */
export function elementBlocks(element: string, sections: Section[], cards: ParamCard[], model: ElementModel): CardBlock[] {
  const sectionById = new Map(sections.map((s) => [s.id, s]));
  const order = new Map(sections.map((s, i) => [s.id, i]));
  const own = new Map<string, ParamCard[]>();
  const pairs = new Map<string, ParamCard[]>();
  for (const c of cards) {
    const o = model.owner.get(c.id) ?? { element: CHIP };
    if (o.element === element && !o.partner) own.set(c.section, [...(own.get(c.section) ?? []), c]);
    else if (o.partner && (o.element === element || o.partner === element)) pairs.set(c.section, [...(pairs.get(c.section) ?? []), c]);
  }
  const block = (sid: string, list: ParamCard[], pair: boolean): CardBlock => ({
    key: `${pair ? "p" : "o"}-${sid}`,
    section: sectionById.get(sid) ?? { id: sid, letter: "", title: sid === "" ? "Other parameters" : sid },
    cards: [...list].sort((a, b) => a.index - b.index),
    pair,
  });
  const bySection = (a: [string, ParamCard[]], b: [string, ParamCard[]]) => (order.get(a[0]) ?? 1e9) - (order.get(b[0]) ?? 1e9);
  return [...[...own.entries()].sort(bySection).map(([s, l]) => block(s, l, false)), ...[...pairs.entries()].sort(bySection).map(([s, l]) => block(s, l, true))];
}

/** Elements that have cards (selector entries), in display order; "chip" first when it has any. */
export function selectableElements(cards: ParamCard[], model: ElementModel): string[] {
  const withCards = new Set<string>();
  for (const c of cards) {
    const o = model.owner.get(c.id);
    if (!o) continue;
    withCards.add(o.element);
    if (o.partner) withCards.add(o.partner);
  }
  const out = model.elements.filter((e) => withCards.has(e.id)).map((e) => e.id);
  return withCards.has(CHIP) ? [CHIP, ...out] : out;
}

/** Status of an element's card set (worst first). */
export function blocksStatus(blocks: CardBlock[]): { values: number; fail: number; warn: number } {
  const all = blocks.flatMap((b) => b.cards);
  return { values: all.length, fail: all.filter((c) => c.status === "fail").length, warn: all.filter((c) => c.status === "warn").length };
}
