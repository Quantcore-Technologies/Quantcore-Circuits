# Cryo probe test chip (chip_06)

A test chip with no qubits: 24 pairs of probe pads (6 columns × 4 rows), each pair joined by an HSQ-spacer trilayer
junction, framed by 24 wire-bond rings on the four edges. The straight finger sweeps 0.4 to 0.9 µm along the columns
and the bent finger is 0.6 µm. The chip is made to be bonded and measured cold, to check junction resistance in the
fridge. It is Quantcore's own test chip from the QWri legacy script `chip_06_test_cyro_TLQ.py`.

The rebuild draws it from Quantcore PDK parts, values each junction on the PDK trilayer process and moves the
wire-bond rings to the 100 µm pad rule. Build this one to see the HSQ test pad and how bond rings frame a test array.

```{figure} ../../images/designs/legacy/chip_06_test_cyro_tlq.png
:width: 100%
:alt: chip_06_test_cyro_tlq as rebuilt on the Quantcore PDK

chip_06_test_cyro_tlq as rebuilt on the Quantcore PDK
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/legacy/chip_06_test_cyro_tlq.ipynb` |
| Source script | `components/python/chip_06_test_cyro_TLQ.py` (QWri legacy, Quantcore internal) |
| Chip | 7.5 × 7.5 mm die |
| On the chip | 24 `testPad_Nb_TL_HSQ` probe structures · 24 wire-bond rings · 4 HSQ corner markers |
| Builds today | yes, rebuilt from its JSON on 2026-11-19 in 1.0 s (the notebook itself was not re-run) |

## Pictures

```{figure} ../../images/designs/legacy/chip_06_test_cyro_tlq_legacy.png
:width: 70%
:alt: chip_06_test_cyro_tlq: the original legacy layout (render of the legacy GDS)

chip_06_test_cyro_tlq: the original legacy layout (render of the legacy GDS)
```

```{figure} ../../images/designs/legacy/chip_06_test_cyro_tlq.png
:width: 70%
:alt: chip_06_test_cyro_tlq: the Quantcore rebuild

chip_06_test_cyro_tlq: the Quantcore rebuild
```

```{figure} ../../images/designs/legacy/chip_06_test_cyro_tlq_tp_4_2.png
:width: 45%
:alt: One test pad: two probe pads with the junction between their tips

One test pad: two probe pads with the junction between their tips
```

```{figure} ../../images/designs/legacy/chip_06_test_cyro_tlq_jj.png
:width: 45%
:alt: The HSQ junction (20 µm box): fingers and overlap

The HSQ junction (20 µm box): fingers and overlap
```

## LOM estimates

The notebook's saved outputs hold no LOM run (its LOM cells were not executed), so there are no estimates to show here and none were computed for this page. It is a test chip, so the build spec gives junction values from the PDK process instead.

## Build spec

The rest of this page is the detailed spec the notebook was built from: components, positions, parameters and what changed from the legacy script.

Source: `components/python/chip_06_test_cyro_TLQ.py` (`create_test_chip()`, writes
`chip_06_test_cryoTLQ_1.0.gds`). Legacy QWri library, Quantcore internal. Notebook
`examples/designs/legacy/chip_06_test_cyro_tlq.ipynb`.

### Changes made in the rebuild

- Device ID restored: `name_chip="CHIP06"`, placed by the frame rule (edge centres → beside the pads with a 50 µm gap → left/right edge → omitted): the rings leave no free block, so the build omits it (no warning).
- Junctions: the drawn test-pad sweep valued on the PDK junction rule (Nb trilayer, Δ = 1.4 meV, I_c·R_n = πΔ/2e = 2.20 mV, R_n 40–50 kΩ, qubits 4–8 GHz; PDK process `get_pdk().junction`: R_n·A 13.5 kΩ·µm², C_J 50 fF/µm², both assumed by the PDK).
- The notebook's JSON was rebuilt from its layout cell. The notebook has not been re-run, so its outputs are cleared and its PNGs may be out of date.

What it is: a cryogenic junction test chip: a 6 × 4 array of `testPad_Nb_TL_HSQ` probe structures, 24 wire-bond
rings on the four edges and HSQ corner markers, on a 7.5 × 7.5 mm die centred on (0, 0) → Designer
(x + 3750, y + 3750). PDK v2 die frame replaces the base-metal corner `Marker`s (rot 1/2/3/0) and the layer-10
outlines (7500 and 5200 µm boxes, 500 µm boxes at (±3350, ±3350)). No qubits or resonators.

Builds: yes. The text labels are not drawn.

### Components (legacy frame)

| instance | legacy → catalog ref | params | at | notes |
|---|---|---|---|---|
| TP_i_j (24) | `testPad_Nb_TL_HSQ.create_testPad(bf / 0.2, tf)` (`TEST_TL`) → `JunctionTestPads(**legacy_test_pad_params("testPad_Nb_TL_HSQ", bf / 0.2, tf))` | pads 500 × 400, middle 300, window 600 × 1100, HSQ boxes; straight finger `0.2·size` = bf, bent finger tf | x = −2200 … 2200 (`np.linspace`, 880 pitch), y = −1950 … 1950 (1300 pitch) | bf = 0.4 … 0.9 µm per column; tf = 0.6 µm (`top_finger = [0.6] * 5`, 4 rows used) |
| WB0 … WB23 | `wirepad` = Box(1000) − Box(800) on 1/0 and 3/0 | `TaperedPad(pad 800 × 800, no taper, negative, window 1000 × 1000, y offset 100)`: the same etch | (x, ±3250) and (±3250, x), x = −2350 … 2350 (`np.linspace`, 6) | the outer edge reaches the die edge (y = ±3750) |
| HSQ0 … HSQ3 | `Marker` with `l` = 500/0 (HSQ), `fab_l` = 150/0, thickness 50, width 150 | `CornerMarker(hsq=True, thickness=50, width=150)` | (±3750, ±3750), rot 1/2/3/0 | HSQ alignment; base-metal markers → PDK frame |
| labels | inverted bf·1000 (100 µm) at (x − 190, 2520); the row labels are generated but never inserted (legacy bug) | MISSING (text cell) | | |

### LOM

Test pads and markers are port-less; the rings are `TaperedPad`s whose finger port is a bare pad node (pad C to
ground). "LOM simulation" = the junction table (area bf × 0.6 µm², assumed Jc). No sim groups / FEM jobs.

### Keep-outs

Legacy positions kept: the rings at y = ±3250 (and x = ±3250) reach the die edge, i.e. into the 100 µm die margin;
the HSQ markers sit in the corner marker areas. Listed by the DRC (`frame_*` warnings) in the notebook.
