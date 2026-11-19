import { useMemo } from "react";
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import type { TooltipContentProps } from "recharts";
import type { PlotSpec, Series } from "@contract/state";
import { Empty } from "@/components/Section";
import { AXIS_PROPS, AxisFrame, ChartLegend, GRID_STROKE, REF_STROKE, TipBox, axisWidthFor, refLabel, tickFormat } from "@/components/charts/common";
import { fmt } from "@/lib/format";
import { GREY, seriesColor } from "@/lib/palette";
import { logTicks, niceTicks } from "@/lib/scale";

type Row = { x: number } & Record<string, number | null>;

interface Model {
  rows: Row[];
  series: { key: string; spec: Series; color: string; points: { x: number; y: number }[] }[];
  yDomain?: [number, number];
  yTicks?: number[];
  integerX: boolean;
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function buildModel(plot: PlotSpec): Model | null {
  const logY = plot.logY === true;
  const byX = new Map<number, Row>();
  const series: Model["series"] = [];
  (plot.series ?? []).forEach((s, i) => {
    if (!s || !Array.isArray(s.x) || !Array.isArray(s.y)) return;
    const key = `s${i}`; // never use the series name as dataKey: dots would be read as paths
    const points: { x: number; y: number }[] = [];
    const n = Math.min(s.x.length, s.y.length);
    for (let j = 0; j < n; j++) {
      const x = s.x[j];
      const y = s.y[j];
      if (!finite(x) || !finite(y) || (logY && y <= 0)) continue;
      points.push({ x, y });
      const row = byX.get(x) ?? ({ x } as Row);
      if (s.kind !== "scatter") row[key] = y;
      byX.set(x, row);
    }
    if (points.length) series.push({ key, spec: s, color: seriesColor(i), points });
  });
  if (series.length === 0) return null;

  const rows = [...byX.values()].sort((a, b) => a.x - b.x);
  const integerX = rows.every((r) => Number.isInteger(r.x));

  // Own y ticks (linear and log) so the axis width can be sized to the labels.
  const ys = series.flatMap((s) => s.points.map((p) => p.y));
  for (const r of plot.refLines ?? []) if (r.axis === "y" && finite(r.value) && (!logY || r.value > 0)) ys.push(r.value);
  if (logY) {
    const { ticks, domain } = logTicks(Math.min(...ys), Math.max(...ys));
    return { rows, series, integerX, yDomain: domain, yTicks: ticks };
  }
  const { ticks, min, max } = niceTicks(Math.min(...ys), Math.max(...ys), 5);
  return { rows, series, integerX, yDomain: [min, max], yTicks: ticks };
}

function XYTooltip(props: TooltipContentProps, names: Map<string, string>, xLabel?: string) {
  if (!props.active || !props.payload?.length) return null;
  const rows = props.payload
    .filter((p) => finite(p.value))
    .map((p) => ({ name: names.get(String(p.dataKey)) ?? String(p.name ?? ""), value: fmt(p.value as number), color: p.color }));
  const x = props.payload[0]?.payload?.x;
  return <TipBox title={`${xLabel ? `${xLabel} ` : "x "}= ${fmt(finite(x) ? x : Number(props.label))}`} rows={rows} />;
}

export function XYPlot({ plot, height = 260 }: { plot: PlotSpec; height?: number }) {
  const model = useMemo(() => buildModel(plot), [plot]);
  if (!model) return <Empty />;

  const logY = plot.logY === true;
  const names = new Map<string, string>(model.series.map((s) => [s.key, s.spec.name]));
  const legend = model.series.map((s) => ({
    name: s.spec.name,
    color: s.color,
    dashed: s.spec.dashed,
    marker: s.spec.kind === "scatter" ? ("dot" as const) : ("line" as const),
  }));
  const refLines = (plot.refLines ?? []).filter((r) => finite(r.value) && (r.axis === "x" || !logY || r.value > 0));

  return (
    <AxisFrame xLabel={plot.xLabel} yLabel={plot.yLabel} legend={<ChartLegend items={legend} />}>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={model.rows} margin={{ top: 10, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID_STROKE} />
            <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} allowDecimals={!model.integerX} tickFormatter={tickFormat} {...AXIS_PROPS} />
            <YAxis
              type="number"
              width={model.yTicks ? axisWidthFor(model.yTicks) : "auto"}
              scale={logY ? "log" : "auto"}
              domain={model.yDomain}
              ticks={model.yTicks}
              allowDataOverflow={logY}
              tickFormatter={tickFormat}
              {...AXIS_PROPS}
            />
            <ZAxis range={[28, 28]} />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: GREY, strokeWidth: 1, strokeDasharray: "2 2" }}
              content={(p: TooltipContentProps) => XYTooltip(p, names, plot.xLabel)}
            />
            {refLines.map((r, i) => (
              <ReferenceLine
                key={`ref-${i}`}
                {...(r.axis === "x" ? { x: r.value } : { y: r.value })}
                stroke={REF_STROKE}
                strokeWidth={1}
                strokeDasharray="4 3"
                ifOverflow="extendDomain"
                label={refLabel(r.label, r.axis)}
              />
            ))}
            {model.series.map((s) =>
              s.spec.kind === "scatter" ? (
                <Scatter key={s.key} name={s.spec.name} data={s.points} dataKey="y" fill={s.color} isAnimationActive={false} />
              ) : (
                <Line
                  key={s.key}
                  name={s.spec.name}
                  dataKey={s.key}
                  type={s.spec.kind === "step" ? "stepAfter" : "linear"}
                  stroke={s.color}
                  strokeWidth={1.75}
                  strokeDasharray={s.spec.dashed ? "5 4" : undefined}
                  dot={s.points.length <= 12 ? { r: 2.5, strokeWidth: 0, fill: s.color } : false}
                  activeDot={{ r: 3, strokeWidth: 0 }}
                  connectNulls
                  isAnimationActive={false}
                />
              ),
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </AxisFrame>
  );
}
