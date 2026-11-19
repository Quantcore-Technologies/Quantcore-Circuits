import { useState } from "react";
import type { Screenshot, Step } from "@contract/state";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Empty } from "@/components/Section";
import { fmtTime, pad2, parseTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function newestShots(shots: Screenshot[]): Screenshot[] {
  return shots
    .map((s, i) => ({ s, i, t: parseTime(s.created)?.getTime() ?? -Infinity }))
    .sort((a, b) => b.t - a.t || b.i - a.i)
    .map((x) => x.s);
}

function stepLabel(id: string | undefined, steps: Step[]) {
  if (!id) return null;
  const s = steps.find((x) => x.id === id);
  return s ? `${pad2(s.index)} ${s.title}` : id;
}

export function ShotImage({ shot, className }: { shot: Screenshot; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!shot.url || failed === shot.url)
    return <div className={cn("flex items-center justify-center bg-paper text-xs text-muted-foreground", className)}>Image not available</div>;
  return <img src={shot.url} alt={shot.title} loading="lazy" onError={() => setFailed(shot.url)} className={cn("bg-paper object-contain", className)} />;
}

function ShotMeta({ shot, steps }: { shot: Screenshot; steps: Step[] }) {
  const step = stepLabel(shot.step, steps);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs uppercase tracking-label text-muted-foreground">
      {step && <span className="num">{step}</span>}
      <Badge variant={shot.source === "gui" ? "default" : "outline"}>{shot.source === "gui" ? "GUI" : "Headless"}</Badge>
      <span className="num normal-case tracking-normal">{fmtTime(shot.created, true)}</span>
    </div>
  );
}

export function ScreenshotViewer({ shot, steps, onClose }: { shot: Screenshot | null; steps: Step[]; onClose: () => void }) {
  return (
    <Dialog open={shot !== null} onOpenChange={(o) => !o && onClose()}>
      {shot && (
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{shot.title}</DialogTitle>
            <DialogDescription>{shot.caption || "KLayout screenshot"}</DialogDescription>
          </DialogHeader>
          <ShotImage shot={shot} className="max-h-[72vh] w-full border border-rule" />
          <DialogFooter>
            <ShotMeta shot={shot} steps={steps} />
            <a href={shot.url} target="_blank" rel="noreferrer" className="ml-auto font-mono text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              {shot.url}
            </a>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  );
}

export function ScreenshotCard({ shot, steps, onOpen, className }: { shot: Screenshot; steps: Step[]; onOpen: (s: Screenshot) => void; className?: string }) {
  return (
    <Card className={cn("group flex min-w-0 flex-col", className)}>
      <button type="button" onClick={() => onOpen(shot)} className="block border-b border-rule focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" aria-label={`Open ${shot.title}`}>
        <ShotImage shot={shot} className="aspect-[4/3] w-full transition-opacity group-hover:opacity-90" />
      </button>
      <div className="flex flex-1 flex-col gap-1.5 px-4 py-3">
        <div className="text-sm font-semibold leading-tight">{shot.title}</div>
        {shot.caption && <div className="text-xs text-muted-foreground">{shot.caption}</div>}
        <div className="mt-auto pt-1">
          <ShotMeta shot={shot} steps={steps} />
        </div>
      </div>
    </Card>
  );
}

export function ScreenshotGallery({ shots, steps }: { shots: Screenshot[]; steps: Step[] }) {
  const [open, setOpen] = useState<Screenshot | null>(null);
  if (shots.length === 0) return <Empty>No screenshots yet — they appear after the layout step (KLayout GUI or headless render).</Empty>;
  return (
    <>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {newestShots(shots).map((s) => (
          <ScreenshotCard key={s.id} shot={s} steps={steps} onOpen={setOpen} />
        ))}
      </div>
      <ScreenshotViewer shot={open} steps={steps} onClose={() => setOpen(null)} />
    </>
  );
}
