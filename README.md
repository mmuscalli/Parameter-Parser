# EORE literature-extraction pipeline — initial scaffold

Status: **early prototype**. This is not tuned or validated yet — it exists to test
whether a simple, well-scoped paper can be parsed reliably and to work out the right
shape for the prompts/schemas before any real tuning or scoring happens.

## What's here

```
extraction_pipeline/
├── config/            # settings + where the API key goes (never commit .env)
├── prompts/           # one instruction file per extraction stage
├── schemas/           # Pydantic models = single source of truth for each stage's
│                       output, plus template_vocab.json (controlled vocabulary
│                       pulled directly from PaperDataTemplate.xlsx's own headers)
├── ingestion/          # PDF -> clean text/tables (pdfinfo/pdftotext/pdfplumber),
│                       # table-page rasterization, and CrossRef DOI lookup
├── calculators/        # deterministic, non-LLM math (unit conversion, %yield).
│                       # Does NOT duplicate your R ionic-strength/pKa/WORM code —
│                       # those stay in Calculators/ and should be wrapped here later.
├── validation/         # plausibility checks + the gold-standard scorer (OFF by
│                       # default — see "Turning validation on" below)
├── stages/             # one module per extraction stage; calls the API via
│                       # api_client.py and validates the response against schemas/
├── eval/gold_standard/ # empty — drop your curated subset CSV here when ready
├── runs/                # per-paper output + audit trail (raw responses, prompts
│                        # used, token counts, model name/version)
├── api_client.py       # thin Anthropic API wrapper; reads ANTHROPIC_API_KEY
├── pipeline.py         # chains the stages for one paper
└── main.py             # CLI entry point
```

## Current scope (deliberately narrow)

Per your instructions, this first pass only targets **one** paper
(`eder1994.pdf`), only pulls parameters that are stated in **running text and
tables** (not the scatter-plot figures — Figs. 1–5 in this paper are out of scope
for now), and does **no** exhaustive testing or tuning.

## No API key is configured yet

`api_client.py` is real, working code — it calls the Anthropic Messages API with
structured output — but there is no key in this environment, so it cannot actually
run yet. To activate it:

1. Copy `config/.env.example` to `config/.env`
2. Add `ANTHROPIC_API_KEY=sk-...`
3. Run `python main.py --pdf "<path to a paper>"`

**Because no key was available, the `runs/eder1994/` outputs in this scaffold were
produced by me (Claude) manually reading the paper and filling in the exact same
prompts/schemas a real API call would use** — so you can judge extraction quality
and parameter design right now. They are labeled `"model": "manual-claude-demo"` in
their metadata, specifically so they're never mistaken for an automated run. Once a
key is added, `main.py` exercises the real code path end to end.

## Turning validation on later

`validation/gold_standard_eval.py` has `ENABLED = False` at the top. When your
curated "most certain" paper subset is ready, drop its CSV into
`eval/gold_standard/`, flip that flag, and point `GOLD_STANDARD_PATH` in
`config/settings.py` at the file. Nothing else needs to change.

## Table-page rasterization

`ingestion/pdf_parser.py` scans each page's text for a `Table N` caption
(`find_table_pages`) and, when `config.settings.RASTERIZE_TABLE_PAGES` is
true (the default), renders exactly those pages to JPEG via `pdftoppm`
(`rasterize_table_pages`) into `runs/<paper_id>/page_images/`. `pipeline.py`
hands those images to the structure-planning and chemistry stages alongside
the OCR'd text, and both prompts (`prompts/structure_planner.md`,
`prompts/chemistry.md`) tell the model to trust the image over the text when
they disagree. This exists because eder1994's Tables 1/2 are a two-column
layout that plain `pdftotext` genuinely garbles — row order and which salt a
value belongs to becomes ambiguous from text alone (confirmed by hand while
building the original demo). Real, tested code: `find_table_pages` correctly
identified eder1994's pages 3 and 4, and `rasterize_table_pages` produced the
actual JPEGs now sitting in `runs/eder1994/page_images/` — this part doesn't
need an API key to verify, only `stages/*.py` does.

Caveat: the caption regex is a simple heuristic (`^\s*Table\s+\d+\b` at the
start of a line) — it can pick up a stray in-text reference that happens to
start a line that way (harmless false positive: just rasterizes one extra
page), and it won't catch a table that continues onto a page with no caption
of its own. Good enough for a first pass; revisit if a paper's tables are
getting missed.

## CrossRef DOI lookup

`ingestion/crossref_lookup.py` queries CrossRef's public `works` API by
title/author when a paper's own text doesn't state a DOI (common for older
scanned papers). `stages/metadata_extractor.py` calls it automatically
whenever the LLM-extracted `paper_doi` comes back null. It only accepts a
match when BOTH a local title-similarity check and CrossRef's own relevance
score clear conservative thresholds (`config.settings.CROSSREF_MIN_*`) —
a wrong-but-plausible DOI attached silently would be worse than no DOI, so a
weak match is rejected with a `reason` rather than guessed.

**Network restriction discovered while building this**: `api.crossref.org`
is blocked by this account's egress policy — confirmed with a direct `curl`
from both the cloud workspace and (separately) the linked computer's shell,
both returning a 403 at the proxy. So this has NOT been live-tested end to
end yet. What it has been tested against:
- An offline mock test suite (`tests/test_crossref_lookup.py`, 4/4 passing)
  using a realistic recorded fixture for eder1994's actual CrossRef record
  (independently confirmed via the RSC article landing page during this
  session: DOI `10.1039/DT9940001125`) plus a wrong-paper case, an
  empty-results case, and a network-failure case.
- A real (unmocked) call against the live, blocked endpoint, confirming it
  fails with a clear, non-crashing `CrossRefMatch(accepted=False, reason=...)`
  rather than an unhandled exception.

Try it again once this runs somewhere with normal internet access (your own
machine outside this sandboxed session, most likely) — the code should work
unmodified; verify the first few real calls before trusting it unattended.
If you want the "polite pool" rate limits, set `CROSSREF_CONTACT_MAILTO` in
`config/settings.py` yourself — it's left blank on purpose rather than
auto-filled.

`runs/eder1994/build_manual_demo.py` calls the real `lookup_doi()` (not a
re-implementation) so you can see this failure handling in action; it then
records the RSC-verified DOI with `doi_source: "manual_fallback"` —
deliberately a different value from `"crossref_api"`, so the data itself
always shows whether a DOI was resolved automatically or by a human.
