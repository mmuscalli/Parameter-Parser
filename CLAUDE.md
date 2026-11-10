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
  current models 400 on `tool_choice` "tool"/"any" (Sonnet 5.5 still does; with
  caching on, paper-reading steps use non-strict tools + "auto" -- see "Cost
  options"). Consequence: schemas
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
Packaging (2026-10-13): PyInstaller 6.22.3 + hooks-contrib 2026.7 (pinned,
`.[build]` extra); `packaging/parameter_extractor.spec`,
`packaging/build_macos.sh` -> `dist/Parameter Extractor.app` (~123 MB,
arm64) + .dmg (~59 MB). `--self-check` (diagnostics.py) verifies a bundle
for free -- all checks pass in the built app run with an empty environment.
pandas is excluded in the spec (pulled in optionally, dead weight 19 MB).
Unsigned (ad-hoc): public macOS release needs Mickey's Apple Developer ID +
notarization, and a real BUNDLE_ID -- his decision. Windows build untested.
**Deferred by Mickey (2026-10-13):** signing/notarization and the Windows
build wait until development has progressed further; until then the app
only needs to run on his own Mac. Don't start on them unprompted.
Main window (2026-10-23, Mickey): inputs (in a QScrollArea) and run controls + results tabs
sit in a vertical QSplitter `main_split`; the user drags the handle, position saved in
QSettings `main_split`; extra window height goes to the results.
Remaining ideas: settings dialog (models, thresholds), drop-PDF-on-Dock-icon
handling (Info.plist already declares PDFs).

## Figure digitizing (started 2026-10-14, branch `figure-digitizer`)

Mickey used PlotDigitizer by hand for the original dataset; this replicates
it in-app. Flow: `pipeline.extract()` (steps 1-5, also runs
`ingestion/figure_finder.find_figures`) -> GUI `FigureReviewDialog` (Skip /
Digitize per figure; `gui/digitizer.py` editor) -> `pipeline.finish(ex,
digitized, skipped)` -> `ingestion/figure_rows.build_figure_rows` appends one
set per series, one row per point (`extraction_confidence="digitized"`,
`extra` dict for non-field columns like initial_pH). `run_pipeline()` =
extract+finish with no figures (CLI unchanged; CSV byte-identical).
- **Finder**: column-aware ("Fig. N" captions match with whitespace removed
  -- eder1994's OCR letter-spaces "F i g . 2"); drops sideways text (the
  publisher watermark broke Fig. 5); a bare "Fig. 4" fragment (tail of a
  table caption) is rejected; area = above caption up to the nearest long
  body-text line. eder1994 is a SCAN (one image per page), so figures must
  be located from text, not embedded images. All 5 eder figures found.
- **Calibration** (`digitizing/calibration.py`): each axis read only from
  its own markers (perpendicular projection onto X1->X2 / Y1->Y2) -- handles
  rotated scans. Replaced (2026-10-15) an oblique-basis method that let a Y
  marker clicked a few px off the axis make x drift with vertical cursor
  moves (Mickey, truman2024). Dashed guide lines through each axis's markers
  show misplacement. Log axes in log10 space.
- **Suggestions** (`stages/figure_planner.py`, prompt `figure_planner.md`,
  model settings key `figure_planner`): only requested when the user picks
  Digitize, on a Python thread via `gui/figure_dialog.PlanBridge`; ~28K input
  tokens/figure (mostly paper text). Live-tested on eder Figs 1/3/5: correct
  series, markers, compositions, dual-axis detection, duplicate check.
- **CSV uses the template's names and order** (Mickey, 2026-10-14; since 2026-10-22 the
  pack's trimmed 208-column copy, not the 280-column xlsx -- see "Prebiotic pack brought to parity"):
  `write_csv` maps ExtractedRow fields via `FIELD_TO_TEMPLATE`
  (paper_doi->paper_DOI, headspace_gas->headspace_gas_name, *_pct_yield ->
  *_%yield; authors -> author1..7), writes ALL 280 template columns in
  template order (paste parity, Mickey's choice), then non-template columns
  (e.g. unrecognized species), then provenance columns. Python field names keep
  `_pct_yield` (no '%' in identifiers). The committed runs/*.csv were
  converted to this format.
- **Review runs alongside extraction** (Mickey's request): extract(...,
  on_figures=cb) hands over the partly filled Extraction right after parsing;
  `Extraction.structure_ready` gates plan_figure(); a failure sets it too
  (with `failure`) so waiters get a PipelineError. MainWindow builds the
  dataset when both the worker and the non-modal FigureReviewDialog are done
  (`_maybe_finish`); if the run fails, digitized work is still saved.
- **Planner context trimmed** to passages mentioning the figure
  (`figure_passages`): ~28K -> ~15K input tokens; Figs 1/5 suggestions
  unchanged, Fig 3 slightly worse (duplicated a series across its 2 axes).
- Digitizer UX (Mickey's feedback): pinch zoom (QNativeGestureEvent) and
  trackpad two-finger scroll pans; only the selected series is editable,
  "Show only the selected series" hides others; Shift+click adds on top.
  Region estimates can be well off -- accepted, users pan.

## Variables beyond PaperDataTemplate (started 2026-10-14, branch `flexible-variables`)

Restore point before this work: tag `v0.2-figure-digitizer` (= figure-digitizer
branch head). Mickey's decisions (see memory too): registry = bundled base +
local additions; PaperDataTemplate.xlsx is FROZEN (never edited by the app;
CSV export in its exact layout stays); a new variable must be ACCEPTED before
its values go in the CSV.
Plan: (1) open-ended capture + surfacing -- DONE; (3) registry + review
screen -- DONE early at Mickey's request (see below); (2) long-format
canonical record, CSV generated from it -- DONE (below); (4) name
normalization (PubChem/ChEBI) + units -- not yet.
Long format (2026-10-14): `ExtractedRow.provenance` (template column ->
`CellSource` origin/quote/source/confidence) is filled in build_rows,
figure_rows and write_values. `ingestion/observations.py`:
rows_to_observations (one per non-empty value; unit from column name via
`unit_for_column`, compound suffixes first) -> `<pdf>_observations.csv`;
the wide CSV is written from `observations_to_records` (pivot) -- still
byte-identical (replay test). GUI Rows tab tooltips show provenance.
eder1994: 948 observations, all with an origin.
Registry + review (2026-10-14): `registry.py` VariableRegistry = bundled
template columns + local JSON (`default_registry_path()`, app-data dir):
added columns + aliases ("kind:name" -> column; species alias names are
role-qualified, e.g. "initial RbCl", "sampled Foo %"). finish(...,
review=callback): registry-known values written directly; the rest grouped
(`new_variables.VariableGroup`) -> GUI `gui/variable_review.py` (default
Don't add; New column / Existing column; editable values; Remember) ->
`apply_decisions` + registry.save(). CLI: no review (nothing new added) but
uses the registry. RunConfig.registry_path=None means template only (tests).
Only explicit aliases auto-apply for parameters -- a model-suggested column
never writes without the user's acceptance once.
Focus terms: RunConfig.focus_terms / GUI "Parameters to look for" / CLI
--look-for -> optional `term_search` step (flat schema, explicit
found/not-found per term; missing terms padded as not found) -> findings
go to review; unfound -> `term_not_found` flags. Live on eder1994: reaction
volume 1 cm3 (vials, suggests solvent_volume_mL), recirculation time not
stated, stirring "without stirring".
Step 1 as built:
- `Methodology.other_parameters` (flat: name, value-as-text, set_label,
  quote, source, confidence) + prompt section (excludes dissolved species
  and analysis details). Live on eder1994: stirring none, sand-bath/reflux
  heating, foil-sealed condenser (sometimes also the 1 cm3 vial setup).
- `flatten_to_template.column_for_solute`: values go to the CSV only if
  their template column exists (no more `__UNRECOGNIZED_COLUMN` columns);
  any sampled %-yield with a template column is written (was only Gly2/3).
- `ingestion/new_variables.py` collects the rest (+ figure_rows returns
  held-out axis columns/species) -> `new_variables.json`, one
  `new_variable` flag per variable, own group atop the GUI Flags tab.
- **Structured-output grammar limit**: adding other_parameters made the API
  reject Methodology ("compiled grammar is too large"). Every Optional field
  adds a grammar alternative; fixed by making Extracted.quote/source/note
  plain `str` (default "", validator maps old nulls). Keep new schemas
  flat and avoid Optional where "" works; check
  `json.dumps(transform_schema(Model)).count("anyOf")` (Methodology: 21->6).

## Wet-dry cycling + cited data (2026-10-14, from the truman2024 test)

truman2024 (Journal of Creation review) reproduces wet-dry data from
Rodriguez-Garcia 2015 and Campbell 2019 -- the first non-curated test paper.
- Cited data: `PlannedSet.data_source` ('' = this paper's data) and
  `FigurePlan/DigitizedFigure.data_source` -> `ExtractedRow.original_data_reference`
  (optional provenance column, written only when filled) + `cited_data`
  flags (own group in the GUI Flags tab). Live: all 5 truman sets
  detected with full references incl. supplementary table numbers.
- Wet-dry: `PlannedSample.cycle_number` (-> template cycle_number); optional
  `wet_dry` stage (stages/wet_dry.py, flat schema) runs only if
  `has_cycling(structure)`; values -> cycle_duration_hr + app STANDARD
  columns (schemas/standard_columns.json, part of the bundled registry
  base, after the template block, only when filled). Mickey: original
  dataset only had initial temperature for wet-dry; extract phases if given.
- Bugs found: per-sample initial concentrations (fixed in build_rows AND
  the chemistry prompt -- it had said "sample_label null for initial";
  unlabelled differing values are now left out + `conflicting_values` flag
  rather than last-one-wins); per-set pH override dropped; caption case.
- Assumed values (Mickey: always flag, never include automatically, user
  decides): `Basis` = stated/derived/assumed (+ confidence, quote, source)
  on SetOverride and CycleParameter; prompts forbid assuming and treat the
  paper's hedges as not stated. "assumed" values are skipped by build_rows
  and become `NewVariable(kind="assumed_value")` in the review (default
  Don't add, excluded from "Add all as suggested", never remembered in the
  registry) + `assumed_value` flags. Low/medium per-set and cycling values
  are flagged. Registry.save() now only writes when something changed.
- Reference run `runs/truman2024_auto/` (2026-10-14, all fixes in): 11 rows
  (Table 2 as 4 single-row sets, Gly 0.1/1/10/100 mM), 8 cited_data flags,
  no assumed values (the model left the Table 2 temperature out).
  `tests/test_truman2024_replay.py` replays it byte for byte;
  `test_pipeline_offline.make_replay(dir)` replays any reference run.

## Units + name matching (2026-10-15)

- `units.py`: explicit unit table (no pint): parse_quantity("1 × 10-3 M"),
  convert(), to_column_unit(raw, unit, column_unit). Refuses ranges, OCR-lost
  exponents ("10–4 M"), unknown units, wrong dimensions -- never guesses.
  Column units come from observations.unit_for_column.
- `names.py`: match_species() = exact rules + generated synonyms (amino
  acids, oligomer names/notations -> "<n>peptide_<AA>" even beyond the vocab,
  named salts, ion charges "Ca2+" -> "Ca+2", hydrates, state suffixes).
  closest_names() is display-only ("Similar existing" in review).
- `ingestion/normalize.py` normalize_chemistry() runs at the start of finish():
  renames to canonical + recomputes mM (fills missing; corrects >1% model
  arithmetic errors with a `unit_conversion` flag); notes go into
  conversion_note -> provenance. Summary lists all changes.
- `new_variables.stored_value()` converts review/registry values to the
  column unit (provenance: "read from '1 cm3'"); unconvertible -> text +
  `unit_conversion` flag; the review window blocks building with them.

Digitizer text fields "Data reproduced from" and series "Notes" are
`gui/widgets.ExpandingLineEdit`: wrapped full-text tooltip + pop-out editor.

## Remembered-variables window (2026-10-15)

`gui/registry_dialog.py` (menu Variables -> Remembered variables…, disabled
during runs): tabs Added columns (rename/remove; remove also drops aliases
-> reviewed again), Synonyms (change column/remove), Built-in (read-only).
Works on a fresh VariableRegistry copy; writes only on Save. Registry JSON
now also stores `alias_labels` (original spelling) for display;
`display_name()` renders species aliases as "RbCl (starting concentration)".

## kim2019 round (2026-10-15): stock solutions, PubChem, cost

kim2019 (Astrobiology, ribonucleotides by dry-down; not peptides) is the third
reference run, `runs/kim2019_auto/` + `tests/test_kim2019_replay.py` (Mickey:
keep it for now, refresh after the open issues are sorted).
- PDF fixes: adaptive x_tolerance when words run together, mid-line/uppercase
  table captions, Symbol/Pi-font chars (µ drawn as "m" -> "5 mL" bug).
- **Stock vs mixture** (Mickey: record both; calculated values marked derived):
  `SoluteEntry.concentration_basis` ("mixture"/"stock") + `stock_solution`,
  `ChemistryExtraction.added_solutions` (every solution combined, volume as
  printed). `calculators/mixing.py` (local, NOT the model) adds the mixture
  value as a `derived` entry (hidden from the model schema via SkipJsonSchema;
  provenance origin "calculated"; `derived_value` flags, own GUI group). Only
  when every volume parses; otherwise a note. Stock values go to
  `stock_<name>_aq_mM`, known wherever `initial_<name>` is (registry pattern),
  reviewed as "stock <name>" otherwise.
- **Molar ratios** (Mickey: calculate locally, mark derived): `ChemistryExtraction.molar_ratios`
  (per set; the model may write either side as reference -- kim2019's live
  run did "3 : cytosine" with cytosine as reference). `derive_from_ratios`
  runs after the stock->mixture step: whichever side's mixture value is known
  gives the other, then its stock value from the volumes; both known -> a
  check (`conflicting_values` on >2% mismatch). Derived values keep the
  unrounded value (`exact_mM`, hidden) for chained steps; stored at 6 s.f.
  kim2019: cytosine 7.5 / 11.25 mM stock for 1:2 / 1:3, as in the paper's logic.
  Flag kinds: derived_value / not_calculated / conflicting_values.
- **Flags** (Mickey: over-flag rather than under-flag; cut noise by grouping
  or rewording, never dropping): low-confidence per-set/cycling values and
  starting species are grouped into one flag per field (+confidence); an
  initial species with no concentration gets `concentration_not_stated`.
- **One quantity, one variable** (Mickey: a volume/concentration tracked twice
  reads like twice the amount): `ingestion/duplicates.py` drops
  methodology other_parameters whose every volume/concentration repeats the
  chemistry record (concentrations only match a LINKED species -- named in
  the text or in a solution whose volume matched; equal numbers alone don't
  count). `duplicate_removed` flags + `repeats_left_out` in new_variables.json.
  Each added solution volume is offered once in the review as
  "volume added: <solution>" (`added_<solution>_volume_uL`).
- **Peptide naming convention** (SUPERSEDED 2026-11-04 -- see "One column format for every compound"; Mickey, 2026-10-15; replaces relying on the
  template's fixed peptide columns): homopolymers `<role>_<n>peptide_<AA>_<mM|%yield>`
  (any n >= 2), heteropolymers in order `<role>_<AA1>-<AA2>-..._<mM|%yield>`.
  `names.peptide_codes/peptide_name` parse Gly-Ala-Ala, GlyAla, H-Gly-L-Ala-OH,
  glycylalanine; `registry.is_peptide_column` makes these columns KNOWN (no
  review needed -- a defined standard, like stock_). Cyclic peptides stay
  unmatched (review). The template's `mixedPeptide_*` columns are not used.
- **Cyclic peptides** (Mickey, 2026-10-15): `<role>_cyclo_<AA1>-<AA2>-..._<mM|%yield>`
  for homo- and heteromeric rings (`names.cyclic_codes`: cyclo(...), c(...),
  DKP_X, "X diketopiperazine/anhydride", 2,5-piperazinedione -> cyclo_Gly-Gly).
  The template's DKP_* columns are rewritten to this naming in set_row_value
  (`current_column_name`), and the PubChem template map follows it. Residue
  order is kept as written (cyclo_Val-Gly and cyclo_Gly-Val stay distinct --
  open question whether to canonicalise rotations). Cyclic yields count
  toward total_sampled_peptides_yield.
- **Figure review is two-pass** (Mickey): Skip/Digitize for every figure
  first, then the chosen ones open in the digitizer in turn; suggestions are
  requested (prefetched) when a figure is chosen.
- **Value quotes are checked too**: `CellSource.quote_verified` ->
  observations column `quote_in_paper` (yes / table image / no / ''; "table image" = not
  in the text but sourced from a table that was rasterized for the model) and the Rows-tab hover text
  ("Model's wording ..."). Pipeline-generated text is no longer put in quote
  fields (set summaries, the cited-data marker).
- **Equations** (Mickey: only ones the authors LABEL): `ingestion/equation_finder.py`
  finds "(N)" set apart from a relation-bearing block (or "Equation N:") --
  column-aware (one/two-column pages), grows the block over stacked lines,
  fractions and sub/superscript fragments, stops at prose; rejects table rows.
  Second rule for OCR'd scans: "(N)" as the LAST WORD of an indented line
  with a relation (eder1994's rate law, eq. 1 p.3 -- reported by Mickey).
  Crops -> `<run>/equations/`, `equations.json`. Over all 76 dataset PDFs: 15
  found in 6 papers, all real (+ eder1994, truman2024, Zamaraev1996,
  lemke2009, kawamura2011, otake2011), no false positives. Free, ~0.5 s/paper.
  Optional LaTeX (`RunConfig.equations_to_latex`, GUI checkbox, CLI
  `--equations-latex`): `stages/equations.py`, ONE batched Sonnet call
  (~$0.02 for 13). Tested pix2tex (~half wrong) and pix2text (accurate except
  the per-mille sign, but torch: 1.8 GB) -- rejected for the app's size.
- **CropBox bug fixed**: pdfplumber positions are MediaBox-based but pypdfium2
  renders the CropBox -- `pdf_parser.render_offset/to_render_box`; figure and
  equation crops (and the digitizer's figure region) now use it.
- **GUI tabs**: Figures (crop or annotated digitized image, status, caption)
  and Equations (crop + LaTeX) next to Rows/Flags/Summary.
- **Digitizer conditions** (alargov2002 Fig. 3: pressure was missed because
  PlannedSeries only had temperature/pH): `SeriesCondition` list (column +
  value AS PRINTED + source) on planned and digitized series; converted in
  `figure_rows.convert_condition` (refuses id/metadata columns; experiment_type
  only Batch/Flowthrough); unknown columns -> review. Editable "Other
  conditions" table in the digitizer. `series.y_column` overrides the panel's
  y column (one axis carrying Gly-Gly AND diketopiperazine).
- **Digitizer automation (optional)**: `digitizing/auto_axes.py` finds plot
  frames (gap-tolerant, merges pieces of slightly rotated scanned lines),
  finds the tick NUMBERS as ink blocks outside each axis (works without tick
  marks; snaps to a tick if present), pairs them in order with
  `AxisVariable.tick_labels` (from the figure planner) or with text-layer
  numbers (`FigureCandidate.tick_numbers`, vector plots), only if evenly
  spaced (linear/log) and counts match -- else says why. Auto-runs on
  suggestions (checkbox, QSettings digitizer/auto_axes) + button per
  coordinate system (frame chosen by view centre, else panel base name).
  `digitizing/auto_points.py`: click an example marker -> centroid-refined,
  FFT normalised cross-correlation, legend boxes excluded, existing points
  skipped, one undo step; similarity spin (default 0.75). alargov2002 Fig. 3:
  all 4 coordinate systems calibrated; 12/14 markers at 0.75, 0 false.
  Text layer alone rarely works (truman figures are images, eder OCR garbled);
  frames not found for truman Figs. 4-5 / eder Fig. 5 (faint/coloured axes).
  numpy is now a declared dependency and NOT excluded in the PyInstaller spec
  (it was); `--self-check` tests it.
  Auto-calibrate checkbox is OFF by default (Mickey, 2026-10-16). Panel-name
  sides use whole words ("diketopiperazine" contains "top").
- **Figure planner context**: besides passages mentioning the figure, it gets
  `composition_passages` (lines stating a concentration anywhere, +-2 lines,
  no reference list) -- starting compositions live in Methods. Indirectly
  stated concentrations (control-run outlet, feed solution) ARE filled in the
  digitizer suggestions, with a note (user checks every suggestion);
  alargov2002 Fig. 3: Gly 65 mM (hand-operated, 22.2 MPa) / 220 mM (HPLC pump).
- **Concentrations for digitized series** (2026-10-16): the planner hesitated to
  put indirect values into `initial_species` (left null 2 of 3 trials even
  when told to). Now it lists them in `FigurePlan.concentrations`
  (species, value AS PRINTED, series labels, basis stated/indirect, source)
  -- filled reliably (3/3) -- and `digitizer.fill_concentrations` converts and
  fills only EMPTY species slots (adds the species if missing).
  `SpeciesAmount.basis/source` shown in the composition table's Source
  column; provenance in figure_rows.
- **Figure finder word gaps**: same adaptive x_tolerance as pdf_parser
  (alargov2002 captions ran together and hid Figs. 1, 2, 4-6). Single-column
  pages: a caption line that continues across the middle with an ordinary
  word gap makes the figure full width (`_continues_across`; kim2019 Figs.
  2-3 are now correctly full width too).
- **Digitizer layout** (Mickey): T and pH are the first two (fixed) rows of the
  "Conditions" table (T accepts units); "y values go in" lives under a
  collapsible "Additional options" (closed).
- **Error log** (`gui/error_log.py`): the packaged app has no console --
  failures and tracebacks go to `<app data>/errors.log` and the run folder's
  error.txt; an excepthook shows and records exceptions in the window itself.
- **total_sampled_peptides_yield** (`calculators/peptide_totals.py`, runs after
  the review): sum of the row's peptide %yields (linear and cyclic),
  origin "calculated" with the parts listed; a stated total ("Total Gly in
  peptides" -> mapped straight to the column) is kept and checked against the
  sum (`conflicting_values` beyond 0.05 points).
- **Quotes are checked** (`validation/quotes.py`): flag quotes not found in the
  paper's text (in-order word match tolerant of interleaved columns and
  sub/superscripts) move to `Flag.unverified_quote`, shown as "Model's wording".
  Root cause was the methodology prompt telling the model to explain derived
  values "in the quote"; SetOverride/CycleParameter now have a `note` field.
- **PubChem** (`pubchem.py`, PUG REST, POST by name, cached in the app-data
  folder incl. misses, fails soft -> `lookup_unavailable` flag): runs in
  normalize_chemistry AFTER names.py rules, only for names the rules didn't
  match. Exact-CID matching only: to a template species
  (`schemas/species_cids.json`, built + hand-checked by
  `scripts/build_species_cids.py` -- 118 of 163; first hits were wrong for CO,
  CO3-2, NiS, Phe3, so check titles if you rebuild), to a species accepted in an
  earlier review (registry `species_ids`), or to an earlier name in the same
  paper. RunConfig.use_pubchem defaults False (tests/library offline); GUI
  checkbox and CLI (`--no-pubchem`) turn it on. template_vocab stays the
  template's column list -- not a chemical dictionary.
- **Cost**: `pricing.py` list prices (checked 2026-10-15; Haiku 5.5 tiered by
  prompt > 100K) -> `StageUsage.cost_usd`, Summary tab column, CLI,
  run_summary.json. The API returns tokens only.

## Parallel stages (2026-10-20, step 1 of the domain-pack plan)

`pipeline.extract`: metadata (page 1 only) runs alongside the structure
planner; after it, methodology, chemistry, term_search, wet_dry (and the
optional equations step, from the start) run at once in a ThreadPoolExecutor
(`settings.MAX_PARALLEL_STAGES`). Progress: `ctx.note` for "running in
parallel", `ctx.step` as each finishes; usage recorded under a lock and
sorted by `STAGE_ORDER`. Client `max_retries=5` (parallel calls can hit a
key's per-minute token limit; the SDK honours retry-after). kim2019 live:
71 s vs ~90 s sequential; the floor is structure + chemistry. Plan agreed
with Mickey: (1) parallel -- done; (2) declarative optional-stage specs,
wet-dry converted first; (3) domain packs (template, vocab, prompts, stages,
calculators); (4) second pack: exoplanets -- test paper Liu2008 (folder next
to the other papers) with an Exoplanet Archive export
`PS_2026.10.20_17.17.08.csv` (header row = archive column names, row 2 = 11 Com
b values, then `# COLUMN name: description` lines; default_flag = 1). Rows
there are per planet/star, not per sample.

## Optional stages as data (2026-10-20, step 2)

`stages/specs/*.json` + `stages/optional.py`: a spec (name, label, origin,
schema_name, trigger {set_types, sample_fields, keywords, always}, set_word,
intro, parameters [{column, unit, description}], rules) is all a stage needs:
models built with pydantic create_model (flat, Literal of the spec's columns;
same field layout as the old CycleParameter), prompt = spec text inside
`prompts/optional_stage.md` (shared rules: stated/derived/assumed, verbatim
quotes, per-set values), `optional_values` -> rows (set-specific wins,
assumed -> review), flags and review generic over `[(spec, result)]`
(`optional=`; `wet_dry=` still accepted). Non-template spec columns become
registry standard columns (after standard_columns.json's, in spec order).
`RunConfig.optional_stages` {name: auto/on/off}. Wet-dry converted:
truman2024 replay byte-identical; live call matches the reference values.
`schemas/wet_dry.py` / `stages/wet_dry.py` are thin compatibility shims.
Exoplanet validation (Mickey): compare against the archive row whose
PLANETARY PARAMETER reference is the paper -- for 11 Com b that's Teng et al.
2023 (folder Teng2023 holds that paper and the PS_*.csv export); the archive
TAP API (exoplanetarchive.ipac.caltech.edu/TAP/sync, table ps) gives every
published parameter set (pl_refname) without a key.

## Domain packs (2026-10-20, step 3)

`src/parameter_extractor/packs/<id>/` (pack.json + template + standard columns +
species CIDs + prompts/ + stages/), loader in `packs/__init__.py`; also the
user's `<app data>/packs/`. `RunConfig.pack` (default prebiotic_chemistry) is
activated in pipeline._start; template/vocab (registry, names,
flatten_to_template, pubchem), prompts (`prompt_loader`: pack's own, else
app's prompts/), stage specs (`optional.load_specs`) all come from
`packs.current()`. Manifest `builtin_stages` (methodology, chemistry) and
`postprocess` (normalize_species, mixing, molar_ratios, peptide_totals)
switch those on; a pack without them gets empty stand-ins
(`empty_methodology`, empty ChemistryExtraction) and rows come from the
structure plan + its stages. Specs can be `"per": "sample"` (values name a
sample = a row, e.g. a planet; whole-set values apply to every row of the set,
sample values win). Moved to the prebiotic pack: template_vocab.json,
standard_columns.json, species_cids.json, wet_dry.json, and the prompts
structure_planner/methodology/chemistry/figure_planner/triage; generic
prompts stay in prompts/ (metadata, term_search, optional_stage, equations).
GUI "Research area" combo (QSettings `pack`), CLI `--pack` / `--list-packs`.
`tests/test_domain_packs.py` runs a throwaway exoplanet-like pack end to end.
Still prebiotic-shaped (for step 4): ExtractedRow's fixed fields and
FIELD_TO_TEMPLATE (metadata column names, Gly peptide yields), the
Methodology fields, names.py's peptide rules. A new pack needs at least its
own structure_planner and figure_planner prompts.

## Exoplanet pack (2026-10-20, step 4)

`packs/exoplanets/`: template = the archive's Planetary Systems (`ps`) layout,
288 columns in order, with descriptions (from Mickey's export
PS_2026.10.20_17.17.08.csv, now in `Paper Lists/Teng2023/`). Rows: set = host
star (hostname), sample = planet (pl_name). No methodology/chemistry; stages
(all `always`): planet_parameters (per sample), stellar_parameters (per set),
system_and_discovery (per sample; discovery only for planets this paper
announces). Postprocess (calculators/exoplanets.py): row_labels,
exoplanet_masses (Earth twins with the archive's factors, pl_bmass* +
pl_bmassprov), reference_names ("Teng et al. 2023" style; st_/disc_refname only
where this paper supplied those values), archive_validation
(validation/exoplanet_archive.py: TAP `ps` by pl_name, compare with the set
whose pl_refname is THIS paper; 0.5% or last-printed-digit tolerance; saves
archive_rows.json + archive_validation.json; flags archive_match /
archive_check; needs `RunConfig.online_checks`, which the GUI/CLI tie to the
"online lookups" switch, i.e. --no-pubchem turns both off).
Stage machinery grew for it: parameters can be `kind: text` (item `text`
field) or `uncertainties: true` (item err_plus/err_minus/limit -> <col>err1,
err2, lim; per-parameter `error_suffixes`, e.g. sy_dist has no lim); every
item has `unit` AS PRINTED and the app converts (`units.convert_printed`:
astronomy table kept apart from chemistry -- "m" is molar there; JD offsets,
not applied to uncertainties; log targets like log(L_sun)). Shared prompt now
says "give the value as printed with its unit".
PDF: pages whose characters are mostly sideways (landscape tables; teng2023
pp. 5, 9) are read turned (`_rotation`, `_turned_page_text`) and rendered
upright (`ParsedPaper.page_rotations`); their captions are found again.
`compact_text` pack option collapses layout spaces (teng2023: 102K -> 80K
tokens). Generic `prompts/figure_planner.md` for packs without their own.
Live run (2026-10-20): 38 rows (32 systems), ~8 min, 365K in / 96K out,
~$1.68. Reference run `runs/teng2023_auto/` (figure crops left out, 36 MB;
archive_rows.json = archive snapshot) + `tests/test_teng2023_replay.py` (~1 min).
Against the archive: 36 planets compared, ~1960 values match, 20 differ -- all
on HD 14067 b / HD 120084 b, where the paper gives an RV fit (Table 3) AND a
joint RV+astrometry fit (Table 4) and the archive took Table 4.
Fixes from that run:
- `optional_values`: a value and its err/lim columns always come from ONE item;
  a second, different value for the same parameter -> first kept +
  `conflicting_values` flag (was column-by-column last-wins, mixing Table 4
  errors onto Table 3 values). Angles (unit deg) compared modulo 360.
- Archive matching: fetch by pl_name OR pl_refname like the paper; names in the
  archive's style (`archive_name`: Greek -> eps/omi/..., Latin "o UMa" -> omi);
  host case-insensitive but the letter not (HD 5608 B = stellar companion,
  not planet b); alias fallback by orbital period within 1% among this paper's
  archive planets (41 Lyn b = HD 81688 b). st_/sy_/disc_ columns compared only
  when their *_refname is this paper (sy_plx is TICv8) -> `from_other_references`.
  Archive zero-padding ("1.7000") ignored for the last-digit tolerance.
- `exo.companion_masses`: > 30 M_J (archive's planet limit) -> `out_of_range`
  flag (kept in CSV; HD 5608 B 121 M_J, HD 175679 b 62 M_J).
- `pdf_parser.open_plumber`: one shared pdfplumber document for parser, figure
  finder and equation finder (closed after extract's local steps) -- each page
  parsed once; teng2023 local time 2.6 min -> 1 min, outputs identical.
Open question for Mickey: which fit to prefer when a paper gives two (the
archive used the joint fit); currently first-listed + flag. -> ANSWERED below.

## Exoplanet solutions + fitting models + stage toggles (2026-10-21)

Mickey (after consulting an exoplanet subject-matter expert): list every fit as
its own row -- joint vs non-joint, and fits joint in different ways, are
separate data points for the same planet -- and record HOW the NEA values
were obtained, with NEA-style names.
- **One row per solution**: the exoplanet structure prompt makes one sample per
  (planet, solution), labelled "HD 14067 b [joint RV + astrometry fit, Table
  4]"; single-solution planets keep the bare name. `row_labels` splits the
  bracket off (`exoplanet_fits.split_solution`): pl_name = planet, pl_fitlabel =
  solution. Planet/system stages: "never mix solutions on one row";
  stellar_parameters is now `per: sample` (a joint fit's own stellar values
  go on its row; star-wide values on all rows). Archive check: one entry per
  row, `solution` in the report and flag text.
- **Fitting models**: code stage `fit_models` (pack `builtin_stages`;
  `schemas/fit_models.py`, `stages/fit_models.py`, pack prompt
  `fit_models.md`, table images sent -- priors are often tabulated). Per model:
  rows / stars it produced, datasets (kind, facility, instrument, bands),
  joint + description, star_and_planets_joint, software (role: fitting code,
  sampler, stellar evolution/atmosphere models...), priors (shape, centre,
  width, lower, upper as printed + unit), assumptions (+quote). Flat schema,
  0 anyOf. `calculators/exoplanet_fits.py` -> columns (standard columns of the
  pack via registry when `pack.uses("fit_models")`, written only when filled):
  pl_fitlabel/data/joint_flag/jointdesc/stjoint_flag/software/exofastver/
  assump/priors, pl_fit<kind>_flag + pl_fit<kind>inst (kind words rv, tran,
  ast, ima, ttv like the archive's flags; sed, spec, occ, phase, plx, astero,
  other); st_fitlabel/data/bands/inst/software/models/exofastver/joint_flag/
  assump/priors; per archive parameter <col>priortype/priorcen/priorwid/
  priorlo/priorhi in the column's unit (convert_printed; widths as errors).
  A stellar-only model applies to all rows of its star; a model that also
  produced planet values only to its own rows. EXOFAST version parsed
  locally (EXOFASTv2 -> 2; no version -> blank + `fit_model` flag). Flags
  (`fit_model`, own GUI group): unknown row/star labels, unconvertible priors,
  rows with no model, models linked to nothing (e.g. SpecMatch feeding
  priors); medium/low-confidence models -> low_confidence.
- **Live test** (not Teng -- Mickey: expensive): nielsen2019 (arXiv
  1811.01882, HD 1397 b, EXOFASTv2 joint SED + RV + transit; PDF in
  `Paper Lists/Nielsen2019/`), 31 s, $0.36. Reference run
  `runs/nielsen2019_auto/` + `tests/test_nielsen2019_replay.py`: 117/117
  compared values match the archive; exofastver 2, stjoint 1, MIST, all SED
  bands, priors named without numbers kept as shape + text. Fixes from it:
  BJD_TDB / HJD_UTC (+ offsets) are Julian dates; fraction/ppm/ppt -> %;
  archive text match ignores case, _/-/spaces and a bracketed abbreviation;
  confidence flags show text values as text and name the planet.
  The splitting prompt was only tested offline (`tests/test_exoplanet_fits.py`
  reshapes teng's recorded responses into two HD 14067 b solutions);
  `runs/teng2023_auto` predates it and replays with fit_models off.
- **Stage toggles**: `optional.toggleable_stages(pack)` = spec stages (+ new
  spec field `description`) + optional code stages (fit_models). GUI
  "Extraction stages:" checkboxes under Research area, rebuilt per area,
  QSettings `stages/<pack>/<stage>`; unticked -> RunConfig.optional_stages
  'off' (ticked = 'auto', i.e. triggers still apply). Research area, stages,
  online lookups and LaTeX are locked during a run (switching the pack
  mid-run would change the active pack). CLI `--skip-stage NAME`;
  `--list-packs` lists stages. GUI test drives truman2024's wet-dry stage
  on/off through the real worker, no API.
- **Expert answers (2026-10-21)**: (1) joint star + planet fit = a stellar model
  and the planet models with their sampled parameters linked in ONE
  likelihood (so e.g. transits constrain stellar density); earlier stellar
  results used as priors/fixed inputs are NOT joint -- prompt + schema say so,
  and `model_flags` flags a joint claim without rows + stars + a stellar model
  (SED data or isochrone/atmosphere software), and the reverse (both sides +
  stellar model + joint, but not marked); the model's answer is kept.
  (2) prior-only analyses (SpecMatch etc.): flag + keep in
  fit_models.output.json, no columns -- as built.
- **Live structure test on teng2023** (all four stages skipped, $0.25): HD 14067 b,
  HD 120084 b, HD 175679 b each split into "[RV fit, Table 3]" + "[joint RV +
  astrometry fit, Table 4]" -> 41 rows; single-fit planets unbracketed; HD
  5608 B stays a separate companion.
- **teng2023 reference re-recorded** (Mickey, 2026-10-21; full live run, 5 min,
  470K in / 80K out, $1.73 -- about the most expensive paper to expect): 41
  rows; 38 compared, 1394 values match, 20 differ. Fitting models: RV-only
  Keplerian fits (RadVel + emcee, 37 rows), joint RV + Hipparcos-Gaia
  astrometry (orvara, 4 rows), isoclassify stellar parameters (23 stars);
  stjoint 0 everywhere (correct: no stellar model in the fits). The archive
  took the joint solution: `exoplanet_archive._mark_archive_solution` gives the
  other solution rows `archive_solution` and the flag says their differences
  are expected. Remaining differences on the joint rows: inclination --
  Table 4 prints i (all), i < 90 and i > 90 (bimodal); the model took "all",
  the archive the prograde value. Known gap: optional stages get NO table
  images (only structure planner, chemistry, fit_models do), so Table 4's
  vertically garbled text cost the inclination uncertainties -- candidate
  fix: a spec option to send table images (~+20K tokens per stage). -> DONE below.

## Posterior modes, paper-first archive differences, table images (2026-10-21)

Mickey / expert: capture ALL recorded values (at least one should match the
archive); note bi-/multimodal posteriors with each mode's values; minor naming
differences and small uncertainty differences -> the paper's value, not a
discrepancy. Plus table images for the planet/stellar/system stages.
- Spec fields `modes` and `table_images` (stages/optional.py). `modes`: item
  field `mode` ('' = the overall value); mode items -> `<col>modal_flag` (1),
  `<col>mode<N>`, `<col>mode<N>err1/err2`, `<col>mode<N>desc` (N <= MAX_MODES
  = 3; more -> unit_conversion-style problem), registered via output_columns;
  not conflicts. `multimodal` flag per parameter (GUI group "How the values
  were obtained"). `table_images`: run_optional_stage sends the rasterized
  table pages + a prompt rule to read tables from the images. On for
  planet/stellar (both) and system_and_discovery (images only).
- Archive compare: `recorded_values()` = the row's value + each mode's; any
  match counts (`matched_mode`). `_minor()`: NAME_COLUMNS (disc_facility/
  telescope/instrument/locale, pl_tsystemref) sharing a significant word, or
  err1/err2 within 20% (UNCERTAINTY_MINOR) -> `minor` (paper's value kept),
  not `differs`; listed in the flag text.
- teng2023 re-recorded again (5 min, 504K in / 85K out, $1.85): 2111 match
  (was 1394 -- images recover uncertainties), 33 differ, 9 minor; joint rows
  match via the prograde inclination mode (118 / 39 / 141 recorded); low-
  confidence flags 26 -> 10. All remaining differences on the RV-only rows
  the archive didn't take (marked) except HD 167042 b e err1: paper +0.033,
  read +0.003 -- dense full-page Table 3 loses superscripts (the API scales
  images to ~1568 px). Candidate fix: split dense table pages into halves.
- tests/test_exoplanet_fits.py now uses frozen fixtures
  (tests/fixtures/exoplanet_fits/) instead of runs/teng2023_auto.

## Dense table pages cut into pieces (2026-10-21)

`ingestion/table_tiles.py` + `pdf_parser.rasterize_pages` (all packs): table
pages render at 220 dpi (settings.TABLE_RASTER_DPI, was 150), cropped to the
content; if still > 1568 px (the API's unscaled limit) x 1.15 tolerance, cut
at white space -- rows first, then columns; column pieces after the first get
the row-label strip (first column up to the widest vertical gap in the left
40%, "gap" = ink in <3% of rows, since captions/rules cross it) pasted on the
left. Files page-N.jpg or page-N-KofM.jpg; `rasterize_*` return {page:
[paths]}. api_client puts a text label before each piece ("Page 9, piece 2
of 2 ..."). teng2023: every table page -> 2 pieces (Table 3's label strip
also takes the P column -- harmless repeat). Live (4.5 min, 547K in / 75K
out, $1.84, same cost as before -- fewer output tokens): HD 167042 b e err
read correctly (+0.033), retrograde inclination errors captured, 0 real
differences left (all 32 on the RV-only rows the archive didn't take),
low-confidence flags 9. Reference re-recorded. Prebiotic papers also get the
sharper pieces on their next live runs (their reference runs replay
unchanged; image tokens up somewhat per table page).

## Broken-off answers (2026-10-21, aa57186-25 = Carleo et al. 2026, TOI-3862 b)

Mickey's app run failed: system_and_discovery ran 7 min / >112K chars for one
two-planet system (a runaway inside a field) until cut off ->
MalformedOutputError, whose message told users to raise max tokens (they
can't). Not reproducible (rerun: 1.3K output tokens). Now:
- `StageSpec.output_budget(structure)` = 4000 + 250 x (sets [+ samples]) x
  parameters (x2 with modes) -> call_structured(max_tokens=...), passed to
  `_send` via the thread-local `api_client._streamed` (replay fakes keep their
  signature). Real use is 5-10x below the budget; Teng's planet stage is capped
  at the global 64K anyway.
- call_structured retries ONCE (full budget) on OutputTruncatedError /
  MalformedOutputError; a truncated try's usage is recorded (paid for).
  `_send` keeps the streamed text; on a parse failure it's saved as
  `<run>/<stage>.failed_output.txt`. Messages now say "running the paper
  again usually works".
- Bug found on the way: assumed TEXT values went to the review as 0.0 and on
  every row of the set -- now value_text + the item's sample row
  (`_assumed(..., sample_label)`); flag text via pipeline `_shown`/`_where`.
- tests/test_api_retry.py (nielsen2019 replay with a flaky stage).
- Full live run after the fix: 68 s, $0.88, 2 solution rows (GP / no GP),
  106/108 match on the adopted one. Open: st_rotp -- the paper gives >13 d
  (archive), 22 +- 3 d (taken), GP 33-49 d; "every value" currently only
  covers posterior modes, not estimates from different methods. -> DONE below.

## Estimates by other methods + the real cause of the runaways (2026-10-21)

- Spec field `alternatives` (on for all 3 exoplanet stages): item field
  `method` ('' = the value the paper adopts); others -> `<col>alt<N>`,
  `<col>alt<N>err1/err2/lim`, `<col>alt<N>method` (N <= 3; repeats of the
  adopted value dropped). `other_estimates` flag per parameter (adopted +
  others, limits as "> 13"; GUI group "How the values were obtained").
  Archive compare: alternatives are recorded values too; a value matched via
  an estimate has its err/lim columns compared from THAT estimate.
- **Root cause of aa57186-25's runaways** (seen in a kept failed_output.txt):
  fields with defaults were OPTIONAL in the schema sent to the model; it
  skipped `method`, put "Method: ..." in `note`, and looped "Done. Done. ..."
  until cut off. Fix: every field REQUIRED in the sent schema
  (`optional.ALL_REQUIRED` json_schema_extra; `schemas/fit_models._Strict`),
  Python defaults kept (old recordings validate); `note` described and
  prompted as one short sentence. Retry budget now 2x the stage budget (not
  the 64K max). A valid answer whose notes report failure ("Extraction
  failed") is asked again once (`optional.GAVE_UP`); twice -> low_confidence
  flag. Before the fix 2 of 3 full runs broke off; after: 2 of 2 clean
  ($0.91 each), all SPECIES+ARIADNE / SED / activity / GP / v sin i
  estimates recorded by method.
- Archive limit-flag convention confirmed from the archive's own data
  (st_vsin "< 3.5" -> lim 1): 1 = upper, -1 = lower, as we map. The archive's
  st_rotp 13 with lim 1 contradicts the paper's "> 13 days" -- left flagged.

## Cost options measured (2026-10-22)

Mickey asked about cheaper processing (asked about TypeSafe's Jev: early access,
text-only, no free-form strings -> not for extraction; maybe decision-shaped
steps later).
- **Prompt caching via shared tools** (`RunConfig.prompt_caching`, ON by default;
  CLI `--no-cache`). The API's cache key includes the request's OUTPUT SCHEMA
  (verified: two calls differing only in output_format never share, paper in
  messages or system alike), so per-step `output_format` can't share a cached
  paper. Instead every paper-reading step sends: SHARED_SYSTEM, the same tool
  list (`PaperContext.tools` = every paper-reading step the run may make, fixed
  before structure planning -- pipeline `_paper_tools`; non-strict, since all
  of them strict exceeds the API's "compiled grammar is too large" limit in
  both packs), the paper (table-image pieces + text, cache_control on the text),
  then "YOUR TASK: <step prompt> ... Answer by calling the `<stage>` tool".
  tool_choice "auto" + disable_parallel_tool_use: Sonnet 5.5 400s on forced
  "tool"/"any" (Haiku 5.5 accepts them). `_send` turns the tool call into
  parsed_output (`_from_tool_call`, `_decoded` fixes lists sent as JSON strings);
  a missing/invalid call is a broken answer -> retried once. The structure
  planner writes the cache (runs alone), the parallel steps read it.
  Live, cached (vs the same profile uncached):
  | paper | standard | economy |
  | teng | $1.43 (was $2.15), 2110 archive matches, 0 real diffs | $0.43 ($0.51), 2082, 0 |
  | nielsen | $0.24 ($0.49), 118, 0 | $0.016 ($0.027), 115, 3 (insol unit blank) |
  | aa57186 | $0.40 ($0.88), 139, 1* | $0.028 ($0.043), 148, 1* |
  | eder1994 | $0.32 ($0.42), 94.9% cells = reference | $0.022, 79.6% |
  (*the archive's st_rotplim). One Haiku answer sent its list as a JSON string
  with junk -> retried fine (non-strict risk). Cached prefix ~7K tokens larger
  (tool definitions).
- **Model profiles** (`RunConfig.model_profile`, settings.MODEL_PROFILES, GUI
  "Models" with hover text naming the models, CLI `--models`): standard
  (Sonnet 5.5; page-1 metadata Haiku), economy (Haiku 5.5; figure_planner /
  equations exempt -> Sonnet). "balanced" (Sonnet structure, Haiku extraction)
  was measured and DROPPED (Mickey): $0.86 / 1380 matches on teng, worse than
  economy on both.
- Fixes from these runs: `_surname` dropped all-caps surnames ("Huan-Yu TENG"
  -> "Huan-Yu et al.", archive check found no set); pl_insol had no unit ->
  "S_E" + flux units + "10^N <unit>" scale prefixes; a dimensioned unit for a
  unitless parameter is refused, not passed through. `_record` returns its
  StageUsage (audit no longer reads ctx.usage[-1] across threads).
- Batch API (50% off, async) not built yet; stacks with caching.

## Batch mode, out-of-credits, shorter quotes (2026-10-22)

- **Batch mode** (`RunConfig.batch_mode`, GUI checkbox, CLI `--batch`): `_send`
  submits each request as a one-request Message Batch (`_send_batch`: create,
  poll 5 s -> 60 s via cancel_event.wait so Cancel is immediate and cancels the
  batch, read the single result; raw params -- `output_config.format` json_schema
  via transform_schema instead of the SDK's `output_format`; tools as usual).
  Parallel stages = parallel one-request batches. 1-hour cache (`_paper_blocks
  (long_lived=True)`). Pricing: `request_cost(..., cache_write_1h_tokens, batch)`
  -- 1h writes 2x input, batch x0.5 on everything; StageUsage.batch; audit
  `batch_id`. Errored results -> `_BatchRequestError` -> mapped like direct
  errors; expired -> BatchExpiredError. Live: nielsen economy $0.010 (vs $0.016),
  ~6.5 min (two ~2.7-min queue waits), cache reads work, 116/0 archive.
- **Out of credits** (`errors.OutOfCreditsError`): 402 / billing_error, or
  "credit balance" / "spend limit" / "spend cap" / "billing" in the message
  (400 spend limits, 429 monthly spend cap) -- direct or batch -- says which
  step, which steps had finished (ctx.usage), and the run folder; CLI also
  appends it to the run's error.txt (GUI already did). Tested offline with real
  SDK exception classes (tests/test_batch_and_credits.py).
- **Shorter quotes/notes** (schemas/common.py): QUOTE_DESC (shortest verbatim
  span, <= 20 words; table: row + column + value), SOURCE_DESC (exact table/row/
  column or section/paragraph), NOTE_DESC (<= 15 words) used by every schema +
  prompt rules. Kept capped: CellSource.quote <= 200 chars, Flag quote parts /
  model_note (`capped`, word boundary + " …"). **Page**: validation/quotes.py
  `PaperText(text, page_texts).page_of()` -> CellSource.page / Flag.page (else the
  page of the table named in the source, `table_page_numbers`); observations
  column `page`; GUI hover "Where: Table 3, p. 9". Reference observations
  regenerated (only page column + 174 capped teng quotes; CSVs unchanged).
- Measured (economy): teng batch run $0.27 (cached non-batch $0.43), 9.5 min,
  2082 archive matches / 0 real diffs, page on 72% of observations. Output did
  NOT shrink (teng 129K -> 153K tokens: more alternative estimates; sources longer
  by design): exoplanet quotes were already ~20 chars. eder: notes 128 -> 60
  chars, chemistry max quote 66 -> 38, tokens ~unchanged. The real overhead is
  JSON FIELD NAMES: 45% of output chars (16 required keys per value), quotes+
  notes+sources 24%. Next lever: a compact answer format (shorter keys, or values
  grouped per row) -- not done, Mickey to decide.
- **Compact answer format** (optional stages, stages/optional.py): `rows: [{set,
  sample, values: [...]}]`, short field-name ALIASES (col v u txt mode meth ep em
  lim b q src c n; code still reads .parameter/.quote/...), required only
  CORE_FIELDS (col v u q src c), the rest left out when empty. `_CompactResult.
  parameters` flattens rows (+ `legacy_parameters` = old flat {"parameters": [...]}
  recordings, which still load). Chosen from token counts (count_tokens, teng's
  306 stellar values): grouped+short+omit 70% of the old format; positional arrays
  58% (rejected: swapped positions can't be validated). Live: teng economy 176 ->
  115 output tok/value (out 129K -> 89K, $0.43 -> $0.33, 2111 archive matches, 0
  real); nielsen standard 168 -> ~118 tok/value, 122 matches 0 real. `u` had to be
  REQUIRED: optional, Sonnet left out "fraction" for pl_trandep (unconverted).
  Prompt legend of the short names in optional_stage.md; pack rules use them.
  fit_models / methodology / chemistry keep their formats (prebiotic to be
  reworked by Mickey).
- Kim 2019 folder renamed to Kim2019 by Mickey: two tests had been SKIPPING
  silently (test_kim2019_replay, test_pdf_parsing) -- paths fixed. A SKIP prints
  but exits 0: grep suite output for SKIP after moving papers.

## Prebiotic pack brought to parity; template trimmed (2026-10-22)

Mickey: lessen reliance on PaperDataTemplate's strict format so the pack
generalises beyond prebiotic peptide synthesis (the .xlsx itself stays frozen).
- **template_vocab.json** (pack's copy): 280 -> 208 columns. Removed (his list):
  cycle_number, cycle_duration_hr, WORM/pKa/pH-calc fields, every free-ion and
  calc_* column (initial_Na+_mM, initial_Ca+2_mM, ...), mixedPeptide_*,
  mixed_peptides_list, sampled_cyclic_peptide_ratio, config_aa, isModeled,
  intoEORE. author1..7 -> `author_list` ("; "-joined, AUTHOR_SEPARATOR in
  flatten_to_template; also the exoplanet pack's standard column). species_names
  163 -> 129 (species with no remaining column: the free ions -> now reviewed as
  new species); species_cids pruned. PlannedSample.cycle_number and the wet-dry
  cycle_duration_hr parameter gone (wet-dry trigger = set type only).
- **Compact answer format for chemistry and methodology** (like the exoplanet
  stages): chemistry `groups: [{set, sample, species: [{nm r ph v u [mM cn b
  stk] q src c}]}]` flattened by a model_validator into the same `solutes` list
  (old recordings load: "solutes" by name); paper_id / in_controlled_vocab
  hidden from the model. Methodology: Extracted -> v/st/q/src/c/n, overrides
  set/f/v/b/q/src/c/n, other parameters nm/v/set/q/src/c (aliases,
  populate_by_name). All compile as strict outputs too (--no-cache path).
- **Output budgets**: chemistry 10000 + 900 x (sets + samples), methodology
  6000 + 500 x sets (call_structured max_tokens; retry at 2x).
- Spec stages skip values for parameters they no longer have (old recordings,
  model slips) instead of failing (`_CompactResult._known_columns_only`).
- Prompt fixes found live: structure planner -- text-only results ARE rows
  (truman's Campbell sets were dropped once); methodology -- an override for
  EVERY varying field, incl. sampled_temperature_C (eder lost it once).
- Live (cached): eder standard $0.24 (ref $0.32), 87.8% of reference cells,
  all differences wording of solvent/analysis method + 1 total; chemistry
  154 -> 136 tok/species; truman standard 11 rows $0.22, chemistry 227 -> 136
  tok/species. eder economy $0.020 (69.7%, before the prompt fixes).
- Reference CSV/observations regenerated by replay with a checker (only the
  removed columns + author_list differ).

## Experimental conditions stage, water types, results from tables/figures only (2026-10-22)

Mickey's follow-ups to the trimmed prebiotic pack:
- **Methodology -> configurable spec stage** `packs/prebiotic_chemistry/stages/
  experimental_conditions.json` (builtin "methodology" dropped from the manifest;
  its prompt deleted). per sample, always, table images, uncertainties on
  pressures/temperatures/pH/flow (`_err_plus`/`_err_minus`), alternatives on
  (negligible cost: optional field), `suffix_separator` "_" ->
  initial_temperature_C_alt1_method (exoplanets keep ""), new template columns
  covered (sampled_pressure_bar, sampled_pH, solvent/loading volume, flow rate /
  cycle, solid material name/type/mass/preheat). New spec features:
  StageParameter `choices` (experiment_type Batch/Flowthrough, solution_type
  Wet/Dry; matched case-insensitively, else left out + unit_conversion-style
  problem), `integer` (cycle_number), StageSpec `open_ended` (+hint) -> Result
  `other` [{nm v set sample q src c}] -> pipeline `_collect_other_parameters` ->
  ex.methodology.other_parameters (duplicate check + review unchanged).
  ex.methodology is otherwise empty for this pack; build_rows writes stage values
  via set_row_value AFTER the row exists (dedicated fields like solvent_name).
  Digitized figure rows get paper-wide conditions from `_paper_wide_methodology`
  (items with set '' -- works with zero sets). Always-on spec stages are counted
  in total_steps up front. Recorded methodology answers replay through
  `stages/conditions_migration.conditions_from_methodology` (make_replay).
  Rules that mattered live: sampled_temperature_C must be a RULE (in a parameter
  description it was ignored: 0/42 -> 42/42 eder, 13/13 kim); no wet-dry details
  in `other` (truman duplicated cycle duration).
- **Water** (`calculators/water.py`, postprocess "water_type"): solvent_name
  normalised to distilled / deionized / Milli-Q / ultrapure / nanopure / tap /
  double-distilled water; bare "water"/"H2O"/"aqueous" -> "distilled water",
  provenance "..., assumed distilled", one `assumed_default` flag per paper.
- **Wet-dry**: cycle_number (per sample, integer) and cycle_duration_hr back in the
  wet-dry spec -- spec columns, NOT the main vocabulary; spec per sample.
- **Rows only from tables (and digitized figures)**: structure prompt -- results
  stated only in the text go to excluded_data (lack the experimental context);
  no results table -> no sets. Postprocess "results_check": no row with a
  measured value (sampled_* / total_sampled_*, or a pending 'sampled' new
  variable; sampled_temperature_C/pressure/pH don't count) -> `no_results` flag.
- Units: a temperature UNCERTAINTY converts without offset (±1 K = ±1 °C).
- Live (standard, cached): eder $0.23 -- every value matches the reference except
  analysis_method wording; kim $0.12, 13 rows (2 text-only results excluded);
  truman $0.19, 8 rows (Campbell text results excluded), cycle_number 1-4.
- Tests: tests/test_conditions_stage.py; prebiotic references regenerated (only
  solvent_name -> distilled water and truman's cycle_duration_hr differ).

## Non-obvious decisions — don't redo this research

- **Schema shape is grounded in `../POLO_variable_mapping.csv`** (one level
  up, in EORE Data Project root), which classifies every PaperDataTemplate
  column as `direct` / `pattern_direct` / `no_analogue_calculated` /
  `no_analogue_gap` / etc. `pattern_direct` (176 of ~280 columns) is why
  chemistry extraction is a list of `{name, concentration}` pairs
  (`schemas/chemistry.py`) instead of ~150 separate fields — those columns
  are literally the same repeated ontology pattern, not distinct properties.
  Re-read that CSV before changing the chemistry schema.
- **`packs/prebiotic_chemistry/template_vocab.json` is generated, not hand-written** — built
  directly from `../PaperDataTemplate.xlsx`'s own header row. If the
  template's columns change, regenerate it (see the one-off script history
  in this conversation — not currently saved as its own script in the repo;
  worth promoting to a real `scripts/build_vocab.py` if it needs to run
  again).
- (SUPERSEDED 2026-11-04: the pack now uses ONE format, `<role>_<name>_<phase>_<measure>` -- see "One column
  format for every compound"; the xlsx itself keeps its old names.) **Column naming in the real template is NOT uniform**: salts/ions use
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

## Chen2007 round (2026-10-23): quotes that don't say which species

Chen2007 (SO2/ferricyanide amide coupling) puts acids, amines and amide
products in Table 2 as STRUCTURE DRAWINGS: quotes like "Entry 1 ... Yield (%) 2"
or the general procedure's "carboxylic acid (3 mmol)" support the number, not
the species. `SoluteEntry.identified_by` (compact `how`) = how the model
identified it (prompt: required when the quote can't name it, c medium) ->
provenance "[identified from: ...]". `validation/quotes.species_named_in`
(name, phrase windows via match_species, AA/peptide 3- and 1-letter codes,
ions for salts "Na+"/"CuII") + `unnamed_species(solutes, page_texts)`: flagged
when `how` is given, or neither the quote nor its PAGE names the species (a
bare table row "97.3 2.77 0.064" is named by its column header) ->
`identity_not_quoted` flags, one per species (GUI group). eder1994 replay:
CaCl2 for Table 2's unlabelled 2.50 M block (the Ca/Ba ambiguity) + 2 unquoted
yields. Products whose sequence wasn't determined ("(FFA)") are named
"Phe2Ala (sequence not determined)", never given a sequence. Common salt names
added to names._COMMON (ferricyanide, carbonate, bisulfite...). Chen2007.xlsx
in the papers folder is NOT a hand-parsed answer key (fragments of an old
digitization). Live: $0.30, 17 rows; amide yields correct but all new variables.
Mickey's answers (2026-10-23), built in `calculators/amounts.py` (postprocess
"amounts", runs BEFORE mixing/ratios so ratios can use its values):
- `SoluteEntry.detection` (compact `det`, sampled only): "detected" -> the TEXT
  "detected" in the product's column (`flatten_to_template.DETECTED`, via
  `extra`; review passes it through; peptide totals list it as "not counted");
  "not detected" -> 0 (0 mM unless a % yield). One derived_value flag each.
- Amounts (mol/mmol/µmol/nmol, new "amount" dimension in units.py) -> mM =
  amount / solvent_volume_mL from the conditions stage (`pipeline._reaction_volumes`,
  per sample, else set; paper-wide entries only if every set agrees). A set-wide
  amount in a set whose samples differ in volume is split per sample
  (`_split_by_sample`; Chen Table 1: 30 mL / 50 mL). Entries marked derived +
  `calculated_from="amount"` (mixing keeps them; identity check still applies);
  a model mM off by >1% is replaced + conflicting_values; no volume ->
  not_calculated. Prompt: amounts as printed, no mM.
Live (2026-10-23, $0.27): 2 zeros, 18 detected, all amounts converted except
Table 1 entry 4 (the conditions step gave it no volume).
Totals (Mickey, 2026-10-23): `ChemistryExtraction.mixture_totals` [{set, sample,
total AS PRINTED, parts [{nm, n share}], q, src}] for "1:1 ratio of each
component, total 1 mmol"; `amounts.split_totals` (before the amount -> mM step;
parts renamed with the species in normalize) fills empty / adds entries with
value x share / sum (calculated_from "total", still converted by
derive_from_amounts), a stated value is kept + checked (conflicting_values >2%).
Live Chen Table 3: Ala 100 mM; AA/Phe, Ala/Phe, Ser/Phe 50 mM each ($0.28).

## Archive "not extracted" audit (2026-10-23, Mickey's teng2023 economy batch run)

463 "the archive also has N values not extracted" were nearly all false:
- archive bookkeeping (`exoplanet_archive.ARCHIVE_ONLY`: pl_controv_flag,
  pl_pubdate, pl_n*/st_n* holding counts...) -> never counted;
- printed "+0.000/-0.000" uncertainties (the compact format can't tell 0 from
  not given, so 0 isn't written) -> archive 0 + our value present = match;
- log(L) uncertainties: `convert_printed(..., is_error=True, about=value)` =
  log10(L+e) - log10(L) (exactly the archive's numbers); a sign check had also
  dropped the negative side;
- pl_tsystemref: spec field `time_system_column` (planet_parameters) fills it
  from the printed epoch unit (`optional.time_system`: "JD-2450000" -> "JD");
- values only in the planet's OTHER solution row (K, M sin i on the joint row)
  -> `in_other_solution` on the adopted row, said so in the flag.
After: 18 left, all on RV-only rows the archive didn't take (incl., true mass).
Economy misread 75 Cet [Fe/H] -0.05 as -0.1 (real, flagged). References
regenerated (only pl_tsystemref + st_lumerr added). GUI: cells without
provenance (source_notes) show their full text on hover.
Rows tab (2026-10-23, Mickey): rows that are the solution the Exoplanet Archive took for
the paper (archive_validation.json: compared, no `archive_solution`) are green
(`ARCHIVE_ROW_COLOR`; a flagged one keeps amber in its id cell), hover says so and whether
it's also the archive's default set; legend under the table (`rows_legend`).
Wording + differing cells (2026-10-23, Mickey): pack.json `units.row` = what a row is called
in messages (`packs.row_word`; exoplanets "object model instance" -- one planet as one fit
models it; default "row"), used in the archive flags and the Rows legend/hover (GUI takes the
pack from the locked combo, not packs.current()). Values on green rows that differ from the
archive (`differs`, not `minor`) are orange cells (`ARCHIVE_DIFF_COLOR`) with extracted vs
archive in the hover (`MainWindow._archive_marks`). Internal names (pl_fitlabel,
`solution`/`archive_solution` keys) unchanged.

## arXiv full text evaluated (2026-10-24, for multi-paper queues; not built into the app yet)

export.arxiv.org/api/query = METADATA only (title, abstract, authors, links, journal_ref,
arxiv:doi; `search_query=doi:<doi>` works only when authors entered the DOI -- Teng's 2308.05343
has none; fallback CrossRef title + first author -> `au:X AND ti:w1 AND ti:w2...` found it).
Full text: arxiv.org/html/<id> (LaTeXML; existed for all three test papers incl. 2018),
/e-print/<id> (LaTeX source; aa57186-25's is the journal-corrected version), /pdf/<id>.
OpenAlex / Semantic Scholar had no arXiv link for Teng; ADS needs a personal token.
Converter prototype (scratchpad, not in repo): LaTeXML tables are span.ltx_tr/ltx_td, math
from alttext, drop .ltx_bibliography. Paper tokens (text + table images now -> arXiv HTML):
nielsen 29.4K -> 17.6K, teng 99.2K -> 62.4K, aa57186 66.4K -> 34.0K. Live economy runs (same
code): nielsen $0.014 -> $0.011, 118/0 both; aa57186 $0.027 -> $0.020, 149 -> 180 matches,
47 -> 9 not extracted; teng $0.065 (PDF batch run $0.19 at half price), 2219 matches, 1 real
difference (75 Cet b a err sub/sup swapped -- LaTeX lists the minus first), 75 Cet [Fe/H] now
right. Found: the model sometimes adds a printed JD offset itself -> units.convert_printed now
leaves a value >= offset/2 alone; JD + offset kept at 15 s.f. (was .10g: lost the 4th decimal).
Caveat: arXiv is a preprint; versions can differ from the published paper.

## arXiv sources, focused search, GUI reorganized (2026-10-24, Mickey's decisions)

Decisions: "Use arXiv text when available" is an OPTION (default off; when on, arXiv text wins
over the PDF); optional ADS token; focused search defaults to cheap passages-only with a
"whole paper" toggle; consolidate options so the window doesn't get crowded.
- `ingestion/arxiv_source.py`: parse_identifier (arXiv ID/URL, DOI/doi.org, ADS bibcode incl.
  arXiv-style), resolve (arXiv doi: search -> CrossRef title + first author -> arXiv title
  search, accepted at title similarity >= 0.85; CrossRef also fills journal_ref "Journal (year)"
  when arXiv has none; journal bibcodes via ADS API with the token), all arXiv requests share a
  3-second rate limit (`_get`, tests patch it), fetch_html_text / fetch_pdf. `identifier_in_text`
  finds arXiv's sideways margin stamp (paper_source reads the non-upright chars) or a DOI.
- `ingestion/html_text.py` (stdlib HTMLParser): LaTeXML span tables (ltx_tr/ltx_td) and <table>s
  -> "a | b" rows, math -> $alttext$, bibliography/nav dropped.
- `paper_source.py`: resolve_paper(item, run_dir, prefer_arxiv, ads_token) -> ResolvedPaper
  (name, pdf | text, record, notes); identifiers always from arXiv (PDF fallback when no HTML);
  a local PDF only with prefer_arxiv, only if the record's title words are on its first pages,
  any failure -> the PDF + a note. run_name: PDF stem / "arXiv_<id>" / "doi_<...>" (dots kept:
  `_start` uses the name, not Path.stem).
- pipeline.extract(item): writes source.json; text sources: ParsedPaper(paged=False,
  read_from) -> no figures/equations/table images, quotes get no page (`pages_for_lookup`);
  metadata from the arXiv record (no metadata call; `_metadata_from_arxiv`, doi_source "arxiv");
  `paper_source` flags (preprint version, journal_ref; fallback notes) -> GUI group "Where the
  text came from"; run_summary read_from. RunConfig.prefer_arxiv / ads_token (summary shows "(set)").
  Prompt rules (optional_stage.md): LaTeX x_{-a}^{+b} -> ep +b / em -a; don't add JD offsets.
- `focused_search.py`: available_parameters (stage params not switched off + fit-model columns),
  keywords_for (user words, else description words), passages (head 1500 chars + hits +-3 lines,
  ' | ' table blocks kept whole, cap 60K chars), 0 hits -> "not mentioned" with no call; one call
  per paper (`answer_model`: flat, all required, Literal columns, prompt focused_search.md),
  `_converted` (units/errors via convert_printed; *exofastver -> 1/2), run_focused_search
  (4 threads; errors per paper don't stop the rest) -> focused_search_<stamp>/ with
  focused_results.csv, papers.csv, focused_summary.json, papers/<name>/. read_paper_list: first
  identifier or .pdf cell per CSV line. CLI: --focus COL (repeat), --papers LIST, --search-word,
  --whole-paper, --list-parameters, --paper ID, --arxiv, --ads-token.
- GUI: SettingsDialog (gui/settings_dialog.py: API key, ADS token + keychain account
  `key_store.ADS_ACCOUNT`, output folder, online lookups; Cmd+, / File menu / Settings button;
  the main window keeps key_edit/out_edit/... as aliases). Main window: Paper (PDF or
  identifier), Research area, collapsible "Run options" (models, batch, arXiv text, LaTeX,
  stages, parameters to look for) with a one-line summary; File menu (Open PDF, Focused search,
  Settings, Quit) + a "Focused search…" button beside Settings. `MainWindow.current_config()` is shared with `gui/focused_window.py`
  (papers list + CSV import, parameter tree with filter, search words, whole-paper box; locks the
  main window's inputs while searching).
- Live (economy): focused search on 3 papers $0.0009 (Nielsen EXOFASTv2 -> 2; Teng, aa57186 not
  mentioned, no call); teng2023 PDF with --arxiv: DOI -> CrossRef -> 2308.05343v1 HTML, $0.059,
  2219 archive matches, 0 differences on the adopted rows.

## Exoplanet Archive reference lists (2026-10-24, Mickey's disc_papers_trim_20.csv)

The file is NOT an arXiv export: one cell per line, the archive's pl_refname HTML links
(`<a refstr=... href=https://ui.adsabs.harvard.edu/abs/2020A&A...644A...1T/abstract ...>Tala Pinto
et al. 2020</a>`; one with %26 for '&', labels with &amp;), header "0". `arxiv_source.identifier_in_cell`
(html.unescape + URL-unquote; ADS abs link -> bibcode; arxiv.org / doi.org links; bare forms) ->
`PaperRef` (str subclass + `.label`, `.first_author`); read_paper_list, the focused window (list
item data keeps the PaperRef, shown as "label  (bibcode)") and the main Paper field accept it.
Journal bibcodes WITHOUT an ADS token: `Bibcode.parse` (A&A 'A1', letters 'L5', ApJ+L -> ApJL) ->
`doi_from_bibcode`: CrossRef filtered by the journal's ISSNs (`JOURNAL_ISSNS`, common astronomy
journals; else query.bibliographic) + year +-1 + query.author = first author, accepted only when
volume AND first page/article number match -> by_doi. by_title: CrossRef title + subtitle, tags
stripped; several arXiv queries (au:<last surname word> + 3 title words; 5 words; au + other words)
so spelling differences ('Characterising'/'Characterizing') don't block it; close-title rule kept.
CrossRef requests spaced 1 s and every service retries 429/503 (Retry-After, else 5/10/20 s) --
the first live run of 19 papers got 429s with 4 parallel lookups.
Live: 16/19 resolved without a token (13 arXiv HTML, 3 arXiv PDF); Tala Pinto 2020, Michel &
Mugrauer 2024, Baran 2015 aren't on arXiv (broad searches confirm). EXOFAST search: none of the
16 mention it -> $0.00 (screened locally). papers.csv has a `reference` column (the label).
Focused-search results layout (Mickey, 2026-10-24): focused_results.csv = one row per paper and
object (`wide_rows`; paper-wide values -- obj '' -- go on every object row of the paper), a column
per parameter holding its value (`cell_text`: in the column unit, else "value unit"; distinct
values '; '-joined), then its uncertainty columns in the pack's naming (`FocusParameter.error_columns`
from the spec suffixes: pl_orbpererr1/2) only when a value has one (`result_columns`); columns
reference, paper, obj, status, <params...>, read_from, title. The old line-per-value file (with
quotes) is focused_values_with_quotes.csv. The window's table has the same columns (hover = quote,
where, as printed). Live teng passages-only gave 14 objects, not every planet: Table 3's rows hold
no search words -- use "Whole paper" for table-wide parameters.
Whole tables in passages mode (2026-10-24): `table_spans` = runs of ' | ' rows with blank lines
between rows allowed (arXiv's are blank-separated -- the old block logic stopped at row 1) + a
'Table N' caption within 8 lines above / 5 below; a hit within TABLE_LOOKBACK = 10 lines above a
table or inside it keeps the whole span (PASJ's unlabelled \tbl caption 'Orbital parameters.' is 7
lines above teng's Table 3). Measured (count_tokens, 3 papers x 3 searches): +10-45% passage tokens
(+1.8K-3.2K, ~$0.003/paper Economy) -> not negligible relatively, so a TOGGLE: `whole_tables`
(default on; GUI "Keep whole tables", disabled under Whole paper; CLI --rows-only). Live teng
period+e: 42 objects (all) vs 17 rows-only; $0.0095 vs $0.0069 (mostly extra output). Answer budget
raised to 6000 + 4000/parameter (3000 + 500 broke off on teng's ~40 objects).

## Many-paper speed + robustness (2026-10-25, Mickey's 1,389-paper run: 14 h, 76 errors)

Measured: batch mode sent each paper as its OWN one-request batch (median 164 s queue wait), 4 at a
time -> ~12.4 of the 14 h; arXiv (2-4 requests/paper at 3 s) was second. Errors: 44 arXiv 429/503/
timeouts, 27 not on arXiv, 3 bibcodes with 5-digit pages (qualifier slot holds a digit:
2024MNRAS.52710955B) treated as PDF paths, 2 lookups failed.
- `api_client.BatchCollector` (on RunContext.batch_collector): threads' requests pooled into shared
  batches (sent after 20 s quiet / 120 s since the first / 2000 requests), each batch polled on its
  own thread; submit() blocks like a direct call (retries, usage, audits unchanged). Focused search
  uses it in batch mode with 64 paper threads (8 when direct); one shared Anthropic client.
- `arxiv_source.resolve_many`: arXiv IDs 50 per id_list query, DOIs 20 per `doi:"a" OR doi:"b"`
  query (verified live), misses -> by_doi(title_search_only=True); bibcodes -> DOIs first.
  `LookupCache` (<app data>/arxiv_cache: lookups.json + texts/*.txt.gz, ".none" = no HTML; "not on
  arXiv" re-asked after 30 days; network errors never cached) used by focused search and full runs
  (RunConfig.arxiv_cache_dir; GUI/CLI default `registry.default_arxiv_cache_dir()`).
- `_spaced`: 6 retries (5/10/20/40/60/60 s or Retry-After) on 429/503 AND timeouts/connection
  errors; a busy answer doubles that service's spacing (<= 15 s), easing 10% per success.
- Bibcode regex/parse accept a digit qualifier; more journal ISSNs (NatSR, PASA, RAA, ...).
- Retry failed: read_paper_list(papers.csv, only_failed=True) keeps labels; CLI --only-failed; GUI
  "Retry failed papers (n)" button re-runs the error rows.
Live retry of the 76 failures (batch, economy): 11.5 min (all 31 model calls in ONE batch; the old
way ~46 min), $0.015; 34 resolved. Of the rest: title-word bug (hyphen fragments 'low-density',
'CoRoT-' -> arXiv 400) fixed (`_title_words` letters only, a rejected query skipped); papers like
CoRoT XXIV, GJ 463 b, beta Pic c confirmed NOT on arXiv. Label-less journal bibcodes: search by
volume + page + initial (rows 100), then `_iop_doi` (older ApJ/ApJL/ApJS/AJ: 10.1088|10.3847/<issn>/
<vol>/<issue>/<page>), then `_listing_doi` (cursor listing of the journal-year, <= 20 x 1000, kept
in `_listings` for the run): 19 of 22 (left: 2 MNRAS, Sci. Rep. too large). MNRAS Letters ISSNs.

## Shared prompts with pack rules; columns every pack gets (2026-10-26, Mickey)

- `stages/prompt_loader.load_prompt`: a pack's `prompts/<name>.rules.md` fills the shared prompt's
  `{{PACK_RULES}}` slot ("Rules for this research area (<label>):"; empty when none) and
  `{{RESEARCH_AREA}}` = the pack's label (lower case). A pack's full `prompts/<name>.md` still
  overrides (structure_planner, chemistry, ...). Slots in figure_planner, metadata, term_search,
  focused_search. The generic figure_planner.md took over everything general from the prebiotic
  copy (tick labels, multiplier, conditions as printed, y_column, points-as-series, data_source,
  duplicates); the prebiotic pack keeps only `figure_planner.rules.md` (compositions, indirect
  concentrations, `concentrations` list, Batch/Flowthrough) -- its own figure_planner.md is gone.
  Exoplanets: no rules (Mickey: tables carry the data; the generic is enough).
- `packs/common_columns.json`: columns every pack gets (paper_title, paper_DOI, author_list,
  year_published, journal_published, paper_arxiv_id), `Pack.standard_column_entries` = common +
  own, minus template columns (prebiotic keeps the template's places; exoplanets' standard_columns
  .json is now empty, same order -> references unchanged). `paper_arxiv_id` is filled (versioned ID)
  when the values come from arXiv's text or its downloaded PDF (`ResolvedPaper.read_arxiv`).

## Reference runs refreshed + rules refined from live runs (2026-10-26)

Framework: `runs/reference/<name>/` = recorded answers (<step>.output/.audit.json), reference.json
(pack, pdf relative to "Paper Files" OR arxiv ID, online_checks, models, cost), archive_rows.json
(exoplanets), arxiv_cache/ seed (record + text: replay needs no network), expected_extracted.csv /
expected_observations.csv / archive_validation.json -- written by REPLAY (registry None, no PubChem),
so the user's local accepted variables never leak in. `scripts/record_reference.py RUN_DIR NAME
--pdf ... | --arxiv ID --pack ...`; `tests/test_reference_runs.py` replays every folder (PDF missing ->
SKIP). Old fixtures (runs/eder1994_auto, kim2019_auto, truman2024_auto, teng/nielsen) are kept: 14
test files depend on eder1994_auto's specifics, and they test old-format answers loading.
Recorded (Standard, live 2026-10-26, $1.47 + $0.71 re-runs): eder1994 (42 rows, = old reference but
wording), faisal2005 (25, flowthrough 240-300 C / 20 MPa), kim2019 (13), truman2024 (8),
aa57186-25_arxiv (2; arXiv 2601.10450v1, 109/110 archive matches on the adopted fit).
Rules refined from these runs:
- kim2019: the nucleobase solution (20 uL) was set-labelled because its CONCENTRATION was stated for
  1:1 -> 1:2/1:3 mixtures 13 uL (CaCl2 9.23 instead of 3.64 mM). Chemistry prompt: set_label on an
  added solution only when its VOLUMES differ; mixing `_missing_solutions` refuses a set whose list
  lacks a solution listed for other sets (not_calculated) instead of a wrong total.
- solution_type: the curated dataset uses Wet / Dry / Wet-Dry (all 61 Evaporation Cycle rows) /
  Drydown (68 rows) -- the conditions spec offered Wet/Dry only. Choices + descriptions updated
  (Methodology Literal too); experiment_type: wet-dry cycling / dry-downs = Batch. kim -> Drydown,
  truman -> Wet-Dry, both Batch.
- aa57186: TESS TOI confirmed in the paper -> discoverymethod/disc_facility were "assumed" (held back).
  system_and_discovery rule: a survey candidate takes the survey's method/facility, b derived,
  disc_year = publication year (archive credits this paper: Transit, TESS). disc_year, sy_snum,
  sy_pnum `integer`.
- Confidence flags show numbers with the unit as printed ('20 MPa', not '= 20' beside a bar column).
- paper_source: single-paper runs look the identifier up in the arXiv LookupCache first.

## Prebiotic token pass (2026-10-27, Mickey: Sonnet must stay; cheaper without losing accuracy)

Measured (eder $0.31): output 60% (chemistry 11K tok; faisal 27K = $0.29 of $0.45), the one cache
write of the paper 26%, uncached step instructions 13%, cache reads 2% -- caching already worked
within a run; the dashboard's low cache share comes from focused searches (one call per paper) and
figure suggestions. Table cells were most of the chemistry answer, each repeating nm/r/ph/u/q/src/c
(the number ~7%).
- `schemas/chemistry.TableResults` (compact `tables`: src, c, cols [nm r ph u lbl how], rows [set
  sample row v[]]) -> `entries()` expands into the same SoluteEntry list (quote "<row> <value>",
  source "<table>, row <row>, column <lbl>", 'nd' -> not detected, 'detected'; `_cell_number`: plain,
  footnote marks, a x 10^n, +-err (value kept), refuses ranges, limits, '10-4' lost exponents).
  Prompt: tables in `tables`, text values in `groups`. Live Standard (same 4 papers): chemistry out
  eder 11.1K->5.7K, faisal 27.1K->5.4K, kim 5.5K->3.7K, truman 6.7K->2.0K; runs $0.31->0.26,
  0.45->0.24, 0.19->0.17, 0.20->0.16; every table value identical to the references (other diffs =
  run-to-run variance outside tables). References eder1994 + truman2024 re-recorded in the table
  format; kim2019 + faisal2005 stay in the groups format (old recordings must keep loading).
- Not worth it (measured): compact_text for prebiotic (1-3%), caching the structure plan as a 2nd
  breakpoint (<2%). Table images are ~half the cached paper -- kept (accuracy).
- Figure suggestions: figure_planner.md puts the paper-wide part first (instructions, plan,
  vocabulary, columns, composition passages -- no longer minus the figure's lines) and splits at
  `<<<this figure>>>`; `call_structured(cached_prefix=...)` sends it with cache_control, then the
  image + figure text. eder live: 18K-token prefix; Fig. 1 $0.076 (write), Fig. 3 $0.026 (read).
  Audit keeps `cached_prefix`.

## Batch mode for single runs (2026-10-27, Mickey asked whether pooling would help)

A run has two dependent phases (structure planner [+ metadata], then the extraction steps), so >= 2
queue waits. A/B on kim2019 (Standard, 4 runs started together): pooling each phase's parallel steps
into ONE batch (BatchCollector, 2 s window) took 700 s (~350 s per phase) vs 333 s for separate
one-request batches (~165 s per phase) -> NOT used for single runs (kept for focused searches, where
it replaced one wait PER PAPER). The waits sat on the poll schedule (5 s x1.5 up to 60 s: 165 / 349 s
marks), i.e. up to a minute after a batch ended -> BATCH_POLL_SECONDS = (5, 15) (checks are free):
same paper 287 s. The real lever for many full runs would be a multi-paper full-extraction queue
(phases of all papers share batches) -- not built.

## Open-ended capture cost; full-extraction paper queue (2026-10-27, Mickey)

- Measured (4 prebiotic live runs): the conditions stage's `other` list + chemistry's
  `unmapped_species` = 92-622 + 0-50 output tokens = 0.8-2.8% of a run (1.5% avg). Species outside
  the vocabulary are extracted anyway (their values are data) -> no toggle built (not worth it for
  cost; could still be added to cut review clutter if Mickey wants).
- `pipeline.extract` = `read_paper` (local: run folder, source, parse, table images, figures,
  equations -> Extraction with table_images / terms / always_on) + `extract_steps(ex)` (API).
  Single runs unchanged (replays + references identical).
- `paper_queue.PaperQueue(items, config, on_change, cancel_event, parallel)`: queue folder
  <output>/queue_<stamp>/ holds each paper's normal run folder; papers get paper_prefix 001, 002, ...
  (full_ids unique in the combined CSV); ONE reader thread reads papers in list order (pdf_parser
  keeps one shared document open -> no parallel parsing), each read paper is submitted to a pool for
  extract_steps (3 at once, 12 in batch mode); QueuedPaper status waiting/reading/extracting/
  extracted/finished/failed/cancelled, figures_reviewed (True when none), digitized/skipped;
  finish_paper(paper, review) on the caller's thread; write_combined -> combined_extracted.csv
  (write_csv over all rows), combined_observations.csv, papers.csv, queue_summary.json.
  `run_queue` = unattended (figures skipped, review None). CLI `--queue LIST [--parallel N]`.
- GUI `gui/queue_window.QueueWindow` (File > Paper queue (full extraction)… / "Paper queue…" button):
  shared `gui/paper_list.PaperListPanel` (also the focused window's), status table, ticks "Review
  figures as the papers are read" / "Review new variables at the end"; a 0.7 s timer opens the next
  paper's FigureReviewDialog in list order (PlanBridge -> plan_figure waits for that paper's
  structure), "Skip figures of the remaining papers"; when all are extracted and reviewed it finishes
  each paper (VariableReviewDialog per paper, registry choices carry over), saves digitized work of
  failed papers, writes the combined files. Main window inputs and the focused / queue buttons are
  locked while either window runs (`_set_inputs_enabled`: enabled and nothing else running).
- Live CLI (economy, kim + truman + eder): 58 s, $0.041, 63 rows, ids 001001001..003013003.

## New-variable categories + "Suggest new variables" switch (2026-10-27, Mickey)

- **Categories** (`variable_categories.py`): a suggested variable's KIND and how its values are
  reported. `value_type` number (one number + unit: parsed, proposed column gets the unit's suffix --
  time `_hr`, volume `_mL`, temperature `_C`, concentration `_mM`, ... -- and values convert to it),
  text (`max_words`; longer -> note), any. Shared `packs/variable_categories.json`: Metadata (text, 12
  words), Experimental Methodology (any, 10 words). Pack's own in pack.json `variable_categories`
  (listed FIRST; same id replaces a shared one). Prebiotic: Chemical Species (sources species),
  Solution Preparation (sources added_solution + model_assigns), Reaction Conditions (number).
  Built-in groups last: Figure columns, Assumed values. `sources` = filled by origin; categories
  without sources (or `model_assigns`) are the model's choices.
- Open-ended spec stages: `other` items get a REQUIRED `cat` (enum of assignable ids; default ""
  hidden from the schema so old recordings load -> `guess()` from the value) and the rule lists
  each category with description + format; names must be short noun phrases; a value with several
  quantities = one entry each (faisal: tube volume / diameter / length now separate).
  `_models(spec_json, categories)` caches per category set. OtherParameter now carries
  `sample_label` (was dropped) and `category`.
- `new_variables._categorised` assigns + formats; NewVariable.category / format_note;
  `group_new_variables` sorts by category order. `stored_value`: a column with no unit keeps the
  printed text ("45 min"), not a bare number. Bare lowercase "m" is refused in formatting (units.py
  reads it as molar; faisal's "20 m" tube length had become 20 M -> `_mM`).
- Review window: header line per category (label, count, format, description), ⚠ on values with a
  format note; methods taking `row` mean the group index (`_table_row` / `_group_at` map).
  Flags: "New experimental parameter 'x' (Reaction Conditions) ... Format: ...".
- **Switch** `RunConfig.suggest_new_variables` (default True; GUI "Suggest new variables" in the new
  Options dropdown, QSettings `suggest_new_variables`; CLI `--no-suggestions`). Off: open-ended
  stages run without `other` (`optional.for_run`, also in `_paper_tools` so the cached tool list
  matches); the review shows only assumed values and the user's search-term findings; everything
  else -> one `new_variable` flag listing names by category; new_variables.json unchanged.
- GUI: Batch / arXiv text / LaTeX / Suggest new variables moved into one "Options:" QToolButton
  dropdown (QMenu of QWidgetAction checkboxes -- menu stays open while ticking; attribute names
  batch_box/arxiv_box/equations_box/suggest_box unchanged; `option_toggles()` lists them; the button
  text names what's on).
- Live faisal2005 (standard, $0.22): 20 suggestions -- 4 species, 3 solution prep (mixing ratio,
  degassing, Gly-Gly stock 30 mM), 7 conditions (residence time "10-200 s" -> format note; tube
  volumes in mL), 1 metadata (supplier + purity), 5 methodology (quenching, pumping, back-pressure
  regulator, ...). Exoplanets have no open-ended stage, so only the shared categories (for search
  findings); candidate categories if one is added: Observations & Data, Stellar Activity.
- **Round 2 (2026-10-27, Mickey + exoplanet specialist):** prebiotic Chemical Species split into
  Starting Species (sources species:initial, species) and Products (species:sampled); new assignable
  Analysis category (instrument, column, eluent, wavelength, standards, detection limit) and the
  conditions step's open_ended_hint no longer EXCLUDES analysis details (it asks for them, one entry
  each). Exoplanets: categories Observations & Data, Stellar Activity, Data Reduction and Software
  (text, 15 words), filled by `system_and_discovery` (now open_ended, hint excludes parameters other
  steps record -- incl. rotation period / v sin i -- and priors/assumptions). Repeat checks
  (ingestion/duplicates.py, duplicate_removed flags, repeats_left_out): `drop_recorded_software`
  (a data_reduction item naming ONLY software the fit_models step recorded) and
  `drop_repeated_values` (value = just numbers + units, <= 2 other words, ALL numbers are values of
  ONE parameter -- column minus alt/mode/err/lim suffixes -- on its rows; a distinctive number needed).
  Live (Standard): nielsen2019 $0.24, 19 suggestions (7 observations, 4 activity, 8 reduction/software;
  the 42.5 +- 3.4 d rotation repeat of st_rotpalt1 now dropped); faisal2005 $0.25, 4 analysis items
  (amino acid / organic acid / ion chromatography columns + detectors, TOC/TN analyzers).

## Developer handoff; Economy consistency (2026-10-29, Mickey)

- **Handoff (developer only)**: `handoff.py` + `dev_features.py`. RunConfig.handoff_dir -> api_client
  `_send_mapping_errors` writes each request to `<dir>/<paper>/requests/<step>-<sha8 of task>.md` (instructions,
  inputs: paper.txt + images/, task, answer JSON Schema by alias) and raises `AnswersNeededError`; answers in
  `answers/<key>.json` are validated (bad -> `.error.txt`, `invalid`). pipeline `_all_requests` gathers a
  whole round (structure+metadata, then the parallel steps). No API key needed; cost recorded as none
  (model "claude-code-handoff"). Gate: source runs need PARAMETER_EXTRACTOR_DEV=1; built apps need the
  DEV_BUILD marker -- only `packaging/build_macos.sh --dev` ("Parameter Extractor Dev.app", no .dmg) adds it
  and handoff.py; the public spec EXCLUDES parameter_extractor.handoff; `--self-check` fails a public build
  that contains it. Why: Anthropic doesn't allow third-party products to offer claude.ai login /
  subscription limits (Agent SDK docs). GUI: Settings "Developer" group (only when enabled), QSettings
  dev/handoff(_dir); CLI `--handoff DIR` (hidden otherwise). Figure suggestions in handoff mode also
  write requests (answer, then ask for the suggestion again). tests/test_handoff.py: 3 rounds from
  eder1994's reference answers reproduce its CSV byte for byte.
- **Economy errors are mostly consistent, not random** (eder x5, faisal x3 live, $0.009-0.018 a pass; later
  passes read the first one's cache). eder: every miss was systematic -- duration_hr never filled (Haiku
  labels "t = 97.3 h" but leaves the field null) -> `structure_planner.fill_durations` reads it from the
  label; solvent "distilled" -> water.py now names bare types. After: 5/5 passes = reference except
  analysis_method wording. faisal: 74-84% per pass (wording forgiven), majority of the non-empty values
  over 2-3 passes 89.5% (random dropped blocks: T/pH in one pass, the NH4+ column in another); the rest
  consistent: sampled_pressure_bar (spec said "if different" -- now a rule like sampled temperature) and
  the Gly-Gly 30 mM STOCK concentration (goes to suggestions instead of stock_ -- Standard too in new runs).
  Voting not built (Mickey to decide).

## Passes + vote, data_location, sealed-batch pressure (2026-10-29, Mickey)

- **Passes** (`voting.py`, RunConfig.passes 1-3, GUI Run options "Passes", CLI `--passes`, QSettings
  `passes`; forced 1 in handoff): chemistry and the pack's spec stages run N times at once on ONE
  structure plan (pipeline `_voted`, inner thread pool; `api_client._streamed.pass_suffix` -> files
  `<stage>.passN.output/audit.json`; the voted answer is saved as `<stage>.output.json` + an audit with
  `voted_from`, so replays reproduce the voted run). Vote: items keyed by what they are (set, sample,
  column/species via names.match_species, role, basis, mode, method), compared by converted value (spec
  stages) or the printed number (chemistry -- a pass that dropped the unit still agrees; the copy WITH a
  unit is kept); the most common value among passes that GIVE one wins (dropouts don't vote), ties ->
  earliest pass; a winning pass's extra items for the key are kept (normal conflict flags). Disagreements
  -> `pass_disagreement` flags grouped per step + column/species (GUI group "Passes disagreed").
  Structure, metadata, term search, fit_models run once. A failed pass is skipped if one succeeds.
  Live Economy x3 (eder1994 $0.039, faisal2005 $0.037; Standard ~$0.24): both 100% of the references'
  values with wording forgiven (scratch scorer counts analysis_method/vessel/headspace/solvent as
  present/absent). Single Economy passes on faisal were 74-84%.
- **data_location** (`ingestion/data_location.py`, packs/common_columns.json -> every pack): "Figure. 1",
  "Figure. 3b", "Table. 2", "Table. S1", "Text: <section>" / "Text" -- format from Mickey's example
  ("Figure. 1"), constants FIGURE/TABLE/TEXT. build_rows: first source naming a table/figure (sample's,
  then set's); text rows use the SET's source (one value per passage), leading "Main text"/"Text"
  dropped. figure_rows: the figure id. All stored replay outputs regenerated with a checker (only
  data_location differs; backup of runs/ in the session scratchpad).
- **Sealed batch -> 1 bar** (`calculators/pressure.py`, prebiotic postprocess "atmospheric_start"):
  new conditions parameter `vessel_sealed` (sealed/open, choices; a pack standard column). Batch +
  sealed + no initial_pressure_bar -> 1.0, provenance "assumed: ...", ONE `assumed_default` flag for
  the paper; digitized rows use the paper-wide vessel_sealed. Next (not built): sampled_pressure_bar by
  Raoult's law (needs water's vapour pressure vs T, composition, volumes).
- Prompt: sampled_pressure_bar now follows the sampled-temperature rule (faisal live: captured).

## kim2017 via developer handoff (2026-10-29): nucleotide paper, compound numbers

Mickey's first nucleotide paper (`Paper Lists/Nucleotide Papers/Kim2017/kim2017.pdf`, Kim & Benner,
Chem. Eur. J., nicotinamide ribose phosphate by dry-down with Ca2+ / ammonium formate). Run through
handoff with Claude Code answering (3 rounds). Every value correct after "Add all as suggested" (14 yields
of 7, 6 recovered nicotinamide, stocks + calculated mixtures, T, times, HPLC details). Fixes from it:
- pdf_parser: SymbolMT glyphs in the private-use area (U+F000 + Symbol code: U+F06D µ, F061 α, F062 β)
  were dropped -> "5 L" for 5 µL. `_symbol_private_use` maps them (Greek, µ, °, ±, ×, ≤, ≥ ...).
- Flags: mixture concentrations calculated from stocks -> ONE derived_value flag per species
  (`pipeline.grouped_mixing_flags`, MixingNote.species/short; was 32 flags); a paper-wide ASSUMED value
  -> one review line / flag for the rows of the step's target sets (was one per set).
- quotes.unnamed_species: a table cell is named by its column header in the source ("column Recovered
  Nicotinamide (%)") -- the '<row> <value>' quote can't be placed on a page.
- Prompts: compound numbers ("nicotinamide 6", "Yield of 7") and inline citations ("ammonia.14") are
  never values -- rules in chemistry.md (name by name, number in `how`), structure_planner.md and the
  shared optional_stage.md. Spec field `alternatives_rule` (the default's examples were astronomy);
  experimental_conditions has a chemistry one.
- Category formats: µL values keep a `_uL` column.
Not done: a reference run (answers are Claude-Code-written, not the app's models).
- **Follow-up (same day): %recovered + live Standard reference.** `SoluteEntry.measure` / TableColumn
  `meas` ("yield" | "recovered") -> `sampled_<name>_%recovered` (flatten_to_template.percent_suffix; also
  from a column header saying recovered/unreacted/remaining -- older answers); alias "sampled X %
  recovered", registry display "measured, % recovered", unit %. Live Standard ($0.16-0.18) found:
  Sonnet planned Table 1 as ONE set whose samples differ by the ammonium formate volume and put those
  volumes in as "concentrations" (µL). Now `AddedSolution.sample_label` (mixing per (set, sample):
  solutions_for / _missing_solutions / derive_mixture_concentrations(samples_by_set)),
  `mixing.volumes_as_concentrations` repairs a volume-unit "concentration" of a species that has a stock
  (-> its stock's added volume, `unit_conversion` flag grouped per species), "volume added" values land
  on their sample's row; structure prompt: duration for every sample incl. a caption's fixed time; the
  Reaction Conditions category and the conditions hint no longer suggest reaction time (= duration_hr).
  Reference `runs/reference/kim2017/` (second live run; every value correct after accepting all
  suggestions; local only, like all of runs/).

## Focused search rows = the pack's rows (2026-10-30, Mickey's eder1994 focused test)

Focused search had no row planning: one call per paper, `obj` chosen by the model from a hint ("the
sample or experiment set") -> eder1994's rows were whole experiment sets. Now:
- Answers have two levels like a structure plan: `set` (field `grp`, alias "set") + `obj` (the sample),
  and `rows` (every row of the paper's results). `wide_rows`: one row per (set, sample); a set's values
  (obj '') fill each of its rows, paper values ('' / '') every row; a set with no samples is its own row;
  old answers (obj only) unchanged. CSVs and the window get a set column (headers from pack units).
  Pack rules `prompts/focused_search.rules.md` (prebiotic: set = condition / table block, obj = time point,
  cycle, entry; compound numbers / citations; exoplanets: set = host star, obj = planet [fit]).
- **Rows as in a full extraction** (`plan_rows`; pack.json `focused_row_plan`, true for prebiotic; window
  checkbox per pack, QSettings focused/<pack>/plan_rows; CLI --plan-rows / --no-plan-rows): the pack's
  structure planner runs first (whole text + table images), the focused prompt gets the plan's labels and
  the table images, outcome.rows = the plan's rows. Live eder1994 Economy, 2 parameters: 42 rows as a full
  run, per-set temperatures, $0.010 (without: 2 invented sets "long-time / short-time", $0.002). Without
  table images Haiku couldn't read eder's garbled table text -- prompts alone can't fix that.
- Prompt: an introduction summarising earlier experiments is other work (eder's "argon" came from it).
- Follow-up: eder1994 focused "80; 81" -- the 80 °C was the untabulated short-time vial experiments ("oven at
  80 °C", Fig. 1), answered paper-wide. `wide_rows` now keeps only the most specific level per parameter
  (sample > set > paper, like a full run); prompt: '' set only for values that hold for every row; values
  from experiments that aren't rows are left out. (Not initial vs sampled temperature: the tables give one
  reaction temperature per condition.)

## Averages, category bar charts, supplementary information (2026-10-31, Mickey's test set prep)

- **Averages**: SetType "Average" (results averaged over runs whose individual values aren't given; individual
  runs given -> "Independent" rows + the average on each row of the set). `SoluteEntry.average` /
  TableColumn `avg` -> `flatten_to_template.with_average`: '_avg' before the unit ('sampled_2peptide_Gly_avg_mM',
  'initial_NaCl_aq_avg_mM', '..._avg_%yield'); alias "... avg"; `SoluteEntry.variable` includes avg; peptide
  avg columns known (registry regex), excluded from peptide totals; set-wide averages (no sample) go on
  each row of the set. Figures: `AxisVariable.average` -> avg column + set type Average.
- **Category bar charts** (Riggi2023 Fig. 2: one bar per mineral): planner rule -- one series per bar, the
  category as a condition, x column null; figure_rows accepts a y-only calibration when x has no column
  (`calibration.pixel_to_y`).
- **Supplementary information** (`ingestion/supplements.py`): '<paper>_SI.pdf' / ' SI' / '-ESI' /
  '_supplementary' / '_supporting information' next to the PDF is read with it (RunConfig.include_supplements,
  Options "Include supplementary information", CLI --no-si): `ParsedPaper.add_supplement` appends its pages
  (marked header telling steps to cite 'SI Table N'), table pages renumbered after the paper's and rendered
  from the SI file into page_images/SI (api_client labels them "Supplementary information page S<n>"),
  `page_label` shows S<n> in provenance/flags, a paper_source flag. Queues and focused searches fold SI files
  into their papers (`drop_supplements`). Table captions 'Table S1' recognised; contents pages (>= 3 dot-leader
  lines) aren't table pages; data_location 'SI Table 1' -> 'Table. S1'. Figures: main PDF only (not yet SI).

## Test Paper List via developer handoff (2026-10-31, Mickey's "Paper Files/Test Paper List")

Six papers run with the prebiotic pack in handoff mode (answers written by Claude in the session, so
the Standard / batch settings didn't apply to them): eder1994 42 rows (= reference except analysis_method
wording), kim2017 14 (= reference; my metadata answer said 2017 -- the accepted-manuscript PDF prints no
year, the live reference's 2018 is the version of record), pulletikurti2022 30 (all from SI Tables S1-S3,
every value checked), tapiero1971 6 (all correct incl. %recovered and ratio columns), Riggi2023 0 and
mizuuchi2019 0 (results only in figures -> digitizer).
Fixes from the evaluation:
- Table cells: '%' after a number or a +- value parses (pulletikurti lost 45 of 60 values silently);
  a dash with a footnote mark is empty; any other unreadable cell is KEPT with no value and grouped into a
  `value_not_read` flag (was dropped without a trace). `meas` "ratio" (u "ratio") for product ratios.
- Assumed values grouped into one flag per (parameter, value); `concentration_not_stated` only for starting
  species, with the reason.
- Auto-calibration (`digitizing/auto_axes.find_frames`) on spreadsheet-style charts: if no dark corner frame,
  a FAINT (< 232) pass with shorter lines (pale axes, small panels -- mizuuchi Fig. 1A-C) whose interior is
  mostly blank (not the gel photo), then `_grid_frames`: >= 3 evenly spaced fully inked horizontal gridlines
  with the same right end (labels glue onto the left end), several runs per group (panels stacked in a
  column share ends), extended down through bars that hide the lower lines; `Frame.gridlines` are the y
  ticks (`_pair_with_gridlines`: top line = highest number, every k-th line if fewer numbers). Riggi Fig. 2:
  all 5 panels 0-6 on the gridlines; mizuuchi: axes snapped to the line when the lowest number sits <= 6 px
  off it. Digitizer: a categorical x axis says "no calibration needed".
- Figure planner (live, Standard, ~$0.07-0.13/figure): species missing from the vocabulary are now given
  (Riggi ImpA 15 mM, mizuuchi RNA 0.6 uM each) -- the vocabulary heading had read as a restriction;
  `max_peptide_length` only for peptides. An axis no column fits is no longer a dead end:
  `figure_rows.axis_column_from_label` ('Length (nt)' -> length_nt, averaged 'Relative RNA concentration'
  -> relative_RNA_concentration_avg) -> reviewed as a new variable (was "neither axis assigned -- left out").
Open: SI figures (main PDF only), text-only averages (excluded by the tables-only rule), Riggi's PDF text
layer carries overlapping draft text.

## SI figures, image options, text-only averages, ranges, Tables tab (2026-10-31, Mickey's answers)

- **SI figures** are offered for digitizing: `find_figures(si, supplement=True, page_offset=...)` (SI_CAPTION_RE
  takes 'Figure S1' or the SI's own 'Figure 1') -> 'Fig. S<n>', files fig-S<n>.png / page-S<p>.png,
  `FigureCandidate/DigitizedFigure.supplement` + `page_label` ('S8'), `.tag` ('S1') for file and audit names
  (annotate, figure_planner.fig<tag>), figure_passages(..., supplement) matches 'Fig. S1'. Review dialog:
  "Skip the supplement's figures" (pulletikurti2022_SI has 90, mostly NMR spectra), pages shown as
  "supplementary information, page S8".
- **Images** (RunConfig `save_images` default True, `save_all_figure_images` default False; Options menu
  "Save table and figure images" / "Also keep images of figures not digitized"; CLI --no-images /
  --all-figure-images): figure renders are needed for the review, so `pipeline._tidy_figure_images` removes
  them in finish() -- digitized figures' crop/page/annotated image kept unless save_images is off; the
  fig-N.digitized.json (data) always stays; summary entries get `image_note` (shown in the Figures tab).
- **Tables tab** (`ingestion/table_finder.py`, local): on the parser's table pages, "Table N" captions
  (column-aware like the figure finder), the block below to the next caption / a gap > 4 lines / two lines
  of running text (`_is_running_text`: long, few numbers, no column gaps; for full-width tables either half
  of a merged two-column line), the block above if nothing is below, rows crossing the middle -> full
  width, a mostly-crossing page = one column; the crop is widened to the ink across the table's rows within
  its column. Landscape (turned) pages: whole page, upright, named by the parser's caption (faisal2005's
  Table 1). -> <run>/tables/table-N.png (SI: table-S<n>.png) + tables.json, RunResult.tables, GUI "Tables"
  tab. Checked on eder1994 (scan), kim2017, kim2019, truman2024, tapiero1971, Riggi2023, pulletikurti SI,
  faisal2005, teng2023. Failures never stop a run (note only).
- **Text-only averages** (Mickey: no rows of their own, but a column on rows of the same set): chemistry
  prompt -- an average stated only in the text for a planned set goes in `groups` with that set, no sample,
  `avg` true (build_rows already puts set-wide averages on each row of the set); averages for experiments
  that aren't rows are left out. Structure prompt says they never get rows.
- **Ranges** (Mickey: keep them; '<name>_range_<unit>', cell 'low:high'): units.parse_range (low < high only,
  so '10-4 M' stays an OCR-lost exponent), format_range, range_to_column_unit; flatten_to_template.with_range /
  without_range; registry: the range of a known column is known. Sources: figure conditions
  (convert_condition, also pH '6-7'), spec stages (item field `hi`, alias; a range only when hi != 0 and >
  v -- a negative value with the default 0 isn't one: st_radv broke the aa57186 replay), chemistry
  (`SoluteEntry.concentration_high` / `hi`, table cells '5-10' via `_cell_range`; normalize writes
  `concentration_range` text, % / ratio as printed else mM, and concentration_mM None -> never in
  calculations), review values (`_categorised` / `stored_value`: '10-200 s' -> residence_time_range_hr
  '0.00277778:0.0555556'). One `value_range` flag per range column. Prompts: optional_stage.md and
  chemistry.md (`hi`).
- Live faisal2005 Standard x2 ($0.23, $0.18): 25 rows = reference except wording; one run dropped the
  per-sample sampled_pH (variance: the second had all 25).

## Appendix figures + overprinted text (2026-10-31, Mickey: Riggi2023's Figures A1/A2 were missed)

Two causes: CAPTION_RE needed a digit right after 'Figure' (appendix numbering 'Figure A1'), and Riggi's PDF
draws its text in several overlapping copies (two clean ~11 pt apart + one with spaces run together), so the
line read 'Figure FigureA1.X-ray... Figure A1'. Now: CAPTION_RE `([A-RT-Z]?)(\d+)` -- 'S' stays reserved for
supplements, so a paper line citing 'Figure S1' isn't a caption; candidates keyed (letter, number) -> 'Fig. A1',
`FigureCandidate/DigitizedFigure.prefix`, `.tag` 'A1' (files fig-A1.png, audit names), figure_passages(prefix=).
`figure_finder.drop_overprinted` (also in table_finder): drops a word repeating a kept word's text within a few
points, a run-together word that is just the words it covers, and a doubled-character word over its copy.
Tables: 'Table A1' too (table_finder keyed (letter, number); pdf_parser.TABLE_CAPTION_RE `[A-Z]?\d+`);
data_location / quotes._TABLE_REF accept the letter ('Figure. A2', 'Table. A1'). Old vs new finder over all 88
PDFs in Paper Files: only Riggi2023 (+A1, A2) and iqubal2017 (+Fig. 15, same overprint problem) changed.

## Digitizer: suggested new columns, category axes, rounding (2026-10-31, Mickey's Riggi2023 Fig. 2 run)

His run: the planner gave no y column (he typed 'avg_max_linear_oligomer_length_n'; with_average then made
'..._n_avg'), and the bar chart's x became a numeric 'mineral_category' review item holding pixel garbage.
- `AxisVariable.new_column` (planner: a new snake_case column with its unit suffix when none fits; prompt +
  prebiotic rules) -> loaded into the digitizer's column field (`digitizer._with_new_column`, '_avg' added for
  averages) with a hint "New variable: offered in the review"; empty field + placeholder when nothing chosen
  (hint names the label-derived column it will get); choosing "(none -- not stored)" sets `store` False (hidden
  field) -> figure_rows makes nothing up. figure_rows: column -> new_column -> label name (if store).
- `AxisVariable.categorical` (bar charts: x column = where the category goes, e.g. solid_material_name; the
  planner repeats the category as a series condition): `calibration.is_categorical` (flag, or no column and no
  x calibration); no x number is ever written; the category goes in x.column from the series' condition, else
  its label minus ' [marker]' (unknown column -> review with the text). Digitizer "categories" checkbox, hover
  and points table show y only.
- **Rounding** (`AxisVariable.decimals`, hidden from the model; digitizer "round:" exact / whole numbers /
  1-3 decimals per axis): `calibration.snap` solves both projections for the rounded values (category axis:
  moves along y only); points snap when added, while dragged (PointItem ItemPositionChange) and when the
  setting changes; figure_rows rounds the stored values too.
- with_average leaves a column that already has an 'avg' word alone.
- **Planner answers**: every field of the plan's models REQUIRED in the sent schema (`schemas/figures._require_all`;
  the planner uses a non-strict tool, where defaulted fields are optional): live, Sonnet once returned no
  `panels` at all and once looped inside an axis `note` ("ok. --- end. ..."). `plan_figure` asks once more when a
  data plot comes back without panels, then a PipelineError. AxisVariable.note described/capped (NOTE_DESC).
  Live after: Riggi Fig. 2 x2 -- 5 panels, x categorical -> solid_material_name, y new_column
  max_linear_oligomer_length_nt (avg), ImpA 15 mM; mizuuchi Fig. 1 -- RNA_length_nt / relative_RNA_concentration_*.
- tests/test_digitizer_columns_rounding.py.

## Ambient conditions, positive / negative controls (2026-11-01, Mickey's Riggi2023 run)

- **Ambient** (Mickey: 'ambient temperature' = 25 °C, 'ambient pressure' = 1 bar, for the experiments referred to,
  unless stated otherwise): experimental_conditions rule (replaces "never assume room temperature"): where the
  paper SAYS ambient / room temperature / r.t., initial (+ sampled) temperature 25 °C, b derived, n 'ambient
  temperature = 25 °C'; ambient / atmospheric pressure -> initial_pressure_bar 1; a value stated for particular
  experiments wins; never in `other`. Safety net `calculators/ambient.apply_ambient` (pack postprocess
  "ambient_conditions", run in extract_steps BEFORE `_collect_other_parameters`): 'assumed' ambient items ->
  derived; `other` items saying ambient temperature/pressure -> the parameters (where none given for those
  experiments), the entry dropped if that's all it said; one `assumed_default` flag per convention used
  (`Extraction.ambient_notes`). His run had put it in `other` ('temperature conditions') and quoted 1 bar from
  the Discussion; live after the change the step itself gave 25 °C / 1 bar from the Methods sentence.
- **Controls**: `positive_control` / `negative_control` (text, <= 12 words) in the prebiotic conditions spec
  (spec columns = known standard columns); rule: same wording for sets sharing controls, set '' when all do.
  Figure planner rule: series-specific controls as conditions.
- **Digitized rows now get every paper-wide stage value** (`pipeline._paper_wide_values` -> build_figure_rows
  `paper_wide=`, written where the series has none; the series' own conditions win) -- before, only the
  Methodology fields reached them (controls, solid mass, vessel_sealed ... didn't).
- Figure planner + digitizer column list = registry.known_columns() (template + pack standard + accepted),
  not just the template (vessel_sealed, positive_control were not offered).
- Live (Standard, $0.19) + Mickey's Fig. 3 / Fig. A2 digitizations: 7 rows, all 25 °C / 1 bar / both controls.
  tests/test_ambient_controls.py.

## Column order by category (2026-11-02, Mickey)

The CSV (and the Rows tab) is no longer in PaperDataTemplate's order (the paste-parity decision of 2026-10-14
is superseded): `column_order.ColumnOrder` -- entry_number, full_id, set_id, sample_id; then one block per
variable category by `table_order`; provenance (yield_below_threshold_note, source_notes, extraction_confidence)
last. All template columns are still written (empty ones too), so every paper's CSV has the same columns.
- Configured, not coded: `VariableCategory.columns` (names), `.patterns` (regex), `.table_order`; pack.json
  `category_columns` {category id: {columns, patterns, table_order}} adds to any category (shared included);
  column-only categories = model_assigns false (never offered to the model). Shared file: metadata (10; paper
  columns, data_location, original_data_reference), methodology (20), NEW `other` (900, assignable: "only
  when no other category fits"). Prebiotic: methodology (set_type, experiment/solution type, vessel, solvent,
  controls), conditions 30 (duration, T/P/pH, volumes, flow, solid material, wet-dry), analysis 40
  (analysis_method), solution_prep 50 (^added_), starting_species 60 (^(initial|stock)_, AA identity),
  products 70 (^(total_)?sampled_, ^max_.*length, peptide flags). Exoplanets: metadata (pl_name, hostname, ids,
  pl_refname...), discovery 25, planet 30 (^pl_), star 40, system 50, fitting 60 (^(pl|st)_fit, matched before
  ^pl_ by definition order), then the suggestion categories 70-80.
- Placement: explicit column > the category it was accepted under (this run: accepted[*].category -> 
  write_template_csv(column_categories=); remembered: registry added_columns[col]["category"], add_column(category=))
  > its base column (longest known prefix + '_' / archive suffix err1/lim/mode/alt/prior; range/avg markers
  stripped) > first matching pattern (definition order) > Other. In a block: explicit order, template, standard,
  name; derived after the value: range/avg, then err (+ before -), modes, alternatives, priors.
- Rows tab: CSV order minus empty columns; `gui/widgets.ColumnGroupBand` -- a separate strip above the table
  naming each block ONCE, centred over its visible columns, following scroll/resize (tooltip = full name).
  It replaced a QHeaderView subclass painting the band, which on Mickey's native macOS style showed the
  category over every column (offscreen screenshots looked fine -- check GUI drawing with the native platform:
  run without QT_QPA_PLATFORM=offscreen and grab()). Header items = plain column names (UserRole too);
  alternate blocks tinted (GROUP_TINT, flag/archive colours win). LEADING/TRAILING_COLUMNS gone.
- Categories in the files (the dataset CSV keeps ONE header row -- pandas, spreadsheets, the combined queue CSV):
  observations CSV has a `category` column; `<paper>_columns.csv` lists every column with its category.
- Reference CSVs (runs/reference/*, runs/*_auto) reordered by a checker (same cells per row, new order; backup
  in the session scratchpad); replays reproduce them byte for byte. tests/test_column_order.py.

## One name per species; stock values as solution preparation (2026-11-02, Mickey's Riggi2023 run)

His run had ImpA three times: the chemistry wrote "adenosine 5'-phosphorimidazolide (ImpA)" as a STOCK value
only, mixing derived an identical mixture value under that name, the figure series said "ImpA"; plus a
conditions `other` "ImpA stock concentration".
- `names.abbreviations_in(text, names)` ('full (ABBR)' in a name, or a multi-word name the paper's text
  defines as 'full (ABBR)' -- words matched across '(cid:48)' / primes) + `preferred_name` (the abbreviation,
  unless only the full name is a vocabulary species; roman numerals / lowercase '(aq)' aren't abbreviations).
  Applied in normalize_chemistry (abbreviations=, `_rename` notes) and figure_rows (abbreviations=);
  `Extraction.abbreviations` from the chemistry + digitized series names. Prompts (chemistry, figure_planner
  rules): one name per species, the paper's abbreviation; a stock used as the reaction solution itself ->
  also the mixture value; no plan sets (figure-only paper) -> composition with set ''. Conditions hint: stock
  solutions are not `other`.
- `new_variables._without_repeated_calculations`: a calculated value is dropped from a review line where stated
  values with the same number cover its rows.
- Stock concentrations: review category solution_prep (source species:stock), column order ^(added|stock)_ ->
  Solution Preparation; starting species = ^initial_.
- Live Riggi (Standard, $0.08 after the prompt fixes): ImpA stock + mixture 15 mM under one name; review:
  initial_ImpA_aq_mM (figure + chemistry, one line), stock_ImpA_aq_mM and the 100 uL volume under Solution
  Preparation; three 'other' restatements dropped as repeats (one was the halite negative control's
  description -- over-eager but flagged). An earlier live try returned NO chemistry (no sets) -> the no-sets rule.
  tests/test_species_names.py.
- Repeat check narrowed (Mickey, 2026-11-02: "a little redundancy is preferable to missing values"):
  `duplicates.drop_repeated_amounts` drops an other-parameter only if, besides every amount matching the
  chemistry, nothing is left after removing the amounts, the MATCHED species / solution names and framing words
  (`_FRAMING`: stock, solution, prepared, ultrapure water, ..., molar ratio) -- `_says_more`. Kept now: Riggi's
  "15 mM ImpA in saturated NaCl, no solid phase" (halite negative control), "15 mM ImpA in NaCl" (another
  species), "... in ultrapure water, no other salts"; still dropped: "15 mM ImpA stock solution", kim2019's
  "20 uL, 3.75 mM in case of 1:1 molar ratio". kim2019's "0.5 M ammonia solution, with acetamide added" is now kept
  (was dropped: the acetamide would have been lost).

## New prebiotic parameters; token pass on the structure and figure steps (2026-11-03, Mickey)

- Conditions-spec text parameters (often suggested): `pH_buffer` ('none' when stated; Solution Preparation),
  `reagent_suppliers` (Metadata, after the paper columns: the pack lists metadata's full order),
  `replicates`, `stirring_agitation` (Experimental Methodology); excluded from `other` in the hint. Live Riggi:
  none / Sigma-Aldrich ... / triplicate, averaged / vortexed briefly, then undisturbed.
- Audit (Mickey's Standard Riggi run, $0.39): figure_planner $0.19 (Fig. 2: 13.6K OUTPUT tokens, 63% of it
  conditions repeated on all 29 bars), structure_planner $0.13 (= the paper's cache write: text 29.3K, tools
  10.6K, table-page images 9.4K tokens; its own output small). count_tokens is free -- use it for audits.
  1. Figure answers say each condition once: `FigurePlan.shared_conditions` (merged into every series by
     `digitizer._with_shared`, the series' own value wins); conditions the paper states for ALL experiments are
     left out (the app fills them -- _paper_wide_values); shared compositions via `concentrations` series [].
     Prebiotic figure rules rewritten (one composition paragraph). Fig. 2 live: 13.6K -> 5.3K output, $0.19 -> $0.10.
  2. Figure prompt column list: `figure_planner.planner_columns` drops derived variants (err/alt/mode/prior/
     range/avg) and Row/Metadata/Provenance columns: 354 -> 209 columns, ~6K -> ~3.3K tokens of the prefix.
  3. Table images: `pdf_parser._table_crops` sends the table finder's crops (220 dpi, tiled if large; labels
     "Page 4, Table 1 ...") instead of the whole page, for pages where EVERY captioned table was found (else
     the page, as before; landscape pages whole). eder 10.1K -> 2.5K, kim2019 4.4K -> 0.7K, Riggi 9.6K -> 3.1K
     image tokens. Live eder (Standard, $0.25): 42/42 rows = reference except analysis_method wording.
  4. Tool schemas: `api_client.model_facing_schema` strips pydantic titles and class docstrings (dev notes):
     prebiotic tools 10.6K -> 8.8K tokens, exoplanets 9.5K -> 8.3K.
  Riggi cached prefix 49.7K -> 41.4K; structure step $0.134 -> $0.113; typical Riggi run ~$0.39 -> ~$0.29.
  Not done (small or risky): short field names for the structure plan (~20% of its ~4K output tokens; the prompt
  names fields), dropping the reference list (5K tokens on Riggi, but cited-data references come from it).
  tests/test_token_pass.py.

## Structure plan short names; two conditions rules; written-out powers (2026-11-03, Mickey)

- `schemas/structure_plan.py`: the model answers with aliases -- sets / set, type, varies, src, ds, samples /
  label, hr, src; n_rows, excluded; paper_id hidden (unused). populate_by_name: saved answers
  (structure_planner.output.json, model_dump = full names), the other steps' prompts (plan JSON with full names)
  and recorded answers are unchanged. Both packs' structure prompts reworded (legend + short names; sample `src`
  brief, 'Table 1, row 3'). Measured: 8-15% of the plan's output tokens (count_tokens on references) -- small,
  as expected; live eder 3.6K vs 3.75K, kim 1.6-1.9K vs 2.0K, truman 1.0K vs 1.25K.
- Consistency checks (live, Standard, vs references): eder1994 42 rows, every cell equal; kim2019 13 rows,
  same plan shape; truman2024 8 rows; aa57186 same plan (fit-model free text wording differs).
- Found on the way, NOT caused by this change (bisected: replayed reference plan + live steps; spec versions
  of earlier rounds): kim2019's conditions step dropped sampled_temperature_C and the summed solvent volume in
  every full live run. Rules clarified: sampled_temperature_C = the temperature when sampled or stopped -- for
  heated reactions, dry-downs and wet-dry cycles the heating temperature; solvent_volume_mL = the sum of the
  combined solutions' volumes when only those are given (b derived). After: 2/2.
- Wet-dry cycle durations: the curated dataset's Evaporation Cycle rows are CUMULATIVE (cycle n of 24 h ->
  24 n h; varying lengths add up) -- structure prompt rule; truman live 24/48/72/96.
- `chemistry._cell_number` reads written-out powers ('10^-4', '10⁻⁴', '1e-4', '2 × 10^-3'); a bare '10-4' is
  still refused (lost superscript). truman Table 2's starting Gly was unread before.
- Test-harness note: replaying the structure step only (make_replay for that stage, real _send for others)
  is the way to isolate a downstream step; a replay of every step except one sends that step no cached paper.

## Figure suggestions on the cached paper: built, measured, OFF (2026-11-03, Mickey's request)

`RunConfig.figure_suggestions_on_paper` (default False): figure_planner reads the extraction's cached paper
(api_client `call_structured(on_paper=True)`: paper blocks, then the figure instructions as a 2nd cached layer,
then the figure image + text; answered via the shared tool list -- `_paper_tools(has_figures=)` adds FigurePlan)
while `PaperContext.fresh()` (used < 4.5 min ago, 55 with the 1-h cache; every shared request refreshes
`last_used`); composition passages are dropped on that route (whole paper present).
Measured live, Riggi2023 Standard, Figs. 2, 3, A2 in turn (figure calls; input-only cost, since output varies):
own prompt $0.074 / $0.024 / $0.012 per figure; on paper $0.063 / $0.035 / $0.024 -- reading the ~45-52K cached
paper per figure costs more than the figure prompt's own 14K-token cache from the 2nd figure on, and the
figure tool adds ~3.5K tokens to EVERY run's cached prefix (+$0.016 with no figures). 0/1/3 figures:
+$0.016 / +$0.005 / +$0.028 on paper. Quality no better (it added Methods-wide conditions like 'ambient' per
series). Kept as an option; the earlier claim that it would save money was wrong.
Fixes from the runs: convert_condition reads '72 hr (3 days)' (a bracketed restatement) and 'ambient' /
'room temperature' -> 25 °C, 'ambient' / 'atmospheric' pressure -> 1 bar.

## Haiku vs Sonnet evaluation for the prebiotic pack (2026-11-03, Mickey)

Full write-up: `eval/model_comparison_2026-11-03.md` (37 live runs, 5 reference papers; configs S = current,
Hext = Sonnet structure + Haiku chemistry/conditions, Hall = Haiku everything; x1/x2/x3 passes). Mean accuracy
vs the Sonnet references / mean cost per paper: S 98.8% $0.193; Hext x1 98.6% $0.092; Hall x1 96.5% $0.013;
Hall x3 98.7% $0.031. Haiku's systematic miss: truman's NaCl stated once in the running text (8/8 runs).
Handoff mode can't evaluate a model (the answers are Claude Code's). Cost-measurement gotcha: runs of one paper
back to back read each other's cache -- re-price each model's first cached read as the write (scratch
haiku_agg.py). No default changed (Mickey decides; prebiotic was "Sonnet must stay" on 2026-10-27).
Fixes from it: `voting.vote_chemistry` takes the combined solutions from ONE pass (the volume list most passes
agree on) and points stock values at its names -- per-name voting kept "calcium chloride solution" AND
"CaCl2 stock" (16 uL), mixing refused (kim2017/kim2019 lost CaCl2 under passes); open-ended `other` items
written like parameter values (v number + u / txt) are read as text (optional._OtherBase) -- Haiku's kim2017
conditions step had failed validation twice.
Mickey's decision (2026-11-03): Standard stays the default; NEW profile `balanced` (settings.MODEL_PROFILES:
Sonnet structure_planner, Haiku "*"; figure_planner/equations exempt -> Sonnet) as the mid option (GUI "Models",
CLI --models balanced); Economy + 3 passes covers the all-Haiku option. Model / Passes hover texts rewritten short
with 2026-11-03 costs + accuracy and recommendations (balanced not recommended for exoplanets: teng 2026-10-22).

## Digitizer: clear axis markers, Tab between series, automatic points (2026-11-03, Mickey)

- "Clear all axis markers" (Axes box): every coordinate system's X1/X2/Y1/Y2 + values removed (log kept); one undo
  step ("calibrations" entry in `_undo`). Tab / Shift+Tab = next / previous series (wraps) when the figure canvas
  (PlotCanvas.event, focus on click) or the series list (eventFilter; not while renaming) has focus -- text fields
  keep normal Tab navigation.
- **Automatic points** (`digitizing/auto_detect.py`, numpy only -- scipy is NOT a dependency: own run-length
  union-find `label`, disc erosion/dilation by shifted copies). Bars: per column the ink run up from the frame
  bottom; segments by colour/height; top = median of the middle 60%, flat-top check (a marker on the axis is a
  dome); hollow bars = two thin equal-height edges + inked top (edges touching a solid bar are anti-aliasing --
  Riggi Fig. 3 paired two across a gridline). Markers: ink = dark or coloured, enclosed holes filled (open -> disc),
  opening with a disc of radius 0.5 x 75th-pct core depth (1.5-4 px: alargov's 3-4 px dashed lines had merged with
  markers at 1.5), components; split touching ones by area (k-means; each part's own fill), drop flat (>1.45 aspect:
  arrowheads) / small fragments; features filled share, fill ratio and up/down/sideways pointing -> shape_of
  (circle .77, square 1.0, triangle .64 +-pointing, diamond .56). Search region = frame + 12 px (markers on an
  axis); centres must be inside; tick numbers drop markers CENTRED on them (blanking their box cut axis markers
  in half, sakata2010 6d); text_boxes (new FigureCandidate/DigitizedFigure field: text-layer words of 2+ chars --
  1-char OCR words can be markers) blanked; legend boxes blanked.
  Grouping by shape/fill/colour/size; `assign_to_series`: one series -> all; bars one per series in order, or by
  colour groups; markers by the series' marker text (`describe`: open/filled, shape words, ▽ symbols, colours;
  'cross'/'+' = stroke -> never matched), ambiguous / unmatched kinds left out with a note.
- GUI: "Find points automatically" (current coordinate system; every panel drawn in the same frame, e.g. a 2nd y
  axis, together) + "Find points automatically when suggestions arrive" (QSettings digitizer/auto_points, OFF),
  run after auto-calibrate in apply_plan. Only series WITHOUT points are filled; one undo step ("points" entry).
  Bars when plan.plot_kind == "bar" or x categorical; markers for scatter*; else auto (>= 2 similar-width bars).
- Measured: synthetic charts <= 2 px; Riggi Fig. 2 (5 panels, 29 bars) and Fig. 3 all right with auto-calibration
  (Fig. 3 reads 2.07/4.03: its axis line sits ~3 px below the gridline spacing -- rounding fixes it); live Sonnet
  suggestions ($0.40 for 6 figures): alargov2002 Fig. 3 26/27 markers right (one triangle on a line read as a
  circle), sakata2010 Fig. 6 48/48; scans (eder1994 Fig. 1, Zamaraev1996 Fig. 2) partial with mix-ups; Excel-style
  coloured markers on equally thick lines (kumar2012) and '+'/'x' markers not found -> 'Find similar points'.
  Corpus run (305 figures with frames) ~0.4 s/figure. tests/test_auto_points.py.

## Paper-wide 'none' vs a figure's own experiments (2026-11-03, Mickey's Riggi2023 run)

Fig. A2's rows (pH-buffered control experiments, Appendix B) got pH_buffer 'none' from "pH buffers were
intentionally excluded from these experiments": the conditions step gave it set '' (= every row, digitized ones
included) and the figure suggestions named the series "pH-buffered" but gave no pH_buffer condition. Fixes:
- `figure_rows.contradicts_absence`: a paper-wide value saying absence ('none', 'no ...', 'not ...', 'without
  ...') is not copied onto a figure whose caption / series label / notes mention the column's subject (5-letter
  stems of its words, not negated: 'pH-buffered'); one `figure_problem` per figure + column. Columns the series
  sets itself are skipped (its own value is written after the paper-wide ones).
- Prompts: generic figure_planner.md -- a figure whose experiments differ from a Methods-wide statement gives its
  own value; prebiotic figure_planner.rules.md -- pH_buffer for buffered series (as printed, or the paper's
  description when unnamed); experimental_conditions rule -- set '' fills every row incl. digitized / appendix
  experiments; name the exceptions in `n`. Live ($0.24): conditions n "except pH-buffered controls with organic
  buffers, Appendix B"; Fig. A2 series pH_buffer 'pH-buffered (buffer not named)'.
- Bug found on the way: `observations.unit_for_column('pH_buffer')` was 'pH' (regex matched a leading 'pH_'), so
  a figure's pH_buffer text was refused as "isn't a number". Now only pH value columns (+ _err/_range/_alt/...)
  are 'pH'; *_method / *desc columns are text.

## Column data types; replicates as a whole number (2026-11-03, Mickey's Riggi2023 run)

- `value_types.py`: TYPES any / number / integer ("Whole number") / text / yes_no; `whole_number` reads counts
  ('triplicate' 3, 'in duplicate' 2, 'three runs', 'n = 3'; None for several numbers); `coerce(value, type)` ->
  (value, problem); `column_type(column, registry)` = the user's choice (registry added_columns[col]["type"]),
  else the pack's stage parameter (integer -> integer, kind text -> text, else number), else number for a column
  with a unit, else any.
- replicates is now `integer` (was text): Riggi had '3' on figure rows and 'triplicate experiments; maximum
  lengths averaged' (paper-wide) on Fig. 3's rows -> all 3. Integer stage parameters read written-out counts
  from the item's text; a non-whole number is left out with a problem. Figure conditions on unit-less columns
  are coerced to the column's type (`convert_condition(condition, registry)`).
- Review window: "Data type" column (combo) per variable: a built-in column shows its type (fixed); an added
  column its remembered type (editable); a new column the category's suggestion (number -> Number, else Any).
  Stored-as preview converts; values that don't fit show ⚠ and block "Build dataset" (`problems`). The type is
  saved with a new column (`registry.add_column(value_type=)`, `set_column_type` for added columns) and applied
  to later papers' recognised values (pipeline passes column_type to write_values). Remembered-variables window:
  "Data type" combo on Added columns. A value that couldn't be put in the column's unit is still written as text
  + flagged (unchanged); ranges ('low:high') pass under Number. tests/test_value_types.py.

## Research areas in the registry; built-in column choices; editable categories (2026-11-03, Mickey)

- **Research areas**: every remembered column (`columns[c]["pack"]`) and synonym (`alias_areas[key]`) belongs to a
  pack or to `registry.STANDARD` ("standard" = every pack). A `VariableRegistry(path, pack=None)` is ONE pack's view:
  `added_columns` / `aliases` are properties filtered to that pack + Standard (the info dicts themselves, so edits
  stick); `all_columns` / `all_aliases` hold everything; `for_pack(p)` = another view of the same `_Store` (one
  save). New columns/synonyms get the active pack; a column another pack already remembers, accepted again, becomes
  Standard; `set_column_area` moves a column (its synonyms follow). Entries without a tag count as Standard (old
  behaviour). Mickey's local registry: all 33 columns + 34 synonyms tagged prebiotic_chemistry (backup next to it:
  variable_registry.before-research-areas-2026-11-03.json). `load_specs / spec_standard_columns / fit_columns /
  standard_columns / column_type` take a `pack` (no global switching needed for another pack's columns).
- **Built-in columns** (`builtin_columns` in the file: {area: {column: {type, category}}}, common columns under
  Standard): `set_builtin(column, value_type, category)` ('' = default), `chosen_type` (column_type uses it),
  `builtin_categories()` -> ColumnOrder `forced` (wins over the pack's `columns` lists), `builtin_types()` ->
  `value_types.apply_column_types(rows, ...)` in finish() after the review (unfit values left out, one
  unit_conversion flag per column). Prompts / stage specs are NOT changed by these choices.
- **Categories editable** (`categories` in the file: {area: {"added": [...], "changed": {id: {fields}}}}):
  variable_categories.use_local(edits) (pipeline._start from config.registry_path -- None = bundled only, so tests
  are unaffected; GUI at start and after either window); `categories(pack, local=None)`: pack's own (+ category
  columns) with the pack's edits + the user's own, then `shared_categories` (Standard edits; the user's own before
  Other). EDITABLE_FIELDS label/description/value_type/max_words/table_order/model_assigns; ids of the app's own
  can't change (pack.json / sources refer to them). A user category with model_assigns is offered to the model
  (prompt listing + the `cat` enum).
- **GUI**: `gui/registry_dialog.py` -- Added columns / Synonyms / Built-in as QTreeWidgets with a collapsible group
  per area (Standard, then packs), filter box, click-to-edit cells via `ChoiceDelegate` (research area, category --
  the area's table_categories + "(automatic)", data type, synonym column); Built-in shows Source + Default, changed
  rows bold/amber, a warning label + a one-time confirmation (`builtin_confirmed`), reset selected / all; row
  identifiers + provenance columns aren't listed (fixed places). `gui/categories_dialog.py` (Variables > Variable
  categories…): area combo, table (ID, Label, Description, Value format, Max words, Table order, Model may assign,
  Origin), add / remove (own only) / reset to default, warning + one-time confirmation for the app's categories,
  checks ids (format, unique vs the area + Standard / packs + figure/assumed) and descriptions. Checked natively
  (screenshots). tests/test_research_areas.py.

## "Sam Papers" test set via handoff (2026-11-03, Mickey): RNA / nucleotide papers

11 PDFs in `Paper Files/Test Paper List/Sam Papers`, prebiotic pack, answered in handoff mode one by one
(`runs/handoffs_sam/`, local). Full write-up incl. persistent issues: `eval/sam_papers_2026-11-03.md`. 7/11 have results
only in figures (or are reviews/perspectives); rows from tables: Caimi 32 (literature comparison Table 1, cited rows
`ds`), Ferris 1993 19, Hirakawa 27, Song 3.
- Tables: Roman numerals ("Table IV": `table_finder.TABLE_RE` group 4, `table_number`/`table_name`, crops
  `page-N-tableIV.jpg`, `api_client._piece_label`, data_location "Table. IV", quotes._TABLE_REF); Nature
  "Extended Data Table N |" (prefix "ED", "Extended Data Table 1"); `pdf_parser.TABLE_CAPTION_RE` no longer matches
  citations ('Table 1) in', '... in/see/of/and/Supplementary Table 1. Next sentence'); `_rows_continue_beside`: a table
  found in one half whose rows continue at the same heights in the other (no running text there) is full width (liu2026
  T1, hirakawa T2, kumar2012 T2-3, mitsuzawa2004 T2 were half crops). Corpus check (99 PDFs): only those changes.
- `pdf_parser._without_sideways`: rotated characters left out of upright pages' text -- publisher stamps ("Downloaded
  from ... by <reader> ... IP address", 5/11 papers + eder1994) were read backwards and sent to the API; also rotated axis
  titles. paper_source still reads the arXiv stamp from the chars. eder1994's reference observations: 11 quotes now found
  in the text ("yes", was "table image"); test_pipeline_offline's identity flags now only CaCl2 (the stamp had kept two
  bare-row quotes from being placed on a page).
- names._is_abbreviation: the abbreviation's letters must occur in the name ('d-ribose (Wako)' is a supplier).
- value_types.coerce: 'detected' passes number / integer (regression of the data-type round: products found without an
  amount were refused in `_mM` columns).
- Stage triggers `set_patterns` (regexes on set label + what varies); wet_dry matches wet-dry / dry-wet /
  dehydration-rehydration / evaporation cycl... -- wet-dry sets typed Independent (summary or cited rows) get cycle details.
- Metadata: year 0 / journal '' when not printed (prompt); an accepted CrossRef match fills them
  (`CrossRefMatch.matched_journal`); year 0 written blank. Ferris 1986, Morasch 2019 (manuscript) filled correctly.
- new_variables: species without any amount aren't offered for review (flag only); a value already formatted 'low:high'
  converts like a printed range; a range value of a suggestion gets its own group/column ('<alias> range').
- Flags grouped: concentration_not_stated per species, cited_data per publication (`_cited_data_flags`), total split by
  ratio per ratio (MixingNote species 'total ...'); low-confidence chemistry ranges shown 'lo-hi'.
- Units: µm / mm / cm column suffixes `_um/_mm/_cm`, `nt` (residues) `_nt`.
- Prebiotic pack: category `product_properties` (Product Properties, assignable, any <= 12 words, order 72) + conditions
  hint asks for whole-product results (longest product, average length, linkage ratios).
- tests/test_sam_papers.py. Persistent issues listed in the eval file (no nucleotide oligomer naming convention /
  standard columns; caption-only results; composition / rate / property tables; species uncertainties; duration ranges;
  review papers cost a full run; cross-paper abbreviations).

## Mickey's answers to the Sam Papers issues (2026-11-03)

- **Nucleic-acid naming** (`names.oligonucleotide_match/oligonucleotide_name`): `<n>mer_<bases>` ('4mer_A', '3mer_AAU',
  '12mer_dT') from (pA)4, (Ap)3, (dT)12, 'A 4-mer', 'oligo(A) 10-mer', U43, 'adenylate tetramer', 'tetraadenylate';
  poly(A) without a length and linkage isomers (pA3'pA) stay unmatched. Columns `(initial|sampled)_<n>mer_<bases>_(mM|
  %yield)` are KNOWN (registry `is_oligonucleotide_column`, no `_aq_`). Standard columns `total_sampled_oligomers_yield`
  (sum of 2-mers and longer) + `max_oligomer_length_nt` (longest with a value) filled by postprocess "oligomer_totals"
  (`calculators/oligomer_totals.py`, a stated value kept + checked); conditions spec parameter max_oligomer_length_nt.
- **Rows from text / captions** when they carry complete conditions (composition AND temperature AND duration) -- the
  tables-only rule was about mostly empty rows. Kinetics tables are rows (intervals hr/hi); molecule properties and
  fraction compositions stay excluded.
- **Paper kind** (`StructurePlan.paper_kind`, alias `kind`: experimental/review/perspective/theory/abstract/other):
  not experimental + no sets -> extract_steps skips methodology/chemistry/fit_models/spec stages (`ex.skipped_kind`,
  a `no_results` flag saying why).
- **Duration ranges**: `PlannedSample.duration_hr_high` (alias `hi`) -> `duration_range_hr` 'low:high', duration_hr blank.
- **Species uncertainties**: SoluteEntry `err_plus/err_minus` (ep/em; table cells '29.18 ± 2.40' via `_cell_error`) ->
  `<column>_err_plus` / `_err_minus` (prebiotic naming like the conditions stage; minus stored negative, like the
  archive's err2), converted like the value (`error_cells`); known wherever the value's column is.
- **Rates**: `measure` "rate" -> `sampled_<name>_rate_mM_hr` (mM/h). Units: inverse_time (h-1...), second_order
  (M-1 h-1), conc_rate (mM/h), molar_energy (kJ/mol, kcal/mol). Optional spec stage `kinetics` (keyword trigger: rate
  constant, half-life, Arrhenius, ...; per sample; uncertainties; table images; open-ended -> category Kinetics, order
  74): rate_constant_first_order_per_hr, rate_constant_second_order_per_M_hr, half_life_hr, activation_energy_kJ_mol,
  rate_constant_reaction, kinetic_model. eder1994 triggers it (step count 6 -> 7); recordings made before it existed
  replay it as an empty answer (`make_replay`: unrecorded spec stage -> `response_model()`, 0 tokens).
- **Whole numbers within N px** (Riggi bars: averages 3.45 next to whole 2, 3): `AxisVariable.whole_within_px`
  (hidden from the model); `calibration._snapped_fraction` snaps to the whole number when it is within that many
  pixels, else rounds to `decimals`. Digitizer "round:" offers "whole if within 3 px, else 1 / 2 decimals"; automatic
  digitizing uses 2 decimals + 3 px when the user hasn't chosen.
- **Error bars**: `DigitizedPoint.err_hi_py/err_lo_py`; digitizer mode "Error bars" (click above/below a point; points
  table shows +a/-b; undo); `auto_detect.find_error_bars` (capped whiskers, lighter grey allowed via `whisker_mask`;
  bars: upper whisker) with "Also find error bars" (QSettings digitizer/auto_errors); `figure_rows._error_bar` ->
  `<column>_err_plus/_err_minus` (after the axis multiplier). Riggi Fig. 2: kaolinite +0.49, chabazite +0.52, no false.
- **Automatic figure parsing** (`digitizing/auto_figure.py`, RunConfig/Options "Digitize easy figures automatically",
  CLI --auto-figures, off by default): only bar / scatter data plots that don't repeat a table, when the axes calibrate,
  points are found and assigned without notes; else the reasons are shown and the figure goes to the editor.
  `DigitizedFigure.auto_digitized` -> `auto_digitized` flags (GUI group "Figures digitized automatically"); unattended
  runs (`run_pipeline`, queues) use `pipeline.auto_digitize_figures` (no SI figures).
- **PubChem synonyms + active names** (`compound_names.py`): `pubchem.synonyms(cid)` (PUG REST /cid/<cid>/synonyms,
  cached under "synonyms" in pubchem_cache.json; `useful_synonyms` drops CAS / UNII / InChIKey / database codes, > 50
  chars; 25 max). Bundled: species_cids.json entries have `synonyms` (`scripts/add_species_synonyms.py`, network).
  Accepted compounds: review acceptance -> `registry.remember_compound(paper name, cid, synonyms)` (synonyms fetched in
  normalize when PubChem identifies a new compound). Registry `compounds` {area: {name: {cid, synonyms, active}}}; the
  default name = the vocabulary's / the paper's; `set_active_name`. ONLY the files use the active name:
  write_template_csv orders with default names (template places kept) then renames the header (`renames_for`);
  observations' `column` too; queue combined CSV with the registry; Rows tab maps back for provenance
  (`CompoundNames.to_default`). Interconversion: `harmonize` (any of a compound's names -> active), `to_default`,
  `convert_dataset_csv` (merges columns of one compound). Offline matching: normalize renames a name equal to a stored
  synonym (unique to one compound) before PubChem ('Trisodium trimetaphosphate' -> sodium_triMP). GUI: Remembered
  variables -> tab "Compounds" (per research area; Active name drop-down of default + synonyms; Reset; "Convert a
  dataset CSV…" -> <name>_active_names.csv).
- tests/test_sam_answers.py.

## One column format for every compound (2026-11-04, Mickey)

Peptides were a special convention (`<n>peptide_<AA>`, no phase); now every compound -- salts, amino acids,
peptides, nucleotides -- has ONE column format, `<role>_<name>_<phase>_<measure>` (flatten_to_template
`species_column`; `PHASE_CODES` aq / gas / s from SoluteEntry.phase; measures mM, %yield, %recovered, ratio,
rate_mM_hr; `_avg` / `_range` markers after the phase, `_err_plus/_minus` after the measure):
'initial_Gly_aq_mM', 'sampled_Gly-Gly_aq_%yield', 'sampled_4mer_A_aq_mM', 'initial_CO_gas_mM'. Mickey's choices
(asked): peptide names = sequence with compact repeats -- `names.peptide_name`: 'Gly-Gly', 'Gly-Gly-Gly', a run of
>= 4 of one residue '(Gly)4' / '(Gly)10' / 'Gly-(Ala)4' (`COMPACT_RUN`), cyclic 'cyclo_' + that; and a phase marker
on EVERY compound (also amino acids, peptides, oligonucleotides, which had none).
- Peptides are compounds like any other: their default name is the sequence, PubChem synonyms (bundled; keys of
  species_cids.json renamed) can be chosen as the active name (compound_names.py). They stay KNOWN without a review
  when written in the convention's form (`registry.is_peptide_column`: canonical sequence only -- 'Gly-Gly-Gly-Gly'
  isn't, '(Gly)4' is), as before.
- The fixed ExtractedRow fields sampled_2/3peptide_Gly_mM / _pct_yield are gone (values in species_mM / extra like
  every compound); plausibility's 0-100 % check covers every `_%yield` / `_%recovered` column.
- Old names convert everywhere (`flatten_to_template.current_column_name`, idempotent): set_row_value, saved
  digitizations' axis columns, the registry on load (`_Store._migrate_compound_columns`: columns, synonym targets,
  built-in choices, compound/species-id names; first save writes `variable_registry.before-compound-columns-2026-11-04.json`
  -- Mickey's 10 remembered peptide/yield columns convert), the Compounds tab's "Convert a dataset CSV…"
  (`convert_dataset_csv`: legacy format first, then active names). `match_species('2peptide_Gly')` -> 'Gly-Gly'
  ("peptide name (old naming)"), so recorded answers replay.
- `scripts/migrate_compound_columns.py` rewrote the pack's template_vocab.json (78 columns) and species_cids.json keys
  (idempotent). PaperDataTemplate.xlsx untouched.
- Chemistry prompt: peptide naming rewritten; `ph` DEFINED now that it names the column ('aq' also for products of a
  dried residue analysed in solution; 'gas' / 'solid' only for amounts of a gas / undissolved solid; unsure -> aq;
  `schemas/chemistry.PHASE_DESC`). Recorded answers: only truman2024_auto had 'solid' (3 peptide yields -> `_s_`
  columns in its fixture, as recorded).
- References regenerated by replay after a cell-level check against the old files with headers converted: all six
  runs/reference runs 0 cell differences (eder1994 observations: provenance text only -- "name matched '2peptide_Gly'
  -> Gly-Gly", totals list new names); runs/ backup in the session scratchpad. tests/test_compound_columns.py.
- **Follow-up (same day, Mickey): peptides reviewed; repeat shortening for every compound.**
  `registry.is_known_column` no longer accepts `is_peptide_column` -- only the pack's own peptide columns are known,
  a new peptide (or a peptide average) is reviewed like any compound (is_peptide_column still finds a row's peptides
  for the totals). Oligonucleotide columns are still known without review (not part of this request).
  `names.compact_repeats`: ANY name of hyphen-joined units with a run of >= 4 identical units -> '(unit)n'
  ('TEST-TEST-TEST-TEST' -> '(TEST)4', 'A-B-B-B-B-C' -> 'A-(B)4-C'; runs of 2-3 stay); peptide_name uses it;
  applied in species_column, normalize_chemistry (rename note "repeated units shortened") and figure_rows species;
  prompts say so. truman2024: (Gly)7, (Gly)9-13 % yields have no vocabulary column -> left for review; Table 1's
  stated totals then don't match the accepted yields before the review -> 4 conflicting_values flags (references
  regenerated; others unchanged).
- **Follow-up 2 (same day, Mickey): new compounds of ANY type are reviewed** -- oligonucleotide columns no longer
  known by rule either; is_known_column = the pack's columns + the user's accepted ones (+ err / range / stock of
  those). Figures: `flatten_to_template.canonical_compound_column` (current format, match_species name, repeats
  shortened) on axis columns in figure_rows, so a compound read off a plot and the same compound in a table propose
  ONE column ('sampled_Lys-Lys-Lys-Lys_aq_%yield' -> 'sampled_(Lys)4_aq_%yield'). A figure axis whose compound has no
  column still gets its rows built (conditions, durations); the values wait in the review (kind figure_axis, row_ids)
  and land on those rows when accepted (tests/test_compound_columns.test_new_peptide_on_a_figure_axis).
- **One review line per compound (same day, Mickey):** `new_variables._merge_figure_axes_into_compounds` (in
  group_new_variables) puts a figure_axis group's values into the species group proposing the same compound column
  -- one decision for table/text AND plot values (before: accepting one and rejecting the other left the column half
  filled in this paper and filled automatically in later ones, since an accepted column is known). VariableGroup
  `.sources` ({'Table 1': 4, 'Fig. 3': 8}, `source_label`) / `.merged`; NewVariable `include` (default True):
  apply_decisions writes only included values, the unticked ones become a left-out group (new_variables.json +
  new_variable flag), all unticked = not added. Review window: merged line named "<name>   (in Table 1 and Fig. 3)",
  count tooltip per source, "Include values from:" one checkbox per source above the values, an Include column per
  value ("(left out)" in Stored as); problems() checks only included values. Checked natively.

## Running the test suite (2026-11-04)

`python scripts/run_tests.py` runs every tests/test_*.py in its own process, one per CPU core (`-j N` to change;
words after it pick files by name), slowest first (last run's times in tests/.last_times.json, gitignored), and
lists FAILED and SKIPPED files with their output tails (exit 1 on either). The files are independent: temp folders
only, registry_path None / tmp registries, an empty app-data folder per file (tests/_isolation.py, 2026-11-09).
Measured on Mickey's 8-core Mac: ~95-110 s vs ~6-7 min one at a time; the floor is the slowest file
(test_teng2023_replay ~1 min). A new test file must keep that independence (no shared output paths, no user prefs).

## Template pack for new research areas (2026-11-05, Mickey: start of in-app pack creation)

Goal (Mickey): pack creation and editing inside the app, like the variable categories / remembered columns windows.
Step 1 built: a TEMPLATE pack that ships with the app, hidden from every pack list, as the basis of new packs.
- `packs/_template/`: pack.json (`"is_template": true`, every key preceded by an `_about_<key>` explanation --
  ignored by the loaders; tests check each `_about_x` names an existing key), columns.json (8 example columns, units
  as name suffixes), standard_columns.json (empty), stages/example_measurements.json (a working spec: always,
  per sample, table images, open-ended, uncertainties on temperature / yield), prompts/structure_planner.rules.md
  (example rules), README.md (the guide: files, the run flow, columns, every stage + parameter field, row rules,
  the existing calculators and which pack each suits, testing, what still needs code).
- `PackManifest.is_template`; `packs.available(include_template=False)` leaves it out (all GUI combos, CLI,
  registry areas use available()); `activate()` can still load it by id; `packs.template_pack()`;
  `packs.create_pack(id, label, description, base=user_packs_dir())`: id `[a-z][a-z0-9_]{1,40}`, not taken, non-empty
  label; copies the folder, rewrites id/label/description, is_template false.
- Shared row-planning prompt `prompts/structure_planner.md` (generic; slots {{SET_WORD}} / {{SAMPLE_WORD}} from pack
  `units`, {{PACK_RULES}} from `structure_planner.rules.md`, {{RESEARCH_AREA}}); prebiotic and exoplanets keep their
  full own prompts (unchanged). stages/structure_planner.py passes the unit words.
- `--self-check`: "Template for new research areas" (bundled and valid). tests/test_template_pack.py: hidden, valid,
  id checks, a created pack found + run end to end with stand-in answers (shared prompt + rules used, K -> °C on every
  row, uncertainties, text values).
Next steps (not built): GUI "New research area…" (create_pack + editors for columns / stages / rules / categories),
a stage editor (parameters table, trigger, options), validation of a pack (columns named in categories exist, spec
columns' units match suffixes), and calculations a pack can declare without code (a small declarative layer).

## Data Packs menu: new / edit / copy / check research areas (2026-11-05, Mickey)

Menu "Data Packs" (main window, after Variables; locked during runs): New research area…, Edit research area…,
Copy a research area…, Check research area…, Open research areas folder. `MainWindow.refresh_packs(select)` rebuilds
the Research area list after a create / save.
- `pack_editing.py`: `PackDraft.load(folder)` = manifest (raw dict: `_about_*` and unknown keys kept), columns file,
  standard file, stage specs by file, rules per RULE_PROMPTS (structure_planner, figure_planner, focused_search,
  metadata), own whole prompts; `new_stage` (essentials filled: trigger always, per sample, table images, `_err_plus`
  style), `remove_stage`, `save()` (refuses the app's own packs -- `builtin` = inside packs.BUILTIN_DIR; empty rules
  delete the file; clears optional._specs_in and the active pack). `check(draft)` -> Problems error/warning/note:
  invalid manifest / specs, unknown built-in steps or calculations (BUILTIN_STAGES, CALCULATIONS -- the registry of
  what exists, with descriptions and the step each needs), calculation needing a step not used, missing files,
  no / duplicate / malformed columns, nothing extracting, stage name / answer-format name (may be empty) clashes,
  never-running triggers, parameters without column / description / duplicated, choices on numbers, units against the
  name suffix (pH isn't a unit; a unit not in the name -> one grouped note per stage), columns outside the list (one
  grouped note per stage), a column filled by several stages, no row rules, template leftovers, categories (ids,
  unknown targets, missing columns -- provenance / row columns count, bad patterns). Built-in packs: notes only.
- `packs.create_pack(..., source=pack, units={...})`: from the template or a copy of any pack (how the app's own are
  changed).
- `gui/pack_windows.py`: NewPackDialog (name -> id suggestion, description, set / row words, start from template or a
  copy); PackEditor tabs General (name, description, words, focused row plan, compact text, built-in steps, ordered
  calculations list, "Edit variable categories…" opening CategoriesDialog on the area), Columns (editable, drag order,
  tooltip = stages filling it; compound vocabulary when chemistry is on), Stages (list + scrolling form: name, label,
  description, role, instruction, values per row/set, trigger words, table images, other values + hint, uncertainty
  naming, rules; parameters table: column, unit, kind, description, allowed words, whole number, ±; add / duplicate /
  remove stages, add / remove / move parameters; fields the form doesn't show are kept), Rules (per shared prompt,
  "Show the shared prompt…"), Check (re-run on Save; errors ask before saving). App's own packs open read-only with
  "Copy to a new research area…". Checked natively (form fields grow; parameter rows refit after layout via
  `_fit_rows` -- the stretched column gets its width late). tests/test_pack_editing.py.
Not built yet: removing a research area, the declarative formula layer (Mickey: later), editing the shared columns.
- **Removing a research area (same day, Mickey):** Data Packs > Remove research area… (lists only the user's own
  areas; locked during runs) -> a warning (Continue… / Cancel) -> `DeleteConfirmDialog`: type exactly "DELETE"
  (Remove enabled and default only then) -> `packs.delete_pack(id)` (rmtree of the folder; refuses the app's own
  packs and the template; resets the active pack if it was that one; clears the spec cache) -> `refresh_packs()`
  (falls back to the default area when the removed one was selected). Remembered variables / categories under its
  id stay in the registry. tests/test_pack_editing.py (both cancels, the full path, button state).

## Formulas: calculations without code (2026-11-05, Mickey)

`formulas.py` + pack.json `formulas: [{column, expression, description, if_present}]` (PackManifest.formulas).
Expression language parsed with `ast` and evaluated by a WHITELIST (never eval): column names (backticks for names
with - % ( ) -> col("...")), numbers, pi, e, + - * / ** % //, comparisons, and/or/not; functions abs, min, max,
round(x, d), sqrt, exp, ln, log10, first(...) (first present), ifelse(test, a, b), sum_of / mean_of / max_of / min_of /
count_of("regex over column NAMES"). Refused: attributes, calls to anything else, lists, lambdas, if-expressions,
free text. A missing / text input -> MISSING -> no value (first() and the aggregates skip missing).
`apply_formulas(rows, formulas)` runs in pipeline.finish after the review and the built-in totals, in list order (a
later formula uses earlier ones' columns); if_present check (default: the paper's value kept, a difference > 1% or
0.05 -> conflicting_values) / keep / replace; values _tidy'd, provenance origin "calculated", source "formula
<col> = <expr> with <inputs>", lowest input confidence. `formula_flags`: per formula one derived_value, one
conflicting_values (rows listed, 6 shown), one not_calculated (division by zero, math errors). Formula columns are
registry standard columns (known, in every CSV). pack_editing.check: no column / bad name / same column twice /
bad if_present / parse errors / own column / uses a LATER formula's column (warning) / unknown columns (warning) /
no description (note) / the template's example (note). Template pack: example formula temperature_K = temperature_C
+ 273.15 (+ README section). Editor tab "Formulas" (before Check, so Check is tab 5): table (column, formula,
description, if-present combo), add / remove / up / down, "Try the selected formula" (inputs from the expression,
live result), function help. tests/test_formulas.py; test_template_pack asserts temperature_K on every row.
- **Editor tidy-up (same day, Mickey):** long explanations behind "?" buttons (`HelpButton`: tooltip on hover, shown
  on click; `_titled(title, help)` section headers; `PackEditor.help_buttons()`). Stage form: "Basics" (name, label,
  description, instruction, values per row/set, runs for) + collapsible "Advanced" (closed; model's role, tables,
  other values + hint, uncertainty naming, rules; opening it scrolls it into view). Calculations: the main list
  shows the ticked ones and those written for the area's ticked built-in steps (`pack_editing.CALCULATION_STEP`);
  the rest sit under a collapsed "Other calculations (n)" list -- ticking one moves it up; toggling a built-in step
  re-sorts; with nothing to show, a one-line note replaces the empty list. Formulas tab: the reference is a grid
  (`_formula_reference`: what to write, monospace at the label size, in one column; one-line descriptions in the
  next; one entry per line -- FUNCTION_HELP restructured), "Try the selected formula" at most 380 px wide.
- Tests must not see the user's own research areas (<app data>/packs; Mickey makes test packs there):
  test_research_areas points `packs.user_packs_dir` at an empty temp folder. Gate commits on the runner's summary
  ("0 failed, 0 skipped"), not on its output existing.
- **Row style is the default for lists of settings (Mickey, 2026-11-05):** `gui/widgets.style_rows(table, delegate=None)`
  (+ `RowSeparatorDelegate`, `ROW_GAP`, `in_cell(widget)` -- moved from categories_dialog): no grid, faint line
  between rows, wrapped text, rows refitted on column resize / inserts / edits. Used by the categories window and the
  pack editor's parameters, rules, formulas, try-it inputs and check tables. Use it for every new scrollable
  multi-column list of settings (not the dense data tables like the Rows tab). Cell widgets go in `in_cell(...)` and
  are read back with `cellWidget(r, c).findChild(...)`.
- Rules tab: one editable row per rule (`pack_editing.rules_to_items`: '- ' lines start a rule, indented lines
  continue it, dash-less paragraphs are one rule each; `items_to_rules` writes '- rule' lines; round-trips every
  built-in rules file), add / remove / up / down.
- Formulas tab: "Columns (click to insert)" between Try (max 330 px) and the reference: every column of the area
  (`draft.all_columns()` + formula outputs, refreshed when the tab opens; filter box); the list never takes focus,
  and `FormulaDelegate` remembers the open Formula cell editor, so a click types the name at its cursor (backticks
  for names that aren't identifiers); with no editor open it's appended to the selected formula.

## Pack editor General / Rules layout (2026-11-06, Mickey)

General tab: Name / ID / Description, then a "Row options" group box (set / sample / row words), then a collapsible
"Optimization and Focused Search" section (`_disclosure` helper: arrow button + box, closed by default;
`optimization_btn` / `optimization_box` hold focused_box + compact_box), 14 px spacing, built-in steps. Calculations
are now `style_rows` tables (`calc_table`, `other_calc_table`; columns Calculator (checkable, UserRole = name) /
Description / Requirements (`pack_editing.CALCULATION_NEEDS`) / Written for); order via Move up / Move down
(`_move_calc`), `_calc_names(table, ticked_only)`; ticking an "other" one moves it up as before; read-only areas
can't tick (`_calcs_locked`). `RowSeparatorDelegate(parent, gap=...)`: the rules table uses RULES_ROW_GAP = 13
(default ROW_GAP 7).

## Dropped connections mid-answer (2026-11-06, Mickey's Riggi2023 run)

Economy, 3 passes: the structure step's stream was cut off ("peer closed connection without sending complete message
body", httpx2 RemoteProtocolError -- the anthropic SDK now uses the `httpx2` fork). The SDK retries only until the
stream starts, so it came out raw and the GUI called it "a bug in the app". `api_client._send_resuming` (inside
_send_mapping_errors, so every step and figure suggestion): `_dropped_connection` (anthropic.APIConnectionError, or
an httpx*/httpcore*/h11 transport error by class name) -> ctx.note + wait STREAM_RETRY_WAITS (3, 10 s; cancel-aware
-> RunCancelledError) and ask again; a third drop -> `errors.NetworkError(stage)` ("broke off during the '<stage>'
step, three times in a row ... running the paper again usually works"). The dropped attempt's tokens aren't
recorded (unknown). tests/test_dropped_connection.py.

## Analysis methods step (2026-11-07, Mickey: instrument settings were left to suggestions)

Riggi2023's Table 2 (MALDI-TOF MS settings) got no suggestions; analysis details came out under a different name in
each paper. Now a built-in step `analysis` (prebiotic pack `builtin_stages`; toggleable like fit_models; runs once,
not voted; skipped for non-experimental papers):
- Column format (Mickey's proposal, made slot-consistent with compound columns): `analysis_<technique>_<setting>
  [_range][_<unit>]` -- hyphens inside a slot, underscores between ('analysis_MALDI-TOF-MS_laser-intensity_range_%',
  'analysis_RP-HPLC_flow-rate_mL_min', 'analysis_RP-HPLC_column'). `analysis_vocab.py`: column / parse_column /
  token, UNIT_TOKENS (existing suffixes: C, um, uL, mL_min, ...; new kV, ns, MHz, eV, per_cm, mW, mA, %), the unit
  for observations (`unit_for_column` handles analysis_ first), `is_vocab_column`.
- Vocabulary `packs/prebiotic_chemistry/analysis_vocab.json` (data, editable): 20 families of settings (general +
  LC, GC, planar, CE, gel, MS, MALDI, UV-Vis, fluorescence, IR, Raman, NMR, X-ray, atomic, elemental, electrodes,
  radiolabel, sequencing, microscopy) with unit / integer / description / aliases, and ~55 techniques with
  families + aliases. Grounded in Rouessac & Rouessac, Chemical Analysis 3rd ed. (Paper Files/"Chemical analysis _
  modern instrumentation methods.pdf", ch. 1-22) + settings seen in our runs (kim2017 HPLC, Riggi MALDI, Sam Papers).
  A vocabulary technique + one of its families' (or general) settings with that unit = KNOWN column (the pack's
  own, like template columns; registry.is_known_column); other techniques/settings -> review (category analysis,
  column already in the format; alias '<technique> <setting>' remembered as usual).
- `schemas/analysis.py` (compact: methods [{tech nm set sample settings [{par v hi u txt q src c n}] q src c}]),
  `stages/analysis.py` (table images; budget 6000 + 400/set), shared prompt `prompts/analysis.md` with
  {{ANALYSIS_VOCABULARY}} = compact listing (names + units only, ~1.2K tokens; the app maps other wordings by
  alias -- the descriptive listing was 4.5K and cost $0.045-0.06/paper Standard, compact ~$0.035).
  `calculators/analysis_columns.apply_analysis` (pipeline.finish, before the review): converts to the setting's unit
  (GC 'm' = metres, not molar; Å; no printed unit -> taken as the setting's, noted), ranges 'low:high', set ''
  = every row incl. figure rows, several values of one setting for the same rows kept '; '-joined, a non-whole
  count kept as printed; flags kind `analysis` (GUI group "Analysis methods"): one summary per technique, problems.
- Conditions spec: new StageSpec field `hint_by_stage` {stage: {runs, off}} appended to open_ended_hint by `for_run`
  (triggered_specs gets the set of running steps): analysis details go to `other` only when the analysis step is off.
- units.py: voltage, short times (ms/µs/ns), frequency, energy, wavenumber, power, current, scan rate, Å, µL/min.
- Replays: `test_pipeline_offline.ADDED_LATER` = code steps recorded runs lack (replayed as empty); eder1994's step
  count 7 -> 8.
- Live (Standard): Riggi2023 -- all 8 Table 2 settings (voltages kV, 140 ns, laser 75:85 %, reflectron, negative)
  + matrix, ratio, target plate, spot volume, calibration standard, ZipTip prep, smoothing; kim2017 -- full RP-HPLC
  method (column, 3 x 150 mm, 5 µm, TEAA/ACN gradient, 0.5 mL/min, 260 nm, 20 µL, retention times, standards) +
  1H NMR 300 MHz D2O, ESI-TOF HRMS, UV-Vis; faisal2005 -- amino acid analyzer (40 °C, 0.05 mL/min, 254 nm as
  printed), organic acid analyzer, IC, TOC. Fixes from the runs: preparative purification isn't analysis;
  replicate-measurements != replicate experiments; `shot-sets` added (Riggi: 5 sets x 1000 shots).
  tests/test_analysis_step.py. Not built: an editor tab for analysis_vocab.json (edit the JSON for now).

## Vocabulary editors; research areas in one menu, two layers (2026-11-07, Mickey)

Mickey: vocabulary-defined columns are written directly (no review) for now. The GUI had two menus (Variables, Data
Packs) whose windows overlapped. Organisation now, said in each window's intro:
- **Pack definition** (Data Packs > Edit research area; app packs read-only, copy to change): General, Columns,
  **Compounds** (new tab: the compound vocabulary -- name, PubChem CID, title, synonyms from species_cids.json; add /
  remove / filter / "Look up missing CIDs on PubChem"; was a plain-text box under Columns), **Analysis methods** (new
  tab: analysis_vocab.json -- family list, the selected family's settings table [name, unit combo incl. 'text' /
  'whole number', description, aliases; add / remove / up / down], techniques table [name, families, description,
  aliases; filter]; no vocabulary -> "Start from the prebiotic chemistry vocabulary" / "Start empty"), Stages, Rules,
  Formulas, Check. Compounds / Analysis methods tabs are enabled only while their built-in step is ticked
  (`_follow_step`). Tests find tabs by name (`PackEditor.tab_index`), not position.
- **Remembered from your reviews** (registry, per user, on top of any pack): RegistryDialog renamed, tabs Accepted
  columns / Synonyms / Compound names / Changes to pack columns (was Added columns / Compounds / Built-in), a
  Research area selector (`area=`; shows that area + Standard); the pack editor's "Remembered from your reviews…"
  opens it filtered to the area.
- One "Data Packs" menu: New / Edit / Copy / Check, then Remembered from your reviews… / Variable categories…, then
  Remove / Open folder. The Variables menu is gone (action attributes registry_action / categories_action kept).
- PackDraft: `analysis_vocab` (None = no file), `cids_file`, `compounds` property (setter keeps a compound's stored
  title/synonyms while its CID is unchanged; sets manifest species_cids on first save); `analysis_problems(vocab)`
  in check (names as column slots, duplicates, unknown families, units the app doesn't convert, an alias naming two
  techniques); duplicate compound names. Saving clears analysis_vocab's cache.

## Table grids: built, measured, OFF (2026-11-07, Mickey: structural change (1) of the cost discussion)

Full write-up: `eval/table_grids_2026-11-07.md`. `ingestion/table_grid.py` reads table cells locally (PDF text layer:
lines + column gaps through numeric lines, sub/superscripts as ^{..}/_{..}, split decimals joined, dot leaders
dropped, landscape pages upright; scanned pages -- text render mode 3 -- never; arXiv ' | ' rows replaced in place)
into numbered grids; chemistry `tables` can map `grid` + `gc`/`gr` (`ChemistryExtraction.fill_grids`), table-reading
spec stages `grids` (cols x rows, or `prows` x `scols` for parameter tables; `optional.fill_grids`); table_finder
entries now carry page_no / box / caption_box. Live on the references: no saving (+6% mean cost, accuracy within
run-to-run noise) -- the compact table formats had already removed the per-cell output; the remaining output is labels,
text values, solutions, free text. So `RunConfig.table_grids` defaults to False. `scripts/eval_references.py` = live
runs scored against runs/reference expected CSVs (rows paired by content; `--src` for a baseline checkout; `--score`).
Fixes found: mixing `_missing_solutions` ignores a solution only one other set lists (kim2017 CaCl2); sampled
temperature isn't a quench temperature (faisal2005); analysis method-level q/src/c optional; 529 overloaded message.
Open (Mickey): truman2024 (a review reproducing data) gets no rows since the 2026-11-03 review rule.

## Shared cached step instructions; reviews' reproduced data are rows again (2026-11-07, Mickey)

- Reviews: structure prompts (generic, prebiotic, exoplanets) plan data a review reproduces from other papers as sets
  with `ds` (source-marked, accepted by default); only a paper with no results at all gets no sets (skipped). Rescinds
  the 2026-11-03 "non-experimental -> no sets" rule.
- Structural change (2): `RunConfig.shared_instructions` (None = automatic: on in PaperQueue, off for single runs).
  `PaperContext.instructions` = every paper-reading step's static prompt (each step's `prompt_text(...)` with
  `api_client.PLAN_MARK` for the plan; built by `pipeline._step_instructions` for the run's tool list; not in handoff),
  sent as a cached system block (`system_blocks`) before the paper; a step's request carries only "Follow the
  instructions for step X" + its plan (`task_for`; falls back to the whole prompt on any mismatch). Audits name the
  cached system prompt instead of copying it. PaperQueue warm-up: the first paper extracts alone until its structure
  plan is back (`_warm`, not batch). Measured (eval/shared_instructions_2026-11-07.md): 5-paper queue -17% total, -32%
  input; single paper +6% (hence off); +22 s per queue. tests/test_shared_instructions.py, test_paper_queue.

## One search page: Focused search and Paper queue folded into the main window (2026-11-08, Mickey)

The Focused search and Paper queue windows (gui/focused_window.py, gui/queue_window.py) are gone; the main window does
all three. Layout: Research area + a mode line (`mode_label`); three panes in `top_split` -- Papers
(`gui/paper_list.PaperListPanel`: a table Paper | Status, `id_edit` = `pdf_edit` (Enter adds; a typed, not-added paper
still runs: `run_items()`), Add PDFs / list (CSV) / Remove / Clear, PDFs dropped on the window), Parameters
(`gui/parameter_panel.ParameterPanel`: each switchable stage a tri-state group with its parameters; QSettings
stages/<pack>/<stage> as before), Run options (grouped, `_build_options`: the groups that apply first -- Several papers
`multi_widget` (n > 1, full), Focused search `focused_widget` (single parameters unticked) -- then Models and cost,
Paper text, Review + Saved with the results `review_widget` (hidden for a focused search; Passes row too)).
Mode rules: everything ticked = full extraction; a whole stage unticked = full extraction without it
(`optional_stage_choices`); single parameters unticked = focused search (`params.focused`); several papers + full =
queue. `_start_run` dispatches: one paper -> the usual run + figure review; `gui/multi_runs.QueueRun` /
`FocusedRun` (controllers reporting to the main window: statuses in the Papers list, "Search results" tab
`search_table`, Skip figures / Retry failed buttons; selecting a paper after a queue shows its results). Settings is a
menu (Settings… with PreferencesRole, results folder, open folder, Online lookups mirroring `pubchem_box`); File has
Add PDFs / Add list. "Parameters to look for" left the window (`focus_terms()` returns []; CLI --look-for stays).
`main_split` position now saved as main_split_v2 (the old one-paper layout's would squeeze the panes).

## Constructed parameters in the Parameters panel (2026-11-08, Mickey)

Steps whose columns are BUILT from a vocabulary get a group of that vocabulary's items in the main window's Parameters
panel, in one standard shape meant for future (incl. user-defined) vocabularies: `scopes.py` ScopeGroup(step, label,
description, items=[ScopeItem(key, label, tip, detail)]); `scopes.groups(pack, registry)`.
- "Chemical compounds" (step chemistry, listed first): the pack's species_names + compounds remembered in reviews,
  shown by ACTIVE name (compound_names), key = default name. "Analysis methods": the analysis vocabulary's instrument
  families (not "general"), hover/detail = their techniques.
- Some unticked -> `RunConfig.scopes {step: [keys]}` (missing = everything): NOT a focused search (`focused`,
  `checked_columns` ignore scope groups). Prompt slots `{{COMPOUND_SCOPE}}` (chemistry.md; the controlled vocabulary
  sent is the scope) and `{{ANALYSIS_SCOPE}}` (analysis.md; `prompt_listing(vocab, families)` lists only those
  families + general); the app also drops anything outside the scope (`filter_compounds` after normalize, by
  canonical name -- a peptide is its own compound, 'Gly' doesn't include 'Gly-Gly'; `filter_analysis`, unknown
  techniques dropped) with `scope` flags (GUI group "Scope of this run"). Added solutions / ratios involving the
  chosen compounds are still asked for (stock -> mixture calculations).
- All unticked -> optional_stages[step] 'off'; `pipeline._chemistry_on` now gates chemistry (step count, tools,
  submit) like the spec stages. Mode line: "Full extraction -- only compounds: 5 of 129; analysis methods: NMR".
- CLI: no flags yet (RunConfig.scopes works from code). tests/test_scopes.py (eder1994 replay with scope Gly).

## Digitizer: settings for every coordinate system; layout pass (2026-11-08, Mickey)

- "Use in every coordinate system" (Axes tab, menu): Rounding / Columns and multipliers / Log scales / Categories (x axis)
  / All of these -> `DigitizerWidget.apply_to_all_panels(what)` copies the current coordinate system's settings to the
  others; points of panels whose rounding changed snap; one undo step ("panel settings": AxisVariables, log flags and
  points restored). Riggi Fig. 2 (5 bar panels) needed the y rounding set five times before.
- Layout: suggestions box hidden while empty (`_NoteLabel`), Tool buttons in a 3 x 2 grid, then tabs (`self.tabs`):
  Axes (coordinate system + Add + name; calibration grid Marker 1 / Marker 2 / log scale; categories; Columns form with
  x multiplier and hints; Rounding X / Y; copy menu; Automatic calibration: Calibrate current / Calibrate all
  (`auto_calibrate_all`: only systems without markers) / Clear markers + checkbox; Whole figure: Data reproduced from),
  Series (list, Add / Remove / Show only this series; Read against, Notes; Conditions and Initial composition with
  +/- buttons; Additional options), Points (`points_series_combo` synced with the list; Find in current / Find in all,
  error bars, when-suggestions-arrive; Find similar points + similarity; status; points table). No horizontal scroll
  in the tools pane; it opens at >= 480 px / 40%. Round choices shortened ("whole ±3 px, else 1 decimal"). Attribute
  names unchanged. Checked natively. tests/test_digitizer_copy_settings.py.

## Local model servers (2026-11-08, Mickey: a framework for locally hosted models, all search types)

`local_models.py` + RunConfig `provider` ("anthropic" default | "local") and `local` (LocalSettings as a dict). Two
server kinds: "ollama" (native POST /api/chat -- the only way to set `num_ctx`; Ollama's small default would silently
cut a paper off) and "openai" (POST /v1/chat/completions: LM Studio, llama.cpp, vLLM; optional bearer key). Plain
urllib, streamed (NDJSON / SSE) on a helper thread so Cancel works while the server reads a long prompt; socket timeout
= `timeout_sec` (wait for the next piece). Hook: api_client._send_mapping_errors -> `local_models.send` (after the
handoff check), returning an Anthropic-message-shaped SimpleNamespace, so call_structured (retry on broken answers,
audits, usage) is unchanged; cost 0.0 in _record.
- Request: the step's schema = transform_schema + model_facing_schema, sent as the constraint (`format` /
  `response_format` json_schema strict) AND in the system prompt (a grammar doesn't carry the field descriptions);
  temperature 0; output budget = min(step budget, context - estimated prompt); a prompt estimated (chars/3.5 + 600 per
  image) within 1024 tokens of the model's context is REFUSED with a message (raise the context length). Images only
  for models marked `vision` (else dropped + a ctx note). Header X-Parameter-Extractor-Step (server logs; the tests'
  fake server).
- RunConfig.__post_init__ for local: prompt_caching, batch_mode, shared_instructions, figure_suggestions_on_paper off
  (the non-cached path sends each step's prompt with the paper + its images). `needs_api_key` (not local, not handoff)
  replaces the key checks in pipeline._start and focused_search (no Anthropic client made for local). `model_for`:
  profile roles structure_planner / "*" / figure_planner (equations use figure_planner). `to_public_dict` drops the
  local key. One semaphore per server URL (`parallel`, default 1) -> parallel steps, passes, queues and focused searches
  just wait their turn. Every local run: paper flag `local_model` (unvalidated); run_summary `provider`.
- Settings: <app data>/local_models.json (`default_path`, `load`/`save`; key never written -- keychain account
  `key_store.LOCAL_ACCOUNT`). GUI: Settings > Model provider (`gui/local_models_panel.LocalModelsPanel`: server type,
  address, Test connection -> models with context length + reads-images (vision from Ollama /api/show capabilities),
  time limit, requests at once, model profiles table: Profile | Plans the rows | Extraction steps | Figure
  suggestions); the dialog scrolls. Main window: Models list = local profiles when the provider is local
  (`_refresh_profiles`; QSettings provider / local_model_profile), batch box disabled, no API key needed (hint asks for
  a local profile instead); local settings / key written only when changed. CLI: --provider local, --models <local
  profile> (default the first), --local-settings PATH, --list-local-models, env LOCAL_SERVER_API_KEY.
- Tests: tests/test_local_models.py (fake Ollama + OpenAI servers replaying runs/reference/eder1994 -> the reference CSV
  byte for byte; request formats; vision off; 2-at-once gate; listing; context refusal; unreachable server; the
  Settings window end to end). test_gui_offline points local_models.default_path at a temp file. --self-check: "Local
  model support".
- Installed for the live test (Mickey's OK): Homebrew `ollama` 0.40.15 (started with `ollama serve`; not a login
  service) + `gemma3:12b` (8.2 GB, vision, 128K max context). M2 / 24 GB: ~10 tokens/s generation.
- Live test (2026-11-08, eder1994, Ollama gemma3:12b, 64K context, images on, 1 request at a time): finished end to end
  in 33 min, $0, 91K in / 8.5K out (structure 6 min, chemistry 10 min; ~10 tok/s). Quality is the model's, as
  expected: 31 rows (reference 42), durations and temperatures right, Table 1's yield numbers read correctly but
  labelled as starting Gly instead of Gly-Gly / Gly3 yields -> no peptide yields, no salt concentrations; the
  conditions step filled flow / solid-material columns that don't apply. A 12B model is a framework check, not a
  usable extractor for this pack; larger models (30B+) are the realistic floor. A step's elapsed_sec includes its wait
  for the server's other requests.

## Drafting a research area from sample papers (2026-11-08, Mickey)

`pack_drafting.py`: Data Packs > New research area… > Start from "A draft made from sample papers (uses the API)"
(NewPackDialog `DRAFT`, shown only when the dialog gets `config=` -- the main window passes `current_config`; papers via
the shared PaperListPanel, progress bar, Cancel stops after the current request) or CLI `--draft-pack ID --area-name
NAME [--area-description TEXT] --papers LIST | --pdf | --paper`.
1. `survey_paper` per paper (4 at a time; text + table images via focused_search._paper_text; stage `pack_survey`,
   Claude Haiku 5.5 forced through RunConfig.models + profile "standard" in `_config`, budget 8K): `PaperSurvey` --
   field, row_unit, set_unit, variables [name, column WITHOUT unit, unit, kind number/integer/text, role, description,
   level row/set/paper, uncertainty, where, example]. Prompt prompts/pack_survey.md (bibliographic details and a
   sample's time point excluded). A failed paper is reported, not fatal; none surveyed -> PipelineError, no pack.
2. `synthesize` (stage `pack_synthesis`, Sonnet 5.5, budget 16K; input = compact JSON lines per paper):
   `PackProposal` -- description, set/sample words, 3-7 categories, 1-4 stages (per, keywords [] = always, parameters
   with column/unit/kind/description/category/choices/uncertainties/papers, rules, other_hint), row_rules.
   prompts/pack_synthesis.md (general columns over per-substance ones; merge synonyms; no metadata/methodology/other ids).
3. `write_pack`: packs.create_pack from the template, then PackDraft: example stage + formula removed; categories
   (table_order 30, 40, ...; reserved ids renamed '<id>_area'); category_columns (set_type -> methodology, duration_hr ->
   the first category); `column_for(base, unit, kind)` adds the app's suffix (variable_categories.unit_suffix: '°C' ->
   _C, K stored as °C, % -> _pct, min -> _hr, s-1 -> _per_hr), else the unit as a token ('_eV'), but NO suffix when the
   token would be misread ('% h-1' -> '_per_h' reads as hours); 'ph' -> 'pH'; a column already used by an earlier stage
   is dropped (`dropped`). Stages open_ended with the proposal's hint. Row rules -> structure_planner.rules.md.
   `check_new_id` validates before anything is paid for. Report drafted_from.md (pack folder + work folder
   <output>/pack_draft_<id>_<stamp>/ with each paper's audits and surveys.json).
- Live (3 prebiotic papers: eder1994, kim2019, faisal2005; standard): 41 s, $0.055, 21 parameters in 3 stages
  (conditions + materials, results, methods), 5 row rules, no check problems. A full eder1994 extraction with the
  drafted pack: 42 rows (= the hand-made pack's), $0.35, T / duration / Gly 1000 mM / NaCl 3330 mM / diglycine yields
  right; triglycine yields lost -- the draft chose one product + product_yield_pct per row (a general-columns choice the
  user can change in the editor). tests/test_pack_drafting.py (canned answers; the dialog end to end).

## Compounds for drafted packs; suggested additions to existing packs (2026-11-08, Mickey)

- **`compound_setup.py`** (local + PubChem, no model): `find_compounds(draft, pubchem)` -> `CompoundPlan` (compounds
  with CID / PubChem title / synonyms / roles / measures / categories / sources; `Replacement`s; not_identified):
  (1) substance PAIRS -- a text parameter whose name/description says species/reactant/product/additive/... + numeric
  parameters sharing its first word with a concentration or % unit (reactant_species + reactant_concentration_mM;
  product_name + product_yield_pct) -> replaced; compounds from the description's 'e.g. / such as' lists, choices and
  the draft's survey examples (`drafted_surveys.json`, now written to the pack folder by draft_pack);
  (2) compound-named columns ('mgcl2_concentration_mM': `names_in_column` drops GENERIC words, `formula_case` restores
  element case -- a digit, or 2-4 elements); (3) class columns with examples ('activating_agent_concentration_mM', e.g.
  diamidophosphate). A candidate counts when names.match_species (against the PREBIOTIC vocabulary: 'sodium_triMP') or
  PubChem identifies it; same CID = one compound. Role: product words / results category -> sampled, else initial;
  columns initial_<n>_aq_mM, sampled_<n>_aq_mM / _aq_%yield (species_column) in the replaced parameter's category.
  `apply` (ticked parts only): vocabulary + species_cids entries {cid, title, synonyms}, replaced parameters removed,
  CHEMISTRY_RULE added to every stage, builtin chemistry + postprocess normalize_species/mixing/molar_ratios;
  `ensure_chemistry_prompt` copies the prebiotic chemistry.md into the pack (the app has no generic one -- before this,
  ticking chemistry in a drafted pack had no prompt). `set_up_compounds(folder, pubchem, plan)` = find + apply + save.
  On Mickey's 'Prebiotic (Sam Papers)' draft (a copy): 7 compounds, all with CIDs (MgCl2, NaCl, UMP, 2',3'-cGMP, ribose,
  diamidophosphate, trimetaphosphate), 8 parameters replaced, check clean.
- **Additions** (`pack_drafting.suggest_additions(folder, papers, config)`): the same per-paper survey, then one request
  (stage `pack_additions`, prompts/pack_additions.md) with `_pack_summary` (categories, built-in steps, stages +
  parameters, other columns, row rules or the pack's own structure prompt excerpt, compound vocabulary) -> `PackAdditions`
  (parameters with stage + reason, new_stages, categories, rules with target rows/stage, compounds -- only with
  chemistry, notes). Local filter: a column already in all_columns() or a compound already in the vocabulary ->
  `left_out`. `Suggestion`s (kind/title/detail/reason/papers/payload/include); `apply_additions` writes the ticked ones
  (compounds resolved on PubChem; row rules into structure_planner.rules.md, or appended to the pack's own whole
  structure_planner.md when it has no {{PACK_RULES}} slot). Live (prebiotic copy; Bujdak1994, Chang1969, Flores1973 --
  Flores read nothing): 26 s, $0.047, 3 conservative suggestions (irradiation wavelength, energy input mode, detector
  wavelength -- the last overlapped the analysis step, hence built-in steps in the summary now).
- GUI: PackEditor bottom bar "Find compounds…" (`gui/pack_assist.CompoundSetupDialog`: tables of compounds and
  replaced parameters with ticks) and "Suggest additions from papers…" (`AdditionsDialog`: papers panel, Get
  suggestions on a thread, table with ticks, Apply); both save the editor first, then `_reopen` (summary message, the
  editor again on the new files). Off for the app's own packs (copy first); suggestions need `config` (PackEditor's new
  argument; the main window passes current_config). NewPackDialog draft option "Then find compounds…" (QSettings
  draft/find_compounds; DraftResult.compound_lines). CLI: `--find-compounds [ID]` (alone, or after --draft-pack),
  `--suggest-additions ID --papers ... [--apply-suggestions]`. tests/test_compound_setup.py.

## Keychain access across rebuilds (2026-11-08, Mickey: password asked twice after every rebuild)

macOS ties a keychain item's "Always Allow" to the app's code signature; PyInstaller's ad-hoc signature changes with
every build, so the stored keys (Anthropic + ADS) were asked for again each time. `packaging/make_signing_identity.sh`
(Mickey runs it once -- adding a certificate to his login keychain needs his OK) creates a self-signed code-signing
identity "Parameter Extractor Local Signing" (system LibreSSL: its .p12 imports into the keychain; OpenSSL 3+ would need
-legacy; key ACL -T /usr/bin/codesign; codesign accepts the UNTRUSTED certificate -- checked in a throwaway keychain --
so no password / trust setting). build_macos.sh re-signs the .app with it when present (`SIGN_IDENTITY` overrides the
name); the designated requirement is then 'identifier <bundle id> and certificate leaf = H"..."', the same on every
build -> one "Always Allow" per app (public and Dev have different bundle ids). Not a distribution signature.
Tests and dev scripts: PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 makes key_store a no-op (scripts/run_tests.py sets it for every
test; the GUI tests set it too) -- reading the keychain from the venv Python had also prompted. Use it in any ad-hoc
script that builds a MainWindow.

## Draft robustness, compound identity, naming conventions (2026-11-08, Mickey's 'Sam Papers' redraft)

His observations: the suggestions pass found more than twice the compounds of the draft; 'mg' (elemental magnesium) where
the paper used MgCl2; inconsistent names ('pH' instead of initial_pH); the drafting dialog's new checkbox overlapped the
paper buttons. Found too: ImpA -> 'isopropyl methylphosphonate' and RCP -> 'CP-640186' (PubChem's first hit for codes),
'borate' -> 'BORaTe' (formula casing), 'primer' -> a drug (column words sent to PubChem).
- **Survey**: `PaperSurvey.compounds` [{name as written, full_name, role starting/product/reagent/other, example}]
  (prompt: every salt by formula, buffers, activating agents, every product; not enzymes, dyes, kits, classes);
  **passes** (`survey_paper(passes=)`, audits pack_survey.passN; `merge_surveys` = union, first wins; dialogs default
  2 -- QSettings draft/survey_passes; CLI --survey-passes, default 2); the synthesis digest and the report list them.
- **compound_setup**: survey compounds are a source (trusted: kept without a CID when nothing identifies them; full
  name looked up first); `is_compound_name` drops classes / enzymes / panel letters, 'X/Y' split; a column token is
  spelled from its description's formula words or the survey names ('mg' + 'Mg2+ (as MgCl2)' -> MgCl2, salts before
  ions) and goes to PubChem only as a formula (`formula_case` now: a digit, or 2 elements in <= 4 letters / 3 in <= 5;
  re-casing only for lower-case tokens); codes (`is_abbreviation`) count only when PubChem lists the code among the
  compound's synonyms or a full name identifies them; a name the prebiotic vocabulary rules match takes that pack's
  hand-checked CID (`_reference_cids`). Pairs: a text column must only NAME substances (NAMING_WORDS) -- not
  'product_phase_state'; partners also by a shared substance word or, for products, result words in the same stage;
  replacements de-duplicated; survey products get the product pairs' measures. Chemistry is switched on only when
  compounds / replacements are applied.
- **conventions.py** `canonical(column, unit, kind)`: pH -> initial_pH / sampled_pH (measured/final words), reaction
  temperature -> initial/sampled_temperature_C, pressure -> initial/sampled_pressure_bar, a sample's reaction time ->
  dropped (duration_hr), wet-dry cycles -> cycle_number (integer), cycle length -> cycle_duration_hr, analysis
  technique -> analysis_method, solvent -> solvent_name, volume -> solvent_volume_mL, mineral/clay/surface ->
  solid_material_name (+ _mass_g), headspace / vessel / buffer / replicates / flow rate / longest oligomer;
  `strip_unit_words` ('primer_concentration_um' + mM -> primer_concentration_mM). Applied (on by default, QSettings
  draft/tidy_names, CLI --no-tidy) in write_pack (`tidy_parameter`, DraftResult.tidied, report section), in
  suggest_additions (before the already-a-column check) and as `CompoundPlan.renames` in the editor's renamed
  'Find compounds / tidy names…' review (third table).
- Live redraft of Sam Papers (11 PDFs, 2 passes): 133 compounds from the surveys, 108 with CIDs, codes without a listed
  synonym left without one; renames pH / reaction_pH / final_pH / reaction temperature / wet-dry cycles; reaction time
  dropped. tests/test_compound_setup.py (test_reported_misses_and_conventions, test_survey_passes_are_merged).

## Columns tab by category; pre-parse evaluated (2026-11-08, Mickey)

- **Columns tab** (pack editor): a `_ColumnTree` (QTreeWidget) -- one bold, link-coloured header per variable category
  (ColumnOrder of the pack on disk: every category, also empty ones, in table_order; Row / Provenance blocks first /
  last), 40 px header rows for the space between categories, columns as children with Unit (unit_for_column) and
  Filled by (stage_columns; 'not filled by a stage' muted). Double-click renames; drag reorders, a drop ONTO a column
  is refused (never a child of a column), a drop on a category moves the column there. Save: columns.json in tree order
  (= the dataset's order within a block), and columns placed under a category other than their default become explicit
  entries of it (`_store_column_categories`, only the moved ones). `add_column_named` adds to the selected category
  (else Other). `column_list` is gone (tests use add_column_named).
- **Compound columns get their own blocks** (compound_setup.apply): categories starting_compounds ("Starting
  Compounds") and products ("Products"), model_assigns false, after the area's own, with PATTERNS
  (`COMPOUND_CATEGORIES`: initial/stock_<n>_<phase>_mM, sampled_<n>_<phase>_<measure>) -- not explicit columns, so
  compounds accepted in later reviews land there too (they had gone to 'Reaction conditions').
- **Pre-parse** (Mickey: switch off parameters papers don't report before a multi-paper run?): `preparse.py` (Haiku,
  text only, the stage parameters listed) + `RunConfig.parameters_off` (for_run / triggered_specs / _paper_tools /
  step instructions drop them; a stage with none left doesn't run). Live A/B on the references
  (eval/preparse_2026-11-08.md): prebiotic mean $0.272 -> $0.263 incl. the pre-parse (-3%), accuracy 97.5% -> 89.7% --
  savings came from values then missed; the pre-parse drops parameters filled by rule/inference (sampled_temperature_C,
  summed solvent volume). NOT wired into the GUI (Mickey can decide otherwise); preparse.py kept as an evaluation tool.
- Risk-free saving kept: `StageSpec.could_trigger(paper_text)` -- a keyword-only-triggered stage (kinetics) whose words
  aren't in the paper isn't in a SINGLE paper's tool list (~3.6K cached tokens); with shared instructions (queues) the
  tool list stays fixed for the cross-paper cache.

## Prebiotic vs a suggestions-extended copy (2026-11-08, Mickey's "Prebio Chem DUPE")

eval/dupe_pack_2026-11-08.md: 18 live runs (Ferris 1993, Hirakawa 2025, Song 2024; 3 runs per pack; suggestions accepted
into a throwaway registry). DUPE +24% cost ($0.397 vs $0.320; product_structure always runs, bigger prefix, kinetics
output), consistency 74% vs 84%; a few valid extra columns (exchangeable cation, linkage, sequence composition) and
steadier compound names, but vocabulary junk caused misnamings (dTMP -> 'TMP', ppA -> p2A) and it missed sampled_pH.
Fix from it: suggest_additions filters compounds with compound_setup.is_compound_name (also for the model's own list),
splits 'X/Y', compares names with primes normalised; NOT_A_COMPOUND also covers ssDNA/dsDNA, oligo*, Cy5, FAM, Alexa*.

## Stage discipline; cross-path audit (2026-11-08, Mickey)

- **New stages cost a request per paper**: suggest_additions -- a suggested stage needs >= MIN_NEW_STAGE_PARAMETERS (3)
  parameters, else they join the closest existing stage (`_closest_stage`, word overlap; left_out note); its trigger is
  keywords only (the model's, else `_derived_keywords`; apply_additions never writes {"always": true}); prompt asks for
  stages rarely and keywords REQUIRED. Drafting -- `_disciplined_stages`: stages with < 3 parameters merged, at most
  MAX_ALWAYS_STAGES (2, most parameters) without keywords, the others get derived ones (notes in drafted_from.md).
- **Audit** (eval/audit_2026-11-08.md, improvements x paths). Fixed: normalize_chemistry -- a PubChem hit for a CODE
  counts only when corroborated (template CID, accepted CID, another non-code name of the paper with that CID, PubChem
  synonym, title), else a note; `PubChem.lookup_checked` (synonym check) for Find compounds; review suggestions
  (`new_variables._categorised`, kind parameter) proposed under conventions.canonical ('final pH' -> sampled_pH);
  pipeline flag `not_a_compound` (compound_setup.is_compound_name; never dropped); suggest_additions leaves out the
  user's accepted columns for the area (registry) too; drafting / suggestions / preparse pass the arXiv LookupCache.
  tests/test_audit_consistency.py.

## Readability pass on the main window (2026-11-08, Mickey: usable by domain scientists)

- One user-facing term: **data pack** (was "research area" in the window and "Data Packs" in the menu) -- every
  string literal in gui/*.py, pack_editing, packs, pack_drafting, compound_setup, cli (tokenize-based replace; code
  identifiers and the MODEL prompts keep "research area"); registry.STANDARD_LABEL "Standard (every data pack)".
- The workflow is numbered on screen (`_step`): **1 Data pack** (combo + New… + Edit… buttons -- `new_pack_btn`,
  `edit_pack_btn` (`_edit_current_pack`), + the pack's description `pack_description`), **2 Papers**, **3 What to
  extract** (was Parameters), **4 Options** (was Run options), **5 Run** (Extract data; `mode_label` now beside it).
  Under the Run row: `settings_hint` (missing key / folder, was scrolled out of sight under the panes), the status line
  (START_TEXT with a "Getting started" link), the privacy note.
- Help menu: Getting started… (`GETTING_STARTED`, `show_getting_started`).
- Plainer wording: tabs "Extracted data" (was Rows) and "Things to check" (was Flags) with tab tooltips; options
  "AI model and cost", "Read values: Once / Twice / Three times, keep the majority" (passes), "Half price, slower (batch
  mode)", "Read the arXiv version when there is one", "Also read the supplementary information", "While reading",
  "Suggest values the data pack has no column for", "Read simple plots automatically", "Numbered equations as text";
  focused search "Searching for a few values" / mode "Search for N values only"; parameter panel "Step / value",
  "Find a value…" and a plain explanation; Summary tab "Cost of each step" with tokens explained. Attribute names
  unchanged (tests: mode text "Search for 2 values only in 2 papers", menu "New data pack…").

## Editor opening speed (2026-11-08, Mickey: the data pack editor froze on opening)

Measured: opening the editor took 47 s for his 'Prebio Chem DUPE' pack (12 s for prebiotic) -- 1.7M calls of
RowSeparatorDelegate.sizeHint: `widgets.style_rows` queued a full resizeRowsToContents for EVERY inserted row and EVERY
filled cell (dataChanged), O(n^2) for the 277-row compound table. Now one restartable single-shot QTimer per table
coalesces a burst into one refit, and a hidden table (another tab) refits when shown (`_RefitOnShow`). After: 0.18 s /
0.46 s, every tab switch <= 0.06 s; all style_rows tables benefit (categories, suggestions, compound review).
Remembered-from-reviews window 0.92 -> 0.56 s: `category_options` cached per area per fill (was recomputed for ~4,800
rows), `variable_categories.bundled_shared` reads its file once (mtime-checked). scripts/run_tests.py appends every
failing file's full output to tests/.last_failures.log (a rare flaky failure hasn't been reproducible).

## Organics in target: drafted pack vs prebiotic (2026-11-09, Mickey)

Five papers (`Test Paper List/Organics in target`: mckay1997, takeuchi2020, muchowska2019, burchell2020, mars_delivery2018)
run in handoff mode with a pack drafted from them (`organics_in_target` in the user packs folder) and with prebiotic
chemistry; suggestions accepted and remembered. Write-up: `eval/organics_2026-11-09.md` (drafted pack 89/89 values,
$0.99; prebiotic 37/89, $0.75 -- its row rules exclude shock / delivery text results; it was better on the one aqueous
paper). Fixes:
- `units.unit_slug` ('molecules per joule' = 'molecules J-1' = 'molecules/J'; convert_printed treats equal slugs as the
  same unit); new units GPa, m/s, km/s, J/kJ/mJ, g/cm3, kg/m3; `observations.unit_for_column` falls back to a known
  unit's slug at the end of a column (`_GPa`, `_km_per_s`, `_J`; single letters only J/W/V) and
  `variable_categories.unit_suffix` names suggestions that way; '~' / '≈' / 'about' parse; wt% / mol% -> %;
  thousands separators (`units._number`, value_types `_as_float`: '1,000 rpm' was 1 rpm); temperature DIFFERENCES
  (`units.is_difference`: increase / rise / ΔT ...) convert without offset (stage values via is_error, review values via
  to_column_unit(difference=)); a limit for a parameter without a limit column -> note + flag (stage_values).
- Compound values: `flatten_to_template.printed_measure` -- a value in a unit the app can't put in mM keeps it as the
  measure (`sampled_HCN_gas_molecules_per_J`, `initial_FeCl2_aq_mmol`; alias '<role> <name> (<unit>)') instead of being
  dropped; starting compositions in % -> `_pct` (alias '<role> <name> %'; was proposed as _mM).
- PubChem: `query_name` spells Greek letters out (α-ABA had come back as GABA); compound_setup: a code whose full
  name PubChem didn't find isn't looked up as a code (HKG -> a drug); the name column is kept while non-chemistry
  per-product values depend on it (plan.note); COMPOUND_CATEGORIES get `sources` and any-measure patterns; chemistry
  switched on adds "amounts" + a `solvent_volume_mL` parameter to the first always-on stage.
- Grid rule / `grids` field only with RunConfig.table_grids (`StageSpec.grids`, for_run(grids=), chemistry
  prompt_text(grids=) removes the paragraph once -- never touch the paper text inside a prompt: shared instructions
  match on it).
- `Extraction.no_figure_rows`: run_pipeline without auto-digitizing, run_queue (`PaperQueue(digitize_by_hand=False)`),
  or a paper with no figures -> an empty row plan skips the extraction steps ('figures-only paper' no_results flag).
- TABLE_CAPTION_RE: 'Table N' + ONE space + a continuation word (for, shows, lists ...) is a citation; 14/148 corpus PDFs
  changed; faisal2005 reference observations regenerated (page 2 -> 3 for Table 1 values).
- pack_drafting works in handoff (`_handoff_folder`, `_survey_all` collects AnswersNeededError); design prompt asks for
  specific trigger words; drafted `column_for` gets `_us`/`_ns`/`_ms`/`_nmol`... (µs had become `_hr`).
- Exoplanet pack: pl_dens / st_dens unit g/cm3 (were '' -- 'g cm-3' is now a known unit and was refused).
- Not fixed: MDPI 'corrected version' PDFs with two text layers (burchell2020; no z-order in pdfplumber).
tests/test_organics_round.py.
- **Held-out test (same day, Mickey):** five other papers of the folder (tingle1991, kazemi2021, deluca2022, chyba1990,
  dacosta2022), both packs, handoff: drafted pack 40/41 values (70% of cells in its own columns -- higher than on its
  drafting papers), prebiotic 12/41; $0.93 vs $0.82 (prebiotic $0.59 on three no-row papers). Write-up with the
  direction (draft per batch; shared modules, starting with the analysis step + solution-chemistry calculations):
  `eval/organics_heldout_2026-11-09.md`. Trigger hit counts measured; thresholds NOT added (a false trigger ~$0.01, a
  miss loses values). Fixes: `flatten_to_template._with_marker` puts _range/_avg before any unit slug
  (`observations.unit_slug_suffix`) or a stage parameter's own unit (`with_range(column, unit)`); mTorr.

## Shared modules for data packs (2026-11-09, Mickey: step 2 after the held-out test)

`pack_modules.py`: MODULES `analysis` (builtin step + a copy of the prebiotic analysis_vocab.json + `hint_by_stage`
on open-ended stages + an Analysis category with pattern ^analysis_) and `solution_chemistry` (builtin chemistry +
CHEMISTRY_POSTPROCESS normalize_species / mixing / molar_ratios / amounts / water_type + solvent_volume_mL and
solvent_name on the first always-on stage + CHEMISTRY_RULE + the chemistry prompt via ensure_chemistry_prompt).
`techniques_named(texts)` (source vocabulary names + aliases; short all-caps names case-sensitive; a match inside a
longer technique's match is dropped) / `analysis_evidence(papers)` on the surveys' method-like variables + notes.
`draft_pack(..., modules_on=True)` -> `pack_drafting.add_modules` adds `analysis` when the surveys name a technique;
DraftResult.modules / module_evidence, report section "Shared modules added"; compound_setup.apply calls
`add_solution_chemistry` (its old names re-exported). CLI `--add-module MODULE ID`, `--no-modules`. Re-draft of the
organics pack as `organics_modules` (user packs folder): Muchowska 12 -> 45 filled columns, McKay / Takeuchi gain
their instrument details, nothing lost; ~+$0.02-0.035 per paper for the analysis step. Write-up:
`eval/pack_modules_2026-11-09.md`. Fix: a unit slug right after 'per' isn't the column's unit ('_molecules_per_J').
Open (Mickey): drafted pressures follow the app's bar convention (shock pressure 7 GPa -> 70,000 bar).
tests/test_pack_modules.py.
- **More modules (same day, Mickey; bar stays the default pressure unit):** `kinetics` and `wet_dry` (copies of the
  prebiotic stage files via `_add_stage`, their categories, wet_dry's two row rules into structure_planner.rules.md),
  `product_totals` (peptide_totals + oligomer_totals + their standard columns; `needs` solution_chemistry, which it
  adds). Each Module has `evidence(papers)` (survey words / product compounds); `evidence_for` -> draft_pack adds every
  module called for; `add_modules(folder, ids)` = one save (+ chemistry prompt). GUI: pack editor "Add modules…"
  (`gui/pack_assist.ModulesDialog`). The organics pack was swapped for the module version (same id; backup in
  `<app data>/pack_backups/`). test_pack_drafting's basic draft passes modules_on=False (its canned survey is about
  peptides, which now brings product_totals).

## Modules by reference, not copies (2026-11-09, Mickey)

Mickey: modules should be a clearly defined part of a data pack, LINKED so an improvement reaches every pack (copies
in each pack would drift). `modules/<id>/` (module.json -- `modules.ModuleManifest`: builtin_stages, postprocess, needs,
variable_categories, category_columns, standard_columns, pack_parameters, stage_rules, stage_hints, row_rules -- plus
stages/*.json, prompts/*.md, analysis_vocab.json); `<app data>/modules/` for the user's own (an app module id can't be
replaced). Files moved from the prebiotic pack (git mv): analysis_vocab.json, prompts/chemistry.md, stages/kinetics.json,
stages/wet_dry.json. pack.json `"modules": [...]`; `packs.Pack`: `own_manifest` (the file) vs `manifest`
(`merged_manifest`: module steps / calculations appended; a module category left out when the pack has the same id or
review sources, or already places every column it would hold; category_columns only into existing categories),
`module_ids()`, `file(name)` (pack's own first), prompt_path pack -> modules -> app, prompt_rules adds row_rules,
standard_column_entries adds module columns. `optional.load_specs` -> `_pack_specs(folder, module_ids)`: own specs +
module stage_rules / stage_hints (pack's own hint wins) / pack_parameters (first always-on stage, if no stage has the
column), then module stage specs (caches cleared on save / delete). Prebiotic = builtin [], postprocess ambient /
atmospheric / results_check + all five modules; every reference replay byte-identical.
- `pack_modules.py`: add_modules / add_module / remove_module write references; used(), describe(id), evidence_for;
  `migrate_copies(folder)` turns copies into links (identical files -- JSON compared parsed -- removed; differing
  ones kept and win; module-provided steps / calculations / identical categories / rules / hints / same-named stages
  out of the pack). Ran on Mickey's organics_in_target and prebio_chem_dupe (backup
  `<app data>/pack_backups/before-module-links-20261109-155832/`): both clean in the check.
- PackDraft: linked_modules / effective_steps / effective_calculations / module_columns; check: unknown modules,
  categories from modules accepted, a column named in its parameter's own unit slug ('_um_per_s' = µm/s) passes.
- Editor: **Modules tab** (list with ticks + Linked / "brought along by X" on the left; the selected module's
  description, what it brings, and -- for analysis -- its vocabulary, read-only, on the right). The "Analysis methods"
  tab and the "Add modules…" dialog are gone; built-in steps and calculations a module brings show ticked, greyed,
  "(from the X module)", and aren't written into the pack; Compounds tab follows the chemistry step from either
  source; the Stages tab notes stages linked modules run. A pack's own analysis_vocab.json stays editable there.
- Suggest-additions summary lists the linked modules and their steps / columns (no suggestions for what they cover).

## Module settings per pack; Data Packs window; steps vs stages vs modules (2026-11-09, Mickey)

Mickey: modules stay single shared versions, but a pack needs its own tweaks (units etc.), tracked per pack; a
standalone Data Packs place; and clear terms (steps / stages / modules were ambiguous; show where model calls come
from).
- **`module_settings.py`** + PackManifest `module_settings` {module id: {steps {name: off / keywords / table_images /
  rules_off / extra_rules}, parameters {module column: off / unit / description}, calculations_off, row_rules_off,
  stage_rules_off, families_off}}; only differences stored (`cleaned`). A unit change RENAMES the column
  (`unit_choices` / `column_in_unit`: same-dimension units whose name unit_for_column reads back -- half_life_hr ->
  half_life_min, pressure _GPa, temperature _K; seconds/days/L aren't offered: `_s` is the solid phase). module.json
  `fixed` {column: why} (solution_chemistry: solvent_volume_mL, solvent_name) -> unit unchangeable. Applied at load:
  packs.merged_manifest (calculations_off, category columns renamed), Pack.prompt_rules (row_rules_off),
  optional._pack_specs(folder, ids, settings_json) (`apply_to_spec`: step off -> gone, params off/renamed/described,
  column names also renamed in rules/intro; `pack_parameter`; stage_rules_off), analysis_vocab.vocabulary
  (families_off; techniques left with no family dropped; cache `_FILTERED`). PackDraft.module_settings /
  module_specs / module_columns / effective_calculations honour them; check() section "Module settings"
  (`ms.problems`: unknown module/step/parameter/calculation, unit the column can't be named in = error, fixed unit,
  a keyword-only step left without words). Default packs unchanged (references byte-identical).
- **Terms** (user-facing): *step* = one model request per paper (built-in = code; configurable = JSON in stages/ --
  folder and code names unchanged); *calculation* = local, free; *data pack*; *module* (linked, shared). GUI/CLI/check
  strings "stage" -> "step" (Stages tab -> "Steps", "Configurable steps"; check areas "Step 'x'" / "Steps").
  `pack_windows.PACK_PARTS_HTML` explains them (editor Overview tab, Help > How data packs work…).
- **`pack_overview.py`** `paper_flow(pack)` -> FlowStep(kind request / optional / local, label, source APP / PACK /
  "the X module", when = trigger text, repeats for passes, always) in run order: row planning, paper details, built-in
  steps (BUILTIN_LABELS), configurable steps, figure suggestions / equations (optional), calculations, formulas;
  `summary` ("5 model requests for every paper, up to 2 more ..."), `as_html`.
- **Editor tabs** (order shows the layers): Overview (parts + paper flow as saved; refreshed on Save), General,
  Columns, Steps, Rules, Formulas, Compounds, Modules, Module settings (`gui/module_settings_tab.ModuleSettingsTab`:
  linked modules list (• = changed); per module: its steps (run on/off, trigger words, table images, its rules
  tickable, extra rules), values table (Use / Column [renamed live] / Stored in combo / Description / From), its
  calculations, row and stage rules, instrument families; Reset to defaults; settings of unlinked modules dropped on
  save), Check. Tab tooltips say whose each tab is. Stages tab note lists module steps.
- **Data Packs window** (`gui/packs_window.DataPacksWindow`; Data Packs > All data packs and modules…, step-1 button
  "All data packs…"): tab Data packs (list app / yours; details = defined by the pack, modules linked (+ "changed" /
  "brought along"), paper flow; Use for the next run, New, Copy, Edit, Check, Remove (own only; `remove_pack(parent,
  pack)`), Open folder); tab Modules (shared): what each brings (describe(), now in step/calculation words), linked
  by which packs, Open my modules folder. MainWindow._open_pack_editor(folder, tab index or NAME, parent).
- Main window: "What to extract" step tooltips say "one request to the AI model ... from <source>"
  (parameter_panel._step_sources); Getting started mentions the cost per step.
- Docs: template README "Words used here and in the app" + "Module settings"; `modules/README.md` (module folder and
  module.json keys; in package data). tests/test_module_settings.py (settings applied, other packs unaffected, check,
  cleaned, flow, a paper run with half-lives stored in minutes, the tab, the window).

## One Modules tab; overview layout; drafting with modules first (2026-11-09, Mickey)

- Editor: the Modules and Module settings tabs are ONE "Modules" tab: list (tick = link; column "In this data pack":
  linked / brought along by X / • changed); the right side scrolls through the selected module's page -- title +
  status + Reset, description, "What it brings", "Settings for this data pack" (`module_settings_tab.ModuleSettingsEditor
  .build(mod)` when linked; `release()` before a page is replaced -- it held deleted widgets once), and the Analysis
  methods vocabulary (`vocab_box`, built once, reparented per page). The page follows the pane's width (horizontal
  scrolling off, Ignored size policy). `self.module_settings_tab` is the editor helper (values(linked ids), reset,
  changed, values_table).
- Layout: `pack_overview.PARTS` / `parts_html()` / `STYLE` (tables with padding, line-height) used by the editor's
  Overview, Help > How data packs work (now a resizable dialog with a QTextBrowser, not a message box) and the Data Packs
  window; `as_html` = one table per kind (#, Step + grey description, From, Runs for). Document margins 18.
- Data Packs window: the editor / New / Copy open with the window hidden (`_aside`) -- after switching apps it had come
  back on top of the modal editor, unusable.
- **Drafting** (eval/drafting_modules_2026-11-09.md): modules chosen from the surveys BEFORE the design
  (`pack_modules.evidence_for`, new `solution_evidence`); `pack_drafting.modules_brief` -> prompt slot {{MODULES}} from
  module.json `covers` (new field); `write_pack(modules=)` links them, drops parameters/steps/categories a module covers
  (`covered_by_module`: module columns, kinetics/wet-dry/totals/analysis words, substance+amount words for chemistry)
  -> report "Left to the modules"; a step named like a module step is renamed. `draft_pack(compounds=None|True,
  pubchem=)`: compound setup runs automatically when the chemistry step is linked (GUI/CLI no longer call it
  afterwards). Survey compound role `analysis` (skipped), compound numbers stripped (`_without_compound_number`), product
  measures from the examples (`_example_measure`). `api_client._decoded` takes the leading JSON of a string with stray
  words after it. Live: no duplicate steps (was 3), check clean; eder1994 with the drafted pack 42 rows, 150/150
  values equal to the reference (replayed with the measure fix).

## Window chains; Peptides and oligomers module; series fill-in (2026-11-09, Mickey)

- **Input lost after Help > How data packs work > All data packs > Check > close each** (reproduced: the hidden help
  dialog stayed the active modal widget). Rules now: no window opens the next one from inside its own handlers --
  it records what comes next and closes, the opener opens it (help: `wanted` flag, packs window after exec returns;
  PackEditor.next_folder for Copy / a helper's rewrite, `MainWindow._open_pack_editor` loops over it). The Data Packs
  window is ApplicationModal but shown with show() (no exec): `_aside` hides it while an editor runs, and hiding a
  window inside its own exec() ends that loop. One instance (`_packs_window`, WA_DeleteOnClose).
  tests/test_window_chains.py drives the chains with timers (schedule the next step BEFORE an act that blocks in exec)
  and checks activeModalWidget() is None and the main window takes input.
- **Module `peptides_oligomers`** ("Peptides and oligomers"; git mv of product_totals; `modules.ALIASES` maps the old id
  in resolve / unknown / settings_for). New manifest fields: `prompt_rules` {built-in step: [rules]} -> the step prompt's
  `{{MODULE_RULES}}` slot (prompt_loader; `Pack.module_prompt_rules`, module setting `prompt_rules_off`; the line is
  removed when empty) -- the chemistry prompt's peptide / cyclic / n-mer / oligomer-table / unsequenced-product rules
  moved there (a generic "(X)4 for 4+ repeats" line stays); `compound_series` -> compound_setup `_fill_series`: every
  length between the shortest and longest of a homopolymer series (`names.homopolymer` / `homopolymer_name`, peptides
  and n-mers, <= MAX_SERIES_LENGTH 60) with the roles / measures ALL members share. Prebiotic links it; Mickey's DUPE
  pack updated (backup pack_backups/before-module-rename-*). Live/replay: truman through the drafted pack -> (Gly)4..12
  in the dataset (were held for review), totals = reference.

## Peptides and oligomers module: rings, linkage isomers, nucleotides, polymers (2026-11-09, Mickey)

names.py (app-wide rules; the module's chemistry `prompt_rules` tell the model the same names): `cyclic_name` writes a
ring from its alphabetically first rotation (cyclo(Val-Gly) = cyclo(Gly-Val) -> 'cyclo_Gly-Val'; the reverse direction
stays distinct); `linkage_dimer_match` (A2'p5'A -> "2mer_A_2'-5'", pA3'p5'A -> "p-2mer_A_3'-5'", ApA -> '2mer_A', ApU ->
'2mer_AU'); `nucleotide_match` (pA/ppA/pppA -> AMP/ADP/ATP, 5'-AMP -> AMP, dTMP, "3'-AMP", cAMP -> "3',5'-cAMP",
"2',3'-cGMP", full names like "adenosine 5'-diphosphate", underscores read as spaces); `polymer_match` (polyA / poly(rA)
-> poly(A), poly(dT), polyglycine -> poly(Gly); not polyphosphates); `AMBIGUOUS` {TMP, TDP, TTP, p2A, p3A}: never matched,
never looked up on PubChem (normalize -> `ambiguous_name` flag), never preferred over a full name, never in a compound
vocabulary (compound_setup.is_compound_name). oligomer_totals counts 'p-<n>mer_' too. Tests that used 2'-CMP for the
PubChem identity path now use glycolaldehyde / hydroxyacetaldehyde (nucleotides are rule-matched, not looked up).

## Modules drafted from papers; five new app modules (2026-11-09, Mickey)

`module_drafting.py` (Data Packs window > Modules > "Suggest modules from papers…" = gui/pack_assist.ModuleDraftDialog;
CLI `--draft-modules --papers LIST [--write-modules] [--modules-out DIR] [--survey-cache DIR]`): surveys (pack_drafting
.survey_paper, now with `cache_dir`: key = paper path+size+mtime / identifier, passes, prompt, model) -> one Sonnet
request (prompts/module_synthesis.md, `existing_brief()` = every module's covers + columns; stage "module_synthesis" in
pack_drafting._config) -> `check_proposals`: column_for / tidy_parameter; columns a module OWNS (`_existing_columns`,
not its pack_parameters) dropped; `core_columns()` (conventions targets + the app packs' own step and non-compound
template columns) -> pack_parameters; `clean_description` strips unit talk; evidence words: GENERIC_SHARE 0.85,
MIN_PRECISION 0.5 against the papers the designer listed (`_listed`); shared columns -> the larger proposal;
< MIN_PARAMETERS 3 dropped; `extends` (an existing module, aliases resolved) -> written into a USER module, reported for
an app module. `write_module` -> module.json (`evidence.words`, category, category_columns, pack_parameters, row_rules)
+ stages/<id>.json (trigger keywords = evidence, `min_hits` MIN_TRIGGER_HITS 3). ModuleManifest `evidence`, `covers`;
pack_modules.evidence_for links any module with evidence words. StageTrigger `min_hits` (default 1 = as before):
`keyword_hits` counts mentions outside the reference list. focused_search.read_paper_list takes a whole line as a path
when it is an existing .pdf containing commas.
New app modules (rounds reviewed by me; eval/modules_from_papers_2026-11-09.md): mineral_surfaces, impact_shock,
heat_flow_chamber, flow_reactor, fluid_inclusions (each one keyword step, min_hits 3) + peptides_oligomers' step
`oligomer_linkage` (2'-5'/3'-5' shares; Prebiotic gets it -> its spec list / step counts in tests updated). Not linked by
the Prebiotic pack (link them per pack). Cost record: rounds $0.605 / $0.359 / $0.313, held-out surveys $0.065, two
validation extractions $0.46.

## Cost pass on the module structure (2026-11-09, Mickey)

eval/cost_pass_2026-11-09.md (pack Prebiotic chemistry, now also linking mineral_surfaces + flow_reactor; 5 references +
Hirakawa/Ferris/Islam; Standard / Balanced / Economy). Built:
- `structure_plan.step_plan_json` (one-line JSON, the fields steps use, ids 'S1' / 'S1.2' + ID_NOTE) replaces
  `structure.model_dump_json(indent=2)` in every extraction step (not figure_planner); `plan_ids` -> RunContext.plan_ids
  (pipeline after planning); `expand_ids` in api_client.call_structured (before audit/output are written) puts labels
  back: set fields get the set label (also from a sample id), sample fields the sample label, other fields the label
  of what they name; `_fill_set_from_sample` uses the sample id (labels like 't = 97.3 h' repeat across sets).
  Prompts (optional_stage, chemistry, term_search, SAMPLE_KEY) ask for ids.
- Row planning: PlannedSample.source default '' and only when it differs from the set's; excluded <= 8 words; notes one
  sentence (prebiotic + generic structure prompts). Chemistry `mM` only for mass/volume (prompt + field description).
- Balanced: `api_client.steps_model_differs` -> the planner's paper blocks uncached (`_paper_blocks(cached=False)`);
  `warm_cache(ctx)` (one max_tokens=1 request with the steps' exact prefix: tools, system, paper) before the parallel
  steps; skipped when `_send` is replaced (tests: `_REAL_SEND`), batch, handoff, local, no caching; usage stage
  `cache_warmup` (stage_order).
- SoluteEntry v / u / q / src / c have Python defaults (None / None / '' / '' / 'low') while staying required in the sent
  schema (`_required`): one incomplete species no longer fails the step.
Results: Standard reference cost $0.247 -> $0.229 (-7%, 8 papers -9%), accuracy 94.6% -> 96.6-98.1%; Balanced $0.103 ->
$0.084 (-18%), 92-94%; Economy $0.016, 88%. tests/test_cost_pass.py.

## Tests that survive data pack changes (2026-11-09, Mickey: linking a module kept breaking tests)

Two causes, both fixed:
- **The user's own data reached tests.** Everything per user (data packs + modules made in the app, registry, caches,
  local model settings) lives under `registry.default_registry_path().parent`; env `PARAMETER_EXTRACTOR_DATA_DIR`
  (`registry.DATA_DIR_ENV`) now replaces that folder. `scripts/run_tests.py` gives every test file an empty temp one;
  every tests/test_*.py starts with `import _isolation` (tests/_isolation.py: the same for direct runs, keychain off,
  QSettings as an ini file in that folder under org "ParameterExtractorTests"). New test files: keep that line first.
- **Tests pinned the app packs' exact contents** (Prebiotic's steps, categories, column blocks, the `cat` enum, request
  counts, category positions, "unknown" example columns a module could define). Rewritten to check the RULE with
  expectations from the pack: `tests/pack_facts.py` -- `module_ids`, `module_step_names`, `module_category_ids`,
  `without_module_steps/categories`, `request_steps`, `in_order` / `present_in_order`, `linked(pack, *modules)` (the
  pack itself, or a copy in the test's data folder that links them -- for tests of what a module DOES), `module_step(
  name)` (a module's step via a pack linking it). Made-up names for unknown columns/compounds (`zz_test_...`,
  Trp-Met-Cys, (Gly)90, 37mer_CGU). Fakes of `_send` answer an unknown step with an empty answer.
- **Replays of reference runs stay sensitive to UNLINKING** a module they were recorded with
  (`pack_facts.RECORDED_WITH`: Prebiotic analysis, solution_chemistry, kinetics, wet_dry, peptides_oligomers) -- the
  pack really extracts something else then; the assertion message says which module and how to fix it
  (`why_replay_differs`: re-record or relink). Linking more never changes a replay (unrecorded steps replay empty).
  The check of the app's own packs (test_pack_editing) also fails on purpose when Prebiotic's category lists name a
  column whose module was unlinked.
- `scripts/check_test_robustness.py [link unlink new analysis]`: the suite under each change to the app packs (every
  module linked; two unlinked; a new always-on module with a step/column/category linked to both packs; Analysis
  unlinked), restored with git afterwards (refuses while those pack.json files have uncommitted changes); ~6 min, all
  pass. Run it after changing tests that touch packs.
- App fixes found by it: the pack editor's `tab_index` found no "Check" tab once its title carried a count ("Check
  (1/2)") -- Data Packs > Check on a pack with problems crashed; `schemas/wet_dry.py` / `stages/wet_dry.py` read the
  Wet-dry module's step itself (they failed on import / KeyError when the active pack didn't link it).

## Local model server on Mickey's Windows PC; first real test (2026-11-10)

- `docs/local_model_server_brief.md` (for a Claude agent on another machine: what the app sends, sizes, tests, what to
  report) -> `docs/local_model_server_report.md` (Mickey's PC: RTX 3090 24 GB, Ollama 0.40.16 at
  `http://192.168.1.129:11434` on the LAN, q8_0 KV cache + flash attention, `LLAMA_ARG_FIT_TARGET=512`). Settings to
  enter: `qwen3.8:27b` context 131072 (vision), `gemma4:31b` context 81920 (vision), requests at once 1, profile =
  qwen for all roles. `/api/show` reports 262144 for both -- the models' limit, NOT what fits in VRAM (layers spill to
  the CPU: ~30 -> 6.5 tok/s). Both are thinking models (~1K tokens of reasoning per request before the JSON).
- Live eder1994 (prebiotic, no PubChem, no registry, qwen everywhere): 5.3 min, $0, 42/42 rows (13 sets), 87.2% of the
  reference -- ALL 84 misses experiment_type / solution_type: the model reasoned 'Batch' / 'Wet' in its note but left
  the optional `txt` out and sent v = 0 (Sonnet/Haiku always fill it). Every other value = reference. Steps: plan 66 s,
  metadata 12 s, kinetics 60 s, analysis 94 s, conditions 166 s, chemistry 251 s; 21K output tokens. No `other`
  suggestions. Kept locally: `runs/local_models/eder1994_qwen3.8-27b_20261110/` (+ run_eder1994_local.py).
- Fixes: `local_models.LOCAL_REQUIRED` ("txt") required in the schema sent to local servers (`_require_local_fields`;
  Claude requests unchanged); `optional.stage_values` reports a text parameter answered without text as a problem
  (-> unit_conversion flag naming the model's note) instead of skipping it silently; the low-confidence flag shows
  '(no text given)' for such values, not '= 0'. tests/test_local_models.py::test_text_values_a_local_model_must_give.
  NOT yet re-run live (server down) -- next: eder1994 again, then a long exoplanet paper for the 128K context.
