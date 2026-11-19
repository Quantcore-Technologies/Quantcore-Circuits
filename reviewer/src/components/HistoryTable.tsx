import type { Iteration } from "@contract/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty } from "@/components/Section";
import { fmt, fmtSigned, fmtTime, shortKey } from "@/lib/format";
import { cn } from "@/lib/utils";

const keysOf = (items: Record<string, number>[]) => {
  const keys: string[] = [];
  for (const it of items) for (const k of Object.keys(it ?? {})) if (!keys.includes(k)) keys.push(k);
  return keys;
};

/** Optimiser iterations: knobs and residuals ((value − target) / tol) as columns. */
export function HistoryTable({ history }: { history: Iteration[] }) {
  if (history.length === 0) return <Empty>No optimiser iterations yet</Empty>;
  const rows = [...history].sort((a, b) => a.iteration - b.iteration);
  const knobs = keysOf(rows.map((r) => r.knobs));
  const residuals = keysOf(rows.map((r) => r.residuals));

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent [&>th]:align-bottom">
          <TableHead rowSpan={2}>Iter</TableHead>
          <TableHead rowSpan={2}>Time</TableHead>
          <TableHead rowSpan={2} className="text-right normal-case tracking-normal">
            ‖r‖
          </TableHead>
          {knobs.length > 0 && (
            <TableHead colSpan={knobs.length} className="border-l border-rule pl-3 text-left">
              Knobs
            </TableHead>
          )}
          {residuals.length > 0 && (
            <TableHead colSpan={residuals.length} className="border-l border-rule pl-3 text-left">
              Residuals (Δ / tol)
            </TableHead>
          )}
          <TableHead rowSpan={2} className="text-right">
            Accepted
          </TableHead>
        </TableRow>
        <TableRow className="hover:bg-transparent">
          {knobs.map((k, i) => (
            <TableHead key={`k-${k}`} className={cn("text-right font-mono normal-case tracking-normal", i === 0 && "border-l border-rule")}>
              {k}
            </TableHead>
          ))}
          {residuals.map((k, i) => (
            <TableHead key={`r-${k}`} className={cn("text-right font-mono normal-case tracking-normal", i === 0 && "border-l border-rule")}>
              {shortKey(k)}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.iteration} className={cn(!r.accepted && "text-muted-foreground")}>
            <TableCell className="num font-bold">
              {r.iteration}
              {r.label && <span className="ml-1 font-mono text-2xs font-normal text-muted-foreground">{r.label}</span>}
            </TableCell>
            <TableCell className="num whitespace-nowrap text-xs">{fmtTime(r.time, true)}</TableCell>
            <TableCell className="num text-right font-semibold">{fmt(r.objective, 3)}</TableCell>
            {knobs.map((k, i) => (
              <TableCell key={k} className={cn("num text-right", i === 0 && "border-l border-rule")}>
                {fmt(r.knobs?.[k])}
              </TableCell>
            ))}
            {residuals.map((k, i) => {
              const v = r.residuals?.[k];
              const ok = typeof v === "number" && Number.isFinite(v);
              return (
                <TableCell key={k} className={cn("num text-right", i === 0 && "border-l border-rule", ok && (Math.abs(v) <= 1 ? "text-pass" : "text-signal"))}>
                  {fmtSigned(v)}
                </TableCell>
              );
            })}
            <TableCell className="text-right text-xs">{r.accepted ? "yes" : <span className="text-muted-foreground">rejected</span>}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
