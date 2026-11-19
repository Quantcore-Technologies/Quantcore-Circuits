import type { PlotSpec, State } from "@contract/state";
import { HistoryTable } from "@/components/HistoryTable";
import { PlotGrid } from "@/components/PlotCard";
import { Section, TabPage } from "@/components/Section";
import { TargetsTable } from "@/components/TargetsTable";
import { plotsFor } from "@/lib/state";

/** If the backend sends no history plot, derive the objective curve from `history` itself. */
function fallbackPlot(state: State): PlotSpec[] {
  if (state.history.length === 0) return [];
  const rows = [...state.history].sort((a, b) => a.iteration - b.iteration);
  return [
    {
      id: "__objective",
      title: "Objective vs iteration",
      tab: "history",
      kind: "xy",
      xLabel: "Iteration",
      yLabel: "‖r‖ (tolerances)",
      logY: rows.every((r) => r.objective > 0),
      series: [{ name: "objective", x: rows.map((r) => r.iteration), y: rows.map((r) => r.objective) }],
      refLines: [{ axis: "y", value: 1, label: "tolerance" }],
      caption: "Derived from the iteration table",
    },
  ];
}

export function HistoryTab({ state }: { state: State }) {
  const sent = plotsFor(state, "history");
  const plots = sent.length ? sent : fallbackPlot(state);
  const n = state.history.length;
  const failing = state.targets.filter((t) => t.status === "fail").length;
  return (
    <TabPage>
      <Section title="Targets" aside={failing > 0 ? <span className="text-signal">{failing} outside tolerance</span> : state.targets.length > 0 && "all within tolerance"}>
        <TargetsTable targets={state.targets} />
      </Section>
      <Section title="Convergence">
        <PlotGrid plots={plots} />
      </Section>
      <Section title="Iterations" aside={`${n} iteration${n === 1 ? "" : "s"} · residual = (value − target) / tol`}>
        <HistoryTable history={state.history} />
      </Section>
    </TabPage>
  );
}
