# Accuracy evaluation, November 2026

Plan (Mickey's doc): "Accuracy Evaluation Plan" on claude.ai. Four batches, each run by several arms, scored against
the hand dataset (P1), the Exoplanet Archive (E1) and a validated model standard (all batches).

| File | What it is |
|---|---|
| `make_subsets.py` | copies the prebiotic batches P1 (60), P2 (16), P3 (10) into `Paper Files/Accuracy Test 2026-11/` |
| `make_exoplanet_subset.py` | E1: 30 discovery papers sampled by detection method (seed 20261120) + Teng 2023 + Nielsen 2019; saves each paper's archive parameter sets |
| `batches.json` | batch -> paper key -> its PDF / arXiv id, hand-dataset id, archive reference |
| `score.py` | the scorer (docstring: what is compared and how) |
| `arms.json` | which queue folders are which arm (filled as the runs are made); `python score.py arms.json` |
| `arms_test.json`, `results_test/` | Phase 0 check: the study's curated queue rebuilt on 2026-11-20 against the hand data, and against its 11-17 queue as a stand-in model standard (same answers: 1.0) |
| `arms_v3check.json`, `results_test_v3check/` | Phase 0 check: the hand scores reproduce `evaluate_v3.py` exactly (46 papers, every count) |

Run from the repository root with the project venv: `PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 ../.venv/bin/python eval/accuracy_2026-11/score.py eval/accuracy_2026-11/arms.json`.
