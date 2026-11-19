import type { Circuit, CircuitBranch, CircuitNode } from "@contract/state";
import { Empty } from "@/components/Section";
import { svgRich } from "@/components/SymbolText";
import { useElementWidth } from "@/hooks/useElementWidth";
import { fmt } from "@/lib/format";
import { GREY, INK } from "@/lib/palette";
import { clamp } from "@/lib/scale";

type P = { x: number; y: number };
type BranchType = CircuitBranch["type"];

type Pad = { left: number; right: number; top: number; bottom: number };

const BASE_PAD: Pad = { left: 24, right: 24, top: 44, bottom: 28 };
const EDGE = 6; // keep labels this far from the SVG edge
const PARALLEL_SPACING = 66; // px between parallel branches of the same node pair
const SYMBOL_WIDTH = 28; // perpendicular extent reserved for any symbol
const HALF_BODY: Record<BranchType, number> = { C: 4, L: 16, JJ: 8, SQUID: 14, TL: 24, R: 16, HANGER: 18 };

const add = (a: P, b: P): P => ({ x: a.x + b.x, y: a.y + b.y });
const mul = (a: P, k: number): P => ({ x: a.x * k, y: a.y * k });
const sub = (a: P, b: P): P => ({ x: a.x - b.x, y: a.y - b.y });
const len = (a: P) => Math.hypot(a.x, a.y);

/** Symbol body in a local frame: wire along +x, centred on the origin; leads are drawn by the caller. */
function SymbolBody({ type }: { type: BranchType }) {
  const s = { stroke: INK, strokeWidth: 1.5, fill: "none" } as const;
  switch (type) {
    case "C":
      return (
        <g {...s} strokeWidth={2.25}>
          <line x1={-4} x2={-4} y1={-12} y2={12} />
          <line x1={4} x2={4} y1={-12} y2={12} />
        </g>
      );
    case "L":
      return <path {...s} d="M -16 0 a 4 4 0 0 1 8 0 a 4 4 0 0 1 8 0 a 4 4 0 0 1 8 0 a 4 4 0 0 1 8 0" />;
    case "JJ":
      return (
        <g {...s}>
          <rect x={-8} y={-8} width={16} height={16} fill="#fff" />
          <path d="M -8 -8 L 8 8 M 8 -8 L -8 8" />
        </g>
      );
    case "SQUID":
      return (
        <g {...s}>
          <rect x={-14} y={-11} width={28} height={22} />
          {[-11, 11].map((y) => (
            <g key={y} transform={`translate(0 ${y})`}>
              <rect x={-5} y={-5} width={10} height={10} fill="#fff" />
              <path d="M -5 -5 L 5 5 M 5 -5 L -5 5" />
            </g>
          ))}
        </g>
      );
    case "TL":
      return <rect {...s} x={-24} y={-4} width={48} height={8} fill="#fff" />;
    case "R":
      return <polyline {...s} points="-16,0 -13.3,-6 -8,6 -2.7,-6 2.7,6 8,-6 13.3,6 16,0" />;
    case "HANGER":
      // Coupled-line section: two short parallel lines with a small gap, each fed from one side.
      return (
        <g {...s}>
          <path d="M -18 0 V -4.5 H 12" strokeWidth={2.25} />
          <path d="M 18 0 V 4.5 H -12" strokeWidth={2.25} />
        </g>
      );
    default:
      return <rect {...s} x={-10} y={-6} width={20} height={12} strokeDasharray="2 2" />;
  }
}

interface Placed {
  branch: CircuitBranch;
  a: P; // wire start (node side)
  b: P; // wire end
  start: P; // offset start
  end: P; // offset end
  mid: P;
  dir: P;
  outward: P;
}

interface Rail {
  node: CircuitNode;
  y: number;
  xs: number[];
  symbolX: number;
}

const hint = (n: CircuitNode): P => {
  const [px, py] = Array.isArray(n.pos) ? n.pos : [0.5, 0.5];
  return { x: clamp(Number(px) || 0, 0, 1), y: clamp(Number(py) || 0, 0, 1) };
};

/** Map one axis of the position hints onto [lo, hi], stretched to the hints' own extent. */
const fit = (values: number[]) => {
  const min = Math.min(...values);
  const span = Math.max(...values) - min;
  return (v: number, lo: number, hi: number) => (span < 1e-6 ? (lo + hi) / 2 : lo + ((v - min) / span) * (hi - lo));
};

function layout(circuit: Circuit, W: number, H: number, PAD: Pad) {
  const hints = (circuit.nodes ?? []).map((n) => ({ n, h: hint(n) }));
  const fx = fit(hints.map((x) => x.h.x));
  const fy = fit(hints.map((x) => x.h.y));
  const nodes = new Map<string, CircuitNode & { p: P }>();
  for (const { n, h } of hints) {
    nodes.set(n.id, { ...n, p: { x: fx(h.x, PAD.left, W - PAD.right), y: fy(h.y, PAD.top, H - PAD.bottom) } });
  }

  // Group parallel branches: same node pair, or same node to the same ground.
  const groups = new Map<string, { branch: CircuitBranch; a: P; b: P; ground?: string }[]>();
  for (const br of circuit.branches ?? []) {
    const [i, j] = br.nodes ?? [];
    const n1 = nodes.get(i);
    const n2 = nodes.get(j);
    if (!n1 || !n2 || n1 === n2) continue;
    if (n1.ground && n2.ground) continue;
    let item: { branch: CircuitBranch; a: P; b: P; ground?: string };
    let key: string;
    if (n1.ground || n2.ground) {
      const top = n1.ground ? n2 : n1;
      const g = n1.ground ? n1 : n2;
      item = { branch: br, a: top.p, b: { x: top.p.x, y: g.p.y }, ground: g.id };
      key = `${top.id}|${g.id}`;
    } else {
      // Same orientation for every branch of a pair, so parallel offsets do not collide.
      const [u, v] = n1.id < n2.id ? [n1, n2] : [n2, n1];
      item = { branch: br, a: u.p, b: v.p };
      key = `${u.id}|${v.id}`;
    }
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }

  const placed: Placed[] = [];
  const rails = new Map<string, Rail>();
  for (const items of groups.values()) {
    items.forEach((it, k) => {
      const v = sub(it.b, it.a);
      const L = len(v) || 1;
      const dir = mul(v, 1 / L);
      const horizontal = !it.ground && Math.abs(dir.y) < 0.2;
      // Horizontal pairs: first branch on the direct wire, the others stacked below (node labels sit above).
      const perp = horizontal ? { x: 0, y: 1 } : { x: dir.y, y: -dir.x };
      const off = horizontal ? k * PARALLEL_SPACING : (k - (items.length - 1) / 2) * PARALLEL_SPACING;
      const start = add(it.a, mul(perp, off));
      const end = add(it.b, mul(perp, off));
      const mid = mul(add(start, end), 0.5);
      let outward: P;
      if (off !== 0) outward = mul(perp, Math.sign(off));
      else if (Math.abs(dir.x) < 0.2) outward = { x: 1, y: 0 }; // vertical: labels to the right
      else if (Math.abs(dir.y) < 0.2) outward = { x: 0, y: -1 }; // horizontal: labels above
      else outward = perp.y < 0 ? perp : mul(perp, -1); // diagonal: off the wire, upwards
      placed.push({ branch: it.branch, a: it.a, b: it.b, start, end, mid, dir, outward });
      if (it.ground) {
        const g = nodes.get(it.ground)!;
        const rail = rails.get(g.id) ?? { node: g, y: it.b.y, xs: [], symbolX: g.p.x };
        rail.xs.push(end.x);
        rails.set(g.id, rail);
      }
    });
  }
  for (const n of nodes.values()) if (n.ground && !rails.has(n.id)) rails.set(n.id, { node: n, y: n.p.y, xs: [], symbolX: n.p.x });

  return { nodes: [...nodes.values()], placed, rails: [...rails.values()] };
}

interface LabelLine {
  text: string;
  size: number;
  weight?: number;
  fill: string;
}

const LINE_H = 14;
const textWidth = (text: string, size: number, weight = 400) => text.length * size * (weight >= 600 ? 0.62 : 0.56);

/** Where a branch's label block goes: beside vertical wires, above (or below) horizontal ones. */
function labelGeometry(p: Placed) {
  const { branch: br, mid, outward } = p;
  const lines: LabelLine[] = [
    { text: br.label || br.id || "", size: 12, weight: 600, fill: INK },
    { text: typeof br.value === "number" && Number.isFinite(br.value) ? `${fmt(br.value)}${br.unit ? ` ${br.unit}` : ""}` : "—", size: 11, fill: INK },
  ];
  if (typeof br.designValue === "number" && br.designValue !== br.value) lines.push({ text: `design ${fmt(br.designValue)}`, size: 10, fill: GREY });

  const at = add(mid, mul(outward, SYMBOL_WIDTH / 2 + 8));
  const anchor: "start" | "end" | "middle" = outward.x > 0.5 ? "start" : outward.x < -0.5 ? "end" : "middle";
  const blockH = lines.length * LINE_H;
  const firstBaseline = outward.y < -0.5 ? at.y - blockH + LINE_H - 3 : outward.y > 0.5 ? at.y + LINE_H - 2 : at.y - blockH / 2 + LINE_H - 3;
  const width = Math.max(...lines.map((l) => textWidth(l.text, l.size, l.weight)));
  const x0 = anchor === "start" ? at.x : anchor === "end" ? at.x - width : at.x - width / 2;
  const box = { x0, x1: x0 + width, y0: firstBaseline - 12, y1: firstBaseline + (lines.length - 1) * LINE_H + 3 };
  return { lines, at, anchor, firstBaseline, box };
}

function BranchLabel({ p }: { p: Placed }) {
  const g = labelGeometry(p);
  return (
    <text x={g.at.x} y={g.firstBaseline} textAnchor={g.anchor} className="num">
      {g.lines.map((l, i) => (
        <tspan key={i} x={g.at.x} y={g.firstBaseline + i * LINE_H} fontSize={l.size} fontWeight={l.weight} fill={l.fill}>
          {i === 0 ? svgRich(l.text) : l.text}
        </tspan>
      ))}
    </text>
  );
}

/** Bounding box of everything drawn (labels estimated from character counts). */
function extents(lay: ReturnType<typeof layout>) {
  const xs: number[] = [];
  const ys: number[] = [];
  const addBox = (x0: number, x1: number, y0: number, y1: number) => {
    xs.push(x0, x1);
    ys.push(y0, y1);
  };
  for (const n of lay.nodes) {
    if (n.ground) continue;
    const w = Math.max(textWidth(n.label || n.id, 12, 700), textWidth(n.island ?? "", 10) * 1.1);
    addBox(n.p.x - w / 2, n.p.x + w / 2, n.p.y - 38, n.p.y + 4);
  }
  for (const r of lay.rails) addBox(Math.min(r.symbolX - 11, ...r.xs), Math.max(r.symbolX + 11, ...r.xs), r.y, r.y + 20);
  for (const p of lay.placed) {
    const b = labelGeometry(p).box;
    addBox(b.x0, b.x1, b.y0, b.y1);
    addBox(p.mid.x - SYMBOL_WIDTH, p.mid.x + SYMBOL_WIDTH, p.mid.y - SYMBOL_WIDTH / 2, p.mid.y + SYMBOL_WIDTH / 2);
  }
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

/** Lay out, then grow the padding until the estimated label extents fit inside the SVG. */
function fittedLayout(circuit: Circuit, W: number, H: number) {
  let pad = { ...BASE_PAD };
  let lay = layout(circuit, W, H, pad);
  for (let i = 0; i < 3; i++) {
    const e = extents(lay);
    const grow = {
      left: Math.max(0, EDGE - e.minX),
      right: Math.max(0, e.maxX - (W - EDGE)),
      top: Math.max(0, EDGE - e.minY),
      bottom: Math.max(0, e.maxY - (H - EDGE)),
    };
    if (grow.left + grow.right + grow.top + grow.bottom < 1) break;
    pad = { left: pad.left + grow.left, right: pad.right + grow.right, top: pad.top + grow.top, bottom: pad.bottom + grow.bottom };
    lay = layout(circuit, W, H, pad);
  }
  return lay;
}

function PlacedBranch({ p }: { p: Placed }) {
  const h = HALF_BODY[p.branch.type] ?? 10;
  const angle = (Math.atan2(p.dir.y, p.dir.x) * 180) / Math.PI;
  const s1 = add(p.mid, mul(p.dir, -h));
  const s2 = add(p.mid, mul(p.dir, h));
  const wire = { stroke: INK, strokeWidth: 1.25, fill: "none" } as const;
  return (
    <g>
      <polyline {...wire} points={`${p.a.x},${p.a.y} ${p.start.x},${p.start.y} ${s1.x},${s1.y}`} />
      <polyline {...wire} points={`${s2.x},${s2.y} ${p.end.x},${p.end.y} ${p.b.x},${p.b.y}`} />
      <g transform={`translate(${p.mid.x} ${p.mid.y}) rotate(${angle})`}>
        <SymbolBody type={p.branch.type} />
      </g>
      {(p.branch.type === "TL" || p.branch.type === "HANGER") && (
        <text
          x={p.mid.x - p.outward.x * (SYMBOL_WIDTH / 2 + 2)}
          y={p.mid.y - p.outward.y * (SYMBOL_WIDTH / 2 + 2)}
          dy="0.32em"
          textAnchor={p.outward.x > 0.5 ? "end" : p.outward.x < -0.5 ? "start" : "middle"}
          fontSize={11}
          fontStyle="italic"
          fill={INK}
        >
          {p.branch.type === "TL" ? "λ/4" : "κ"}
        </text>
      )}
      <BranchLabel p={p} />
    </g>
  );
}

function GroundRail({ rail }: { rail: Rail }) {
  const xs = [...rail.xs, rail.symbolX];
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const gx = rail.symbolX;
  const y = rail.y;
  return (
    <g stroke={INK} strokeWidth={1.25}>
      {x1 > x0 && <line x1={x0} x2={x1} y1={y} y2={y} />}
      {rail.xs
        .filter((x) => x > x0 + 0.5 && x < x1 - 0.5)
        .map((x, i) => (
          <rect key={i} x={x - 2.5} y={y - 2.5} width={5} height={5} fill={INK} stroke="none" />
        ))}
      <line x1={gx} x2={gx} y1={y} y2={y + 10} />
      <line x1={gx - 11} x2={gx + 11} y1={y + 10} y2={y + 10} strokeWidth={1.75} />
      <line x1={gx - 7} x2={gx + 7} y1={y + 14} y2={y + 14} strokeWidth={1.5} />
      <line x1={gx - 3} x2={gx + 3} y1={y + 18} y2={y + 18} strokeWidth={1.25} />
    </g>
  );
}

/** Lumped-element schematic drawn from `circuit.nodes[].pos` and `circuit.branches`. */
export function CircuitSchematic({ circuit }: { circuit: Circuit | null }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(720);
  if (!circuit || (circuit.nodes ?? []).length === 0) return <Empty>No circuit yet</Empty>;

  const W = Math.max(width, 420);
  const H = Math.round(clamp(W * 0.46, 300, 440));
  const { nodes, placed, rails } = fittedLayout(circuit, W, H);

  return (
    <div ref={ref} className="w-full min-w-0 overflow-hidden">
      <svg width={W} height={H} role="img" aria-label={`Lumped circuit ${circuit.name}`} className="block">
        {rails.map((r) => (
          <GroundRail key={r.node.id} rail={r} />
        ))}
        {placed.map((p) => (
          <PlacedBranch key={p.branch.id} p={p} />
        ))}
        {nodes
          .filter((n) => !n.ground)
          .map((n) => (
            <g key={n.id}>
              <rect x={n.p.x - 3.5} y={n.p.y - 3.5} width={7} height={7} fill={INK} />
              <text x={n.p.x} y={n.p.y - 26} textAnchor="middle" fontSize={12} fontWeight={700} fill={INK}>
                {n.label || n.id}
              </text>
              {n.island && (
                <text x={n.p.x} y={n.p.y - 12} textAnchor="middle" fontSize={10} fontFamily="JetBrains Mono, Consolas, monospace" fill={GREY}>
                  {n.island}
                </text>
              )}
            </g>
          ))}
      </svg>
    </div>
  );
}
