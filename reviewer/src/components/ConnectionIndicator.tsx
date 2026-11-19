import type { ConnectionMode } from "@/hooks/useLiveState";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fmtClock } from "@/lib/format";
import { GREY, INK, PASS, SIGNAL } from "@/lib/palette";

interface Props {
  mode: ConnectionMode;
  updated: string;
  fetchedAt: Date | null;
  forcedSample: boolean;
  error: string | null;
}

export function ConnectionIndicator({ mode, updated, fetchedAt, forcedSample, error }: Props) {
  const label = mode === "connecting" ? "Connecting" : mode;
  // Explicit ?sample is not a failure: keep it grey rather than red.
  const colour = mode === "live" ? PASS : mode === "polling" ? INK : mode === "offline" && !forcedSample ? SIGNAL : GREY;
  const hollow = mode === "polling" || mode === "connecting";
  const detail =
    mode === "live"
      ? "Subscribed to /api/events (server-sent events)."
      : mode === "polling"
        ? "Event stream unavailable; polling /api/state every 3 s."
        : forcedSample
          ? "Showing the sample fixture (?sample); the backend is not contacted."
          : mode === "offline"
            ? "Backend unreachable; retrying /api/state every 3 s."
            : "Contacting the backend…";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex cursor-default items-center gap-2 whitespace-nowrap" aria-live="polite">
          <span
            className="inline-block h-2 w-2"
            style={{ background: hollow ? "transparent" : colour, border: `1.5px solid ${colour}` }}
            aria-hidden
          />
          <span className="text-2xs font-semibold uppercase tracking-label" style={{ color: mode === "live" ? PASS : undefined }}>
            {label}
          </span>
          <span className="num text-xs text-muted-foreground">updated {fmtClock(updated || fetchedAt)}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end">
        <div>{detail}</div>
        {fetchedAt && <div className="mt-1 text-white/70">last fetch {fmtClock(fetchedAt)}</div>}
        {error && !forcedSample && <div className="mt-1 text-white/70">{error}</div>}
      </TooltipContent>
    </Tooltip>
  );
}
