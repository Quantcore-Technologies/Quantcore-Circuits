import type { Job, JobProgress } from "@contract/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty } from "@/components/Section";
import { JobStatusBadge } from "@/components/StatusBadge";
import { fmt, fmtTime } from "@/lib/format";

const running = (s: string) => ["solving", "rendering", "running"].includes((s || "").toLowerCase());

function duration(s?: number): string {
  if (s == null || !Number.isFinite(s)) return "";
  if (s < 90) return `${s.toFixed(0)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

/** Solve progress: adaptive pass n of max, the last convergence delta against its target, mesh size, elapsed time. */
export function JobProgressCell({ job }: { job: Job }) {
  const p: JobProgress | null | undefined = job.progress;
  if (!p) return <span className="text-muted-foreground">—</span>;
  const last = p.delta?.length ? p.delta[p.delta.length - 1] : null;
  const frac = p.pass != null && p.maxPasses ? Math.min(1, p.pass / p.maxPasses) : job.hasResults ? 1 : 0;
  const live = running(job.status) && !p.stale;
  return (
    <div className="min-w-[11rem] space-y-1 text-xs">
      {(p.pass != null || live) && (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full ${p.converged || job.hasResults ? "bg-pass" : "bg-primary"} ${live ? "animate-pulse" : ""}`}
              style={{ width: `${Math.round(frac * 100)}%` }}
            />
          </div>
          <span className="num whitespace-nowrap">{p.pass != null ? `pass ${p.pass}${p.maxPasses ? ` / ${p.maxPasses}` : ""}` : "starting"}</span>
        </div>
      )}
      {last != null && (
        <div className="num text-muted-foreground">
          Δ {fmt(last, 3)}
          {p.target != null && ` / ${fmt(p.target, 3)}`}
          {p.converged != null && <span className={p.converged ? "text-pass" : "text-signal"}> {p.converged ? "converged" : "not converged"}</span>}
          {p.elements?.length ? ` · ${p.elements[p.elements.length - 1].toLocaleString()} tets` : ""}
        </div>
      )}
      {p.stale && <div className="text-signal">solver process is gone (interrupted)</div>}
      {p.elapsedS != null && <div className="num text-muted-foreground">{duration(p.elapsedS)}</div>}
      {live && (p.stage || p.logTail) && <div className="max-w-[18rem] truncate font-mono text-2xs text-muted-foreground">{p.stage || p.logTail}</div>}
    </div>
  );
}

export function JobsTable({ jobs }: { jobs: Job[] }) {
  if (jobs.length === 0) return <Empty>No simulation jobs yet</Empty>;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Job</TableHead>
          <TableHead>Group</TableHead>
          <TableHead>Analysis</TableHead>
          <TableHead>Solver</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Progress</TableHead>
          <TableHead className="text-right">Created</TableHead>
          <TableHead className="text-right">Finished</TableHead>
          <TableHead>Results</TableHead>
          <TableHead>Project</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((j) => (
          <TableRow key={j.name}>
            <TableCell className="max-w-[18rem] break-all font-mono text-xs font-medium">{j.name}</TableCell>
            <TableCell className="font-semibold">{j.group}</TableCell>
            <TableCell className="font-mono text-xs">{j.analysis}</TableCell>
            <TableCell className="text-xs">{j.solver}</TableCell>
            <TableCell>
              <JobStatusBadge status={j.status} />
            </TableCell>
            <TableCell>
              <JobProgressCell job={j} />
            </TableCell>
            <TableCell className="num whitespace-nowrap text-right text-xs">{fmtTime(j.created)}</TableCell>
            <TableCell className="num whitespace-nowrap text-right text-xs">{fmtTime(j.finished)}</TableCell>
            <TableCell className="text-xs">
              {j.hasResults ? <span className="font-semibold text-pass">{j.source === "kept" ? "yes (kept)" : "yes"}</span> : <span className="text-muted-foreground">no</span>}
            </TableCell>
            <TableCell className="max-w-[22rem] break-all font-mono text-2xs text-muted-foreground">{j.project || "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
