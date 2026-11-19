import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { State } from "@contract/state";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Header, Logo } from "@/components/Header";
import { NavTabs } from "@/components/NavTabs";
import { useLiveState } from "@/hooks/useLiveState";
import { parseTab, type TabId } from "@/lib/tabs";
import { CircuitTab } from "@/tabs/CircuitTab";
import { HamiltonianTab } from "@/tabs/HamiltonianTab";
import { HistoryTab } from "@/tabs/HistoryTab";
import { LayoutTab } from "@/tabs/LayoutTab";
import { LogTab } from "@/tabs/LogTab";
import { ParametersTab } from "@/tabs/ParametersTab";
import { PlotsTab } from "@/tabs/PlotsTab";
import { SimulationTab } from "@/tabs/SimulationTab";

/** Selected tab, initialised from and mirrored into `?tab=` (`?tab=overview` is an alias of `parameters`). */
function useTabParam(): [TabId, (t: string) => void] {
  const [tab, setTab] = useState<TabId>(() => parseTab(new URLSearchParams(window.location.search).get("tab")) ?? "parameters");
  const select = useCallback((t: string) => {
    const id = parseTab(t);
    if (!id) return;
    setTab(id);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", id);
    window.history.replaceState(null, "", url.toString().replace(/([?&])sample=(&|$)/, "$1sample$2"));
  }, []);
  return [tab, select];
}

/** Publish the sticky header's height as --sticky-h (sticky summary column, scroll margins). */
function useStickyHeight(enabled: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!enabled || !el) return;
    const set = () => document.documentElement.style.setProperty("--sticky-h", `${Math.ceil(el.getBoundingClientRect().height)}px`);
    set();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, [enabled]);
  return ref;
}

function tabCount(state: State, id: TabId): number | null {
  switch (id) {
    case "parameters":
      return state.cards.length;
    case "layout":
      return state.screenshots.length;
    case "plots":
      return state.plots.filter((p) => p.tab === "plots").length;
    case "simulation":
      return state.jobs.length;
    case "history":
      return state.history.length;
    case "log":
      return state.log.length;
    default:
      return null;
  }
}

function Splash({ message, detail }: { message: string; detail?: string | null }) {
  return (
    <div className="mx-auto max-w-[1920px] px-4 py-16 sm:px-8">
      <Logo />
      <div className="mt-10 border-t border-ink pt-2 text-2xs font-semibold uppercase tracking-label">{message}</div>
      {detail && <div className="mt-2 font-mono text-xs text-muted-foreground">{detail}</div>}
    </div>
  );
}

export default function App() {
  const live = useLiveState();
  const [tab, setTab] = useTabParam();
  const { state } = live;
  const stickyRef = useStickyHeight(state !== null);
  const goal = state ? (state.goal.reached ? "targets met" : `targets ${state.goal.passed}/${state.goal.total}`) : "";
  useEffect(() => {
    document.title = state ? `${state.design.name} · ${goal} — Quantcore Circuits` : "Quantcore Circuits";
  }, [state, goal]);

  if (!state) {
    const failed = live.mode === "offline";
    return <Splash message={failed ? "No data yet — backend and sample fixture are unreachable" : "Connecting…"} detail={failed ? live.error : null} />;
  }

  return (
    <TooltipProvider delayDuration={250}>
      <Tabs value={tab} onValueChange={setTab} className="min-h-screen bg-background text-foreground">
        <div ref={stickyRef} className="sticky top-0 z-30 bg-background">
          <Header state={state} live={live} />
          <div className="mx-auto max-w-[1920px] px-4 sm:px-8">
            <NavTabs state={state} count={(id) => tabCount(state, id)} />
          </div>
        </div>
        <main className="mx-auto max-w-[1920px] px-4 pb-24 sm:px-8">
          <TabsContent value="parameters">
            <ParametersTab state={state} />
          </TabsContent>
          <TabsContent value="layout">
            <LayoutTab state={state} />
          </TabsContent>
          <TabsContent value="circuit">
            <CircuitTab state={state} />
          </TabsContent>
          <TabsContent value="hamiltonian">
            <HamiltonianTab state={state} />
          </TabsContent>
          <TabsContent value="plots">
            <PlotsTab state={state} />
          </TabsContent>
          <TabsContent value="simulation">
            <SimulationTab state={state} />
          </TabsContent>
          <TabsContent value="history">
            <HistoryTab state={state} />
          </TabsContent>
          <TabsContent value="log">
            <LogTab state={state} />
          </TabsContent>
        </main>
      </Tabs>
    </TooltipProvider>
  );
}
