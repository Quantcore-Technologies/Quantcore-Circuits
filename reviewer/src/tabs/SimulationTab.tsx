import type { State } from "@contract/state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Heatmap } from "@/components/charts/Heatmap";
import { FemCompareTable } from "@/components/FemCompareTable";
import { JobsTable } from "@/components/JobsTable";
import { PlotCard } from "@/components/PlotCard";
import { Empty, Section, TabPage } from "@/components/Section";
import { plotsFor } from "@/lib/state";

export function SimulationTab({ state }: { state: State }) {
  const { cmatrix } = state;
  const plots = plotsFor(state, "simulation");
  const done = state.jobs.filter((j) => j.hasResults).length;
  return (
    <TabPage>
      <Section title="Jobs" aside={state.jobs.length > 0 && `${done} of ${state.jobs.length} with results`}>
        <JobsTable jobs={state.jobs} />
      </Section>
      <Section title="Estimate vs FEM" aside={(state.femCompare?.length ?? 0) > 0 && `${state.femCompare?.length} branches`}>
        <FemCompareTable rows={state.femCompare ?? []} />
      </Section>
      <Section title="Capacitance matrix"
 className="xl:col-span-6" aside={cmatrix?.job && <span className="font-mono normal-case tracking-normal">{cmatrix.job}</span>}>
        {cmatrix ? (
          <Card>
            <CardHeader>
              <CardTitle>Maxwell C-matrix</CardTitle>
            </CardHeader>
            <CardContent>
              <Heatmap data={{ rows: cmatrix.labels ?? [], cols: cmatrix.labels ?? [], values: cmatrix.matrix ?? [], unit: cmatrix.unit }} />
            </CardContent>
          </Card>
        ) : (
          <Empty>No C-matrix yet</Empty>
        )}
      </Section>
      <Section title="Plots" className="xl:col-span-6">
        {plots.length ? (
          <div className="grid grid-cols-1 gap-6">
            {plots.map((p) => (
              <PlotCard key={p.id} plot={p} />
            ))}
          </div>
        ) : (
          <Empty />
        )}
      </Section>
    </TabPage>
  );
}
