import { useState, type ReactNode } from "react";
import type { CardRef, ParamCard as Card, PlotSpec } from "@contract/state";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { PlotBody } from "@/components/PlotCard";
import { Sym } from "@/components/Sym";
import { SymbolText } from "@/components/SymbolText";
import { Tex } from "@/components/Tex";
import { SOURCE_COLOUR, STATUS_COLOUR, STATUS_LABEL, cardDomId, cardNumber, sourceKind, uprightScripts } from "@/lib/cards";
import { fmtNum, fmtPct, fmtSigned } from "@/lib/format";
import { PALETTE, PASS, SIGNAL } from "@/lib/palette";
import { cn } from "@/lib/utils";

const UP = PALETTE[0];
const DOWN = PALETTE[2];

/** Resolves a "From" chip reference (card id or number, element id, section letter) to a jump action, or null. */
export type RefResolver = (ref: string | undefined) => { label: string; short: string; go: () => void } | null;

/** Long identifiers ("q1_r1_feedline_Q1R1_hfss_eigenmode") wrap after "_", ".", "/" or "\" rather than mid-word. */
function breakable(text: string): ReactNode[] {
  return text.split(/(?<=[_./\\])/).flatMap((part, i) => (i ? [<wbr key={i} />, part] : [part]));
}

function ChartIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
      <path d="M1.5 1.5 V12.5 H12.5" />
      <path d="M3.5 9.5 L6.3 6.2 L8.6 8 L12 3.8" />
    </svg>
  );
}

function IconButton({ label, active, onClick, children }: { label: string; active?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          aria-label={label}
          aria-pressed={active}
          className={cn(
            "flex h-7 w-7 items-center justify-center border text-[14px] font-semibold leading-none transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            active ? "border-ink bg-ink text-white" : "border-transparent text-muted-foreground hover:border-rule-strong hover:text-foreground",
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

function SourceTag({ source }: { source: string | undefined }) {
  const kind = sourceKind(source);
  if (!kind || !source) return null;
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      <span className="h-2 w-2 shrink-0" style={{ background: SOURCE_COLOUR[kind] }} aria-hidden />
      <span className="truncate font-mono text-[11px]" title={source}>
        {source}
      </span>
    </span>
  );
}

function StatusTag({ status }: { status: Card["status"] }) {
  if (!status) return null;
  const colour = STATUS_COLOUR[status];
  const label = STATUS_LABEL[status];
  if (!colour || !label) return null;
  return (
    <span className="border px-1 text-2xs font-semibold uppercase leading-[14px] tracking-label" style={{ color: colour, borderColor: colour }}>
      {label}
    </span>
  );
}

/** Small uppercase key on the left of a secondary line. */
function Line({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2 text-xs leading-5">
      <span className="w-[3.25rem] shrink-0 text-2xs font-semibold uppercase tracking-label text-muted-foreground">{k}</span>
      <span className="num min-w-0">{children}</span>
    </div>
  );
}

function TargetLine({ card }: { card: Card }) {
  const t = card.target;
  if (!t) return null;
  const dev = card.value !== null && Number.isFinite(t.tol) && t.tol > 0 ? (card.value - t.value) / t.tol : null;
  const ok = dev !== null && Math.abs(dev) <= 1;
  return (
    <Line k="Goal">
      {fmtNum(t.value)}
      {Number.isFinite(t.tol) && <span className="text-muted-foreground"> ± {fmtNum(t.tol)}</span>}
      {dev !== null && (
        <span className="ml-2 font-semibold" style={{ color: ok ? PASS : SIGNAL }}>
          Δ {fmtSigned(dev, Math.abs(dev) >= 100 ? 0 : Math.abs(dev) >= 10 ? 1 : 2)} tol
        </span>
      )}
    </Line>
  );
}

function DesignLine({ card }: { card: Card }) {
  const d = card.design;
  if (d === null || d === undefined) return null;
  const v = card.value;
  const rel = v !== null && d !== 0 ? (v - d) / Math.abs(d) : null;
  return (
    <Line k="Design">
      {fmtNum(d, 4, true)}
      {rel !== null &&
        (Math.abs(rel) < 5e-5 ? (
          <span className="ml-2 text-muted-foreground">= value</span>
        ) : (
          <span className="ml-2 font-semibold" style={{ color: rel > 0 ? UP : DOWN }}>
            {rel > 0 ? "↑" : "↓"} {fmtPct(Math.abs(rel))}
          </span>
        ))}
    </Line>
  );
}

function RangeLine({ card }: { card: Card }) {
  const r = card.range;
  if (!r) return null;
  const [lo, hi] = r[0] <= r[1] ? r : [r[1], r[0]];
  const ref = card.value ?? (lo + hi) / 2;
  const half = ref !== 0 ? (hi - lo) / 2 / Math.abs(ref) : null;
  return (
    <Line k="Range">
      {fmtNum(lo, 4, true)} – {fmtNum(hi, 4, true)}
      {half !== null && <span className="ml-2 text-muted-foreground">±{fmtPct(half)}</span>}
    </Line>
  );
}

function SubGrid({ sub }: { sub: NonNullable<Card["sub"]> }) {
  if (sub.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 border-t border-rule pt-3">
      {sub.map((s, i) => (
        <div key={`${s.symbol}-${i}`} className="min-w-0">
          <div className="truncate text-[13px] leading-5 text-muted-foreground">
            <Sym symbol={s.symbol} />
          </div>
          <div className="num whitespace-nowrap text-[17px] font-semibold leading-6">
            <span className={cn(s.value === null && "text-rule-strong")}>{fmtNum(s.value, 4, true)}</span>
            {s.unit && s.value !== null && <span className="ml-1 text-xs font-normal text-muted-foreground">{s.unit}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function RefChip({ r, resolve }: { r: CardRef; resolve: RefResolver }) {
  const target = resolve(r.ref);
  const body = (
    <>
      <SymbolText value={r.label} className="text-muted-foreground" />
      {r.value && <span className="num font-semibold text-foreground">{r.value}</span>}
      {r.ref && <span className="num text-muted-foreground">· {target?.short ?? r.ref}</span>}
    </>
  );
  const cls = "inline-flex max-w-full items-baseline gap-1.5 border border-rule-strong px-1.5 py-px text-xs leading-5 [overflow-wrap:anywhere]";
  if (!target) return <span className={cls}>{body}</span>;
  return (
    <button type="button" onClick={target.go} title={`Go to ${target.label}`} className={cn(cls, "text-left hover:border-ink hover:bg-paper focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring")}>
      {body}
    </button>
  );
}

function PlotDialog({ plot, card, open, onOpenChange }: { plot: PlotSpec; card: Card; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && (
        <DialogContent className="w-[min(1000px,94vw)]">
          <DialogHeader>
            <DialogTitle>{plot.title || plot.id}</DialogTitle>
            <DialogDescription>
              <span className="num">{cardNumber(card.index)}</span> {card.title}
              {plot.caption && <> · {plot.caption}</>}
            </DialogDescription>
          </DialogHeader>
          <PlotBody plot={plot} height={420} />
        </DialogContent>
      )}
    </Dialog>
  );
}

export function ParamCard({ card, plot, resolve, highlighted }: { card: Card; plot: PlotSpec | null; resolve: RefResolver; highlighted?: boolean }) {
  const [showFormula, setShowFormula] = useState(false);
  const [showPlot, setShowPlot] = useState(false);
  const statusColour = card.status ? STATUS_COLOUR[card.status] : null;
  const from = card.from ?? [];
  const notes = card.notes ?? [];
  const known = card.value !== null;

  return (
    <article
      id={cardDomId(card.index)}
      className={cn(
        "pscroll relative flex min-w-0 flex-col border border-rule bg-card outline outline-2 -outline-offset-1 transition-[outline-color] duration-700",
        highlighted ? "outline-ink" : "outline-transparent",
      )}
    >
      {statusColour && <span className="absolute inset-x-[-1px] top-[-1px] h-[2px]" style={{ background: statusColour }} aria-hidden />}

      <div className="flex flex-1 flex-col px-4 pb-4 pt-3.5">
        <header className="flex items-start gap-3">
          <span className="num shrink-0 text-[26px] font-normal leading-[26px] tracking-tight text-[#b9b9b9]">{cardNumber(card.index)}</span>
          <div className="min-w-0 flex-1">
            <h3 className="text-[15px] font-semibold leading-[19px] [overflow-wrap:anywhere]">{breakable(card.title)}</h3>
            {(card.source || STATUS_LABEL[card.status ?? "info"]) && (
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <SourceTag source={card.source} />
                <StatusTag status={card.status} />
              </div>
            )}
          </div>
          {(plot || card.formula) && (
            <div className="-mr-1.5 -mt-0.5 flex shrink-0 items-center">
              {plot && (
                <IconButton label={`Plot: ${plot.title || plot.id}`} onClick={() => setShowPlot(true)}>
                  <ChartIcon />
                </IconButton>
              )}
              {card.formula && (
                <IconButton label={showFormula ? "Hide formula" : "Show formula"} active={showFormula} onClick={() => setShowFormula((v) => !v)}>
                  Σ
                </IconButton>
              )}
            </div>
          )}
        </header>

        {card.description && (
          <p className="mt-2.5 text-[13px] leading-[18px] text-muted-foreground [overflow-wrap:anywhere]">
            <SymbolText value={card.description} strict />
          </p>
        )}

        {showFormula && card.formula && (
          <div className="mt-3 border-y border-rule bg-paper px-3 py-2 text-[14px]">
            <Tex tex={uprightScripts(card.formula)} display className="overflow-y-hidden" />
          </div>
        )}

        <div className="mt-4">
          {card.symbol && (
            <div className="text-[14px] leading-5">
              <Sym symbol={card.symbol} />
            </div>
          )}
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2">
            {known ? (
              <span className="num text-[42px] font-medium leading-[48px] tracking-[-0.025em]">{fmtNum(card.value, 4, true)}</span>
            ) : (
              <span className="num text-[26px] font-medium leading-8 text-rule-strong" aria-label="no value">—</span>
            )}
            {card.unit && known && <span className="text-[17px] text-muted-foreground">{card.unit}</span>}
          </div>
          {(card.target || card.design != null || card.range) && (
            <div className="mt-1.5">
              <TargetLine card={card} />
              <DesignLine card={card} />
              <RangeLine card={card} />
            </div>
          )}
        </div>

        {card.sub && card.sub.length > 0 && (
          <div className="mt-4">
            <SubGrid sub={card.sub} />
          </div>
        )}
      </div>

      {(from.length > 0 || notes.length > 0) && (
        <footer className="border-t border-rule px-4 py-2.5">
          {from.length > 0 && (
            <div className="flex flex-wrap items-baseline gap-1.5">
              <span className="mr-1 text-xs text-muted-foreground">From</span>
              {from.map((r, i) => (
                <RefChip key={`${r.label}-${i}`} r={r} resolve={resolve} />
              ))}
            </div>
          )}
          {notes.length > 0 && (
            <ul className={cn("space-y-1 text-[11px] leading-[15px] text-muted-foreground [overflow-wrap:anywhere]", from.length > 0 && "mt-2")}>
              {notes.map((n, i) => (
                <li key={i} className="flex gap-1.5">
                  <span aria-hidden>–</span>
                  <span>
                    <SymbolText value={n} strict />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </footer>
      )}

      {plot && <PlotDialog plot={plot} card={card} open={showPlot} onOpenChange={setShowPlot} />}
    </article>
  );
}
