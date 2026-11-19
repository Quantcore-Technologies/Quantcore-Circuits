import { Fragment, type ReactNode } from "react";

export interface RichPart {
  text: string;
  sub: boolean;
}

// Loose: every "_x" / "_{xy}" is a subscript (labels and symbols such as "C_Σ − C_g").
const LOOSE = /_(\{[^}]*\}|[^\s_^]+)/g;
// Strict: only a single letter followed by "_x" ("C_Σ 97.1 fF"), so names like "q1_r1_feedline" stay intact.
const STRICT = /(^|[^\p{L}\p{N}_])(\p{L})_(\{[^}]*\}|[\p{L}\p{N}]+)/gu;

export function parseSubscripts(s: string, strict = false): RichPart[] {
  const parts: RichPart[] = [];
  const re = new RegExp(strict ? STRICT : LOOSE);
  let last = 0;
  for (let m = re.exec(s); m; m = re.exec(s)) {
    const underscore = strict ? m.index + m[1].length + m[2].length : m.index;
    const subText = strict ? m[3] : m[1];
    if (underscore > last) parts.push({ text: s.slice(last, underscore), sub: false });
    parts.push({ text: subText.replace(/^\{|\}$/g, ""), sub: true });
    last = m.index + m[0].length;
  }
  if (last < s.length) parts.push({ text: s.slice(last), sub: false });
  return parts;
}

/** Plain-text physics symbol with subscripts, e.g. "f_q" → f<sub>q</sub>. */
export function SymbolText({ value, strict = false, className }: { value: string | null | undefined; strict?: boolean; className?: string }) {
  if (!value) return <span className={className}>—</span>;
  return (
    <span className={className}>
      {parseSubscripts(value, strict).map((p, i) =>
        p.sub ? (
          <sub key={i} className="text-[0.75em]">
            {p.text}
          </sub>
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
    </span>
  );
}

/** Same as SymbolText, as SVG <tspan>s. */
export function svgRich(s: string, strict = false): ReactNode[] {
  let shifted = false;
  return parseSubscripts(s, strict).map((p, i) => {
    const dy = p.sub && !shifted ? 3 : !p.sub && shifted ? -3 : 0;
    shifted = p.sub;
    return (
      <tspan key={i} dy={dy || undefined} fontSize={p.sub ? "0.78em" : undefined}>
        {p.text}
      </tspan>
    );
  });
}
