import { useMemo, useState, type ReactNode } from "react";
import type { ChipElement, ElementKind, ElementLink, ElementParam } from "@contract/state";
import { Sym } from "@/components/Sym";
import { STATUS_COLOUR } from "@/lib/cards";
import { KIND_LABEL, naturalCompare, roleLabel } from "@/lib/elements";
import { fmtNum, fmtSigned } from "@/lib/format";
import { GREY, PASS, SIGNAL } from "@/lib/palette";
import { cn } from "@/lib/utils";

interface Column {
  key: string;
  label: string;
  symbol: string;
  unit: string;
  of: boolean; // values of a linked element (a qubit row's readout)
}

interface LinkColumn {
  role: ElementLink["role"] | "*"; // "*": all links in one column (ports)
  header: string;
}

const dev = (p: ElementParam | undefined): number | null =>
  p && p.value !== null && p.target && Number.isFinite(p.target.tol) && p.target.tol > 0 ? (p.value - p.target.value) / p.target.tol : null;

function columnsFor(rows: ChipElement[]): Column[] {
  const out = new Map<string, Column>();
  for (const e of rows)
    for (const p of e.params) {
      const c = out.get(p.key);
      if (!c) out.set(p.key, { key: p.key, label: p.label, symbol: p.symbol, unit: p.unit, of: Boolean(p.of) });
      else if (p.of) c.of = true;
    }
  // drop columns with no value anywhere (e.g. κ before any hanger exists)
  return [...out.values()].filter((c) => rows.some((e) => e.params.some((p) => p.key === c.key && p.value !== null)));
}

function linkColumnsFor(kind: ElementKind, rows: ChipElement[]): LinkColumn[] {
  if (kind === "port") return rows.some((e) => e.links.length) ? [{ role: "*", header: "Connects" }] : [];
  const roles: ElementLink["role"][] = [];
  for (const e of rows) for (const l of e.links) if (!roles.includes(l.role)) roles.push(l.role);
  return roles.map((role) => ({ role, header: roleLabel(kind, role) }));
}

function targetsMet(e: ChipElement): { met: number; total: number } {
  const t = e.params.filter((p) => p.target);
  return { met: t.filter((p) => p.status === "pass").length, total: t.length };
}

type Sort = { key: string; dir: 1 | -1 } | null;

function sortRows(rows: ChipElement[], sort: Sort): ChipElement[] {
  const list = [...rows];
  if (!sort) return list.sort((a, b) => naturalCompare(a.id, b.id));
  const val = (e: ChipElement): number | string | null => {
    if (sort.key === "__id") return e.id;
    if (sort.key === "__targets") {
      const t = targetsMet(e);
      return t.total ? t.met / t.total : null;
    }
    if (sort.key.startsWith("__link:")) {
      const role = sort.key.slice(7);
      return e.links.find((l) => role === "*" || l.role === role)?.to ?? null;
    }
    return e.params.find((p) => p.key === sort.key)?.value ?? null;
  };
  return list.sort((a, b) => {
    const va = val(a);
    const vb = val(b);
    if (va === null && vb === null) return naturalCompare(a.id, b.id);
    if (va === null) return 1; // missing values last, whatever the direction
    if (vb === null) return -1;
    const d = typeof va === "number" && typeof vb === "number" ? va - vb : naturalCompare(String(va), String(vb));
    return d * sort.dir || naturalCompare(a.id, b.id);
  });
}

function SortHead({ id, sort, onSort, className, title, children }: { id: string; sort: Sort; onSort: (k: string) => void; className?: string; title?: string; children: ReactNode }) {
  const active = sort?.key === id;
  return (
    <th scope="col" className={cn("sticky top-0 z-10 whitespace-nowrap border-b border-ink bg-background px-2 pb-1.5 pt-2 align-bottom font-normal first:pl-3", className)} aria-sort={active ? (sort!.dir > 0 ? "ascending" : "descending") : undefined}>
      <button type="button" onClick={() => onSort(id)} title={title} className={cn("inline-flex items-end gap-1 text-left hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring", active ? "text-foreground" : "text-muted-foreground")}>
        {children}
        <span className={cn("text-[9px] leading-[14px]", !active && "opacity-0")} aria-hidden>
          {active && sort!.dir < 0 ? "▼" : "▲"}
        </span>
      </button>
    </th>
  );
}

function ValueCell({ p, divider, onOpenCard }: { p: ElementParam | undefined; divider: boolean; onOpenCard: (cardId: string) => void }) {
  const cls = cn("px-2 py-1.5 text-right align-top", divider && "border-l border-rule");
  if (!p || p.value === null) return <td className={cn(cls, "text-rule-strong")}>—</td>;
  const d = dev(p);
  const colour = p.status ? STATUS_COLOUR[p.status] : null;
  const title = [
    `${p.label}${p.of ? ` (${p.of})` : ""}: ${fmtNum(p.value, 6)}${p.unit ? ` ${p.unit}` : ""}`,
    p.target && `goal ${fmtNum(p.target.value)} ± ${fmtNum(p.target.tol)}${p.unit ? ` ${p.unit}` : ""}`,
    d !== null && `Δ ${fmtSigned(d, 2)} tol`,
    p.source && `source ${p.source}`,
    p.card && "click for the card",
  ]
    .filter(Boolean)
    .join("\n");
  const body = (
    <>
      <span className="num block font-semibold leading-[18px]" style={colour ? { color: colour } : undefined}>
        {fmtNum(p.value, 4, true)}
      </span>
      {d !== null && (
        <span className="num block text-2xs leading-3" style={{ color: Math.abs(d) <= 1 ? PASS : SIGNAL }}>
          Δ {fmtSigned(d, Math.abs(d) >= 10 ? 0 : 1)}
        </span>
      )}
    </>
  );
  return (
    <td className={cls} title={title}>
      {p.card ? (
        <button type="button" onClick={() => onOpenCard(p.card!)} className="ml-auto block text-right underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
          {body}
        </button>
      ) : (
        body
      )}
    </td>
  );
}

function LinkChips({ links, detail, onSelect }: { links: ElementLink[]; detail?: boolean; onSelect: (id: string) => void }) {
  if (links.length === 0) return <span className="text-rule-strong">—</span>;
  return (
    <span className="flex flex-wrap gap-x-1.5 gap-y-0.5">
      {links.map((l) => (
        <button key={`${l.role}-${l.to}`} type="button" onClick={() => onSelect(l.to)} title={l.label ? `${l.to} (${l.label})` : l.to} className="font-mono text-[11px] leading-[18px] hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
          {l.to}
          {detail && <span className="ml-1 font-sans text-2xs text-muted-foreground">{[l.role, l.label !== l.to ? l.label : null].filter(Boolean).join(" · ")}</span>}
        </button>
      ))}
    </span>
  );
}

function KindTable({
  kind,
  rows,
  selected,
  flash,
  onSelect,
  onOpenCard,
}: {
  kind: ElementKind;
  rows: ChipElement[];
  selected: string | null;
  flash: string | null;
  onSelect: (id: string) => void;
  onOpenCard: (cardId: string) => void;
}) {
  const [sort, setSort] = useState<Sort>(null);
  const cols = useMemo(() => columnsFor(rows), [rows]);
  const links = useMemo(() => linkColumnsFor(kind, rows), [kind, rows]);
  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort]);
  const anyTargets = rows.some((e) => targetsMet(e).total > 0);
  const own = cols.filter((c) => !c.of);
  const of = cols.filter((c) => c.of);
  const grouped = of.length > 0 && cols.every((c, i) => (i < own.length ? !c.of : c.of)); // own columns, then linked ones
  const onSort = (k: string) => setSort((s) => (s?.key === k ? (s.dir > 0 ? { key: k, dir: -1 } : null) : { key: k, dir: 1 }));
  const scroll = rows.length > 12;
  const failing = rows.filter((e) => e.status === "fail").length;
  // the same subtitle on every row ("Xmon · Trilayer Squid") says nothing per row: keep it in the tooltip only
  const subtitles = rows.length > 1 && new Set(rows.map((e) => e.subtitle ?? "")).size === 1 ? false : true;

  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-3 pb-1.5">
        <h3 className="text-2xs font-semibold uppercase tracking-label">
          {KIND_LABEL[kind].many} <span className="num ml-1 font-normal text-muted-foreground">{rows.length}</span>
          {!subtitles && rows[0]?.subtitle && <span className="ml-3 font-normal normal-case tracking-normal text-muted-foreground">all {rows[0].subtitle}</span>}
        </h3>
        {failing > 0 && (
          <span className="text-2xs uppercase tracking-label text-signal">
            <span className="num">{failing}</span> outside tolerance
          </span>
        )}
      </div>
      <div className={cn("overflow-x-auto border-t border-ink", scroll && "max-h-[min(62vh,620px)] overflow-y-auto overscroll-contain")}>
        <table className="w-full border-collapse text-[13px]">
          <thead>
            {grouped && (
              <tr>
                <th colSpan={1 + links.length} className="bg-background" />
                <th colSpan={own.length} className="whitespace-nowrap bg-background px-2 pt-1.5 text-left text-2xs font-normal uppercase tracking-label text-muted-foreground">
                  {KIND_LABEL[kind].one}
                </th>
                <th colSpan={of.length} className="whitespace-nowrap border-l border-rule bg-background px-2 pt-1.5 text-left text-2xs font-normal uppercase tracking-label text-muted-foreground">
                  {kind === "qubit" ? "Readout and coupling" : "Linked"}
                </th>
                {anyTargets && <th className="bg-background" />}
              </tr>
            )}
            <tr>
              <SortHead id="__id" sort={sort} onSort={onSort} className="text-left">
                <span className="text-2xs font-semibold uppercase tracking-label">{KIND_LABEL[kind].one}</span>
              </SortHead>
              {links.map((l) => (
                <SortHead key={l.role} id={`__link:${l.role}`} sort={sort} onSort={onSort} className="text-left">
                  <span className="text-2xs font-semibold uppercase tracking-label">{l.header}</span>
                </SortHead>
              ))}
              {cols.map((c, i) => (
                <SortHead key={c.key} id={c.key} sort={sort} onSort={onSort} title={c.label} className={cn("text-right", grouped && i === own.length && "border-l border-rule")}>
                  <span className="flex flex-col items-end leading-4">
                    <span className="text-[13px] text-foreground">
                      <Sym symbol={c.symbol} />
                    </span>
                    <span className="text-2xs">{c.unit || " "}</span>
                  </span>
                </SortHead>
              ))}
              {anyTargets && (
                <SortHead id="__targets" sort={sort} onSort={onSort} className="text-right" title="targets within tolerance">
                  <span className="text-2xs font-semibold uppercase tracking-label">Targets</span>
                </SortHead>
              )}
            </tr>
          </thead>
          <tbody>
            {sorted.map((e) => {
              const t = targetsMet(e);
              const colour = e.status ? STATUS_COLOUR[e.status] : null;
              const isSel = e.id === selected;
              return (
                <tr key={e.id} id={`pel-row-${e.id}`} className={cn("border-b border-rule outline outline-2 -outline-offset-2 transition-[background-color,outline-color] duration-500 hover:bg-paper", isSel && "bg-paper", flash === `pel-row-${e.id}` ? "outline-ink" : "outline-transparent")}>
                  <th scope="row" className="relative whitespace-nowrap py-1.5 pl-3 pr-2 text-left align-top font-normal">
                    <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: colour ?? "transparent" }} aria-hidden />
                    <button type="button" onClick={() => onSelect(e.id)} title={e.subtitle ? `${e.label} · ${e.subtitle}` : e.label} className="text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" aria-current={isSel ? "true" : undefined}>
                      <span className={cn("block font-semibold leading-[18px] hover:underline", isSel && "underline underline-offset-2")}>{e.label}</span>
                      {subtitles && e.subtitle && <span className="block max-w-[14rem] truncate text-2xs leading-3 text-muted-foreground">{e.subtitle}</span>}
                    </button>
                  </th>
                  {links.map((l) => (
                    <td key={l.role} className="px-2 py-1.5 align-top">
                      <LinkChips links={e.links.filter((x) => l.role === "*" || x.role === l.role)} detail={l.role === "*"} onSelect={onSelect} />
                    </td>
                  ))}
                  {cols.map((c, i) => (
                    <ValueCell key={c.key} p={e.params.find((p) => p.key === c.key)} divider={grouped && i === own.length} onOpenCard={onOpenCard} />
                  ))}
                  {anyTargets && (
                    <td className="num whitespace-nowrap px-2 py-1.5 text-right align-top font-semibold" style={{ color: t.total ? (t.met === t.total ? PASS : SIGNAL) : GREY }}>
                      {t.total ? `${t.met}/${t.total}` : "—"}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export interface OverviewFilter {
  query: string;
  failingOnly: boolean;
}

export function matchesFilter(e: ChipElement, f: OverviewFilter): boolean {
  if (f.failingOnly && e.status !== "fail") return false;
  const q = f.query.trim().toLowerCase();
  if (!q) return true;
  const hay = [e.id, e.label, e.subtitle ?? "", ...e.links.map((l) => l.to), ...e.links.map((l) => l.label ?? "")].join(" ").toLowerCase();
  return q.split(/[\s,]+/).some((tok) => tok && hay.includes(tok));
}

/** Element tables by kind (qubits full width; resonators, buses, couplers beside feedlines and ports). */
export function ChipTables({
  elements,
  filter,
  selected,
  flash,
  onSelect,
  onOpenCard,
}: {
  elements: ChipElement[];
  filter: OverviewFilter;
  selected: string | null;
  flash: string | null;
  onSelect: (id: string) => void;
  onOpenCard: (cardId: string) => void;
}) {
  const byKind = useMemo(() => {
    const m = new Map<ElementKind, ChipElement[]>();
    for (const e of elements) if (matchesFilter(e, filter)) m.set(e.kind, [...(m.get(e.kind) ?? []), e]);
    return m;
  }, [elements, filter]);
  const table = (k: ElementKind) => {
    const rows = byKind.get(k);
    return rows && rows.length ? <KindTable key={k} kind={k} rows={rows} selected={selected} flash={flash} onSelect={onSelect} onOpenCard={onOpenCard} /> : null;
  };
  const left = (["resonator", "bus", "coupler"] as ElementKind[]).map(table).filter(Boolean);
  const right = (["feedline", "port"] as ElementKind[]).map(table).filter(Boolean);
  if (byKind.size === 0) return <div className="border-t border-dashed border-rule-strong py-6 text-xs text-muted-foreground">No element matches the filter.</div>;
  return (
    <div className="flex flex-col gap-8">
      {table("qubit")}
      {(left.length > 0 || right.length > 0) && (
        <div className={cn("grid gap-x-10 gap-y-8", left.length && right.length && "min-[1180px]:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]")}>
          {left.length > 0 && <div className="flex min-w-0 flex-col gap-8">{left}</div>}
          {right.length > 0 && <div className="flex min-w-0 flex-col gap-8">{right}</div>}
        </div>
      )}
    </div>
  );
}
