import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fmtClock } from "@/lib/format";

type Result = { kind: "idle" } | { kind: "busy" } | { kind: "ok"; at: Date } | { kind: "error"; message: string };

export function RebuildButton({ disabled, onDone }: { disabled: boolean; onDone: () => void }) {
  const [result, setResult] = useState<Result>({ kind: "idle" });

  const rebuild = async () => {
    setResult({ kind: "busy" });
    try {
      const r = await fetch("api/rebuild", { method: "POST", headers: { Accept: "application/json" } });
      const body = (await r.json().catch(() => ({}))) as { ok?: boolean; error?: string };
      if (r.ok && body.ok) setResult({ kind: "ok", at: new Date() });
      else setResult({ kind: "error", message: body.error ?? `HTTP ${r.status}` });
    } catch (e) {
      setResult({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
    onDone();
  };

  const button = (
    <Button variant="outline" size="sm" disabled={disabled || result.kind === "busy"} onClick={rebuild}>
      {result.kind === "busy" ? "Rebuilding…" : "Rebuild layout"}
    </Button>
  );

  return (
    <div className="flex items-center gap-2">
      {disabled ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span tabIndex={0}>{button}</span>
          </TooltipTrigger>
          <TooltipContent side="bottom" align="end">
            Not available on sample data
          </TooltipContent>
        </Tooltip>
      ) : (
        button
      )}
      {result.kind === "ok" && <span className="num text-xs text-pass">rebuilt {fmtClock(result.at)}</span>}
      {result.kind === "error" && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="max-w-[16rem] cursor-default truncate text-xs text-signal">failed: {result.message}</span>
          </TooltipTrigger>
          <TooltipContent side="bottom" align="end">
            {result.message}
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}
