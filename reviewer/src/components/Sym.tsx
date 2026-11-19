import { Tex } from "@/components/Tex";
import { symbolMarkup } from "@/lib/cards";
import { cn } from "@/lib/utils";

/** A physics symbol from the backend: KaTeX, or a plain identifier shown as monospace text. */
export function Sym({ symbol, className }: { symbol: string | null | undefined; className?: string }) {
  if (!symbol) return null;
  const m = symbolMarkup(symbol);
  if (m.kind === "text") return <span className={cn("font-mono text-[0.9em]", className)}>{m.value}</span>;
  return <Tex tex={m.value} className={className} />;
}
