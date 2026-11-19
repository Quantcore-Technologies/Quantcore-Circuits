import type { CircuitBranch } from "@contract/state";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty } from "@/components/Section";
import { SymbolText } from "@/components/SymbolText";
import { fmt, fmtPct } from "@/lib/format";

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

const deltaRel = (b: CircuitBranch) => (finite(b.value) && finite(b.designValue) && b.designValue !== 0 ? (b.value - b.designValue) / Math.abs(b.designValue) : null);

const TYPE_LABEL: Partial<Record<CircuitBranch["type"], string>> = { HANGER: "Hanger" };

export function BranchesTable({ branches }: { branches: CircuitBranch[] }) {
  if (branches.length === 0) return <Empty>No branches</Empty>;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Branch</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Nodes</TableHead>
          <TableHead className="text-right" title="FEM value when the branch was extracted from a simulation, else the layout estimate">Value</TableHead>
          <TableHead className="text-right">Design</TableHead>
          <TableHead className="text-right">Δ</TableHead>
          <TableHead>Source</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {branches.map((b, i) => {
          const d = deltaRel(b);
          return (
            <TableRow key={b.id ?? i}>
              <TableCell>
                <div className="font-semibold">
                  <SymbolText value={b.label} />
                </div>
                <div className="font-mono text-2xs text-muted-foreground">{b.id ?? "—"}</div>
              </TableCell>
              <TableCell>
                {b.type ? <Badge variant="outline">{TYPE_LABEL[b.type] ?? b.type}</Badge> : <span className="text-muted-foreground">—</span>}
              </TableCell>
              <TableCell className="whitespace-nowrap font-mono text-xs">{Array.isArray(b.nodes) && b.nodes.length ? b.nodes.join(" – ") : "—"}</TableCell>
              <TableCell className="num whitespace-nowrap text-right font-semibold">
                {fmt(b.value)} {finite(b.value) && b.unit && <span className="text-xs font-normal text-muted-foreground">{b.unit}</span>}
              </TableCell>
              <TableCell className="num whitespace-nowrap text-right text-muted-foreground">{fmt(finite(b.designValue) ? b.designValue : null)}</TableCell>
              <TableCell className="num whitespace-nowrap text-right">{d === null ? "—" : `${d > 0 ? "+" : ""}${fmtPct(d)}`}</TableCell>
              <TableCell className="max-w-[10rem] truncate font-mono text-2xs text-muted-foreground" title={b.source}>
                {b.source ?? "—"}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
