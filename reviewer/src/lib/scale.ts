/** "Nice" linear ticks covering [lo, hi]. */
export function niceTicks(lo: number, hi: number, count = 5): { ticks: number[]; min: number; max: number } {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ticks: [0, 1], min: 0, max: 1 };
  if (lo === hi) {
    const d = Math.abs(lo) * 0.1 || 1;
    lo -= d;
    hi += d;
  }
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = min; v <= max + step * 1e-6; v += step) ticks.push(Number(v.toPrecision(12)));
  return { ticks, min, max };
}

/** Decade ticks (with 2/5 or 3 subdivisions when the range is short) for a log axis. */
export function logTicks(lo: number, hi: number): { ticks: number[]; domain: [number, number] } {
  const a = Math.floor(Math.log10(lo));
  let b = Math.ceil(Math.log10(hi));
  if (b === a) b = a + 1;
  const decades = b - a;
  const mult = decades <= 2 ? [1, 2, 5] : decades <= 4 ? [1, 3] : [1];
  const ticks: number[] = [];
  for (let e = a; e <= b; e++) {
    for (const m of mult) {
      const v = Number((m * 10 ** e).toPrecision(6));
      if (v >= 10 ** a && v <= 10 ** b) ticks.push(v);
    }
  }
  return { ticks, domain: [10 ** a, 10 ** b] };
}

/** Linear blend from white to `hex` at fraction t ∈ [0, 1]. */
export function tint(hex: string, t: number): string {
  const c = hex.replace("#", "");
  const rgb = [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16));
  const k = Math.min(1, Math.max(0, t));
  const [r, g, b] = rgb.map((v) => Math.round(255 + (v - 255) * k));
  return `rgb(${r}, ${g}, ${b})`;
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
