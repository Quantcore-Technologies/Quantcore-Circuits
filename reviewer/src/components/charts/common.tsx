import type { ReactNode } from "react";
import { svgRich } from "@/components/SymbolText";
import { fmt } from "@/lib/format";
import { GREY, INK } from "@/lib/palette";

export const AXIS_PROPS = {
  axisLine: { stroke: INK, strokeWidth: 1 },
  tickLine: { stroke: INK, strokeWidth: 1 },
  tickSize: 4,
  tick: { fill: GREY, fontSize: 11 },
} as const;

export const GRID_STROKE = "#efefef";
export const REF_STROKE = "#8c8c8c";

export const tickFormat = (v: unknown) => (typeof v === "number" ? fmt(v, 3) : String(v ?? ""));

/** Y-axis width that fits the given tick labels (Recharts' "auto" misjudges log axes). */
export const axisWidthFor = (ticks: number[]) => Math.ceil(Math.max(...ticks.map((t) => tickFormat(t).length), 1) * 6.6 + 14);

interface TickProps {
  x?: number | string;
  y?: number | string;
  payload?: { value?: unknown };
}

/** Category tick with "_x" subscripts ("f_q (GHz)"). */
export function CategoryTick({ x = 0, y = 0, payload }: TickProps) {
  return (
    <text x={Number(x)} y={Number(y) + 12} textAnchor="middle" fontSize={11} fill={INK}>
      {svgRich(String(payload?.value ?? ""), true)}
    </text>
  );
}

/** Category tick slanted by 35° (many groups: one bar group per qubit / resonator parameter). */
export function SlantedCategoryTick({ x = 0, y = 0, payload }: TickProps) {
  return (
    <text x={Number(x)} y={Number(y) + 10} textAnchor="end" fontSize={11} fill={INK} transform={`rotate(-35 ${Number(x)} ${Number(y) + 10})`}>
      {svgRich(String(payload?.value ?? ""), true)}
    </text>
  );
}

interface LabelViewBox {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
}

/** Small grey label for a dashed reference line: right end above a y-line, top of an x-line. */
export function refLabel(text: string, axis: "x" | "y") {
  const RefLabel = ({ viewBox }: { viewBox?: LabelViewBox }) => {
    const x = viewBox?.x ?? 0;
    const y = viewBox?.y ?? 0;
    const w = viewBox?.width ?? 0;
    return axis === "y" ? (
      <text x={x + w - 4} y={y - 4} textAnchor="end" fontSize={10} fill={GREY}>
        {svgRich(text, true)}
      </text>
    ) : (
      <text x={x + 4} y={y + 10} fontSize={10} fill={GREY}>
        {svgRich(text, true)}
      </text>
    );
  };
  return RefLabel;
}

export interface LegendItem {
  name: string;
  color: string;
  dashed?: boolean;
  marker?: "line" | "dot" | "block";
}

/** Inline legend shown above a chart; only rendered for more than one series. */
export function ChartLegend({ items }: { items: LegendItem[] }) {
  if (items.length < 2) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {items.map((it) => (
        <span key={it.name} className="inline-flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden>
            {it.marker === "dot" ? (
              <circle cx="9" cy="4" r="3" fill={it.color} />
            ) : it.marker === "block" ? (
              <rect x="4" y="0" width="10" height="8" fill={it.color} />
            ) : (
              <line x1="0" x2="18" y1="4" y2="4" stroke={it.color} strokeWidth="2" strokeDasharray={it.dashed ? "4 3" : undefined} />
            )}
          </svg>
          {it.name}
        </span>
      ))}
    </div>
  );
}

/** Swiss-style axis captions: y label flush-left above the plot, x label flush-right below it. */
export function AxisFrame({ xLabel, yLabel, legend, children }: { xLabel?: string; yLabel?: string; legend?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      {(yLabel || legend) && (
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
          <span className="text-2xs text-muted-foreground">{yLabel}</span>
          {legend}
        </div>
      )}
      {children}
      {xLabel && <div className="text-right text-2xs text-muted-foreground">{xLabel}</div>}
    </div>
  );
}

export interface TipRow {
  name: string;
  value: string;
  color?: string;
}

export function TipBox({ title, rows }: { title?: string; rows: TipRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="border border-ink bg-white px-2 py-1.5 text-xs">
      {title && <div className="num mb-1 text-muted-foreground">{title}</div>}
      {rows.map((r, i) => (
        <div key={`${r.name}-${i}`} className="flex items-center gap-2">
          {r.color && <span className="inline-block h-2 w-2" style={{ background: r.color }} />}
          <span>{r.name}</span>
          <span className="num ml-auto pl-3 font-semibold">{r.value}</span>
        </div>
      ))}
    </div>
  );
}
