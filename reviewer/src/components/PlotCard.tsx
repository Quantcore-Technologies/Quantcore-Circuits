import type { PlotSpec } from "@contract/state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty } from "@/components/Section";
import { BarPlot } from "@/components/charts/BarPlot";
import { Heatmap } from "@/components/charts/Heatmap";
import { LevelsPlot } from "@/components/charts/LevelsPlot";
import { XYPlot } from "@/components/charts/XYPlot";
import { cn } from "@/lib/utils";

export function PlotBody({ plot, height }: { plot: PlotSpec; height?: number }) {
  switch (plot.kind) {
    case "xy":
      return <XYPlot plot={plot} height={height} />;
    case "bar":
      return <BarPlot plot={plot} height={height} />;
    case "levels":
      return <LevelsPlot levels={plot.levels} yLabel={plot.yLabel ?? "Energy (GHz)"} height={height} />;
    case "heatmap":
      return <Heatmap data={plot.heatmap} />;
    default:
      return <Empty>Unsupported plot kind “{String((plot as { kind?: unknown }).kind)}”</Empty>;
  }
}

export function PlotCard({ plot, height, className }: { plot: PlotSpec; height?: number; className?: string }) {
  return (
    <Card className={cn("flex min-w-0 flex-col", className)}>
      <CardHeader>
        <CardTitle>{plot.title || plot.id}</CardTitle>
      </CardHeader>
      <CardContent className="flex-1">
        <PlotBody plot={plot} height={height} />
      </CardContent>
      {plot.caption && (
        <CardDescription className="border-t border-rule px-4 py-2">{plot.caption}</CardDescription>
      )}
    </Card>
  );
}

/** Responsive grid of plot cards: two columns from `lg` up. */
export function PlotGrid({ plots, className }: { plots: PlotSpec[]; className?: string }) {
  if (plots.length === 0) return <Empty />;
  return (
    <div className={cn("grid grid-cols-1 gap-6 lg:grid-cols-2", className)}>
      {plots.map((p) => (
        <PlotCard key={p.id} plot={p} />
      ))}
    </div>
  );
}
