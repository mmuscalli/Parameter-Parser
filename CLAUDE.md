# extraction_pipeline — context for Claude

Read this first in any new session before touching code here. It's written
for you (the agent), not for Mickey — human-facing docs are in README.md;
**all code lives under `src/parameter_extractor/` since Phase 2 (2026-10-13)** --
module paths below like `ingestion/pdf_parser.py` are relative to it;
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

Scope (Mickey, 2026-10-12): parse a paper the USER has already selected and
pull out metadata, experimental methodology, and reported solution
chemistry. Paper selection is the user's job, so triage is NOT a gate in
`pipeline.py` -- its criteria were Mickey's own dataset scope. It's kept as
an optional screening tool (`main.py --triage-only`) for bulk-filtering
candidates later; don't wire it back in as a gate.

## Status as of 2026-10-12 — read before assuming anything works end-to-end

- **First live run done (2026-10-12, Mickey's Mac):** `main.py` on eder1994
  runs end to end in ~2 min (~81K input / ~22K output tokens) and writes
  `runs/eder1994_auto/` (the PDF was copied as `eder1994_auto.pdf` so it
  wouldn't overwrite the manual demo). Against `runs/eder1994/`: 42/42 rows
  identical on composition, temperatures, both yields and set_type. (The
  auto run initially disagreed on set 001013 -- Table 2's unlabelled
  "2.50 mol dm-3, 87 C" block. Mickey confirmed it's Ca2+, as the auto run
  read it; the manual demo had mis-transcribed it as Ba2+ and was corrected
  in place, with a `corrections` note in the affected `*.provenance.json`.)
- **Local setup that works:** project venv one level up (`../.venv`), with
  this package installed editable (`pip install -e .`, gives the
  `parameter-extract` command; `python main.py` also works without installing).
  Dependencies are declared in `pyproject.toml` (requirements.txt removed).
  **Poppler is no longer used** (Phase 2): PDF text via pdfplumber, page
  renders via pypdfium2. The conda `poppler` env and Homebrew poppler on
  Mickey's Mac are leftovers, not needed.
- **API integration notes:** `api_client.py` uses native structured outputs
  (`client.messages.stream(output_format=Model)`), not forced tool use --
  current models 400 on `tool_choice` "tool"/"any". Consequence: schemas
  sent to the model can't contain free-form dicts (they become always-empty
  objects), hence `Methodology.per_set_overrides` is a list. Streaming +
  `MAX_TOKENS = 64000` because eder1994's chemistry output alone overflowed
  16K.
- **Flags and confidence (added 2026-10-12):** `plausibility_flags.json` is
  `{"paper_level": [...], "rows": {full_id: [...]}}`. Paper-level covers
  paper-wide methodology fields, initial compositions, and "ambiguous
  paper-wide" species (given with no set_label AND for specific sets -- left
  out of the CSV rather than copied onto every row; this happened with NaCl
  in `runs/eder1994_check/`, model run-to-run variance). Thresholds:
  `settings.CONFIDENCE_FLAG_BELOW = "high"` (flag), `CONFIDENCE_DROP_BELOW =
  None` (blanking off by default -- Mickey's choice to turn on). Model
  confidence is self-reported and was "high" even on the mislabelled NaCl,
  so keep structural checks alongside it.
- The one demo (`runs/eder1994/`) was produced by Claude manually acting as
  the model — reading eder1994.pdf, filling in the exact same Pydantic
  schemas a real call would return — because no key was available. Every
  file from that run is tagged `"model": "manual-claude-demo"` in a sibling
  `*.provenance.json`. Do not treat those as a real pipeline run when judging
  whether stages/* actually works; they only validate the schemas/prompts
  are reasonable, not that the API integration is correct.
- New environment: `cp config/.env.example config/.env` and add the key
  (gitignored; `config/settings.py` loads it itself, no VS Code env-file
  injection needed).
- Validation against a curated answer set is OFF on purpose
  (`config/settings.py: USE_GOLD_STANDARD = False`,
  `validation/gold_standard_eval.py: ENABLED = False`) — Mickey is building
  that curated subset separately. Don't turn it on without checking with him
  first; `eval/gold_standard/` is empty by design, not an oversight.

## Goal: standalone public desktop app (decided 2026-10-12)

Mickey wants a standalone app with a simple GUI: a user picks a PDF, enters
an API key, and the parsing runs semi-automatically. Decisions: **public
release**, **native desktop window** (plan: PySide6 -- LGPL, unlike PyQt's
GPL), **drop poppler** for the pure-Python pdfplumber/pypdfium2 (verify on
eder1994 first). Phases: (1) core as a library -- DONE; (2) pure-Python
PDF engine + src/ package layout + pyproject -- DONE 2026-10-13 (live
eder1994 run without poppler: 42/42 rows vs reference, ~8% fewer input
tokens; wheel installed into a fresh venv reproduces the committed CSV
from outside the repo), both on branch `app-structure`;
(3) GUI + packaging (keychain for keys, show token usage, tell users PDFs
are sent to Anthropic; pick a project license before release).

Phase 1 architecture -- keep front ends thin over this:
- `pipeline.run_pipeline(pdf, RunConfig, on_progress, cancel_event) ->
  RunResult` (and `run_triage_only`). No prints; progress via
  `run_context.ProgressEvent`; cancellation checked between stages.
- `config/run_config.RunConfig` carries the key/models/thresholds/output
  dir explicitly; `config/settings.py` + `.env` are only CLI defaults. Don't
  read settings.ANTHROPIC_API_KEY anywhere else.
- `run_context.RunContext` is passed to every stage (config, run_dir,
  client, token usage log).
- `errors.py`: every user-facing failure is a `PipelineError` subclass
  with a plain-language message; `api_client` maps SDK exceptions to them.
- Each run writes `<output_dir>/<pdf stem>_<YYYYmmdd-HHMMSS>/` (never
  overwrites) incl. `run_summary.json` (config minus key, token usage).
- Flags are `validation.plausibility_checks.Flag` objects (kind/message/
  quote/source).
- `tests/test_pipeline_offline.py` replays `runs/eder1994_auto/` responses
  through the real pipeline (patches `api_client._send`) and must reproduce
  the committed CSV byte for byte -- run it after any refactor (~4 s, free).

Phase 3 (started 2026-10-13, branch `app-structure`): `gui/` = PySide6
window over run_pipeline() -- `main_window.py`, `worker.py` (QThread +
signals, cancel via threading.Event), `key_store.py` (keyring; fails soft),
`app.py` (`parameter-extractor-gui`). Optional extra `.[gui]` =
**PySide6-Essentials** pinned `>=6.11,<6.12` (6.12.0 was 5 days old; the
full PySide6 package adds ~1 GB of unused Qt modules). QSettings holds
non-secret prefs only. Live run through the window: 42/42 vs reference.
**Testing gotcha:** never use `QTest.qWait` to wait for the worker -- it
holds the GIL and the worker thread never runs (looks like a hang in
`import pdfplumber`). `tests/test_gui_offline.py` pumps with
processEvents()+time.sleep; set GUI_SCREENSHOT_DIR to save PNGs of each tab.
Next: packaging (.app/.exe, e.g. PyInstaller or Briefcase), app icon,
maybe a settings dialog (models, thresholds).

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
- **CrossRef (`ingestion/crossref_lookup.py`) WORKS from Mickey's local
  machine (verified 2026-10-12: eder1994 -> 10.1039/dt9940001125, title
  similarity 0.98, score 102.6) -- the block below was sandbox-only.** It
  isn't called from `pipeline.py` yet. Original note:
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

1. DONE 2026-10-12 (see Status). Was: add a real API key and run `main.py` on eder1994.pdf; diff the result
   against `runs/eder1994/eder1994_extracted.csv` (the manual version) to
   see how close the automated pipeline gets.
2. DONE 2026-10-12 -- CrossRef works locally; next is wiring it into the
   metadata stage when the paper has no printed DOI.
3. Wait on Mickey's curated gold-standard paper subset before touching
   `validation/gold_standard_eval.py`.
4. Figure/scatter-plot digitization is explicitly out of scope so far — a
   real gap (Figs. 1-5 in eder1994 are richer than Tables 1-2 alone), not
   forgotten, just sequenced after the text/table path is trusted.
