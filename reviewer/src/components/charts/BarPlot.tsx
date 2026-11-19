import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TooltipContentProps } from "recharts";
import type { PlotSpec } from "@contract/state";
import { Empty } from "@/components/Section";
import { AXIS_PROPS, AxisFrame, CategoryTick, ChartLegend, GRID_STROKE, REF_STROKE, SlantedCategoryTick, TipBox, refLabel, tickFormat } from "@/components/charts/common";
import { fmt } from "@/lib/format";
import { INK, seriesColor } from "@/lib/palette";

type Row = { label: string } & Record<string, number | null | string>;

function buildModel(plot: PlotSpec) {
  const groups = (plot.bars ?? []).filter((g) => g && typeof g === "object");
  const names: string[] = [];
  for (const g of groups) for (const k of Object.keys(g.values ?? {})) if (!names.includes(k)) names.push(k);
  if (groups.length === 0 || names.length === 0) return null;
  // b0, b1, … as data keys (series names may contain dots)
  const rows: Row[] = groups.map((g) => {
    const row: Row = { label: String(g.label ?? "") };
    names.forEach((n, i) => {
      const v = g.values?.[n];
      row[`b${i}`] = typeof v === "number" && Number.isFinite(v) ? v : null;
    });
    return row;
  });
  return { rows, names };
}

export function BarPlot({ plot, height = 260 }: { plot: PlotSpec; height?: number }) {
  const model = useMemo(() => buildModel(plot), [plot]);
  if (!model) return <Empty />;
  const legend = model.names.map((n, i) => ({ name: n, color: seriesColor(i), marker: "block" as const }));
  const keyName = new Map<string, string>(model.names.map((n, i) => [`b${i}`, n]));
  // many groups (multi-qubit chips): slanted labels instead of overlapping ones
  const slant = model.rows.length > 6;
  const longest = Math.max(...model.rows.map((r) => String(r.label).length));

  const tooltip = (p: TooltipContentProps) => {
    if (!p.active || !p.payload?.length) return null;
    const rows = p.payload.map((e) => ({ name: keyName.get(String(e.dataKey)) ?? String(e.name ?? ""), value: fmt(e.value as number | null), color: e.color }));
    return <TipBox title={String(p.label ?? "")} rows={rows} />;
  };

  return (
    <AxisFrame xLabel={plot.xLabel} yLabel={plot.yLabel} legend={<ChartLegend items={legend} />}>
      <div style={{ height: slant ? height + Math.min(longest * 4.5, 90) : height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={model.rows} margin={{ top: 10, right: 12, bottom: 0, left: 0 }} barCategoryGap="22%" barGap={1}>
            <CartesianGrid vertical={false} stroke={GRID_STROKE} />
            <XAxis dataKey="label" type="category" interval={0} {...AXIS_PROPS} tick={slant ? SlantedCategoryTick : CategoryTick} height={slant ? Math.min(longest * 4.5, 90) + 16 : undefined} />
            <YAxis type="number" width="auto" tickFormatter={tickFormat} {...AXIS_PROPS} />
            <Tooltip isAnimationActive={false} cursor={{ fill: "#f4f4f4" }} content={tooltip} />
            <ReferenceLine y={0} stroke={INK} strokeWidth={1} />
            {(plot.refLines ?? [])
              .filter((r) => r.axis === "y" && Number.isFinite(r.value))
              .map((r, i) => (
                <ReferenceLine
                  key={`ref-${i}`}
                  y={r.value}
                  stroke={REF_STROKE}
                  strokeDasharray="4 3"
                  ifOverflow="extendDomain"
                  label={refLabel(r.label, "y")}
                />
              ))}
            {model.names.map((n, i) => (
              <Bar key={n} dataKey={`b${i}`} name={n} fill={seriesColor(i)} isAnimationActive={false} maxBarSize={48} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </AxisFrame>
  );
}
