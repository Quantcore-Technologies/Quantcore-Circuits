import { GREY, INK, PASS, SIGNAL } from "@/lib/palette";

const RANGE = 3;

/** (value − target) / tol on a −3…+3 scale; the ±1 tolerance band is shaded. Out-of-range values get an arrow at the edge. */
export function DeviationBar({ dev, status, width = 168 }: { dev: number | null; status: "pass" | "fail" | "unknown"; width?: number }) {
  const h = 16;
  const pad = 6;
  const w = width - 2 * pad;
  const x = (d: number) => pad + ((d + RANGE) / (2 * RANGE)) * w;
  const colour = status === "pass" ? PASS : status === "fail" ? SIGNAL : GREY;
  const known = dev !== null && Number.isFinite(dev);
  const clipped = known ? Math.max(-RANGE, Math.min(RANGE, dev)) : 0;
  const over = known && Math.abs(dev) > RANGE;
  const mx = x(clipped);

  return (
    <svg width={width} height={h} role="img" aria-label={known ? `deviation ${dev.toFixed(2)} tolerances` : "deviation unknown"} className="block">
      <rect x={x(-1)} y={2} width={x(1) - x(-1)} height={h - 4} fill="#ececec" />
      <line x1={pad} x2={width - pad} y1={h / 2} y2={h / 2} stroke="#cfcfcf" />
      {[-3, -2, -1, 1, 2, 3].map((t) => (
        <line key={t} x1={x(t)} x2={x(t)} y1={h / 2 - 2} y2={h / 2 + 2} stroke="#bdbdbd" />
      ))}
      <line x1={x(0)} x2={x(0)} y1={1} y2={h - 1} stroke={INK} />
      {known &&
        (over ? (
          <path
            d={dev > 0 ? `M${mx - 7} ${h / 2 - 5} L${mx} ${h / 2} L${mx - 7} ${h / 2 + 5} Z` : `M${mx + 7} ${h / 2 - 5} L${mx} ${h / 2} L${mx + 7} ${h / 2 + 5} Z`}
            fill={colour}
          />
        ) : (
          <rect x={mx - 2} y={2} width={4} height={h - 4} fill={colour} />
        ))}
    </svg>
  );
}
