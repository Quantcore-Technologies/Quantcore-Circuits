import type { FemCompareRow } from "@contract/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty } from "@/components/Section";
import { fmt, fmtSigned } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Layout estimate vs FEM (from the job's C-matrix) per circuit branch. */
export function FemCompareTable({ rows }: { rows: FemCompareRow[] }) {
  if (rows.length === 0) return <Empty>No FEM results used yet: the table fills when a solved job is read back</Empty>;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Branch</TableHead>
          <TableHead>Nodes</TableHead>
          <TableHead className="text-right">Estimate</TableHead>
          <TableHead className="text-right">FEM</TableHead>
          <TableHead className="text-right">Δ (%)</TableHead>
          <TableHead>Job</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.branch}>
            <TableCell className="font-mono text-xs font-medium">{r.branch}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{r.nodes.join(" – ")}</TableCell>
            <TableCell className="num text-right">
              {fmt(r.estimate)} <span className="text-2xs text-muted-foreground">{r.unit}</span>
            </TableCell>
            <TableCell className="num text-right">{fmt(r.fem)}</TableCell>
            <TableCell className={cn("num text-right", Math.abs(r.deltaPct) > 10 ? "text-signal" : "text-pass")}>{fmtSigned(r.deltaPct, 1)}</TableCell>
            <TableCell className="max-w-[12rem] truncate font-mono text-2xs text-muted-foreground" title={r.job}>{r.job ?? "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
