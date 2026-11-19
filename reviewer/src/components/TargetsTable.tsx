import type { Target } from "@contract/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DeviationBar } from "@/components/DeviationBar";
import { Empty } from "@/components/Section";
import { TargetStatusBadge } from "@/components/StatusBadge";
import { SymbolText } from "@/components/SymbolText";
import { fmt, fmtSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

export const deviation = (t: Target): number | null =>
  t.value !== null && Number.isFinite(t.value) && Number.isFinite(t.target) && Number.isFinite(t.tol) && t.tol > 0 ? (t.value - t.target) / t.tol : null;

export function TargetsTable({ targets }: { targets: Target[] }) {
  if (targets.length === 0) return <Empty>No targets defined yet</Empty>;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Target</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead className="text-right">Goal ± tol</TableHead>
          <TableHead className="text-right">Current</TableHead>
          <TableHead className="text-right">Δ / tol</TableHead>
          <TableHead>
            <span className="num">−3 … +3</span>
          </TableHead>
          <TableHead>Source</TableHead>
          <TableHead className="text-right">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {targets.map((t) => {
          const dev = deviation(t);
          return (
            <TableRow key={t.key}>
              <TableCell>
                <div className="font-semibold">{t.label}</div>
                <div className="font-mono text-2xs text-muted-foreground">{t.key}</div>
              </TableCell>
              <TableCell className="text-sm">
                <SymbolText value={t.symbol} />
              </TableCell>
              <TableCell className="num whitespace-nowrap text-right">
                {fmt(t.target)} <span className="text-muted-foreground">± {fmt(t.tol)}</span> <span className="text-xs text-muted-foreground">{t.unit}</span>
              </TableCell>
              <TableCell className={cn("num whitespace-nowrap text-right text-base font-bold", t.status === "fail" && "text-signal")}>
                {fmt(t.value)} {t.value !== null && <span className="text-xs font-normal text-muted-foreground">{t.unit}</span>}
              </TableCell>
              <TableCell className={cn("num whitespace-nowrap text-right", t.status === "fail" && "text-signal")}>{fmtSigned(dev)}</TableCell>
              <TableCell>
                <DeviationBar dev={dev} status={t.status} />
              </TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">{t.source ?? "—"}</TableCell>
              <TableCell className="text-right">
                <TargetStatusBadge status={t.status} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
