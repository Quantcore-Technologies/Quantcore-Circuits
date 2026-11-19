import type { Estimate } from "@contract/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty } from "@/components/Section";
import { SymbolText } from "@/components/SymbolText";
import { fmt, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** One row per parameter, one column per estimator; the chosen estimate is bold, flagged spreads are red. */
export function ConsensusTable({ estimates }: { estimates: Estimate[] }) {
  if (estimates.length === 0) return <Empty>No estimator results yet</Empty>;
  const estimators: string[] = [];
  for (const e of estimates) for (const k of Object.keys(e.values ?? {})) if (!estimators.includes(k)) estimators.push(k);

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Parameter</TableHead>
          <TableHead className="text-right">Target</TableHead>
          {estimators.map((k) => (
            <TableHead key={k} className="text-right font-mono normal-case tracking-normal">
              {k}
            </TableHead>
          ))}
          <TableHead>Chosen by</TableHead>
          <TableHead className="text-right">Spread</TableHead>
          <TableHead className="w-12" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {estimates.map((e) => {
          const chosenIn = e.chosenBy in (e.values ?? {});
          return (
            <TableRow key={e.param}>
              <TableCell>
                <div className="font-semibold">
                  <SymbolText value={e.label} /> <span className="text-xs font-normal text-muted-foreground">{e.unit}</span>
                </div>
                <div className="font-mono text-2xs text-muted-foreground">{e.param}</div>
              </TableCell>
              <TableCell className="num text-right text-muted-foreground">{fmt(e.target)}</TableCell>
              {estimators.map((k) => {
                const v = e.values?.[k];
                const chosen = k === e.chosenBy;
                return (
                  <TableCell key={k} className={cn("num text-right", chosen ? "font-bold" : "text-muted-foreground")}>
                    {v === undefined ? "" : fmt(v)}
                  </TableCell>
                );
              })}
              <TableCell className="font-mono text-xs">
                {e.chosenBy || "—"}
                {!chosenIn && e.chosen !== null && <span className="num ml-1 font-sans font-bold">= {fmt(e.chosen)}</span>}
              </TableCell>
              <TableCell className={cn("num whitespace-nowrap text-right", e.flagged && "font-semibold text-signal")}>{fmtPct(e.spreadRel)}</TableCell>
              <TableCell className="text-right">
                {e.flagged && (
                  <span className="inline-flex items-center gap-1 text-2xs font-bold uppercase tracking-label text-signal" title="Estimator spread above tolerance — a modelling problem, not a design problem">
                    <span className="inline-block h-2 w-2 bg-signal" aria-hidden />
                    Flag
                  </span>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
