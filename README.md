# Parameter Extractor

Extracts experimental parameters from published prebiotic peptide-synthesis
papers (metadata, experimental methodology, and reported solution chemistry)
into the row/column shape of the EORE `PaperDataTemplate.xlsx` dataset, using
the Claude API.

**Status: prototype.** It runs end to end and reproduces the hand-curated
eder1994 dataset (42/42 rows), but it has been validated on one paper only.
Every output is meant for human review: each run lists anything it's unsure
about in `plausibility_flags.json`. A desktop app is planned (see "Roadmap").

## Install

Requires Python 3.10+. No other software is needed: PDF handling is pure
Python.

```bash
python -m venv .venv
.venv/bin/pip install -e .          # from this folder
```

This installs the `parameter-extract` command. (Without installing, `python main.py`
from this folder does the same thing.)

For the desktop app, install the `gui` extra as well:

```bash
.venv/bin/pip install -e ".[gui]"
.venv/bin/parameter-extractor-gui   # or: .venv/bin/python -m parameter_extractor.gui
```

To build a standalone, double-clickable app (no Python needed to run it), see
[packaging/README.md](packaging/README.md).

To check an installation without running an extraction (free):
`parameter-extract --self-check --pdf some-paper.pdf`.

## API key

Runs call the Anthropic API, so you need your own API key. **The paper's text
and table images are sent to Anthropic** as part of each run.

For the command line, either set `ANTHROPIC_API_KEY` in your shell, or copy
`config/.env.example` to `config/.env` and fill in the key. `config/.env` is
git-ignored; never commit a real key.

## Desktop app

Choose a PDF (or drop it onto the window), paste your API key, pick where
results go, and click **Extract data**. A progress bar follows the six steps.
Cancel stops after the current step. When the run finishes:

- **Rows**: the extracted CSV, measured values first. Flagged rows are
  highlighted; hover for the reason.
- **Flags**: everything to check by hand. Select one to see the full issue,
  the supporting quote from the paper, and where it appears.
- **Summary**: token usage per step, plus buttons to open the results folder
  or the CSV.

Tick *Remember on this computer* to keep the key in the system keychain
(macOS Keychain / Windows Credential Manager). It's never written to a file.
Results are saved exactly as with the command line.

## Command line

```bash
parameter-extract --pdf "path/to/paper.pdf"                 # extract a paper
parameter-extract --pdf "path/to/paper.pdf" --out results/  # choose the output folder (default: ./runs)
parameter-extract --pdf "path/to/paper.pdf" --triage-only   # optional screening only (see below)
```

A run takes about two minutes for a 6-page paper and uses roughly 75K input /
21K output tokens.

The paper is assumed to be one you've already chosen. `--triage-only` is an
optional screen against one curator's inclusion criteria
(`prompts/triage.md`), meant for filtering a pile of candidate papers. It never
stops a normal extraction run.

## What a run produces

Each run writes a new folder, `<output>/<pdf name>_<date-time>/`, and never
overwrites an earlier run:

| File | Contents |
|---|---|
| `<pdf name>_extracted.csv` | One row per sample, in PaperDataTemplate's column naming |
| `plausibility_flags.json` | Anything to check by hand (see below); absent if nothing was flagged |
| `run_summary.json` | Settings used (never the key), models, token usage, timings |
| `<stage>.output.json` / `<stage>.audit.json` | Each step's structured result, plus the exact prompt sent and the raw response |
| `parsed_paper.json`, `page_images/` | The extracted text, and renders of pages containing tables |

### Flags and confidence

Every extracted value carries the model's own confidence rating
(high/medium/low) and a supporting quote from the paper. `plausibility_flags.json`
lists:

- **Paper-level issues**: values below the confidence threshold, and
  structural problems such as a concentration given both paper-wide and for
  specific sets (it's left out of the CSV rather than copied onto every row).
- **Row-level issues**: out-of-range values (temperatures, negative
  concentrations, yields outside 0–100%) and low-confidence measured values.

The thresholds are `CONFIDENCE_FLAG_BELOW` (default `"high"`, so medium and low
values are flagged) and `CONFIDENCE_DROP_BELOW` (default off; set it to blank
low-confidence values out of the CSV) in `src/parameter_extractor/config/settings.py`.
The confidence ratings are the model's self-assessment and vary between runs,
so treat them as a prompt to check, not a guarantee.

## How it works

1. **Parse** the PDF to text (pdfplumber) and render pages with a "Table N"
   caption to images (pypdfium2). Two-column tables often garble in plain text,
   so the model is shown both and told to trust the image.
2. **Plan structure**: identify experiment sets and samples (the CSV's rows).
3. **Metadata**: title, authors, year, journal, DOI. If the paper doesn't
   print a DOI, CrossRef is queried; a match is only accepted when both title
   similarity and CrossRef's own score clear conservative thresholds.
4. **Methodology**: vessel, solvent, temperature, pressure, analysis method, …
5. **Chemistry**: every species and concentration (initial and measured),
   mapped onto the template's controlled vocabulary. Unknown species are
   kept and listed for review, never dropped.
6. **Assemble** the rows, run the checks, and write the outputs.

Figures and scatter plots are not read yet. Only values given in text or
tables are extracted.

## Using it from Python

The command line is a thin wrapper over a library call that a GUI uses too:

```python
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline

result = run_pipeline("paper.pdf", RunConfig(api_key="sk-ant-...", output_dir="results"),
                      on_progress=lambda e: print(e.step, e.total_steps, e.message))
result.csv_path, result.paper_flags, result.row_flags, result.input_tokens
```

Failures raise `parameter_extractor.errors.PipelineError` subclasses whose message
is written for the end user (bad key, model unavailable, scanned PDF, …).
Passing a `threading.Event` as `cancel_event` lets a caller stop a run
between steps.

## Project layout

```
src/parameter_extractor/
  pipeline.py        run_pipeline() / run_triage_only(): the library entry points
  cli.py             the parameter-extract command
  config/            settings.py (defaults) and run_config.py (one run's settings)
  run_context.py     progress events, cancellation, per-run API client and usage log
  errors.py          user-facing error types
  api_client.py      the only place that calls the Anthropic API
  stages/            one module per extraction step
  prompts/           the instructions sent for each step
  schemas/           Pydantic models for each step's output, plus template_vocab.json
                     (the controlled vocabulary, generated from PaperDataTemplate.xlsx)
  ingestion/         PDF parsing, CrossRef lookup, flattening to template rows
  validation/        plausibility/confidence checks; gold-standard scorer (off)
  calculators/       simple deterministic conversions (unit conversion, % yield)
  gui/               the desktop app (PySide6): main_window, background worker, keychain
  diagnostics.py     --self-check: verifies an install or packaged app (no API cost)
packaging/           build the standalone app: PyInstaller spec, build script, icons
tests/               offline tests: no API calls, run in a few seconds
runs/                reference runs for eder1994 (see below)
eval/gold_standard/  empty until a curated answer set exists
```

## Tests

```bash
.venv/bin/python tests/test_pipeline_offline.py
.venv/bin/python tests/test_crossref_lookup.py
.venv/bin/python tests/test_gui_offline.py      # needs the [gui] extra; runs off-screen
.venv/bin/python tests/test_diagnostics.py
```

`test_pipeline_offline.py` replays the saved model responses from
`runs/eder1994_auto/` through the full pipeline (real parsing, rendering,
flattening and checks, with no API calls) and requires the output to match
the committed CSV exactly. Run it after any change.

## Reference runs in `runs/`

- `eder1994/`: the original **hand-built** demo, produced by Claude reading the
  paper and filling the same schemas, before any API key existed. Marked
  `"model": "manual-claude-demo"` in its provenance files. One transcription
  error (set 001013 is Ca²⁺, not Ba²⁺) was found by the automated run and
  corrected, with a note in the provenance files.
- `eder1994_auto/`: the first real automated run. It matches the hand-built
  demo on all 42 rows and is used by the offline test.
- `eder1994_check/`: a later run where the model mislabelled one NaCl value as
  paper-wide; kept as the example that motivated the paper-wide species check.

## Gold-standard validation (off)

`validation/gold_standard_eval.py` scores output against a curated answer set.
It's off (`ENABLED = False`, `settings.USE_GOLD_STANDARD = False`) until that
set exists. Then drop its CSV into `eval/gold_standard/` and switch both on.

## Roadmap

1. ✅ Pipeline as a library (progress, cancellation, user-facing errors, run folders)
2. ✅ Pure-Python PDF handling and installable package
3. Desktop app (PySide6): window ✅; macOS app + .dmg build ✅ (unsigned);
   still to do: code signing/notarization, Windows build
4. Reading figures and scatter plots

Before a public release: choose a project license and a final name.
