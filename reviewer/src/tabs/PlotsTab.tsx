import type { State } from "@contract/state";
import { PlotGrid } from "@/components/PlotCard";
import { Section, TabPage } from "@/components/Section";
import { plotsFor } from "@/lib/state";

export function PlotsTab({ state }: { state: State }) {
  const plots = plotsFor(state, "plots");
  return (
    <TabPage>
      <Section title="All plots" aside={`${plots.length} plot${plots.length === 1 ? "" : "s"}`}>
        <PlotGrid plots={plots} />
      </Section>
    </TabPage>
  );
}
