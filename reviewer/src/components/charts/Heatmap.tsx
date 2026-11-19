import { Empty } from "@/components/Section";
import { useElementWidth } from "@/hooks/useElementWidth";
import { fmt } from "@/lib/format";
import { GREY, INK, PALETTE } from "@/lib/palette";
import { clamp, tint } from "@/lib/scale";

export interface HeatmapData {
  rows: string[];
  cols: string[];
  values: number[][];
  unit: string;
}

const CHAR_W = 6.8; // approx. width of an 11 px monospace glyph

/** Matrix heatmap with the value printed in every cell; colour encodes |value| (log-scaled). */
export function Heatmap({ data, caption }: { data: HeatmapData | null | undefined; caption?: string }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const rows = data?.rows ?? [];
  const values = Array.isArray(data?.values) ? data.values : [];
  const nCols = Math.max(data?.cols?.length ?? 0, ...values.map((r) => (Array.isArray(r) ? r.length : 0)));
  const cols = Array.from({ length: nCols }, (_, j) => data?.cols?.[j] ?? `${j + 1}`);
  if (!data || values.length === 0 || nCols === 0) return <Empty />;

  const rowLabels = values.map((_, i) => rows[i] ?? `${i + 1}`);
  const flat = values.flat().filter((v) => Number.isFinite(v));
  const maxAbs = Math.max(...flat.map(Math.abs), 1e-12);
  const labelW = Math.max(...rowLabels.map((l) => l.length)) * CHAR_W + 12;
  const longest = Math.max(...cols.map((c) => c.length)) * CHAR_W;
  const rotate = longest > Math.min(92, (width - labelW - 2) / nCols) - 6;
  // a column label rotated by −40° reaches ~cos(40°)·length to the right of its cell centre
  const overhang = rotate ? Math.min(longest, 140) * 0.77 : 0;
  const cell = clamp(Math.floor((width - labelW - overhang - 2) / nCols + (rotate ? 0.5 : 0)), 34, 92);
  const top = rotate ? Math.min(longest * 0.72 + 12, 110) : 20;
  const W = labelW + nCols * cell + (rotate ? Math.max(0, overhang - cell / 2) + 4 : 0);
  const H = top + values.length * cell;

  return (
    <figure className="flex flex-col gap-2">
      <div ref={ref} className="w-full min-w-0 overflow-x-auto">
        <svg width={W} height={H} role="img" aria-label="Matrix heatmap" className="block">
          {cols.map((c, j) => {
            const cx = labelW + j * cell + cell / 2;
            return rotate ? (
              <text key={`c${j}`} x={cx} y={top - 6} transform={`rotate(-40 ${cx} ${top - 6})`} fontSize={11} fontFamily="JetBrains Mono, Consolas, monospace" fill={INK}>
                {c}
              </text>
            ) : (
              <text key={`c${j}`} x={cx} y={top - 7} textAnchor="middle" fontSize={11} fontFamily="JetBrains Mono, Consolas, monospace" fill={INK}>
                {c}
              </text>
            );
          })}
          {values.map((row, i) => (
            <g key={`r${i}`}>
              <text x={labelW - 8} y={top + i * cell + cell / 2} dy="0.32em" textAnchor="end" fontSize={11} fontFamily="JetBrains Mono, Consolas, monospace" fill={INK}>
                {rowLabels[i]}
              </text>
              {cols.map((_, j) => {
                const v = Array.isArray(row) ? row[j] : undefined;
                const ok = typeof v === "number" && Number.isFinite(v);
                const t = ok ? Math.log1p(Math.abs(v)) / Math.log1p(maxAbs) : 0;
                const x = labelW + j * cell;
                const yy = top + i * cell;
                return (
                  <g key={`v${i}-${j}`}>
                    <rect x={x} y={yy} width={cell} height={cell} fill={ok ? tint(PALETTE[0], 0.08 + 0.92 * t) : "#fafafa"} stroke="#fff" strokeWidth={1} />
                    <text
                      x={x + cell / 2}
                      y={yy + cell / 2}
                      dy="0.32em"
                      textAnchor="middle"
                      fontSize={cell >= 56 ? 13 : 11}
                      fontWeight={i === j ? 700 : 400}
                      fill={ok && t > 0.55 ? "#fff" : ok ? INK : GREY}
                    >
                      {ok ? fmt(v, 3) : "—"}
                    </text>
                  </g>
                );
              })}
            </g>
          ))}
        </svg>
      </div>
      <figcaption className="text-xs text-muted-foreground">
        Values in {data.unit || "—"}; shade ∝ log(1 + |value|).{caption ? ` ${caption}` : ""}
      </figcaption>
    </figure>
  );
}
