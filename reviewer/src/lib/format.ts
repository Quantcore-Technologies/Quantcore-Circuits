const MINUS = "−";

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Number with ~4 significant digits, typographic minus, "—" for missing values. */
export function fmt(v: number | null | undefined, digits = 4): string {
  if (!isNum(v)) return "—";
  let s: string;
  if (v === 0) s = "0";
  else if (Math.abs(v) >= 1e6) s = v.toExponential(2).replace(/\.?0+e/, "e").replace("e+", "e");
  else if (Math.abs(v) >= 10 ** digits) s = Math.round(v).toString();
  else if (Math.abs(v) < 1e-3) s = v.toExponential(Math.max(digits - 2, 1));
  else s = Number(v.toPrecision(digits)).toString();
  return s.replace("-", MINUS);
}

/** Narrow no-break space: thin-space digit grouping that never wraps. */
export const THIN = " ";

/**
 * fmt() with the integer part grouped in threes from five digits on: "80 185", "30 982", but "4200".
 * `fixed` keeps trailing zeros of non-integers so computed values always show `digits` significant digits ("69.20").
 */
export function fmtNum(v: number | null | undefined, digits = 4, fixed = false): string {
  let s = fmt(v, digits);
  if (fixed && isNum(v) && !Number.isInteger(v) && Math.abs(v) >= 1e-3 && Math.abs(v) < 10 ** digits) s = v.toPrecision(digits).replace("-", MINUS);
  if (s === "—" || /e/i.test(s)) return s;
  const neg = s.startsWith(MINUS);
  const [int, frac] = (neg ? s.slice(1) : s).split(".");
  const grouped = int.length >= 5 ? int.replace(/\B(?=(\d{3})+(?!\d))/g, THIN) : int;
  return (neg ? MINUS : "") + grouped + (frac !== undefined ? `.${frac}` : "");
}

/** Fixed decimals with explicit sign, e.g. "+0.40", "−4.80". */
export function fmtSigned(v: number | null | undefined, decimals = 2): string {
  if (!isNum(v)) return "—";
  const s = Math.abs(v).toFixed(decimals);
  if (Number(s) === 0) return s;
  return (v < 0 ? MINUS : "+") + s;
}

export function fmtUnit(v: number | null | undefined, unit?: string): string {
  const s = fmt(v);
  return s === "—" || !unit ? s : `${s} ${unit}`;
}

/** Relative value as a percentage with two significant digits, e.g. 0.0034 → "0.34 %". */
export function fmtPct(rel: number | null | undefined): string {
  if (!isNum(rel)) return "—";
  const p = rel * 100;
  const s = Math.abs(p) >= 100 ? Math.round(p).toString() : Number(p.toPrecision(2)).toString();
  return `${s.replace("-", MINUS)} %`;
}

export function parseTime(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

const pad = (n: number) => n.toString().padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Local "hh:mm:ss". */
export function fmtClock(d: Date | string | null | undefined): string {
  const t = typeof d === "string" ? parseTime(d) : d ?? null;
  if (!t) return "—";
  return `${pad(t.getHours())}:${pad(t.getMinutes())}:${pad(t.getSeconds())}`;
}

/** Local time, prefixed with the date when it is not today: "02 Nov 20:04". */
export function fmtTime(iso: string | null | undefined, withSeconds = false): string {
  const t = parseTime(iso);
  if (!t) return "—";
  const hm = withSeconds ? fmtClock(t) : `${pad(t.getHours())}:${pad(t.getMinutes())}`;
  const now = new Date();
  const sameDay = t.getFullYear() === now.getFullYear() && t.getMonth() === now.getMonth() && t.getDate() === now.getDate();
  return sameDay ? hm : `${pad(t.getDate())} ${MONTHS[t.getMonth()]} ${hm}`;
}

export const pad2 = (n: number) => pad(n);

export const shortHash = (h: string | null | undefined, n = 8) => (h ? h.slice(0, n) : "—");

/** "Q1.f_q_GHz" style keys are long; strip the trailing unit suffix for column headers. */
export const shortKey = (key: string) => key.replace(/_(GHz|MHz|fF|nH|um|µm|Ohm)$/i, "");
