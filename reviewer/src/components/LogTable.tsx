import type { LogEntry } from "@contract/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty } from "@/components/Section";
import { fmtTime, parseTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const LEVEL_CLASS: Record<string, string> = {
  info: "text-muted-foreground",
  warn: "text-warn",
  error: "text-signal",
};

/** Newest first; entries without a parseable time keep their relative order. */
export function newestFirst(log: LogEntry[]): LogEntry[] {
  return log
    .map((e, i) => ({ e, i, t: parseTime(e.t)?.getTime() ?? -Infinity }))
    .sort((a, b) => b.t - a.t || b.i - a.i)
    .map((x) => x.e);
}

export function LogTable({ log, limit, compact = false }: { log: LogEntry[]; limit?: number; compact?: boolean }) {
  if (log.length === 0) return <Empty>No log entries yet</Empty>;
  const entries = newestFirst(log).slice(0, limit ?? log.length);
  return (
    <Table>
      {!compact && (
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-28">Time</TableHead>
            <TableHead className="w-16">Level</TableHead>
            <TableHead>Message</TableHead>
          </TableRow>
        </TableHeader>
      )}
      <TableBody>
        {entries.map((e, i) => (
          <TableRow key={`${e.t}-${i}`} className="align-top">
            <TableCell className={cn("num whitespace-nowrap align-top text-xs text-muted-foreground", compact && "w-24")}>{fmtTime(e.t, true)}</TableCell>
            <TableCell className={cn("align-top text-2xs font-bold uppercase tracking-label", LEVEL_CLASS[e.level] ?? "text-muted-foreground", compact && "w-12")}>
              {e.level}
            </TableCell>
            <TableCell className={cn("align-top font-mono text-xs", e.level === "error" && "text-signal")}>{e.msg}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
