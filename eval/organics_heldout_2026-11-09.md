# Held-out test of the drafted "Organics in impacts" pack (2026-11-09)

The first round (`organics_2026-11-09.md`) scored the drafted pack on the same five papers it was drafted from. Here it is
scored on five other papers from `Test Paper List/Organics in target` that it has never seen, against the Prebiotic
Chemistry pack. Both packs ran in developer handoff mode with the same reading of each paper: Claude Code answered every
request, so this compares the packs, not models. Suggestions were accepted where reasonable and remembered, as in round one.

| Held-out paper | What it is | Closest drafting paper |
|---|---|---|
| tingle1991 (OLEB) | Murchison meteorite shocked to 19–36 GPa, organic loss by SALI-MS | McKay, Takeuchi |
| kazemi2021 (MethodsX) | capture of a fluorescent dye in ice-particle impacts on Al at 1.7 km/s | Burchell |
| deluca2022 (JGR Planets) | ablation of polypyrrole coatings on olivine dust at 10–20 km/s | Burchell |
| chyba1990 (Science) | model of cometary delivery of organics to the early Earth | Mars delivery |
| dacosta2022 (MNRAS) | valine destruction by keV electrons (radiation, not impact) | none (an edge case) |

The 1989 and 1992 Nature papers in the folder are scans with no text layer and were left out.

## Results

Values a curator would record (results, conditions, materials, methods), counted by hand against the final CSVs:

| | Drafted pack | Prebiotic Chemistry |
|---|---|---|
| Rows | 10 | 3 (tingle only) |
| Values captured, held-out set | **40 of 41** | 12 of 41 |
| Values captured, drafting set (round one) | 89 of 89 | 37 of 89 |
| Cells in the pack's own columns, held-out | **70%** | 44% |
| Cells in the pack's own columns, drafting set | 54% | 74% |
| Cost, Standard, 5 papers (estimated) | $0.93 | $0.82 |
| Spent on papers that gave no rows | $0 | $0.59 (kazemi, deluca, dacosta) |

Per paper (drafted pack values / prebiotic values): tingle 12/12, kazemi 6/0, deluca 9/0, chyba 7/0, dacosta 6 of 7/0.
The one value missed was da Costa's overall cross-section range (1–100 × 10⁻¹⁶ cm²); the pack recorded the 1 keV values
instead.

The share of cells in the pack's own columns *rose* on unseen papers. The drafting-set figure is pulled down by
McKay's paper-wide suggestion columns repeated on 16 rows. The pack's columns were not fitted to its five sample papers
alone: impact velocity, peak pressure, projectile, target and product columns carried most of the held-out data.

**Precision.** No values were wrong, but two were put in columns that only loosely fit (a drafted pack has no column for
some adjacent quantities):
- da Costa's electron energies (1 and 2 keV) went into `energy_input_J`, which is described as energy per shot or pulse.
  They were stored correctly converted, as 1.6×10⁻¹⁶ J, but the column means something else.
- Tingle's "~70% of the organic matter volatilized" went into `conversion_pct`.

New quantities of the adjacent subtopics went through review as suggestions: charge yield, capture efficiency, destruction
cross-section, crater sizes, coating thickness, delivery half-life. Those whose units the app doesn't convert (C/kg,
cm²) were kept as text.

**Prebiotic pack.** Its row rules gave rows only for Tingle (Table I's three shots). On the others it correctly found no
experiments of its kind, but in app-style runs it still paid for its extraction steps ($0.14–0.23 each). Command-line runs
and queues now skip them (the figure-only rule from round one). Its kinetics step fired on DeLuca and da Costa with
nothing to record.

## Triggers

`delivery_model` (keywords "simulation", "delivery", "infall", ...) fired on 4 of 5 held-out papers; only Chyba is a
delivery model. Counting keyword hits outside the reference list:

| Paper | delivery_model hits (distinct words) | kinetics hits (distinct) |
|---|---|---|
| mars_delivery2018 (real) | 83 (7) | 0 |
| chyba1990 (real) | 13 (3) | 7 (7) |
| mckay / takeuchi / tingle | 4 / 5 / 3 (2 each) | 0 |
| deluca2022 / dacosta2022 | 7 (1) / 2 (1) | 6 (3) / 2 (1) |
| mitsuzawa2004 / Sakata2014 / Liu 2026 (real kinetics) | – | 30 / 12 / 19 |
| eder1994, faisal2005, truman2024, Song 2024, Hirakawa 2025 | – | 1–2 |

A threshold (about 3 distinct words, or about 10 hits) would separate these, but a false trigger costs about $0.01 while
a missed one loses values. Triggers were left as they are.

## Fixed from this round

- `_range` / `_avg` markers go before any unit the app reads, and before a stage parameter's own unit even when the app
  doesn't convert it: `crater_diameters_range_um`, `particle_speed_range_km_per_s`, `carbon_delivery_rate_range_kg_per_yr`
  (they had gone after the unit).
- mTorr is a pressure unit (DeLuca's 30–100 mTorr had no unit).

## What this says about the direction

- **Drafting generalises within a field.** A pack drafted from five papers captured 40 of 41 values on five unseen
  papers of the same folder, and the edge case (radiation instead of impact) still mostly fit. Making "draft a pack
  for this batch" the default first step is supported.
- **A broad pack doesn't transfer.** Prebiotic captured 29% of the held-out values (42% on the drafting set) and paid
  for steps on papers it couldn't use.
- **The drafted pack missed the curated parts.** It recorded analysis methods as one text column; prebiotic's analysis
  step recorded 20 GC-MS / NMR settings on Muchowska. It also lacked prebiotic's amount, mixing and water handling until
  compound setup added them. This is the case for shared modules: the analysis step and the solution-chemistry
  calculations already exist as built-ins any pack can switch on, and a drafted pack should get them by default.
- **Adjacent subtopics come in through suggestions.** That works, but each one lands as text or a loosely fitting column
  the first time. Suggest-additions after a few runs, or drafting from a slightly broader sample, closes those gaps.
