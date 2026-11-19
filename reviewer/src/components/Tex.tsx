import { useMemo } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { cn } from "@/lib/utils";

/** KaTeX render; falls back to the raw source (in red) if it does not parse. */
export function Tex({ tex, display = false, className }: { tex: string | null | undefined; display?: boolean; className?: string }) {
  const html = useMemo(() => {
    if (!tex) return null;
    try {
      return katex.renderToString(tex, { displayMode: display, throwOnError: true, output: "html", strict: "ignore" });
    } catch {
      return null;
    }
  }, [tex, display]);

  if (!tex) return <span className={className}>—</span>;
  if (html === null) return <code className={cn("font-mono text-xs text-signal", className)}>{tex}</code>;
  return <span className={cn(display && "tex-left block overflow-x-auto py-1", className)} dangerouslySetInnerHTML={{ __html: html }} />;
}
