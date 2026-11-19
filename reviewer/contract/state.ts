// Data contract between the Python backend (`qcc review` / quantcore_circuits.track) and the dashboard.
//
// GET  /api/state          -> State (below)
// GET  /api/events         -> text/event-stream; sends `event: state` with data {"updated": iso} whenever the state
//                             changes (the client then refetches /api/state). A comment ping every 15 s.
// GET  /files/<relpath>    -> files inside the run directory (screenshots: Screenshot.url already points here)
// POST /api/rebuild        -> {ok: boolean, error?: string}; rebuilds the layout from design.json
//
// Units: frequencies GHz, anharmonicity / chi / g / kappa MHz, capacitances fF, inductances nH, lengths µm.
// Conventions: alpha < 0; chi = E11 − E10 − E01 + E00 (MHz).

export type StepStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface Step {
  id: string; // "synthesis" | "layout" | "render" | "simulate" | "extract" | "hamiltonian" | "compare" | "feedback"
  index: number; // 1-based position in the pipeline
  title: string; // "LOM synthesis"
  status: StepStatus;
  summary?: string; // one line, e.g. "Lj 9.26 nH, C_Σ 97.1 fF, λ/4 4227 µm"
  started?: string; // ISO time
  finished?: string;
  metrics?: Record<string, number | string>;
}

export interface Target {
  key: string; // "Q1.f_q_GHz"
  label: string; // "Q1 frequency"
  symbol: string; // "f_q"  (render as plain text or KaTeX)
  unit: string; // "GHz"
  target: number;
  tol: number; // absolute tolerance in `unit`
  value: number | null; // current best estimate (consensus), null = not yet known
  source?: string; // estimator that produced `value`
  status: "pass" | "fail" | "unknown";
}

export interface Goal {
  reached: boolean;
  passed: number;
  total: number;
  summary: string; // "3 of 4 targets within tolerance"
}

export interface Screenshot {
  id: string;
  title: string; // "Chip — after iteration 2"
  url: string; // "/files/shots/chip_it2.png"
  step?: string; // Step.id
  caption?: string;
  created: string;
  source: "gui" | "headless"; // KLayout GUI capture or headless KLayout render
}

export interface Series {
  name: string;
  x: number[];
  y: number[];
  kind?: "line" | "scatter" | "step";
  dashed?: boolean;
}

export interface Level {
  label: string; // "|g,1⟩"
  energy: number; // GHz, ground = 0
  group?: string; // column in a level diagram, e.g. "qubit", "resonator", "dressed"
}

export interface PlotSpec {
  id: string;
  title: string;
  tab: "hamiltonian" | "plots" | "simulation" | "history" | "circuit";
  kind: "xy" | "bar" | "levels" | "heatmap";
  xLabel?: string; // axis label incl. unit, e.g. "Flux Φ/Φ0"
  yLabel?: string;
  logY?: boolean;
  series?: Series[]; // kind = xy
  bars?: { label: string; values: Record<string, number | null> }[]; // kind = bar: groups → {series: value}
  levels?: Level[]; // kind = levels
  heatmap?: { rows: string[]; cols: string[]; values: number[][]; unit: string }; // kind = heatmap
  refLines?: { axis: "x" | "y"; value: number; label: string }[]; // e.g. target lines
  caption?: string;
}

export interface CircuitNode {
  id: string; // "q1"
  label: string; // "Q1 island"
  ground?: boolean;
  island?: string; // FEM net, e.g. "Q1.island"
  pos: [number, number]; // layout hint in [0, 1] x [0, 1], y downwards; ground nodes at y ≈ 1
}

export interface CircuitBranch {
  id: string; // "Cq"
  type: "C" | "L" | "JJ" | "SQUID" | "TL" | "R" | "HANGER"; // HANGER = coupled-line λ/4 hanger coupler (κ)
  nodes: [string, string];
  value: number | null; // extracted value in `unit`
  designValue?: number | null; // value the design asked for (side by side, never overwritten)
  unit: string; // "fF" | "nH" | "Ω" | "µm"
  label: string; // "C_Σ − C_g"
  source?: string; // "cmatrix:q1_r1_..._q3d" | "design" | "lom"
}

export interface Circuit {
  name: string;
  nodes: CircuitNode[];
  branches: CircuitBranch[];
}

export interface HamiltonianTerm {
  symbol: string; // KaTeX, e.g. "\\omega_q/2\\pi"
  label: string; // "qubit frequency"
  value: number;
  unit: string;
}

export interface Hamiltonian {
  model: string; // "Transmon + λ/4 resonator (dispersive, Kerr)"
  latex: string; // KaTeX display string
  terms: HamiltonianTerm[];
  levels: Level[]; // dressed spectrum from the QuTiP solve
  truncation: Record<string, number>; // {"qubit": 8, "resonator": 6}
  solver: string; // "QuTiP 5.3 eigenstates"
  pair?: string[]; // [qubit, resonator] the model describes, e.g. ["Q1", "R1"] (a multi-qubit chip: one pair)
}

export interface Estimate {
  param: string; // "Q1.f_q_GHz"
  label: string;
  unit: string;
  target?: number | null;
  values: Record<string, number | null>; // estimator → value, e.g. {"metal_lom": 5.02, "scqubits": 5.03, ...}
  chosen: number | null;
  chosenBy: string; // estimator selected by the policy
  spreadRel: number | null; // (max − min) / |mean|
  flagged: boolean; // spread above tolerance (modelling problem, not a design problem)
}

export interface Job {
  name: string;
  group: string; // "Q1R1" | "chip"
  analysis: string; // "q3d_cmatrix" | "hfss_eigenmode" | ...
  solver: string; // "ansys" | "elmer" | "palace"
  status: string; // "exported" | "rendered" | "running" | "done" | "failed" | ...
  created?: string;
  finished?: string;
  hasResults: boolean;
  project?: string | null; // .aedt path if rendered
  source?: "kept"; // results come from the kept copy (examples/tutorials/fem/<job>), not a solve in build/jobs
  progress?: JobProgress | null; // what the job directory shows about the solve (null: only exported)
}

/** Solve progress read from build/jobs/<job>/ (job.json, solve.log, *_convergence.txt). All fields optional. */
export interface JobProgress {
  elapsedS?: number; // seconds since the solve started (running) or the solve wall time (done)
  stale?: boolean; // job.json says "solving" but the AEDT process is gone
  stage?: string; // last line of qcc_solve_status.txt
  logTail?: string; // last meaningful line of solve.log
  pass?: number; // last adaptive pass
  maxPasses?: number; // settings.maximum_passes
  passes?: number[];
  elements?: number[]; // solved tetrahedra per pass
  delta?: (number | null)[]; // convergence criterion per pass
  target?: number | null;
  criterion?: string | null;
  converged?: boolean;
  modesGHz?: number[]; // eigenmode: the mode frequencies of the latest pass (while AEDT runs)
}

/** Estimate vs FEM of one circuit branch (filled from a job's results). */
export interface FemCompareRow {
  branch: string;
  nodes: string[];
  type: string;
  unit: string;
  estimate: number;
  fem: number;
  deltaPct: number;
  job?: string; // the FEM job (simulation) the value came from; subset runs fill one circuit from several jobs
}

export interface CMatrix {
  labels: string[];
  matrix: number[][]; // Maxwell matrix, fF
  unit: "fF";
  job: string;
}

export interface Iteration {
  iteration: number;
  objective: number; // normalised residual norm
  residuals: Record<string, number>; // target key → (value − target) / tol
  knobs: Record<string, number>; // "Q1.cross_length" → 300
  accepted: boolean;
  time: string;
  kind?: "lom" | "optimise"; // rows the automatic tracking wrote (one per evaluated design / optimiser step)
  label?: string;
}

export interface LogEntry {
  t: string;
  level: "info" | "warn" | "error";
  msg: string;
}

export interface DesignInfo {
  name: string;
  path: string;
  hash: string;
  pdk: string;
  stack: { substrate: string; epsR: number; thickness_um: number };
  chipBox: [number, number, number, number]; // µm
  instances: number;
  routes: number;
}

// ---- Parameter cards (the main content of the Parameters tab) ---------------------------------------------------
export interface CardRef {
  label: string; // "C_island" (plain text; render "_x" as subscript)
  value: string; // preformatted "64.05 fF"
  // where this value comes from: a ParamCard.id ("Q1R1.cg"), a card number ("05"), a ChipElement.id ("R1"),
  // a section letter ("D"), or a plain word that is not a link ("design")
  ref?: string;
}

export interface CardSub {
  symbol: string; // KaTeX
  value: number | null;
  unit: string;
}

export interface ParamCard {
  id: string; // stable, e.g. "Q1.f01", "R1.kappa", "Q1R1.g", "chip.cpw", "sim.self.Q1.island"
  section: string; // Section.id
  element?: string; // ChipElement.id the card belongs to ("Q1", "R1", …) or "chip" (process, simulation, jobs, feedback)
  partner?: string; // second element of a two-element card: coupling Q1–R1 has element "Q1", partner "R1"
  index: number; // global running number, shown as "01", "02", ...
  title: string; // "Qubit capacitance"
  symbol: string; // KaTeX, e.g. "C_\Sigma", "\alpha/2\pi"
  value: number | null; // the headline number (h2)
  unit: string;
  sub?: CardSub[]; // secondary numbers (h3/small): "E_C/h 279.9 MHz"
  target?: { value: number; tol: number } | null;
  design?: number | null; // value the design asked for (LOM synthesis); show the deviation
  range?: [number, number] | null; // estimator min–max (spread)
  source?: string; // estimator / "fem" / "estimate" / "design.json"
  status?: "pass" | "fail" | "warn" | "info";
  from?: CardRef[]; // dependency chips ("From  C_island 64.05 fF · D")
  formula?: string; // KaTeX, shown on demand (Σ button)
  plot?: string; // PlotSpec.id, shown on demand (chart button)
  description?: string;
  notes?: string[];
}

export interface Section {
  id: string;
  letter: string; // "A" | "B" | ...
  title: string; // "Qubit Q1"
  subtitle?: string;
}

export interface SummaryItem {
  label: string;
  symbol?: string; // KaTeX
  value: number | string | null;
  unit?: string;
  status?: "pass" | "fail" | "warn" | "info" | null;
}

export interface SummaryGroup {
  id: string;
  index: string; // "0", "A", ...
  title: string; // "Process and CPW"
  items: SummaryItem[];
}

// ---- Chip elements (chip overview: one row per qubit / resonator / …; any number of each) -------------------------
export type ElementKind = "qubit" | "resonator" | "coupler" | "feedline" | "bus" | "port";

export interface ElementParam {
  key: string; // column key, the same for every element of a kind: "f_q", "alpha", "EJ_EC", "f_r", "g", "chi", "kappa"
  label: string; // "Qubit frequency"
  symbol: string; // KaTeX, e.g. "f_{01}"
  value: number | null;
  unit: string;
  status?: "pass" | "fail" | "warn" | "info" | null;
  target?: { value: number; tol: number } | null;
  source?: string; // estimator / "fem" / "estimate"
  card?: string; // ParamCard.id that explains the value
  of?: string; // ChipElement.id the value belongs to when it is not this element (qubit row: f_r "of" R1)
}

export interface ElementLink {
  to: string; // ChipElement.id
  role: "readout" | "feedline" | "flux" | "coupling" | "port" | "drive"; // relation of this element to `to`
  label?: string; // e.g. the route name of a flux line
}

export interface ChipElement {
  id: string; // "Q1", "R1", "FL", "PAD_F1"
  kind: ElementKind;
  label: string; // "Q1" (coupler: "Q1–Q2")
  subtitle?: string; // "Xmon · Trilayer Squid", "λ/4 · hanger on FL"
  params: ElementParam[];
  links: ElementLink[];
  status?: "pass" | "fail" | "warn" | "info" | null; // worst status over `params`
}

export interface State {
  schema: "qcc-state/0.1";
  updated: string;
  design: DesignInfo;
  currentStep: string | null; // Step.id
  steps: Step[];
  goal: Goal;
  targets: Target[];
  screenshots: Screenshot[];
  plots: PlotSpec[];
  circuit: Circuit | null;
  hamiltonian: Hamiltonian | null;
  consensus: Estimate[];
  jobs: Job[];
  cmatrix: CMatrix | null;
  femCompare: FemCompareRow[]; // estimate vs FEM per branch, when a job's results were used
  history: Iteration[];
  log: LogEntry[];
  sections: Section[]; // card sections, in order
  cards: ParamCard[];
  summary: SummaryGroup[]; // "process" group: chip-level constants (overview strip)
  elements: ChipElement[]; // chip elements in display order (qubits, resonators, buses, couplers, feedlines, ports)
}
