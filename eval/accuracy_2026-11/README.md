# Accuracy evaluation, November 2026

Plan (Mickey's doc): "Accuracy Evaluation Plan" on claude.ai. Four batches, each run by several arms, scored against
the hand dataset (P1), the Exoplanet Archive (E1) and a validated model standard (all batches).

| File | What it is |
|---|---|
| `REPORT.md` | the final write-up: what was run, results per batch and arm, findings, app findings, limits |
| `make_subsets.py` | copies the prebiotic batches P1 (60), P2 (16), P3 (10) into `Paper Files/Accuracy Test 2026-11/` |
| `make_exoplanet_subset.py` | E1: 30 discovery papers sampled by detection method (seed 20261120) + Teng 2023 + Nielsen 2019; saves each paper's archive parameter sets |
| `batches.json` | batch -> paper key -> its PDF / arXiv id, hand-dataset id, archive reference |
| `score.py` | the scorer (docstring: what is compared and how). Beyond evaluate_v3: names that mean the same compound match (silica = SiO2, argon = Ar), and two-letter names ('Ar', 'N2') are compared at all -- the study's word matcher skipped them |
| `make_draft_samples.py`, `drafts.json` | Phase 1: the papers each drafted pack was made from; `model_standard` lists the standard's papers |
| `redraft_from_saved.py` | a drafted pack written again from its saved surveys and design (nothing asked) |
| `inspect_misses.py` | one paper's printed hand values a run misses, next to the run's values (validation) |
| `arms_mscheck.json`, `results_mscheck/` | Phase 2: the 12 P1 model-standard runs scored as an arm against the hand data (0.858) |
| `arms.json` | which queue folders are which arm, and `model_standard`: the standard's run folders per batch (P1 12, P2 16, P3 10, E1 10 papers; Phases 2 and 5); `python score.py arms.json` |
| `arms_test.json`, `results_test/` | Phase 0 check: the study's curated queue rebuilt on 2026-11-20 against the hand data, and against its 11-17 queue as a stand-in model standard (same answers: 1.0) |
| `arms_v3check.json`, `results_test_v3check/` | Phase 0 check: the hand scores reproduce `evaluate_v3.py` exactly (46 papers, every count) |

Run from the repository root with the project venv: `PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 ../.venv/bin/python eval/accuracy_2026-11/score.py eval/accuracy_2026-11/arms.json`.
