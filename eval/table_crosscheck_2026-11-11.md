# F3 prototype: a free second reading of table values (2026-11-11)

Question (review suggestion F3): can the app compare each value a model read from a table with the same cell read
locally -- from the PDF's text layer or the arXiv HTML text -- and flag the cells that disagree, with few false alarms?
No model requests; the prototype reads finished run folders. Tool: `scripts/table_crosscheck_proto.py`.

## How it checks

A step's answer names the table cell ("Table 3, row HD 4732 b, column e"). The prototype finds that row in a grid of
the second reading -- or the column, when the table is transposed (one object per column) -- and compares:
- **uncertainty mismatch**: the same number is in the row, with other ± values -> flagged (strong evidence);
- **value not in its row**: counted, not flagged (often a table without a usable grid, or a value from another
  table carrying the same row label);
- grids whose text layer lost decimal points or ran columns together ('312 08') are skipped, never flagged.

## Results

Exoplanets: teng2023, second reading = arXiv HTML text (the paper's own LaTeX tables). Ground truth = the NASA
Exoplanet Archive comparison of each run (adopted rows).

| Run | Values located | Flagged | Known-wrong flagged | Known-right flagged |
|---|---|---|---|---|
| qwen3.8:27b, priming (e1_teng) | 498 / 606 | 29 | **17 / 17** | 3 / 195 |
| qwen3.8:27b, modes run | 481 / 607 | 24 | 11 / 11 | 4 / 192 |
| qwen3.8:27b, sample run | 452 / 582 | 49 | 11 / 14 | 4 / 186 |
| qwen3.8:27b, thinking off | 490 / 616 | 20 | 15 / 16 | 5 / 197 |
| Claude Sonnet (teng2023_auto) | 204 / 516 * | 0 | — | 0 / 202 |

Across the four local runs: **54 of 58 known errors flagged (93%)**, 16 of 770 known-right values flagged (2%). The
"known-right" flags looked like real misreadings too (the archive comparison accepts an uncertainty within 20%: e.g.
HD 4732 b ω read +0.193, table +0.169), as did the flags the archive can't judge (75 Cet log g read +0.04, table +0.03).
(*) the Claude run is in the older answer format, whose sources name only the table, so fewer rows are located.

PDF text layer for teng2023: unusable -- the landscape Table 3 loses its decimal points; detected and skipped (0 flags).

Prebiotic: chemistry table values, second reading = the PDF text layer (Claude reference runs; only plain values,
so only "value in its row" can be checked; recall from synthetic errors: the value replaced by another row's).

| Reference | Values from table cells | Located | False alarms | Synthetic wrong-row errors caught |
|---|---|---|---|---|
| kim2017 | 20 | 20 | 0 | 20 / 20 |
| truman2024 | 64 | 64 | 0 | 51 / 64 |
| faisal2005 | — | its table (landscape page) not read | — | — |
| kim2019 | 0 (values from the text) | — | — | — |
| eder1994 | scanned: no text layer | — | — | — |

## What it shows

- Where a clean second reading exists, it catches nearly all misread uncertainties with very few false alarms, at no
  cost: exactly the errors issue 12 of docs/local_model_notes.md describes (dense tables), and the hardest for a
  reviewer to spot.
- The weak spot is coverage: the tables models misread most (dense, landscape) are often the ones whose PDF text
  layer is unusable; the arXiv text covers them, but only for papers on arXiv (and it is the preprint: a published
  version may differ -- a flag would have to say which reading it compared with).
- Layouts not handled yet: one parameter per row with the object in a column header (nielsen2019's EXOFAST table:
  0 of 27 located); tables on landscape pages the table finder doesn't hand over (faisal2005).

## Recommendation

Worth building as a flag group ("Table values to check: a second reading disagrees"), grouped per table, both readings
in the text: arXiv text when the paper is on arXiv (the app already resolves and caches it), else the PDF text layer.
Never changing a value -- flags only. Open choices for Mickey: whether to fetch the arXiv text for every PDF run that
has an arXiv version (a network request per paper, cached), and whether the "value not in its row" tier should
become a flag too (more recall, more noise).
