import type { Level } from "@contract/state";
import { Empty } from "@/components/Section";
import { useElementWidth } from "@/hooks/useElementWidth";
import { fmt } from "@/lib/format";
import { GREY, INK, RULE, seriesColor } from "@/lib/palette";
import { niceTicks } from "@/lib/scale";

const LABEL_GAP = 13; // min vertical distance between labels, px

/** Push labels apart so none are closer than LABEL_GAP, keeping them inside [top, bottom]. */
function spreadLabels(ys: number[], top: number, bottom: number): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => b.y - a.y); // bottom (lowest energy) first
  const out = new Array<number>(ys.length);
  let prev = Infinity;
  for (const o of order) {
    const y = Math.min(o.y, prev - LABEL_GAP);
    out[o.i] = y;
    prev = y;
  }
  const minY = Math.min(...out);
  if (minY < top) {
    // overflowed at the top: shift everything down again, still respecting the gap from below
    const shift = top - minY;
    let next = -Infinity;
    for (const o of [...order].reverse()) {
      const y = Math.max(out[o.i] + shift, next + LABEL_GAP);
      out[o.i] = Math.min(y, bottom);
      next = out[o.i];
    }
  }
  return out;
}

/** Energy-level diagram: one column per `group`, a tick per level, labels de-overlapped with leaders. */
export function LevelsPlot({ levels, yLabel = "Energy (GHz)", height = 300 }: { levels: Level[] | undefined; yLabel?: string; height?: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const valid = (levels ?? []).filter((l) => l && Number.isFinite(l.energy));
  if (valid.length === 0) return <Empty />;

  const groups: string[] = [];
  for (const l of valid) if (!groups.includes(l.group ?? "")) groups.push(l.group ?? "");
  const named = groups.some((g) => g !== "");

  const energies = valid.map((l) => l.energy);
  const { ticks, min, max } = niceTicks(Math.min(0, ...energies), Math.max(...energies), 5);
  const m = { top: named ? 26 : 12, right: 8, bottom: 10, left: 40 };
  const H = height;
  const W = Math.max(width, 240);
  const plotW = W - m.left - m.right;
  const y = (e: number) => m.top + (H - m.top - m.bottom) * (1 - (e - min) / (max - min || 1));
  const colW = plotW / groups.length;
  const tickW = Math.min(96, colW * 0.38);

  return (
    <div className="flex flex-col gap-1">
      <span className="text-2xs text-muted-foreground">{yLabel}</span>
      <div ref={ref} className="w-full min-w-0 overflow-hidden">
        <svg width={W} height={H} role="img" aria-label="Energy level diagram" className="block overflow-visible">
          <line x1={m.left} x2={m.left} y1={m.top} y2={H - m.bottom} stroke={INK} />
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.left - 4} x2={m.left} y1={y(t)} y2={y(t)} stroke={INK} />
              <line x1={m.left} x2={W - m.right} y1={y(t)} y2={y(t)} stroke={RULE} strokeWidth={0.75} />
              <text x={m.left - 7} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill={GREY}>
                {fmt(t, 3)}
              </text>
            </g>
          ))}
          {groups.map((g, gi) => {
            const x0 = m.left + gi * colW + 14;
            const x1 = x0 + tickW;
            const items = valid.filter((l) => (l.group ?? "") === g);
            const ys = items.map((l) => y(l.energy));
            const labelYs = spreadLabels(ys, m.top + 4, H - m.bottom);
            const colour = groups.length > 1 ? seriesColor(gi) : INK;
            return (
              <g key={g || "levels"}>
                {named && (
                  <text x={x0} y={12} fontSize={10} fontWeight={600} letterSpacing="0.12em" fill={GREY}>
                    {g.toUpperCase()}
                  </text>
                )}
                {items.map((l, i) => {
                  const moved = Math.abs(labelYs[i] - ys[i]) > 0.5;
                  return (
                    <g key={`${l.label}-${i}`}>
                      <line x1={x0} x2={x1} y1={ys[i]} y2={ys[i]} stroke={colour} strokeWidth={2} />
                      {moved && <polyline points={`${x1},${ys[i]} ${x1 + 6},${labelYs[i]} ${x1 + 10},${labelYs[i]}`} fill="none" stroke={GREY} strokeWidth={0.75} />}
                      <text x={x1 + 12} y={labelYs[i]} dy="0.32em" fontSize={12} fill={INK}>
                        {l.label}
                        <tspan dx={8} fontSize={11} fill={GREY}>
                          {fmt(l.energy)}
                        </tspan>
                      </text>
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
