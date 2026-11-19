import type { CardRef, CardSub, ChipElement, DesignInfo, ElementKind, ElementLink, ElementParam, Goal, ParamCard, PlotSpec, Section, State, Step, SummaryGroup, SummaryItem, Target } from "@contract/state";

type Loose<T> = { [K in keyof T]?: unknown };

const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v.filter((x) => x != null) as T[]) : []);
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const num = (v: unknown): number => (typeof v === "number" ? v : Number.NaN);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const optStr = (v: unknown): string | undefined => (typeof v === "string" && v !== "" ? v : undefined);
const STATUSES = ["pass", "fail", "warn", "info"] as const;
type CardStatus = (typeof STATUSES)[number];
const status = (v: unknown): CardStatus | undefined => (STATUSES.includes(v as CardStatus) ? (v as CardStatus) : undefined);

function normalizeDesign(raw: unknown): DesignInfo {
  const d = obj(raw) as Loose<DesignInfo>;
  const stack = obj(d.stack);
  const box = arr<number>(d.chipBox);
  return {
    name: str(d.name, "unnamed design"),
    path: str(d.path),
    hash: str(d.hash),
    pdk: str(d.pdk),
    stack: { substrate: str(stack.substrate), epsR: num(stack.epsR), thickness_um: num(stack.thickness_um) },
    chipBox: box.length === 4 ? (box as DesignInfo["chipBox"]) : [Number.NaN, Number.NaN, Number.NaN, Number.NaN],
    instances: num(d.instances),
    routes: num(d.routes),
  };
}

function normalizeSteps(raw: unknown): Step[] {
  return arr<Step>(raw)
    .filter((s) => typeof s === "object")
    .map((s, i) => ({ ...s, id: str(s.id, `step${i + 1}`), index: typeof s.index === "number" ? s.index : i + 1, title: str(s.title, str(s.id)), status: s.status ?? "pending" }))
    .sort((a, b) => a.index - b.index);
}

function normalizeTargets(raw: unknown): Target[] {
  return arr<Target>(raw).map((t) => ({
    ...t,
    label: str(t.label, str(t.key)),
    symbol: str(t.symbol),
    unit: str(t.unit),
    value: typeof t.value === "number" ? t.value : null,
    status: t.status === "pass" || t.status === "fail" ? t.status : "unknown",
  }));
}

function normalizeGoal(raw: unknown, targets: Target[]): Goal {
  const g = obj(raw) as Loose<Goal>;
  const passed = typeof g.passed === "number" ? g.passed : targets.filter((t) => t.status === "pass").length;
  const total = typeof g.total === "number" ? g.total : targets.length;
  return {
    reached: g.reached === true,
    passed,
    total,
    summary: str(g.summary, total ? `${passed} of ${total} targets within tolerance` : ""),
  };
}

function normalizeSections(raw: unknown): Section[] {
  return arr<unknown>(raw)
    .map(obj)
    .filter((o) => typeof o.id === "string")
    .map((o) => ({ id: str(o.id), letter: str(o.letter), title: str(o.title, str(o.id)), subtitle: optStr(o.subtitle) }));
}

function normalizeCard(o: Record<string, unknown>, i: number): ParamCard {
  const t = obj(o.target);
  const range = arr<unknown>(o.range);
  return {
    id: str(o.id, `card${i + 1}`),
    section: str(o.section),
    element: optStr(o.element),
    partner: optStr(o.partner),
    index: typeof o.index === "number" && Number.isFinite(o.index) ? o.index : i + 1,
    title: str(o.title, str(o.id)),
    symbol: str(o.symbol),
    value: numOrNull(o.value),
    unit: str(o.unit),
    sub: arr<unknown>(o.sub)
      .map(obj)
      .map((x): CardSub => ({ symbol: str(x.symbol), value: numOrNull(x.value), unit: str(x.unit) })),
    target: numOrNull(t.value) !== null ? { value: t.value as number, tol: numOrNull(t.tol) ?? Number.NaN } : null,
    design: numOrNull(o.design),
    range: range.length === 2 && range.every((x) => numOrNull(x) !== null) ? [range[0] as number, range[1] as number] : null,
    source: optStr(o.source),
    status: status(o.status),
    from: arr<unknown>(o.from)
      .map(obj)
      .map((x): CardRef => ({ label: str(x.label), value: typeof x.value === "number" ? String(x.value) : str(x.value), ref: optStr(x.ref) })),
    formula: optStr(o.formula),
    plot: optStr(o.plot),
    description: optStr(o.description),
    notes: arr<unknown>(o.notes).filter((n): n is string => typeof n === "string" && n !== ""),
  };
}

function normalizeCards(raw: unknown): ParamCard[] {
  return arr<unknown>(raw)
    .map(obj)
    .map(normalizeCard);
}

function normalizeSummary(raw: unknown): SummaryGroup[] {
  return arr<unknown>(raw)
    .map(obj)
    .map((g, i) => ({
      id: str(g.id, `group${i}`),
      index: typeof g.index === "number" ? String(g.index) : str(g.index),
      title: str(g.title),
      items: arr<unknown>(g.items)
        .map(obj)
        .map(
          (x): SummaryItem => ({
            label: str(x.label),
            symbol: optStr(x.symbol),
            value: typeof x.value === "number" ? (Number.isFinite(x.value) ? x.value : null) : typeof x.value === "string" ? x.value : null,
            unit: optStr(x.unit),
            status: status(x.status) ?? null,
          }),
        ),
    }));
}

const KINDS: ElementKind[] = ["qubit", "resonator", "coupler", "feedline", "bus", "port"];
const ROLES: ElementLink["role"][] = ["readout", "feedline", "flux", "coupling", "port", "drive"];

function normalizeElements(raw: unknown): ChipElement[] {
  return arr<unknown>(raw)
    .map(obj)
    .filter((o) => typeof o.id === "string" && o.id !== "")
    .map((o): ChipElement => ({
      id: str(o.id),
      kind: KINDS.includes(o.kind as ElementKind) ? (o.kind as ElementKind) : "port",
      label: str(o.label, str(o.id)),
      subtitle: optStr(o.subtitle),
      params: arr<unknown>(o.params)
        .map(obj)
        .filter((x) => typeof x.key === "string")
        .map((x): ElementParam => {
          const t = obj(x.target);
          return {
            key: str(x.key),
            label: str(x.label, str(x.key)),
            symbol: str(x.symbol),
            value: numOrNull(x.value),
            unit: str(x.unit),
            status: status(x.status) ?? null,
            target: numOrNull(t.value) !== null ? { value: t.value as number, tol: numOrNull(t.tol) ?? Number.NaN } : null,
            source: optStr(x.source),
            card: optStr(x.card),
            of: optStr(x.of),
          };
        }),
      links: arr<unknown>(o.links)
        .map(obj)
        .filter((x) => typeof x.to === "string")
        .map((x) => ({ to: str(x.to), role: ROLES.includes(x.role as ElementLink["role"]) ? (x.role as ElementLink["role"]) : "coupling", label: optStr(x.label) })),
      status: status(o.status) ?? null,
    }));
}

/** Fill in defaults so the UI can rely on every top-level collection existing. */
export function normalizeState(raw: unknown): State {
  const o = obj(raw) as Loose<State>;
  const targets = normalizeTargets(o.targets);
  return {
    schema: "qcc-state/0.1",
    updated: str(o.updated),
    design: normalizeDesign(o.design),
    currentStep: typeof o.currentStep === "string" ? o.currentStep : null,
    steps: normalizeSteps(o.steps),
    goal: normalizeGoal(o.goal, targets),
    targets,
    screenshots: arr(o.screenshots),
    plots: arr<PlotSpec>(o.plots).filter((p) => typeof p === "object"),
    circuit: o.circuit && typeof o.circuit === "object" ? (o.circuit as State["circuit"]) : null,
    hamiltonian: o.hamiltonian && typeof o.hamiltonian === "object" ? (o.hamiltonian as State["hamiltonian"]) : null,
    consensus: arr(o.consensus),
    jobs: arr(o.jobs),
    femCompare: arr(o.femCompare),
    cmatrix: o.cmatrix && typeof o.cmatrix === "object" ? (o.cmatrix as State["cmatrix"]) : null,
    history: arr(o.history),
    log: arr(o.log),
    sections: normalizeSections(o.sections),
    cards: normalizeCards(o.cards),
    summary: normalizeSummary(o.summary),
    elements: normalizeElements(o.elements),
  };
}

export function looksLikeState(raw: unknown): boolean {
  const o = obj(raw);
  return typeof o.schema === "string" || "steps" in o || "design" in o;
}

export const plotsFor = (state: State, tab: PlotSpec["tab"]) => state.plots.filter((p) => p.tab === tab);
