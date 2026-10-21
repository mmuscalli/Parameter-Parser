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
- **CSV uses the template's names and order** (Mickey, 2026-10-14):
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
