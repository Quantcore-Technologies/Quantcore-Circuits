import type { State, Step, StepStatus } from "@contract/state";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { SymbolText } from "@/components/SymbolText";
import { fmtTime, pad2 } from "@/lib/format";
import { INK, RULE_STRONG, SIGNAL } from "@/lib/palette";
import { STEP_TAB, TABS, type TabId } from "@/lib/tabs";
import { cn } from "@/lib/utils";

/** Square step marker: filled = done, framed dot = running, cross = failed, frame = pending, slash = skipped. */
export function StepMarker({ status, colour = INK, size = 10 }: { status: StepStatus; colour?: string; size?: number }) {
  const c = status === "failed" ? SIGNAL : colour;
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" aria-hidden className="shrink-0">
      {status === "done" && <rect x="0" y="0" width="10" height="10" fill={c} />}
      {status === "running" && (
        <>
          <rect x="0.75" y="0.75" width="8.5" height="8.5" fill="none" stroke={c} strokeWidth="1.5" />
          <rect x="3" y="3" width="4" height="4" fill={c} />
        </>
      )}
      {status === "failed" && (
        <>
          <rect x="0.75" y="0.75" width="8.5" height="8.5" fill="none" stroke={c} strokeWidth="1.5" />
          <path d="M2.5 2.5 L7.5 7.5 M7.5 2.5 L2.5 7.5" stroke={c} strokeWidth="1.5" />
        </>
      )}
      {(status === "pending" || status === "skipped") && <rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke={RULE_STRONG} strokeWidth="1" />}
      {status === "skipped" && <path d="M1 9 L9 1" stroke={RULE_STRONG} strokeWidth="1" />}
    </svg>
  );
}

/** One step = one segment of the progress bar along the top of the tab row. */
function segmentStyle(status: StepStatus): React.CSSProperties {
  switch (status) {
    case "done":
      return { background: SIGNAL };
    case "running":
      return { background: SIGNAL };
    case "failed":
      return { background: `repeating-linear-gradient(135deg, ${SIGNAL} 0 3px, transparent 3px 5px)` };
    case "skipped":
      return { background: `repeating-linear-gradient(90deg, ${RULE_STRONG} 0 4px, transparent 4px 7px)` };
    default:
      return { background: "#e5e5e5" };
  }
}

const STATUS_TEXT: Record<StepStatus, string> = { pending: "pending", running: "running", done: "done", failed: "failed", skipped: "skipped" };

function stepTime(step: Step): string {
  if (step.status === "running") return step.started ? `since ${fmtTime(step.started)}` : "";
  return step.finished ? fmtTime(step.finished) : step.started ? fmtTime(step.started) : "";
}

function StepsTip({ steps, currentStep }: { steps: Step[]; currentStep: string | null }) {
  return (
    <ol className="flex flex-col gap-2">
      {steps.map((s) => (
        <li key={s.id} className="grid grid-cols-[12px_20px_minmax(0,1fr)_auto] items-baseline gap-x-2">
          <span className="self-center">
            <StepMarker status={s.status} colour={s.id === currentStep ? SIGNAL : INK} size={9} />
          </span>
          <span className="num font-semibold">{pad2(s.index)}</span>
          <span className="min-w-0">
            <span className={cn("font-semibold", s.id === currentStep && "text-signal", s.status === "skipped" && "line-through decoration-rule-strong")}>{s.title}</span>
            {s.summary && (
              <span className="mt-0.5 block leading-4 text-muted-foreground [overflow-wrap:anywhere]">
                <SymbolText value={s.summary} strict />
              </span>
            )}
          </span>
          <span className="num whitespace-nowrap text-right text-2xs uppercase tracking-label text-muted-foreground">
            {STATUS_TEXT[s.status]}
            {stepTime(s) && <span className="ml-1.5 normal-case tracking-normal">{stepTime(s)}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

/**
 * The only navigation row, and the pipeline: wide equal-width tabs in pipeline order, each with one bar segment per
 * design-loop step whose output it shows (red = done, pulsing = running, hatched = failed, grey = pending, dashed =
 * skipped). The tab holding the current step gets the red marker; hover a tab for its steps' summaries.
 */
export function NavTabs({ state, count }: { state: State; count: (id: TabId) => number | null }) {
  const byTab = new Map<TabId, Step[]>();
  for (const s of state.steps) {
    const t = STEP_TAB[s.id];
    if (t) byTab.set(t, [...(byTab.get(t) ?? []), s]);
  }
  const done = state.steps.filter((s) => s.status === "done").length;
  return (
    <TabsList aria-label={`Dashboard sections; design loop ${done} of ${state.steps.length} steps done`}>
      {TABS.map((t) => {
        const steps = byTab.get(t.id) ?? [];
        const current = steps.find((s) => s.id === state.currentStep) ?? null;
        const n = count(t.id);
        const trigger = (
          <TabsTrigger key={t.id} value={t.id}>
            <span className="absolute left-0 right-[2px] top-0 flex h-[3px] gap-[2px]" aria-hidden>
              {steps.map((s) => (
                <span key={s.id} className={cn("h-full flex-1", s.status === "running" && "animate-pulse")} style={segmentStyle(s.status)} />
              ))}
            </span>
            {current && <StepMarker status={current.status} colour={SIGNAL} size={8} />}
            <span className={cn("truncate", current && "text-signal")}>{t.label}</span>
            {n !== null && n > 0 && <span className="num font-normal text-muted-foreground">{n}</span>}
          </TabsTrigger>
        );
        if (steps.length === 0) return trigger;
        return (
          <Tooltip key={t.id}>
            <TooltipTrigger asChild>{trigger}</TooltipTrigger>
            <TooltipContent side="bottom" align="start" className="w-[min(380px,90vw)] max-w-none border border-ink bg-background px-3 py-2.5 text-xs text-foreground">
              <StepsTip steps={steps} currentStep={state.currentStep} />
            </TooltipContent>
          </Tooltip>
        );
      })}
    </TabsList>
  );
}
