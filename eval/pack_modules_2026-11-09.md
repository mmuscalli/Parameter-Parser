# Shared modules for data packs, step 1 (2026-11-09)

Follow-up to `organics_heldout_2026-11-09.md`. The drafted "Organics in impacts" pack captured every value of its field
but recorded analysis methods as one text column, and it handled amounts and water only after compound setup.
`pack_modules.py` turns the parts the prebiotic pack refined over many rounds into modules any pack can take:

| Module | What it switches on | When a draft gets it |
|---|---|---|
| analysis | the analysis step + a copy of the technique vocabulary (58 techniques, editable), a hint telling open-ended stages to leave instrument settings to it, an Analysis category | the sample papers' surveys name an analytical technique (`techniques_named`, most specific match) |
| solution_chemistry | the chemistry step + normalize_species, mixing, molar_ratios, amounts, water_type, the parameters they need (solvent_volume_mL, solvent_name) and the chemistry prompt | compound setup finds compounds (Find compounds / "Then find compounds" / --find-compounds) |

Existing packs: `--add-module analysis|solution_chemistry ID` (CLI), or tick the step in the pack editor.
`--draft-pack ... --no-modules` drafts without them.

## Re-draft of the organics pack (copy: `organics_modules`)

Same survey and design answers, same compound setup. The draft's report lists the evidence: burchell2020 (Raman, SEM),
mckay1997 (GC-MS), muchowska2019 (GC-MS, NMR-1H), takeuchi2020 (UHPLC, LC-MS); mars_delivery2018 named none.

Three papers run again (handoff, same answers; the analysis answers are the ones written for the prebiotic runs):

| Paper | Filled columns before -> after | Gained |
|---|---|---|
| mckay1997 | 21 -> 28 | GC-MS / GC / MS / FTIR instruments and what each measured |
| takeuchi2020 | 31 -> 38 | UHPLC-MS/MS instrument, AccQ-Tag derivatization, MRM, XRD; solvent Milli-Q water |
| muchowska2019 | 12 -> 45 | 22 GC-MS settings (column, carrier gas and flow, oven programme, ...), 10 NMR settings, the pH meter; starting compounds as 33.3 / 66.7 / 66.7 mM (from 0.2 / 0.4 / 0.4 mmol in the 6 mL), solvent volume and type |

Nothing was lost. The one changed column: shock pressure is `peak_shock_pressure_bar` (70,000 bar) instead of
`_GPa` (7 GPa). That's because GPa became a known pressure unit and the app stores pressures in bar.

Cost: the analysis step adds about $0.02-0.035 per paper at Standard prices. Specific trigger words kept the
delivery-model stage off McKay and Takeuchi this time (about -$0.012 each). Net: about +5-20% per paper.

## Found on the way

- A unit right after 'per' in a column name ('..._molecules_per_J') is half of a rate, not the unit itself: the column
  had lost its unit suffix in the re-draft (`observations._unit_by_slug`, `unit_slug_suffix`).
- Technique detection takes the most specific technique ('RP-HPLC', not also 'HPLC'; 'GC-MS and direct MS' gives both).

## More modules (same day, Mickey: keep bar as the default pressure unit; add modules from the other built-ins)

| Module | What it adds | Drafting adds it when the surveys mention |
|---|---|---|
| kinetics | the prebiotic kinetics stage (rate constants, half-lives, activation energies; keyword-triggered) + category Kinetics | rate constants, half-lives, activation energy, Arrhenius, first/second-order, kinetics |
| wet_dry | the wet-dry stage (cycle number and length, phase temperatures / durations / humidity; runs for wet-dry sets) + category Wet-Dry Cycling + two row rules (one row per cycle; cumulative cycle times) | wet-dry / dry-wet, dehydration-rehydration, evaporation / drying / hydration cycles |
| product_totals | peptide_totals + oligomer_totals calculations and their columns (total peptide / oligomer yields, longest oligomer); brings solution_chemistry | peptides, oligomers, n-mers, diketopiperazines, poly(X); product compounds named as peptides / oligonucleotides |

Detection on real surveys: the organics drafting set calls only for `analysis` (correct: no kinetics, cycles or
oligomers). The Sam Papers surveys call for all of them: wet_dry for Caimi, Morasch and Song; kinetics for Calaça Serrão,
Liu, Matreux and Schwintek; product_totals for the oligomer papers.

Pack editor: "Add modules…" (bottom bar) lists every module with what it adds, the ones in the pack greyed. CLI:
`--add-module MODULE ID`.

The organics pack was swapped for the module version (same id `organics_in_target`, so its remembered variables
apply; 3 registry entries made under the temporary id moved). The old version was backed up to `<app data>/pack_backups/`.
