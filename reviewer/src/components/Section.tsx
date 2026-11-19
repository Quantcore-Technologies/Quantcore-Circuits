import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Tab page: a 12-column grid. The tab row names the page, so there is no page title; `aside` is a one-line note. */
export function TabPage({ aside, children }: { aside?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-12 gap-x-8 gap-y-10">
      {aside && <p className="col-span-12 -mb-4 text-xs text-muted-foreground">{aside}</p>}
      {children}
    </div>
  );
}

/** Section with a black top rule and a small uppercase label. */
export function Section({ title, aside, className, children }: { title: string; aside?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section className={cn("col-span-12 min-w-0", className)}>
      <div className="mb-4 flex items-baseline justify-between gap-4 border-t border-ink pt-2">
        <h2 className="text-2xs font-semibold uppercase tracking-label">{title}</h2>
        {aside && <div className="text-2xs uppercase tracking-label text-muted-foreground">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export function Empty({ children = "No data yet", className }: { children?: ReactNode; className?: string }) {
  return <div className={cn("border-t border-dashed border-rule-strong py-6 text-xs text-muted-foreground", className)}>{children}</div>;
}

/** Key figure: small label above a large tabular numeral. */
export function Figure({ label, value, unit, className }: { label: string; value: ReactNode; unit?: string; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="label">{label}</div>
      <div className="num mt-1 text-xl font-bold leading-tight">
        {value}
        {unit && <span className="ml-1 text-xs font-normal text-muted-foreground">{unit}</span>}
      </div>
    </div>
  );
}
