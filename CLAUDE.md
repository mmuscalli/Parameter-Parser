# extraction_pipeline — context for Claude

Read this first in any new session before touching code here. It's written
for you (the agent), not for Mickey — human-facing docs are in README.md;
read that too for the file-by-file structure and usage instructions. This
file exists so a fresh session (VS Code, CLI, wherever) doesn't have to
re-derive decisions that were already made deliberately.

## What this project is

Early prototype for partially automating extraction of experimental
parameters from published prebiotic-peptide-synthesis papers into the row/
column shape of `../PaperDataTemplate.xlsx` (the hand-curated dataset one
level up). The original dataset (50 papers, 1,356 rows) was built entirely
by manual reading — this pipeline is an attempt to speed that up with an
LLM-based extraction pipeline, NOT to replace human review of the output.

## Status as of 2026-10 — read before assuming anything works end-to-end

- **No `ANTHROPIC_API_KEY` has ever been set in the environment this was
  built in.** `stages/*.py` (the actual API-calling code) has therefore
  NEVER been exercised live. It compiles, it's structurally sound, but treat
  it as unverified until you've run it for real.
- The one demo (`runs/eder1994/`) was produced by Claude manually acting as
  the model — reading eder1994.pdf, filling in the exact same Pydantic
  schemas a real call would return — because no key was available. Every
  file from that run is tagged `"model": "manual-claude-demo"` in a sibling
  `*.provenance.json`. Do not treat those as a real pipeline run when judging
  whether stages/* actually works; they only validate the schemas/prompts
  are reasonable, not that the API integration is correct.
- First real thing to do in a new environment with a key: `cp
  config/.env.example config/.env`, add the key, run `python main.py --pdf
  "<some PDF>"` on eder1994.pdf first (ground truth already worked out by
  hand, in `runs/eder1994/`, to compare against) before trying a new paper.
- Validation against a curated answer set is OFF on purpose
  (`config/settings.py: USE_GOLD_STANDARD = False`,
  `validation/gold_standard_eval.py: ENABLED = False`) — Mickey is building
  that curated subset separately. Don't turn it on without checking with him
  first; `eval/gold_standard/` is empty by design, not an oversight.

## Non-obvious decisions — don't redo this research

- **Schema shape is grounded in `../POLO_variable_mapping.csv`** (one level
  up, in EORE Data Project root), which classifies every PaperDataTemplate
  column as `direct` / `pattern_direct` / `no_analogue_calculated` /
  `no_analogue_gap` / etc. `pattern_direct` (176 of ~280 columns) is why
  chemistry extraction is a list of `{name, concentration}` pairs
  (`schemas/chemistry.py`) instead of ~150 separate fields — those columns
  are literally the same repeated ontology pattern, not distinct properties.
  Re-read that CSV before changing the chemistry schema.
- **`schemas/template_vocab.json` is generated, not hand-written** — built
  directly from `../PaperDataTemplate.xlsx`'s own header row. If the
  template's columns change, regenerate it (see the one-off script history
  in this conversation — not currently saved as its own script in the repo;
  worth promoting to a real `scripts/build_vocab.py` if it needs to run
  again).
- **Column naming in the real template is NOT uniform**: salts/ions use
  `<role>_<name>_aq_mM`, amino acids/peptides use `<role>_<name>_mM` (no
  `_aq_` infix). `ingestion/flatten_to_template.py:resolve_template_column()`
  handles both — if you add new species categories, check which pattern they
  actually use in the real header before assuming.
- **CrossRef (`ingestion/crossref_lookup.py`) has never been live-tested.**
  `api.crossref.org` was blocked by this account's sandboxed-session egress
  policy — confirmed via the proxy's own response body:
  `request blocked: no rule or allowlist entry allows host "api.crossref.org"`.
  This is almost certainly a sandboxed-cloud-session-specific restriction,
  NOT something that applies to a normal local machine's internet access —
  so it will very likely just work when run from VS Code / local Claude
  Code on Mickey's own machine, with no code changes. Worth confirming with
  a real call early in a local session, and reporting back whether it
  resolved the pattern of "sandboxed agent sessions can't reach arbitrary
  APIs, but a user's own local environment usually can."
- **Table pages are rasterized and shown to the model as images**
  (`ingestion/pdf_parser.py:find_table_pages` /
  `config.settings.RASTERIZE_TABLE_PAGES`), not just read as text, because
  eder1994's two-column tables genuinely garble row/column alignment in
  plain `pdftotext` output. Verified for real (no API key needed for this
  part) against eder1994.pdf.
- **Deep calculators (ionic strength, pKa deltas, WORM balance) are
  deliberately NOT reimplemented here** — they exist already, in R, in
  `../Calculators/`. `calculators/` in this project only has the two simple
  ones the eder1994 demo needed (unit conversion, peptide %yield<->mM). Wrap
  the existing R scripts (e.g. via `subprocess` + `Rscript`) when it's time
  to compute the derived fields — don't re-derive the math.

## A full backup exists

`../Backups/EORE_Data_Project_FULL_BACKUP_20261012_030042.tar` (724MB,
excludes `.venv`/`.ipynb_checkpoints`/`.Rproj.user`) was made before any of
this pipeline's work began, in case anything here needs to be rolled back.

## Immediate next steps (as of last session)

1. Add a real API key and run `main.py` on eder1994.pdf; diff the result
   against `runs/eder1994/eder1994_extracted.csv` (the manual version) to
   see how close the automated pipeline gets.
2. Re-test `ingestion/crossref_lookup.py` with real network access.
3. Wait on Mickey's curated gold-standard paper subset before touching
   `validation/gold_standard_eval.py`.
4. Figure/scatter-plot digitization is explicitly out of scope so far — a
   real gap (Figs. 1-5 in eder1994 are richer than Tables 1-2 alone), not
   forgotten, just sequenced after the text/table path is trusted.
