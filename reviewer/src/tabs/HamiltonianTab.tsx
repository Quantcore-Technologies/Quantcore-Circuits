import type { Hamiltonian, State } from "@contract/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConsensusTable } from "@/components/ConsensusTable";
import { PlotCard } from "@/components/PlotCard";
import { Empty, Section, TabPage } from "@/components/Section";
import { Tex } from "@/components/Tex";
import { fmt } from "@/lib/format";
import { plotsFor } from "@/lib/state";

function TermsTable({ h }: { h: Hamiltonian }) {
  const terms = h.terms ?? [];
  if (terms.length === 0) return <Empty>No parameters</Empty>;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-24">Symbol</TableHead>
          <TableHead>Parameter</TableHead>
          <TableHead className="text-right">Value</TableHead>
          <TableHead>Unit</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {terms.map((t, i) => (
          <TableRow key={`${t.symbol}-${i}`}>
            <TableCell className="text-[15px]">
              <Tex tex={t.symbol} />
            </TableCell>
            <TableCell>{t.label}</TableCell>
            <TableCell className="num text-right text-base font-bold">{fmt(t.value)}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{t.unit}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function SpectrumTable({ h }: { h: Hamiltonian }) {
  const levels = (h.levels ?? []).filter((l) => Number.isFinite(l.energy));
  if (levels.length === 0) return <Empty>No spectrum yet</Empty>;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>State</TableHead>
          <TableHead className="text-right">Energy (GHz)</TableHead>
          {levels.some((l) => l.group) && <TableHead>Group</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {levels.map((l, i) => (
          <TableRow key={`${l.label}-${i}`}>
            <TableCell>{l.label}</TableCell>
            <TableCell className="num text-right font-semibold">{fmt(l.energy)}</TableCell>
            {levels.some((x) => x.group) && <TableCell className="text-xs text-muted-foreground">{l.group ?? ""}</TableCell>}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function SolverLine({ h }: { h: Hamiltonian }) {
  const trunc = Object.entries(h.truncation ?? {});
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs">
      <dt className="label leading-4">Truncation</dt>
      <dd className="num">{trunc.length ? trunc.map(([k, v]) => `${k} ${v}`).join(" × ") : "—"}</dd>
      <dt className="label leading-4">Solver</dt>
      <dd>{h.solver || "—"}</dd>
    </dl>
  );
}

export function HamiltonianTab({ state }: { state: State }) {
  const h = state.hamiltonian;
  const plots = plotsFor(state, "hamiltonian");
  const qubits = state.elements.filter((e) => e.kind === "qubit").length;
  const pair = h?.pair?.length ? h.pair.join("–") : null;
  const note = h && (pair || qubits > 1) ? `QuTiP model of ${pair ?? "one transmon–resonator pair"}${qubits > 1 ? `; the other pairs use the estimator consensus (Parameters tab)` : ""}` : null;
  return (
    <TabPage aside={note}>
      <Section title="Model">
        {h ? (
          <div className="flex flex-col gap-4">
            <div className="text-[22px] font-bold leading-tight">{h.model || "—"}</div>
            <div className="border-y border-rule py-4 text-[19px]">
              <Tex tex={h.latex} display />
            </div>
            <SolverLine h={h} />
          </div>
        ) : (
          <Empty>No Hamiltonian model yet</Empty>
        )}
      </Section>

      <div className="col-span-12 flex min-w-0 flex-col gap-10 xl:col-span-5">
        <Section title="Parameters">
          {h ? <TermsTable h={h} /> : <Empty />}
        </Section>
        <Section title="Dressed spectrum" aside={h?.solver}>
          {h ? <SpectrumTable h={h} /> : <Empty />}
        </Section>
      </div>
      <Section title="Plots" className="xl:col-span-7">
        {plots.length ? (
          <div className="grid grid-cols-1 gap-6">
            {plots.map((p) => (
              <PlotCard key={p.id} plot={p} />
            ))}
          </div>
        ) : (
          <Empty />
        )}
      </Section>

      <Section title="Estimator consensus" aside="bold = chosen estimate · spread = (max − min) / |mean|">
        <ConsensusTable estimates={state.consensus} />
      </Section>
    </TabPage>
  );
}
