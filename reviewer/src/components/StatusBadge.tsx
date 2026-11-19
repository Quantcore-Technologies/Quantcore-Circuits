import type { StepStatus, Target } from "@contract/state";
import { Badge, type BadgeProps } from "@/components/ui/badge";

type Variant = BadgeProps["variant"];

export function TargetStatusBadge({ status }: { status: Target["status"] }) {
  const v: Record<Target["status"], Variant> = { pass: "pass", fail: "destructive", unknown: "muted" };
  return <Badge variant={v[status] ?? "muted"}>{status ?? "unknown"}</Badge>;
}

export function StepStatusBadge({ status, current }: { status: StepStatus; current?: boolean }) {
  if (current) return <Badge variant="destructive">{status}</Badge>;
  const v: Record<StepStatus, Variant> = { done: "default", running: "outline", failed: "signal", pending: "muted", skipped: "muted" };
  return <Badge variant={v[status] ?? "muted"}>{status}</Badge>;
}

/** Job status is free text in the contract; map the common ones, everything else stays neutral. */
export function JobStatusBadge({ status }: { status: string }) {
  const s = (status || "unknown").toLowerCase();
  let v: Variant = "outline";
  if (s === "done" || s === "finished" || s === "completed") v = "pass";
  else if (s === "failed" || s === "error" || s === "interrupted" || s === "render_failed") v = "destructive";
  else if (s === "running" || s === "solving") v = "default";
  else if (s === "unknown") v = "muted";
  return <Badge variant={v}>{status || "unknown"}</Badge>;
}
