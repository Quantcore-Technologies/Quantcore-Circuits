import type { Circuit, CircuitBranch, State } from "@contract/state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BranchesTable } from "@/components/BranchesTable";
import { CircuitSchematic } from "@/components/CircuitSchematic";
import { PlotGrid } from "@/components/PlotCard";
import { Empty, Section, TabPage } from "@/components/Section";
import { naturalCompare } from "@/lib/elements";
import { plotsFor } from "@/lib/state";

function NodesTable({ state }: { state: State }) {
  const nodes = state.circuit?.nodes ?? [];
  if (nodes.length === 0) return <Empty>No nodes</Empty>;
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Node</TableHead>
          <TableHead>Label</TableHead>
          <TableHead>FEM net</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {nodes.map((n) => (
          <TableRow key={n.id}>
            <TableCell className="font-mono text-xs">{n.id}</TableCell>
            <TableCell>{n.label}</TableCell>
            <TableCell className="font-mono text-xs text-muted-foreground">{n.ground ? "ground" : n.island || "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

interface SubCircuit {
  id: string;
  title: string;
  circuit: Circuit;
}

const uniq = (xs: string[]) => [...new Set(xs)];

/**
 * A chip with several qubits does not fit one readable schematic: split it into one sub-circuit per qubit (island,
 * its coupler pads with their resonators, the feedline node they hang off) plus one for whatever is left (feedline
 * ports, qubit–qubit couplers). Node positions are re-laid per sub-circuit; the netlist table keeps the full picture.
 */
function subCircuits(circuit: Circuit): SubCircuit[] {
  const nodes = circuit.nodes ?? [];
  const branches = circuit.branches ?? [];
  const ground = new Set(nodes.filter((n) => n.ground).map((n) => n.id));
  const other = (b: CircuitBranch, id: string) => (b.nodes[0] === id ? b.nodes[1] : b.nodes[0]);
  const qubits = nodes
    .filter((n) => !n.ground && branches.some((b) => (b.type === "JJ" || b.type === "SQUID") && b.nodes.includes(n.id) && ground.has(other(b, n.id))))
    .map((n) => n.id)
    .sort(naturalCompare);
  if (qubits.length < 2) return [];
  const grounds = nodes.filter((n) => n.ground).map((n) => ({ ...n, pos: [0.5, 0.95] as [number, number] }));
  const make = (id: string, title: string, order: string[], list: CircuitBranch[]): SubCircuit => ({
    id,
    title,
    circuit: {
      name: `${circuit.name} · ${id}`,
      nodes: [...grounds, ...order.map((nid, i) => ({ ...(nodes.find((n) => n.id === nid) ?? { id: nid, label: nid }), pos: [(i + 1) / (order.length + 1), 0.35] as [number, number] }))],
      branches: list,
    },
  });
  const used = new Set<string>();
  const out: SubCircuit[] = [];
  for (const q of qubits) {
    const couplers = uniq(branches.filter((b) => b.type === "C" && b.nodes.includes(q) && !ground.has(other(b, q)) && !qubits.includes(other(b, q))).map((b) => other(b, q)));
    const feeds = uniq(branches.filter((b) => b.type === "HANGER" && couplers.some((c) => b.nodes.includes(c))).flatMap((b) => b.nodes.filter((n) => !couplers.includes(n))));
    const members = new Set([q, ...couplers, ...feeds]);
    const onlyFeed = (b: CircuitBranch) => b.nodes.every((n) => feeds.includes(n) || ground.has(n));
    const list = branches.filter((b) => b.nodes.every((n) => members.has(n) || ground.has(n)) && !onlyFeed(b));
    list.forEach((b) => used.add(b.id));
    const res = list.filter((b) => b.type === "TL").map((b) => b.id);
    out.push(make(q, [q, ...res].join(" · "), [q, ...couplers, ...feeds], list));
  }
  const rest = branches.filter((b) => !used.has(b.id));
  if (rest.length) {
    const order = uniq(rest.flatMap((b) => b.nodes).filter((n) => !ground.has(n))).sort(naturalCompare);
    const feedOnly = rest.every((b) => b.type === "R");
    out.push(make("rest", feedOnly ? `Feedline ${order.join(", ")} · ports` : "Other branches", order, rest));
  }
  return out;
}

export function CircuitTab({ state }: { state: State }) {
  const { circuit } = state;
  const plots = plotsFor(state, "circuit");
  const subs = circuit ? subCircuits(circuit) : [];
  const nb = circuit?.branches?.length ?? 0;
  return (
    <TabPage aside={circuit && <span>Lumped model {circuit.name}</span>}>
      {subs.length > 0 ? (
        <>
          <Section title="Schematics" aside={`one per qubit${subs.some((s) => s.id === "rest") ? " + the rest" : ""} · full netlist below`}>
            <div className="grid grid-cols-1 gap-x-8 gap-y-8 lg:grid-cols-2">
              {subs.map((s) => (
                <figure key={s.id} className="min-w-0 border-t border-rule pt-2">
                  <figcaption className="mb-1 text-[13px] font-semibold">{s.title}</figcaption>
                  <CircuitSchematic circuit={s.circuit} />
                </figure>
              ))}
            </div>
          </Section>
          <Section title="Netlist" className="xl:col-span-8" aside={`${nb} branches · extracted vs. design`}>
            <BranchesTable branches={circuit?.branches ?? []} />
          </Section>
          <Section title="Nodes" className="xl:col-span-4">
            <NodesTable state={state} />
          </Section>
        </>
      ) : (
        <>
          <Section title="Schematic" className="xl:col-span-7" aside={circuit?.name}>
            <CircuitSchematic circuit={circuit} />
          </Section>
          <div className="col-span-12 flex min-w-0 flex-col gap-10 xl:col-span-5">
            <Section title="Branches" aside="extracted vs. design">
              <BranchesTable branches={circuit?.branches ?? []} />
            </Section>
            <Section title="Nodes">
              <NodesTable state={state} />
            </Section>
          </div>
        </>
      )}
      {plots.length > 0 && (
        <Section title="Plots">
          <PlotGrid plots={plots} />
        </Section>
      )}
    </TabPage>
  );
}
