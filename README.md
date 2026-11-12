# Parameter Extractor

Parameter Extractor reads published scientific papers and pulls the experimental values they report into a
dataset: one row per experiment or sample, one column per variable, with the quote, page and confidence behind
every value. It uses an AI model (Anthropic's Claude, or a model you host yourself) to read the paper, and local
code for everything that can be done without one: parsing the PDF, unit conversions, calculations, checks.

It is meant to speed up building a dataset by hand, not to replace the person checking it. Every run lists what
deserves a second look ("Things to check"), and nothing the app is unsure about goes into the dataset without
being flagged.

**Status:** in development and used by its author; not yet publicly released. It ships with two data packs,
*Prebiotic chemistry* and *Exoplanets*, and you can make your own for other fields. The macOS app is unsigned, and
there is no Windows build yet.

## Install

Requires Python 3.10 or later. PDF handling is pure Python, so nothing else is needed.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[gui]"        # from this folder; leave out [gui] for the command line only
.venv/bin/parameter-extractor-gui        # the desktop app
.venv/bin/parameter-extract --help       # the command line
```

To build a double-clickable macOS app (no Python needed to run it), see [packaging/README.md](packaging/README.md).
To check an installation without running an extraction (free): `parameter-extract --self-check`.

## Before the first run

- **An Anthropic API key** (Settings… in the app). It is kept in the system keychain, never in a file. For the
  command line, set `ANTHROPIC_API_KEY`, or copy `config/.env.example` to `config/.env` and fill it in (that file is
  ignored by git).
- **Or a model server** (Models › Connections): a local one (Ollama, LM Studio, llama.cpp, vLLM on your own
  machine or network: no API key, no cost per paper, but slower) or a hosted OpenAI-compatible service. Results
  from models other than the default Claude ones haven't been validated the way Claude's have (every such run is
  flagged). See [docs/local_model_notes.md](docs/local_model_notes.md).
- **Models › Model profiles…** (or *Models…* beside the Model list) sets which model plans the rows, reads the
  paper's details, does the extraction steps, suggests figure settings and converts equations, plus advanced
  settings (output cap, temperature, prompt caching, steps at once, retries, prices). Standard, Balanced and Economy
  are the tested defaults: changing one asks first, marks it as changed, and *Reset to default* restores it. Your own
  profiles, on Claude or on a server, appear in the main window's Model list.
- **A results folder.** Every run writes a new folder there and never overwrites an earlier one.

**Privacy:** each paper's text and table images are sent to Anthropic (or to your own model server) to be read.

## Using the app

The window is laid out as five numbered steps.

1. **Data pack**: what to extract. A data pack defines one research area: its columns, the extraction steps
   that fill them, its rules and its calculations. Pick the one for your field, or make one (below).
2. **Papers**: add PDFs (or drop them on the window), type an arXiv ID, DOI or ADS bibcode, or add a list of
   papers from a CSV or text file. A paper's supplementary information is read with it when it sits next to the
   PDF (`paper_SI.pdf`).
3. **What to extract**: everything ticked gives the full dataset. Untick whole steps you don't need, or untick
   single values to run a cheaper *search for a few values* instead. Some steps can be narrowed further, e.g.
   to a few compounds or a few instrument families.
4. **Options**: the AI model (cost against accuracy), whether to read values two or three times and keep the
   majority, half-price batch mode, reading the arXiv version of a paper, and more. Hover over any option for an
   explanation.
5. **Run**: press **Extract data**. Several papers become a queue, extracted a few at a time.

While a paper is read you may be asked which **figures** to digitize: a built-in plot digitizer reads values off
a figure, with axis calibration, suggestions for the series and their conditions, and automatic detection of
points and bars where the plot is simple enough. At the end, a **review** offers values the data pack has no
column for yet (a new compound, a condition the pack doesn't record). Nothing new is added unless you accept it;
with *Remember* ticked, later papers fill that column automatically.

### Results

The tabs at the bottom show:

- **Extracted data**: the dataset. Hover over a value to see where it came from: the step, the quote, the page,
  the model's confidence, and any conversion or calculation.
- **Things to check**: values worth a second look, grouped by kind (low confidence, assumed values, conflicting
  values, unit problems, values calculated by the app, data reproduced from other papers, ...).
- **Summary**: requests made, tokens used and cost per step; buttons to open the results folder or the CSV.
- **Figures**, **Tables**, **Equations**: what was found in the PDF, and what was digitized.

### Data packs and modules

**Data Packs › All data packs and modules…** lists the packs, what each one asks the model per paper, and the
shared modules they link (analysis methods, solution chemistry, kinetics, wet-dry cycling, peptides and oligomers,
and more). A module is defined once and linked by any number of packs, so an improvement to it reaches all of them;
a pack can still adjust a module's settings for itself (units, trigger words, rules).

To make a pack: **Data Packs › New data pack…** starts from a template, a copy of an existing pack, or a draft
the app writes from a few sample papers you give it (a few cents). The pack editor (Data Packs › Edit…) covers
columns, steps, rules, formulas, compounds and modules, and checks the pack before saving. **Help › How data packs
work…** explains the parts. The template's guide is
[src/parameter_extractor/packs/_template/README.md](src/parameter_extractor/packs/_template/README.md).

## Cost and time

Each paper gets a few requests: one to plan the rows, one for the paper's details, and one per extraction step
the data pack uses. Recorded costs per paper:

| Model choice | Typical paper | Long catalogue paper |
|---|---|---|
| Standard (Claude Sonnet; the default, most accurate) | $0.15–0.30, 1–2 min | up to about $1.85, ~5 min |
| Balanced (Sonnet plans, Haiku extracts) | about $0.08–0.10 | not recommended for exoplanets |
| Economy (Claude Haiku) | $0.01–0.05 | about $0.30–0.45 |
| Local model server | free | free, but ~35 min on a 24 GB GPU |

Batch mode halves the price and takes several minutes longer per paper. A search for a few values costs a fraction
of a full extraction. The Summary tab shows what each run actually cost.

## Command line

```bash
parameter-extract --pdf paper.pdf --out results/              # one paper, full extraction
parameter-extract --paper 2308.05343 --pack exoplanets        # by arXiv ID, DOI or ADS bibcode
parameter-extract --queue papers.csv --batch                  # many papers, half price
parameter-extract --papers papers.csv --focus pl_orbper       # search for a few values in many papers
parameter-extract --list-packs                                # data packs and their steps
parameter-extract --list-parameters --pack exoplanets         # what a search can look for
parameter-extract --provider local --models MY_PROFILE --pdf paper.pdf   # on your own model server
```

`parameter-extract --help` lists every option, including drafting data packs and modules from sample papers. The
command line uses the same data packs and remembered variables as the app, but never adds new variables itself.

## What a run produces

Each run writes `<results folder>/<paper name>_<date-time>/`:

| File | Contents |
|---|---|
| `<paper>_extracted.csv` | The dataset: one row per sample, columns grouped by category (identifiers, metadata, methodology, conditions, starting compounds, products, ...), then provenance columns |
| `<paper>_observations.csv` | The same values in long format, one per line, with unit, quote, page, step and confidence |
| `<paper>_columns.csv` | Every column with its category |
| `plausibility_flags.json` | The "Things to check" list |
| `new_variables.json` | Values offered in the review: what was accepted, and everything left out |
| `run_summary.json` | Settings (never the key), models, tokens, cost, timings |
| `<step>.output.json`, `<step>.audit.json` | Each request's answer and exactly what was sent |
| `tables/`, `figures/`, `equations/` | Crops of the paper's tables, figures and equations; digitized figures with every click |

A queue writes one such folder per paper plus combined CSV files; a search for a few values writes one table for
all papers.

**Correcting and checking.** Double-click a value in *Extracted data* to correct it: it's checked against the
column, saved with the run (`corrections.json`) and written into the CSV files at once (the observations file keeps the
extracted value beside it); right-click to revert it or add a note. Tick entries in *Things to check* as you deal with
them; the tab shows how many are left.

**Earlier runs.** *File › Open a results folder…* shows a finished run (or one paper of a queue) in the result tabs
again. *File › Resume a stopped run…* runs a run or queue that stopped part-way (network, credits, Cancel) again:
steps already answered are reused at no cost and only the missing ones are asked. *File › Rebuild a run's dataset…*
builds the dataset again from the saved answers without asking the model anything, e.g. after accepting variables
or changing a data pack's formulas. Both write a new folder next to the old one. From the command line:
`--resume FOLDER` and `--rebuild FOLDER`.

## For developers

- Code: `src/parameter_extractor/`. `pipeline.py` is the entry point (`run_pipeline(pdf, RunConfig, ...)`); the
  window (`gui/`) and the command line (`cli.py`) are thin layers over it.
- Tests: `python scripts/run_tests.py` runs every offline test (no API calls, about two minutes). Many tests replay
  recorded runs in `runs/`, which isn't in the repository (it contains the papers' text), so on a fresh clone those
  tests skip.
- `CLAUDE.md` is the guide for AI agents working on the code; `docs/history/` holds the dated record of every
  decision and measurement, `eval/` the write-ups of measurements.

Before a public release: a project license, a final name, code signing for macOS, and a Windows build.
