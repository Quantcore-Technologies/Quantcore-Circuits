# QCC Live — design-loop dashboard

One-page, multi-tab live viewer for the quantcore-circuits design loop, organised by chip **element** so the
same page works for one qubit or a chip with many. The header carries the two-row logo (Quantcore wordmark with
CIRCUITS justified under it), the design, the targets badge, the connection state and *Rebuild layout*.

**Tabs = pipeline.** One row of wide, equal-width tabs in pipeline order — Circuit (LOM synthesis), Layout,
Simulation (HFSS render, simulate, extract), Hamiltonian, Parameters (compare to targets), History (feedback), then
Plots and Log. A bar along the top of each tab has one segment per step whose output that tab shows: red = done,
pulsing red = running, hatched red = failed, grey = pending, dashed = skipped, so the row fills from left to right
like a progress bar. The tab holding the current step gets a red marker and label; hover a tab for its steps'
summaries and times. The selected tab is underlined in ink. The row never scrolls: eight columns from 1024 px, two
rows of four below. Parameters is the default tab. Layouts are only shown as KLayout screenshots (PNG).

## Parameters tab

- **Chip overview** (from `state.elements`): one table per element kind. Qubits: f01, α, E_J/E_C, E_C, then the
  readout and coupling columns (f_r of its readout, g, χ, κ, Δ, Purcell T1), targets met; resonators: f_r, ℓ, κ,
  Q_ext, Z0; feedlines; ports (feedline ports, flux-bias pads). Columns come from the params' `key`s, so new
  parameters need no frontend change. Values are coloured by status with Δ/tol under target values; the tooltip has
  goal ± tol, Δ and the source. Click a column head to sort (again: descending, third time: off), filter by element
  / link ids ("Q3 R7 FL") or *Failing only*. Tables with more than 12 rows scroll inside a box with a sticky head.
  Click a row to open the element's cards, a value to jump to the card that explains it, a link id to that element.
- **Element selector** (sticky under the header): Chip | Qubits Q1 … | Resonators R1 … (only elements with cards),
  status square per element; mirrored in `?el=`. The selected element shows its header (id, kind, subtitle, link
  chips) and its cards; coupling cards (`partner`) show under the pair they belong to ("Coupling Q1–R1") in both the
  qubit's and the resonator's view. *Chip* holds process/CPW, simulation (C-matrix), jobs and feedback.
- **Card:** number, title, source tag (blue = FEM / estimator, orange = estimate, grey = design input), status (thin
  top rule + small FAIL / PASS / CHECK tag), description, symbol and the headline value, then goal ± tol with Δ/tol,
  design value with ↑/↓ %, estimator range, `sub` values, "From" chips. A chip's `ref` (card id or number, element
  id, section letter) jumps to that card — switching element if needed — or element; the chart button (only if
  `plot` names an existing PlotSpec) opens the plot; Σ toggles the KaTeX `formula`. Columns follow the width of
  the card area (container queries in `index.css`): 1, 2 from 680 px, 3 from 840 px, 4 from 1140 px.
- Older states still render: without `elements` the overview is derived from `targets` and the section ids
  (`qubit_Q1`, `res_R1`, `coupling_Q1R1`), without `cards` the cards come from `targets` and `hamiltonian.terms`.

## Circuit tab

One schematic for a single qubit; with two or more qubits, one mini schematic per qubit (island, coupler pads with
their resonators, the feedline node) plus one for the rest (feedline ports, qubit–qubit couplers), and the full
netlist and node tables.

Vite 5 + React 18 + TypeScript, Tailwind 3 + shadcn/ui (Radix), Recharts, KaTeX. Fonts are
bundled (`@fontsource`), so the built app works offline.

## Data contract

`contract/state.ts` is the single source of truth for the `State` document and the API
(`GET /api/state`, `GET /api/events` (SSE), `GET /files/<relpath>`, `POST /api/rebuild`).
The app imports these types (`@contract/state`); do not redefine them in `src/`.
`public/sample-state.json` (+ `public/sample/*.png`) is a fixture that conforms to it.

## Develop

```sh
qcc review                 # backend on http://127.0.0.1:8765 (serves /api and /files)
cd reviewer
npm install
npm run dev                # http://localhost:5173, proxies /api and /files to :8765
```

The app subscribes to `/api/events`; if the stream fails it polls `/api/state` every 3 s.
The header shows LIVE / POLLING / OFFLINE and the time of the last state update.
If `/api/state` is unreachable at start-up it shows the sample fixture (labelled
SAMPLE DATA) and keeps retrying in the background.

URL parameters:

- `?sample` — load `./sample-state.json` and never contact the backend
  (`?sample=other.json` loads another fixture next to `index.html`).
- `?tab=parameters|layout|circuit|hamiltonian|plots|simulation|history|log` — initial tab
  (kept in the URL as you switch tabs); `?tab=overview` still works as an alias of `parameters`.
- `?el=Q2` — selected element on the Parameters tab (`chip` for the chip-level cards).

## States from real runs

```sh
python reviewer/scripts/make_states.py            # 2-qubit run + fixture, refresh the 1-qubit run's cards
```

- `build/two_qubit/state.json` — `examples/two_qubit_synth.json`, LOM-only (layout estimates, no FEM, one QuTiP
  solve per pair), feedback revision 1, headless KLayout screenshots; `qcc review examples/two_qubit_synth.json`.
- `build/q1_r1_code/state.json` — the notebook's 1-qubit run, re-analysed with its FEM job; `qcc review
  examples/q1_r1_code.json`.
- `public/sample-state.json` + `public/sample/*.png` — copy of the 2-qubit state (the fixture).

## Build

```sh
npm run build              # tsc --noEmit && vite build
```

Output goes to `../src/quantcore_circuits/review/static/` (emptied on every build) with
relative asset URLs, so `qcc review` can serve it from any path. `public/` (sample fixture,
logos) is copied into the build.

## Layout of `src/`

- `hooks/useLiveState.ts` — fetch / SSE / polling / sample fallback
- `lib/` — `state.ts` (defensive normalisation), `cards.ts` (source colours, symbol clean-up, fallbacks),
  `elements.ts` (element model, card blocks per element, fallbacks for older states), `format.ts`, `palette.ts`,
  `scale.ts`, `tabs.ts`
- `components/ui/` — shadcn components (square corners, no shadows)
- `components/` — header + logo, `NavTabs.tsx` (pipeline tabs, step markers), `ChipOverview.tsx` (element tables),
  `ParamCard.tsx`, tables,
  `CircuitSchematic.tsx` (C, L, JJ, SQUID, TL, R, HANGER symbols), screenshots
- `components/charts/` — `XYPlot`, `BarPlot` (Recharts), `LevelsPlot`, `Heatmap` (SVG)
- `tabs/` — one component per tab
