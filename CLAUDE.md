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
- **Peptide naming convention** (Mickey, 2026-10-15; replaces relying on the
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
