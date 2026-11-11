# extraction_pipeline: guide for agents

Read this before touching code here. It describes the current state, the rules that apply to every change and the
decisions that still hold. It is written for you, the agent; people read `README.md`. The full dated record of every
round (what was built, measured and decided, and why) is in `docs/history/` (index: `docs/history/README.md`, one
line per section). **Search it, don't read it whole** (about 240 KB): `grep -n KEYWORD docs/history/*.md`, then read
the section around the hit. Before redoing research or proposing an idea, search there; it was probably measured.

## What the project is

Parameter Extractor reads scientific papers the USER has chosen and extracts the experimental values they report into
dataset rows, with an LLM, for review by a person. It speeds up building a dataset by hand; it does not replace the
review (Mickey Muscalli, the owner and only developer). It started as a tool for the hand-built prebiotic
peptide-synthesis dataset one level up (`../PaperDataTemplate.xlsx`, 50 papers / 1,356 rows) and is now general:
**data packs** define research areas. Paper selection is the user's job; triage (`--triage-only`) is an optional
screening tool, never a gate in the pipeline.

Front ends: a PySide6 window (`parameter-extractor-gui`), a command line (`parameter-extract`), and PyInstaller
builds for macOS (unsigned; signing, notarization and the Windows build are deferred by Mickey; don't start them).
Version: `parameter_extractor.__version__` (0.3.0, tag `v0.3.0`), the one place it is set.

## Map of the code (`src/parameter_extractor/`, ~36K lines)

- `pipeline.py`: the library entry points. `run_pipeline(pdf_or_id, RunConfig, on_progress, cancel_event)` =
  `extract` (= `read_paper`, local: parse, table images, figures, equations; then `extract_steps`, the model
  requests: row plan [+ paper details], then the other steps in parallel) + `finish` (local: rows, calculations,
  review of new variables, flags, files). The GUI calls `extract` and `finish` itself so figures can be digitized
  in between. No prints: progress via `run_context.ProgressEvent`, cancellation checked between steps.
- `config/run_config.py` `RunConfig`: everything one run needs (key, models, pack, options), passed explicitly.
  `config/settings.py` + `config/.env` are CLI defaults only; never read `settings.ANTHROPIC_API_KEY` elsewhere.
- `run_context.py` (per run: config, run folder, client, usage), `errors.py` (every user-facing failure is a
  `PipelineError` subclass with a plain message), `api_client.py` (the only place that talks to Anthropic:
  `call_structured`, caching, batch mode, retries; local servers via `local_models.py`; developer handoff via
  `handoff.py`).
- `stages/`: one module per built-in step; `stages/optional.py` runs **configurable steps** declared as JSON
  (`stages/specs`, pack and module `stages/*.json`); `stages/prompt_loader.py` assembles prompts (pack's own, else
  module's, else `prompts/`; slots `{{PACK_RULES}}`, `{{MODULE_RULES}}`, `{{RESEARCH_AREA}}`, ...).
- `schemas/`: pydantic answer formats (compact, short aliases), `prompts/`: shared prompts.
- `packs/` (`prebiotic_chemistry`, `exoplanets`, hidden `_template`; users' own in `<app data>/packs/`) and
  `modules/` (shared parts linked by reference: analysis, solution_chemistry, kinetics, wet_dry, peptides_oligomers,
  mineral_surfaces, impact_shock, heat_flow_chamber, flow_reactor, fluid_inclusions; `modules/README.md`).
  Loader `packs/__init__.py` (merged manifest = pack + linked modules + `module_settings.py`).
- `ingestion/`: PDF parsing (`pdf_parser.py`: pdfplumber text, pypdfium2 renders; no poppler), table / figure /
  equation finders, supplements, arXiv and CrossRef sources, rows (`flatten_to_template.py`, `figure_rows.py`),
  `normalize.py`, `new_variables.py`, `observations.py`. `calculators/`: local calculations (mixing, amounts, totals,
  exoplanet masses, ...). `validation/`: plausibility flags, quote checks, exoplanet archive check, gold standard (off).
- Shared logic at the top level: `units.py`, `names.py` (species matching), `registry.py` (columns, synonyms,
  compounds per data pack), `column_order.py`, `value_types.py`, `variable_categories.py`, `formulas.py`, `voting.py`
  (passes), `scopes.py`, `compound_names.py`, `pubchem.py`, `pricing.py`.
- Multi-paper: `paper_queue.py` (full extraction queue), `focused_search.py` (a few values across many papers).
  Earlier runs: `run_folder.py` (a run folder read back into a RunResult: File > Open a results folder…),
  `resume.py` (resume / rebuild from a run's or queue's saved answers into a NEW folder; CLI --resume / --rebuild).
  Pack authoring: `pack_editing.py` (+ `check`), `pack_drafting.py`, `compound_setup.py`, `conventions.py`,
  `pack_modules.py`, `module_drafting.py`, `pack_overview.py`.
- `gui/`: `main_window.py` (five numbered steps: data pack, papers, what to extract, options, run; results tabs),
  `multi_runs.py`, `digitizer.py` + `figure_dialog.py`, `variable_review.py`, `registry_dialog.py`,
  `pack_windows.py` / `packs_window.py` / `pack_assist.py`, `settings_dialog.py` (keys, folder, lookups),
  `models_window.py` (Models menu: profiles and connections).
- `model_profiles.py`: model profiles (a connection + a model per role + output cap, temperature, caching, steps at
  once, retries, prices) and connections (Anthropic API; Ollama / OpenAI-compatible servers, local or hosted) in
  `<app data>/model_profiles.json`; `apply(config, profile_id)` sets RunConfig (`profile_roles`, `temperature`,
  `max_parallel_stages`, `max_retries`, `prices`, or provider "local" + `local` for a server).
- `diagnostics.py`: `--self-check` (free; verifies an install or a built app).

## Rules for every change

- **Tests.** `PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 ../.venv/bin/python scripts/run_tests.py` from the repository root
  (~2 min; each `tests/test_*.py` in its own process; no pytest). Gate: "0 failed, 0 skipped". A SKIP is a failure
  (usually a paper's PDF not found after papers were moved). Failing files' output: `tests/.last_failures.log`.
- **Test isolation.** Every test file starts with `import _isolation` (empty data folder via
  `PARAMETER_EXTRACTOR_DATA_DIR`, keychain off, QSettings in a temp ini), uses temp folders only, and takes facts
  about the app's packs from `tests/pack_facts.py` instead of listing their steps or columns. After changing tests
  that touch packs, or the app's packs themselves: `python scripts/check_test_robustness.py` (~6 min).
- **Replays stay byte-identical.** Recorded answers in `runs/reference/<name>/` (eder1994, faisal2005, kim2017,
  kim2019, truman2024, aa57186-25_arxiv) and the older `runs/*_auto/` fixtures are replayed through the real
  pipeline and must reproduce their expected CSVs exactly. A deliberate output change: regenerate by replay with a
  checker proving only the intended cells changed (back up `runs/` first; `scripts/backup_runs.py`).
  `scripts/record_reference.py` records a new reference. Replays don't see requests, so:
- **Requests to Claude must not change by accident.** Prompts and schemas are tuned and measured; a change meant for
  local models must leave Claude's requests identical (there are tests for it).
- **Run folders are an interface**: every run writes `run_config.json` (paper + settings) first, every audit a
  `request_fingerprint`, a queue its `queue.json`; resume / rebuild and Open a results folder read them. Keep them
  (and the files `run_folder.load_result` reads) when changing what a run writes; a run never writes into another
  run's folder.
- **GUI tests**: pump with `processEvents()` + `time.sleep`; never `QTest.qWait` (holds the GIL; the worker never
  runs). Check drawing natively too, not only offscreen. No window opens the next one from its own handlers (it
  records what comes next and closes; the opener opens it): `tests/test_window_chains.py`. Lists of settings use
  `gui/widgets.style_rows`.
- **Schemas sent to the model**: flat, few `Optional`s (grammar size limit: "compiled grammar is too large"), every
  field required in the sent schema (`optional.ALL_REQUIRED`, `_required`) with Python defaults kept so old
  recordings load. Count with `json.dumps(transform_schema(Model)).count("anyOf")`. `count_tokens` is free; use it
  for audits.
- **Live runs cost money** ($0.01–0.30 a paper, up to ~$1.85 for teng2023 on Standard). Local runs need Mickey's PC
  (Ollama at `http://192.168.1.129:11434`; `parameter-extract --list-local-models`; LAN only, no authentication;
  don't expose it). Ask Mickey before either, with a cost or time estimate.
- **Keys**: only in `RunConfig` and the keychain (`gui/key_store.py`); never in files or logs.
  `PARAMETER_EXTRACTOR_NO_KEYCHAIN=1` in tests and ad-hoc scripts (reading the keychain from the venv prompts).
- **`runs/` is local, never pushed** (audits hold the papers' text). Back it up with `scripts/backup_runs.py`.
- **After a round of code changes:** build both apps (`packaging/build_macos.sh`, `packaging/build_macos.sh --dev`),
  run each with `--self-check` (`env -i HOME=$HOME ".../Contents/MacOS/Parameter Extractor" --self-check`), write
  the round up (below), commit and push. A docs-only change needs no build.
- **Writing a round up:** append a dated section (`## Title (YYYY-MM-DD, Mickey: why)`) to the current month's
  `docs/history/YYYY-MM.md` (a new month starts a new file) and add its line to `docs/history/README.md`. Change
  THIS file only where a current fact, rule or decision changed; keep it short.

## Decisions that still hold (Mickey's)

Search `docs/history/` for the details and the measurements behind each.

- **Wording**: the user-facing term is "data pack" (code and prompts keep "pack" / "research area"). A *step* is one
  model request per paper (built-in = code; configurable = JSON spec; the code still says "stage"); a *calculation*
  is local and free; a *module* is shared and linked by reference, never copied (`pack_modules.migrate_copies`).
- **Defaults**: the Standard profile (Sonnet 5.5; paper details on Haiku) stays the default. Profiles: standard,
  balanced (Sonnet plans, Haiku extracts; not for exoplanets), economy (Haiku; figure suggestions and equations
  stay on Sonnet). Passes 1–3 with a vote. Pressure unit: bar. The built-ins can be changed in the Models window
  (asks first; stored as changes; Reset): an UNCHANGED built-in must send exactly the requests it always did
  (`profile_roles` empty -> the old `model_for` path; tests/test_model_profiles.py compares the built requests).
- **Review before writing**: a value for a column outside the pack's vocabulary (new variable, new compound of any
  type) is written only after the user accepts it once (remembered in the registry). Vocabulary-defined columns
  (the pack's, its modules', analysis vocabulary) are written directly. Assumed values are flagged and offered,
  never included automatically, never remembered.
- **Flags**: over-flag rather than under-flag; cut noise by grouping or rewording, never by dropping.
- **Columns**: `PaperDataTemplate.xlsx` is frozen (never edited). The prebiotic pack uses its own trimmed copy
  (`template_vocab.json`, generated from the xlsx). One column format for every compound:
  `<role>_<name>_<phase>_<measure>` (`initial_Gly_aq_mM`, `sampled_Gly-Gly_aq_%yield`, `sampled_(Gly)4_aq_mM`,
  `sampled_4mer_A_aq_mM`); old names convert (`flatten_to_template.current_column_name`). Analysis columns
  `analysis_<technique>_<setting>[_range][_<unit>]`. Ranges `low:high` in `_range_` columns; averages `_avg`.
  Dataset columns are ordered by variable category (`column_order.py`), all of a pack's columns written.
- **Rows**: set = an experiment condition / host star, sample = a time point / planet (pack words in `units`).
  Rows come from tables, digitized figures, and text or captions that give complete conditions; a review's
  reproduced data are rows marked with their source (`original_data_reference`, `cited_data` flags). Exoplanets:
  one row per (planet, fit solution); every posterior mode and estimate by another method is kept.
- **Units**: an explicit table (`units.py`, no pint), never guess: ranges, lost exponents ("10-4 M"), unknown units
  are refused and flagged. A plain "u" reads as µ where the µ form is known; lower-case "um" / "mm" / "nm" are read
  as molar or metre by the column they go into. Astronomy has its own table ("m" is molar in chemistry).
- **Names**: species matching is exact rules + synonym tables, never fuzzy. PubChem (exact CID matches, codes only
  when corroborated) only for names the rules don't match; `names.AMBIGUOUS` (TMP, p2A, ...) never matched.
- **Ambient**: "ambient / room temperature" = 25 °C, "ambient / atmospheric pressure" = 1 bar; a sealed batch with no
  stated pressure starts at 1 bar (flagged). Bare "water" = distilled water (flagged).
- **Validation against a curated answer set is OFF** (`settings.USE_GOLD_STANDARD`, `gold_standard_eval.ENABLED`);
  Mickey is building the set. Don't turn it on; `eval/gold_standard/` is empty by design.
- **Deep calculators** (ionic strength, pKa, WORM) are not reimplemented; they exist in R in `../Calculators/`, and
  their columns were removed from the prebiotic pack on 2026-10-22.
- **Developer handoff** (`handoff.py`: Claude Code answers the requests) only with `PARAMETER_EXTRACTOR_DEV=1` or the
  Dev build; excluded from the public build (claude.ai login can't be offered by third-party apps). Handoff answers
  are Claude Code's, so they can't evaluate a model.
- **Local models**: unvalidated, every run flagged. Servers and profiles in the Models window
  (`model_profiles.json`; the old `local_models.json` is brought over once as the connection "Local server"); a
  server's key is in the keychain (account `model-connection:<id>`, the migrated one keeps `local-model-server`).
  A hosted server without prices shows its cost as unknown, a private one as $0. Enter the context
  length that fits on the GPU, not the model's reported maximum. `local_models.LOCAL_REQUIRED` makes fields local
  models skip (`txt`, `sample`, `mode`, `meth`) required for local servers only. Pain points and the checklist for a
  new model: `docs/local_model_notes.md`; test tool `scripts/check_local_model.py`.

## Already measured and decided: don't propose again

| Idea | Result | Where |
|---|---|---|
| Table grids (cells read locally, the model maps them) | +6% cost, no accuracy gain; off (`RunConfig.table_grids`) | `eval/table_grids_2026-11-07.md` |
| Pre-parse switching off parameters a paper lacks | −3% cost, accuracy 97.5% → 89.7%; not wired in | `eval/preparse_2026-11-08.md` |
| Figure suggestions on the cached paper | costs more from the 2nd figure on; off | history 2026-11-03 |
| Pooling one paper's parallel steps into one batch | slower than one-request batches | history 2026-10-27 |
| Balanced profile for exoplanets | worse than Economy on cost and matches | history 2026-10-22 |
| Shared cached step instructions for single papers | +6% for one paper; on only in queues | `eval/shared_instructions_2026-11-07.md` |
| Trigger thresholds beyond `min_hits` | a false trigger ~$0.01, a miss loses values | `eval/organics_heldout_2026-11-09.md` |
| pix2tex / pix2text for equations | inaccurate, or 1.8 GB of dependencies | history 2026-10-15 |
| compact text for prebiotic; caching the plan as 2nd breakpoint | 1–3% / < 2% | history 2026-10-27 |
| TypeSafe's Jev for extraction | text-only, no free-form strings | history 2026-10-22 |

Open suggestions from the 2026-11-11 review (resume / rebuild, corrections in the window, opening old runs, cost
estimates, local-model speed-ups, ...) and their status: `docs/improvement_suggestions_for_agent.md`.

## Environment

- Project venv one level up: `../.venv` (package installed editable, `pip install -e ".[gui,build]"`).
  PySide6-Essentials pinned `>=6.11,<6.12`; PyInstaller 6.22.3. numpy is a dependency (not excluded in the spec);
  pandas is excluded; scipy is not used.
- Papers: `../Paper Files/` (PDFs, never in the repository). Reference runs and fixtures: `runs/` (local).
- User data (packs, modules, registry, caches, local model settings): `~/Library/Application Support/Parameter
  Extractor/`; `PARAMETER_EXTRACTOR_DATA_DIR` replaces it (tests).
- Keychain across rebuilds: builds are re-signed with the local identity from `packaging/make_signing_identity.sh`
  when present, so "Always Allow" survives a rebuild.
- Branches: `main` (on GitHub since 2026-11-11) and `flexible-variables`, both at the same commit; keep them
  together until Mickey retires `flexible-variables`. Tags: `v0.2-figure-digitizer`,
  `backup/flexible-variables-before-public`, `v0.3.0`. Tag a state whenever both apps are built for use.
- Backups: full project archive `../Backups/EORE_Data_Project_FULL_BACKUP_20261012_030042.tar` (before this
  pipeline); dated `runs/` archives from `scripts/backup_runs.py` in `../Backups/`.
