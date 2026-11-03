# Haiku vs Sonnet for the prebiotic chemistry pack (2026-11-03)

Question (Mickey): can the cheaper Haiku model take over some of the parsing steps that use Sonnet, possibly
with several passes and a vote, without losing accuracy?

## Method

- Five papers with recorded Sonnet reference runs (`runs/reference/`): eder1994, faisal2005, kim2017, kim2019,
  truman2024. One live run per paper and configuration, Standard pricing, no batch mode, online lookups off.
- Configurations (page-1 metadata is Haiku in all of them; figure suggestions were not tested):
  - **S** -- current: Sonnet for the structure plan, chemistry and conditions (incl. wet-dry).
  - **Hext** -- Sonnet structure plan, Haiku chemistry + conditions.
  - **Hall** -- Haiku for every step.
  - x1 / x2 / x3: passes of the chemistry and conditions steps, combined by vote (`voting.py`); the structure
    plan always runs once.
- Accuracy: the share of the reference CSV's filled cells (identifiers, metadata and provenance left out)
  reproduced -- numbers within 1%, text equal; for free-text columns whose wording varies even between Sonnet
  runs (analysis method, vessel, solvent, gas, solid name, cited reference) only filled-vs-empty counts.
- Cost: as a fresh run would pay. Runs of the same paper ran back to back, so a run could read the cache the
  previous one left; each model's first cached read was re-priced as the cache write.
- Developer handoff mode could not be used: in handoff the answers are written by Claude Code, so it measures
  neither Haiku's accuracy nor its cost. 37 live runs, about $4.

## Results

| Config | eder1994 | faisal2005 | kim2017 | kim2019 | truman2024 | mean accuracy | mean cost / paper |
|---|---|---|---|---|---|---|---|
| S x1 (current) | 100% $0.249 | 100% $0.251 | 100% $0.147 | 93.8% $0.171 | 100% $0.149 | **98.8%** | **$0.193** |
| Hext x1 | 100% $0.113 | 95.7% $0.115 | 100% $0.073 | 100% $0.085 | 97.2% $0.072 | 98.6% | $0.092 |
| Hext x2 | 100% $0.124 | 100% $0.127 | 100% $0.082 | 86.1% $0.091 | 97.2% $0.078 | 96.7% | $0.100 |
| Hext x3 | 100% $0.137 | 100% $0.136 | 100% $0.086 | 89.9% $0.100 | 97.2% $0.084 | 97.4% | $0.109 |
| Hall x1 | 100% $0.016 | 95.3% $0.017 | 100% $0.010 | 89.9% $0.012 | 97.2% $0.010 | 96.5% | $0.013 |
| Hall x2 | 100% $0.028 | 100% $0.030 | 100% $0.016 | 78.8% $0.019 | 97.2% $0.018 | 95.2% | $0.022 |
| Hall x3 | 100% $0.038 | 100% $0.038 | 100% $0.026 | 96.2% $0.029 | 97.2% $0.024 | **98.7%** | **$0.031** |

Relative to the current setup: Hext x1 costs about half (0.48x) for -0.2 points; Hall x1 about a fifteenth
(0.07x) for -2.3 points; Hall x3 about a sixth (0.16x) at the same mean accuracy.

## What the misses were

- **truman2024, NaCl 0.25 M (4 rows), every Haiku configuration.** The concentration is stated once in the
  running text, away from Table 1; Sonnet links it to the table's experiments, Haiku never did (8 of 8 runs).
  More passes can't fix a miss every pass makes.
- **kim2019 (the hardest paper here).** Its 1:2 and 1:3 ratio sets use a different nucleobase volume, so the
  summed solvent volume and the CaCl2 mixture concentration (calculated from the volumes) depend on per-set
  volumes the passes don't agree on; one Haiku structure plan also typed 10 rows' sets differently. Sonnet's
  only miss is the reference's "Eppendorf tube" as vessel material (not a material the paper states).
- **faisal2005, single Haiku pass:** the Gly-Gly 30 mM stock concentration (Hall x1, the known Economy gap) or
  the headspace gas (Hext x1); both recovered with 2-3 passes.
- **eder1994 and kim2017:** 100% in every configuration.

## Fixed during the evaluation (all configurations benefit)

- **Votes over passes named one solution twice.** Passes call the same solution differently ("calcium chloride
  solution" / "CaCl2 stock"); the vote per name kept both, so the mixing calculation saw 16 uL of CaCl2 and
  refused. The combined solutions now come from one pass (the list most passes agree on) and stock values point
  at it. Before the fix kim2017 x2/x3 lost CaCl2 on every row; after, 100%. This also affected the existing
  Economy + passes option.
- **Haiku's conditions answer failed validation (kim2017, 2 of 2 single-pass runs):** it wrote the open-ended
  `other` items like parameter values (a number plus unit / text field). Those are now read as the text they
  stand for instead of failing the step.

## Reading the numbers

- The structure plan is most of the remaining cost once extraction is on Haiku (about $0.05-0.08 of Hext's
  $0.09), so Haiku for the structure plan is where Hall's large saving comes from; its accuracy cost here was
  one mis-typed set group (kim2019, one run).
- One run per configuration: differences of a few points between configurations on one paper are within
  run-to-run variance (kim2019's x2 vs x3, for example). The pattern across papers is more reliable than any
  single cell.
- Accuracy is measured against Sonnet references, so it can only show where Haiku differs from Sonnet, not
  where both are wrong.
