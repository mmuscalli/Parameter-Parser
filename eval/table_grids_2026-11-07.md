# Tables read by the app ("table grids") -- evaluation (2026-11-07)

Question (Mickey, after the cost discussion): does letting code read table cells, with the model only mapping
columns and rows to variables and samples, cut cost without losing accuracy?

## What was built

- `ingestion/table_grid.py`: a table's cells from the PDF text layer (words -> lines -> columns from the gaps through
  every numeric line; sub/superscripts attached as `^{..}` / `_{..}`; split decimals joined and dot leaders dropped;
  landscape pages read upright) or from an arXiv text's ' | ' rows. Only reliable tables become grids (`usable`):
  scanned pages (OCR text, render mode 3) never; cells that can't be one value are marked "not readable".
  `cell_value` reads values, ± and asymmetric uncertainties (also nested `\times 10^{-7}`), limits, ranges, powers
  of ten, units in the cell, n.d.
- Chemistry `tables` may name a `grid` with `gc` / `gr` positions (cells read by `ChemistryExtraction.fill_grids`);
  table-reading spec stages may answer `grids` with columns x rows, or for parameter tables `prows` x `scols`
  (`optional.fill_grids`). Unreadable mapped cells -> `value_not_read` flags.
- Grids follow the PDF text, or replace a text source's tables in place. `RunConfig.table_grids` (now off).
- `scripts/eval_references.py`: live runs of runs/reference papers scored against their expected CSVs (rows paired
  by content), cost and output tokens per step; `--src` runs another checkout for a baseline.

## Results (Standard, live, one run per row)

| paper | baseline | grids, round 1 | round 2 | round 3 (final) |
|---|---|---|---|---|
| aa57186 (arXiv) | 97.2% $0.302 | 95.5% $0.346 | 98.6% $0.369 | 96.2% $0.321 (also 94.1% $0.334) |
| faisal2005 | 95.0% $0.337 | 85.0% $0.312 | 95.0% $0.347 | 95.0% $0.357 |
| kim2017 | 100% $0.234 | 100% $0.201 | 100% $0.257 | 100% $0.265 |
| kim2019 | 100% $0.233 | 82.8% $0.252 | 82.8% $0.251 | 72.2% $0.243 |
| nielsen2019 (archive matches) | 124 $0.214 | 120 (+3 not extracted) $0.243 | | |

Baseline = the commit before this work plus the two unrelated fixes made during it (mixing check, quench rule),
so only the grids differ. Mean over the four gridded references: baseline $0.277, grids $0.29 (+6%).

## Why it didn't pay

- Where the model mapped a grid, that step's output did drop (kim2017 chemistry -47% in round 1, faisal conditions
  -53%, aa57186 planet parameters -26 to -57%). But the compact `tables` format (2026-10-27) had already made each
  cell cheap: what remains of an answer is mostly set / sample labels repeated per row, values from the text, the
  combined solutions and free-text items -- not table numbers.
- The model didn't use the grids consistently (round 2 mostly copied values again), and sometimes did both.
- Grids add input: 0.2-0.7K tokens per prebiotic paper, 2.4K for nielsen (its 65-row RV table), 4.3K for aa57186
  before tables were replaced in place.
- Run-to-run variation (about +-$0.03 and several accuracy points per paper) is as large as the effect.

## Kept

Grids stay available (`RunConfig.table_grids`), with tests (tests/test_table_grids.py): they read values exactly from
the PDF (truman2024's 10^-4 M exponent, lost in the plain text, is recovered), and a large parameter table (an arXiv
exoplanet paper) is where they help most. Teng2023's landscape tables can't be gridded: its text layer has no
decimal points.

## Found and fixed on the way (all runs benefit)

- kim2017: a planned 'preparative synthesis' set with its own stocks made the mixing check refuse every other set
  (CaCl2 lost on all rows): a solution only one other set lists no longer counts as missing.
- faisal2005: the quench temperature (5 °C) was taken as the sampled temperature: rule clarified.
- eder1994: the analysis step failed when the model left out a technique's own quote: those fields are optional.
- truman2024 now gets no rows: since 2026-11-03 a review paper is skipped (its data are other papers'); its reference
  predates that decision -- an open question, not a regression.
- "Overloaded" API errors get a plain message.
