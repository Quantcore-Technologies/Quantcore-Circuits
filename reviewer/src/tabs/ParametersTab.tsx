import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ChipElement, ElementKind, ParamCard as Card, PlotSpec, State } from "@contract/state";
import { ChipTables, matchesFilter, type OverviewFilter } from "@/components/ChipOverview";
import { ParamCard, type RefResolver } from "@/components/ParamCard";
import { Empty } from "@/components/Section";
import { Sym } from "@/components/Sym";
import { STATUS_COLOUR, cardDomId, cardNumber, cardsFor } from "@/lib/cards";
import { CHIP, KIND_LABEL, KIND_ORDER, blocksStatus, elementBlocks, elementModel, selectableElements, worstStatus, type CardBlock, type ElementModel } from "@/lib/elements";
import { fmtNum } from "@/lib/format";
import { GREY, PASS, SIGNAL } from "@/lib/palette";
import { cn } from "@/lib/utils";

const EL_ANCHOR = "pel";

/** Selected element, initialised from and mirrored into `?el=`. */
function useElementParam(selectable: string[], fallback: string | null): [string | null, (id: string) => void] {
  const [chosen, setChosen] = useState<string | null>(() => new URLSearchParams(window.location.search).get("el"));
  const selected = chosen && selectable.includes(chosen) ? chosen : fallback;
  const select = useCallback((id: string) => {
    setChosen(id);
    const url = new URL(window.location.href);
    url.searchParams.set("el", id);
    window.history.replaceState(null, "", url.toString().replace(/([?&])sample=(&|$)/, "$1sample$2"));
  }, []);
  return [selected, select];
}

function countLine(elements: ChipElement[]): string {
  const n = new Map<ElementKind, number>();
  for (const e of elements) n.set(e.kind, (n.get(e.kind) ?? 0) + 1);
  return KIND_ORDER.filter((k) => n.get(k))
    .map((k) => `${n.get(k)} ${(n.get(k) === 1 ? KIND_LABEL[k].one : KIND_LABEL[k].many).toLowerCase()}`)
    .join(" · ");
}

/** Chip-level constants that are not already in the header (substrate and εr are). */
function ProcessStrip({ state }: { state: State }) {
  const g = state.summary.find((x) => x.id === "process");
  const items = (g?.items ?? []).filter((it) => !/^(substrate|permittivity|values from)$/i.test(it.label));
  if (items.length === 0) return null;
  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
      {items.map((it, i) => (
        <div key={`${it.label}-${i}`} className="flex items-baseline gap-1.5">
          <dt className="text-muted-foreground">
            {it.symbol ? <Sym symbol={it.symbol} /> : it.label}
          </dt>
          <dd className="num font-semibold">
            {typeof it.value === "number" ? fmtNum(it.value) : (it.value ?? "—")}
            {it.unit && it.value !== null && <span className="ml-1 text-xs font-normal text-muted-foreground">{it.unit}</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function FilterBar({ filter, onChange, total, shown }: { filter: OverviewFilter; onChange: (f: OverviewFilter) => void; total: number; shown: number }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="relative">
        <span className="sr-only">Filter elements</span>
        <input
          type="search"
          value={filter.query}
          onChange={(e) => onChange({ ...filter, query: e.target.value })}
          placeholder="Filter: Q3 R7 FL…"
          className="h-7 w-44 border border-rule-strong bg-background px-2 text-xs placeholder:text-muted-foreground focus-visible:border-ink focus-visible:outline-none"
        />
      </label>
      <button
        type="button"
        aria-pressed={filter.failingOnly}
        onClick={() => onChange({ ...filter, failingOnly: !filter.failingOnly })}
        className={cn("h-7 border px-2 text-2xs font-semibold uppercase tracking-label transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring", filter.failingOnly ? "border-signal bg-signal text-white" : "border-rule-strong text-muted-foreground hover:border-ink hover:text-foreground")}
      >
        Failing only
      </button>
      {shown !== total && (
        <span className="num text-2xs uppercase tracking-label text-muted-foreground">
          {shown}/{total} shown
        </span>
      )}
    </div>
  );
}

function StatusSquare({ status }: { status: string | null | undefined }) {
  const c = status === "fail" ? SIGNAL : status === "pass" ? PASS : status === "warn" ? STATUS_COLOUR.warn! : null;
  return <span className="inline-block h-[7px] w-[7px] shrink-0" style={c ? { background: c } : { border: `1px solid ${GREY}` }} aria-hidden />;
}

/** One row of element buttons (Chip | Q1 Q2 … | R1 R2 … | FL …), sticky under the header while reading cards. */
function ElementSelector({ ids, model, chipStatus, selected, onSelect }: { ids: string[]; model: ElementModel; chipStatus: string | null; selected: string | null; onSelect: (id: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const set = () => document.documentElement.style.setProperty("--sel-h", `${Math.ceil(el.getBoundingClientRect().height)}px`);
    set();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => {
      ro.disconnect();
      document.documentElement.style.setProperty("--sel-h", "0px");
    };
  }, []);
  const groups: { label: string; ids: string[] }[] = [];
  if (ids.includes(CHIP)) groups.push({ label: "", ids: [CHIP] });
  for (const k of KIND_ORDER) {
    const list = ids.filter((id) => model.byId.get(id)?.kind === k);
    if (list.length) groups.push({ label: KIND_LABEL[k].many, ids: list });
  }
  return (
    <div ref={ref} className="sticky z-20 -mx-4 border-b border-rule bg-background px-4 py-2 sm:-mx-8 sm:px-8" style={{ top: "var(--sticky-h, 88px)" }}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2" role="tablist" aria-label="Chip elements">
        {groups.map((g) => (
          <div key={g.label || "chip"} className="flex flex-wrap items-center gap-1">
            {g.label && <span className="mr-1 text-2xs font-semibold uppercase tracking-label text-muted-foreground">{g.label}</span>}
            {g.ids.map((id) => {
              const e = model.byId.get(id);
              const on = id === selected;
              return (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => onSelect(id)}
                  title={e ? `${KIND_LABEL[e.kind].one} ${e.label}${e.subtitle ? ` · ${e.subtitle}` : ""}` : "Chip-level values"}
                  className={cn(
                    "inline-flex h-7 items-center gap-1.5 border px-2 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                    on ? "border-ink bg-ink text-white" : "border-rule-strong hover:border-ink",
                  )}
                >
                  <StatusSquare status={id === CHIP ? chipStatus : e?.status} />
                  {id === CHIP ? "Chip" : (e?.label ?? id)}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Chip view subtitle: its blocks ("Process and CPW · Simulation · Feedback"), or the one block's own subtitle. */
function chipSubtitle(blocks: CardBlock[]): string {
  if (blocks.length === 1) return [blocks[0].section.title, blocks[0].section.subtitle].filter(Boolean).join(" · ");
  return blocks.map((b) => b.section.title).join(" · ");
}

const ROLE_TEXT: Record<string, string> = { readout: "readout", feedline: "feedline", flux: "flux", coupling: "coupled to", port: "port", drive: "drive" };

function ElementHeader({ id, model, blocks, onSelect }: { id: string; model: ElementModel; blocks: CardBlock[]; onSelect: (id: string) => void }) {
  const e = model.byId.get(id);
  const { values, fail, warn } = blocksStatus(blocks);
  const links = e?.links ?? [];
  return (
    <header className="flex flex-wrap items-end gap-x-5 gap-y-2 pb-1 pt-6">
      <h2 className="text-[34px] font-bold leading-[34px] tracking-tight">{id === CHIP ? "Chip" : (e?.label ?? id)}</h2>
      <div className="min-w-0 flex-1 pb-0.5">
        <div className="text-[13px] text-muted-foreground">
          {id === CHIP ? chipSubtitle(blocks) : [e && KIND_LABEL[e.kind].one, e?.subtitle].filter(Boolean).join(" · ")}
        </div>
        {links.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {links.map((l) => (
              <button
                key={`${l.role}-${l.to}`}
                type="button"
                onClick={() => onSelect(l.to)}
                className="inline-flex items-baseline gap-1.5 border border-rule-strong px-1.5 py-px text-xs leading-5 hover:border-ink hover:bg-paper focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <span className="text-muted-foreground">{ROLE_TEXT[l.role] ?? l.role}</span>
                <span className="font-semibold">{l.to}</span>
                {l.label && l.label !== l.to && <span className="font-mono text-[11px] text-muted-foreground">{l.label}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="pb-1 text-2xs uppercase tracking-label text-muted-foreground">
        <span className="num">{values}</span> value{values === 1 ? "" : "s"}
        {fail > 0 && (
          <span className="text-signal">
            {" · "}
            <span className="num">{fail}</span> fail
          </span>
        )}
        {warn > 0 && (
          <span className="text-warn">
            {" · "}
            <span className="num">{warn}</span> check
          </span>
        )}
      </div>
    </header>
  );
}

function BlockHeader({ block }: { block: CardBlock }) {
  const { section, cards } = block;
  const fail = cards.filter((c) => c.status === "fail").length;
  return (
    <header className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-t border-ink pt-3">
      <h3 className="text-[15px] font-semibold leading-5">{section.title}</h3>
      {section.subtitle && <p className="min-w-0 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">{section.subtitle}</p>}
      <span className="ml-auto text-2xs uppercase tracking-label text-muted-foreground">
        <span className="num">{cards.length}</span> value{cards.length === 1 ? "" : "s"}
        {fail > 0 && (
          <span className="text-signal">
            {" · "}
            <span className="num">{fail}</span> fail
          </span>
        )}
      </span>
    </header>
  );
}

export function ParametersTab({ state }: { state: State }) {
  const [flash, setFlash] = useState<string | null>(null);
  const [pending, setPending] = useState<{ id: string; block: ScrollLogicalPosition } | null>(null);
  const [filter, setFilter] = useState<OverviewFilter>({ query: "", failingOnly: false });
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const { sections, cards, derived } = useMemo(() => cardsFor(state), [state]);
  const model = useMemo(() => elementModel(state, cards), [state, cards]);
  const selectable = useMemo(() => selectableElements(cards, model), [cards, model]);
  const fallback = selectable.find((id) => model.byId.get(id)?.kind === "qubit") ?? selectable[0] ?? null;
  const [selected, select] = useElementParam(selectable, fallback);
  const blocks = useMemo(() => (selected ? elementBlocks(selected, sections, cards, model) : []), [selected, sections, cards, model]);
  const plots = useMemo(() => new Map<string, PlotSpec>(state.plots.map((p) => [p.id, p])), [state.plots]);
  const chipStatus = useMemo(() => worstStatus(cards.filter((c) => (model.owner.get(c.id)?.element ?? CHIP) === CHIP).map((c) => c.status)), [cards, model]);

  // Scroll after the render that shows the target (selecting another element first re-renders the card grid).
  useEffect(() => {
    if (!pending) return;
    const el = document.getElementById(pending.id);
    setPending(null);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: pending.block });
    setFlash(pending.id);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setFlash(null), 1600);
  }, [pending]);

  const openCard = useCallback(
    (card: Card) => {
      const o = model.owner.get(card.id) ?? { element: CHIP };
      if (selected !== o.element && selected !== o.partner) select(o.element);
      setPending({ id: cardDomId(card.index), block: "center" });
    },
    [model, selected, select],
  );
  const openElement = useCallback(
    (id: string) => {
      if (selectable.includes(id)) {
        select(id);
        setPending({ id: EL_ANCHOR, block: "start" });
      } else setPending({ id: `pel-row-${id}`, block: "center" }); // no cards (port, feedline): show its row
    },
    [selectable, select],
  );
  const openCardId = useCallback(
    (cardId: string) => {
      const c = cards.find((x) => x.id === cardId);
      if (c) openCard(c);
    },
    [cards, openCard],
  );

  const resolve: RefResolver = useCallback(
    (ref) => {
      if (!ref) return null;
      const r = ref.trim();
      const card = /^\d{1,3}$/.test(r) ? cards.find((c) => c.index === Number(r)) : cards.find((c) => c.id === r);
      if (card) {
        const o = model.owner.get(card.id);
        const where = o && o.element !== selected && o.partner !== selected ? ` (${o.element === CHIP ? "Chip" : o.element})` : "";
        return { label: `${cardNumber(card.index)} ${card.title}${where}`, short: cardNumber(card.index), go: () => openCard(card) };
      }
      if (r === CHIP || model.byId.has(r)) return { label: r === CHIP ? "Chip" : r, short: r === CHIP ? "Chip" : r, go: () => openElement(r) };
      if (/^[A-Z]$/.test(r)) {
        const s = sections.find((x) => x.letter === r);
        const first = s && cards.filter((c) => c.section === s.id).sort((a, b) => a.index - b.index)[0];
        return first ? { label: `${r} ${s!.title}`, short: r, go: () => openCard(first) } : null;
      }
      return null;
    },
    [cards, model, sections, selected, openCard, openElement],
  );

  const shown = model.elements.filter((e) => matchesFilter(e, filter)).length;
  const origin = state.summary.find((g) => g.id === "process")?.items.find((i) => /values from/i.test(i.label))?.value;
  const { goal } = state;
  const ownCount = blocks.filter((b) => !b.pair).length;

  return (
    <div className="flex min-w-0 flex-col">
      {model.elements.length > 0 && (
        <section aria-label="Chip overview" className="flex flex-col gap-5 pb-10">
          <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
            <div className="min-w-0">
              <h2 className="text-[21px] font-semibold leading-[26px]">Chip overview</h2>
              <p className="mt-0.5 text-[13px] text-muted-foreground">
                {countLine(model.elements)}
                {goal.total > 0 && (
                  <>
                    {" · "}
                    <span style={{ color: goal.reached ? PASS : SIGNAL }}>
                      {goal.passed} of {goal.total} targets met
                    </span>
                  </>
                )}
                {typeof origin === "string" && <> · values from {origin}</>}
              </p>
            </div>
            <FilterBar filter={filter} onChange={setFilter} total={model.elements.length} shown={shown} />
          </div>
          <ProcessStrip state={state} />
          {model.derived && <div className="border-l-2 border-warn bg-paper px-3 py-2 text-xs text-muted-foreground">This state has no element list (older backend); the overview is derived from the targets.</div>}
          <ChipTables elements={model.elements} filter={filter} selected={selected} flash={flash} onSelect={openElement} onOpenCard={openCardId} />
        </section>
      )}

      {derived && cards.length > 0 && (
        <div className="mb-6 border-l-2 border-warn bg-paper px-3 py-2 text-xs text-muted-foreground">This state has no parameter cards (older backend); showing the targets and Hamiltonian terms instead.</div>
      )}
      {cards.length === 0 && <Empty>No parameters yet — cards appear once the loop has produced values.</Empty>}

      {selected && cards.length > 0 && (
        <section id={EL_ANCHOR} aria-label="Element parameters" style={{ scrollMarginTop: "var(--sticky-h, 88px)" }}>
          <ElementSelector ids={selectable} model={model} chipStatus={chipStatus} selected={selected} onSelect={(id) => select(id)} />
          <ElementHeader id={selected} model={model} blocks={blocks} onSelect={openElement} />
          <div className="mt-5 flex flex-col gap-10">
            {blocks.map((b) => (
              <section key={b.key} className="min-w-0" aria-label={b.section.title}>
                {(b.pair || ownCount > 1) && (
                  <div className="mb-4">
                    <BlockHeader block={b} />
                  </div>
                )}
                <div className="pgrid-wrap">
                  <div className="pgrid">
                    {b.cards.map((c) => (
                      <ParamCard key={c.id} card={c} plot={c.plot ? (plots.get(c.plot) ?? null) : null} resolve={resolve} highlighted={flash === cardDomId(c.index)} />
                    ))}
                  </div>
                </div>
              </section>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
