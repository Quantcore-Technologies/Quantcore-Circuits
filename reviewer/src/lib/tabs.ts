/** In pipeline order (synthesis → layout → simulation → Hamiltonian → targets → feedback), so the tabs' step bars
 *  fill from left to right like a progress bar; Plots and Log have no step. Parameters is the default tab. */
export const TABS = [
  { id: "circuit", label: "Circuit" },
  { id: "layout", label: "Layout" },
  { id: "simulation", label: "Simulation" },
  { id: "hamiltonian", label: "Hamiltonian" },
  { id: "parameters", label: "Parameters" },
  { id: "history", label: "History" },
  { id: "plots", label: "Plots" },
  { id: "log", label: "Log" },
] as const;

export type TabId = (typeof TABS)[number]["id"];

/** Old tab names that still work in `?tab=` links. */
const ALIASES: Record<string, TabId> = { overview: "parameters" };

export const isTabId = (v: string | null | undefined): v is TabId => TABS.some((t) => t.id === v);

/** `?tab=` value → tab id (aliases resolved), or null if unknown. */
export const parseTab = (v: string | null | undefined): TabId | null => (isTabId(v) ? v : v ? (ALIASES[v] ?? null) : null);

/** The tab that shows each pipeline step's output (and carries its segment of the progress bar). */
export const STEP_TAB: Record<string, TabId> = {
  synthesis: "circuit",
  layout: "layout",
  render: "simulation",
  simulate: "simulation",
  extract: "simulation", // C-matrix → circuit values: shown with the C-matrix
  hamiltonian: "hamiltonian",
  compare: "parameters",
  feedback: "history",
};
