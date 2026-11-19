import type { Goal, State } from "@contract/state";
import type { LiveState } from "@/hooks/useLiveState";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ConnectionIndicator } from "@/components/ConnectionIndicator";
import { RebuildButton } from "@/components/RebuildButton";
import { fmt, shortHash } from "@/lib/format";

const logo = `${import.meta.env.BASE_URL}logo-quantcore-black.png`;

/** "Quantcore" wordmark with CIRCUITS in small letter-spaced caps under it, justified to the wordmark's width. */
export function Logo() {
  return (
    <div className="inline-flex shrink-0 flex-col" role="img" aria-label="Quantcore Circuits">
      <img src={logo} alt="" className="block h-[17px] w-auto" />
      <span className="mt-[5px] flex justify-between text-[8.5px] font-semibold leading-none text-ink" aria-hidden>
        {"CIRCUITS".split("").map((c, i) => (
          <span key={i}>{c}</span>
        ))}
      </span>
    </div>
  );
}

/** Small header badge: targets within tolerance. */
export function GoalBadge({ goal }: { goal: Goal }) {
  if (goal.total === 0) return <Badge variant="muted">Targets —</Badge>;
  return (
    <Badge variant={goal.reached ? "pass" : "signal"} className="num" title={goal.summary}>
      Targets {goal.passed}/{goal.total}
    </Badge>
  );
}

function StackText({ design }: { design: State["design"] }) {
  const { substrate, thickness_um, epsR } = design.stack;
  if (!substrate && !Number.isFinite(thickness_um) && !Number.isFinite(epsR)) return null;
  return (
    <span className="num">
      {substrate} {fmt(thickness_um)} µm, ε<sub className="text-[0.75em]">r</sub> {fmt(epsR)}
    </span>
  );
}

export function Header({ state, live }: { state: State; live: LiveState }) {
  const { design } = state;
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex max-w-[1920px] flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 sm:px-8 lg:flex-nowrap">
        <Logo />
        <span className="h-7 w-px shrink-0 bg-rule-strong" aria-hidden />
        {/* design facts shrink (ellipsis) before the controls on the right ever wrap */}
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-4 gap-y-0.5 lg:flex-nowrap lg:overflow-hidden">
          <span className="max-w-[18rem] shrink-0 truncate text-[15px] font-bold leading-tight" title={design.name}>
            {design.name}
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="shrink-0 cursor-default font-mono text-xs text-muted-foreground">{shortHash(design.hash)}</span>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              <div className="font-mono">{design.hash || "no hash"}</div>
              {design.pdk && <div className="mt-1 text-white/70">{design.pdk}</div>}
              {design.path && <div className="mt-1 font-mono text-white/70">{design.path}</div>}
            </TooltipContent>
          </Tooltip>
          {design.pdk && <span className="hidden min-w-0 truncate text-xs text-muted-foreground min-[1500px]:inline">{design.pdk}</span>}
          <span className="min-w-0 truncate whitespace-nowrap text-xs text-muted-foreground">
            <StackText design={design} />
          </span>
        </div>
        <div className="ml-auto flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 lg:flex-nowrap">
          {live.sample && <Badge variant="outline" className="border-ink">Sample data</Badge>}
          <GoalBadge goal={state.goal} />
          <ConnectionIndicator mode={live.mode} updated={state.updated} fetchedAt={live.fetchedAt} forcedSample={live.forcedSample} error={live.error} />
          <RebuildButton disabled={live.sample} onDone={live.refresh} />
        </div>
      </div>
    </header>
  );
}
