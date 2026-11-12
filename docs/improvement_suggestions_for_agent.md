# Suggested improvements to Parameter Extractor: instructions for the implementing agent

Written 2026-11-11, after a review of the app's design, code and recorded results. You are an agent working in this
repository for Mickey Muscalli, the project's owner and only developer. This file gives you a list of suggested
improvements and tells you what to do with it.

## Your task

1. **Summarize the suggestions to Mickey first.** Don't change any code before he has answered. The section
   "How to present the summary" says what the summary should contain.
2. **Wait for his choices.** He may accept, decline, change or postpone each suggestion. Record his answer in the
   Status column of the table below (edit this file), so a later session can pick up where you stopped.
3. **Implement only the accepted suggestions**, one at a time, following "How to implement an accepted suggestion".

The suggestions are proposals from a review, and Mickey hasn't seen them yet. Several rest on a claim that needs a
measurement before it is worth building; those say so. If a measurement shows a suggestion doesn't pay off, report
that and stop: in this project a measured "no" is a normal, useful result (see "Already measured and decided").

## Orientation

- **What the app is.** `src/parameter_extractor/` (about 36,000 lines of Python) reads scientific papers and extracts
  experimental values into dataset rows with an LLM, for review by a person. A *data pack* defines one research
  area (its columns, steps, rules, calculations). Two packs ship with the app, `prebiotic_chemistry` and
  `exoplanets`, and users can draft their own. Front ends: a PySide6 desktop window, a command line
  (`parameter-extract`), and PyInstaller builds for macOS.
- **How a paper is processed** (`pipeline.py`): `read_paper` (local: parse the PDF, table images, figures, equations)
  → `extract_steps` (model requests: the row plan first, then the other steps in parallel) → `finish` (local:
  build rows, calculations, review of new variables, flags, CSV files).
- **Where the project's knowledge is.** `CLAUDE.md` in the repository root (a short guide, loaded into your session
  automatically) and `docs/history/` (the dated record of every decision and measurement, split out of CLAUDE.md on
  2026-11-11 by P1; about 240 KB, so search it for a heading or keyword rather than reading it). Other write-ups: `eval/*.md` (measurements), `docs/local_model_notes.md` (what changes with
  local models), `README.md` (for people, out of date, see P3).
- **Keep your context small.** A previous session ran out of context on this review, because CLAUDE.md alone takes
  much of the window. Read source files in ranges (grep for the function, then read 50–100 lines), not whole
  files: several are 1,500–2,400 lines. Work on one suggestion at a time, and update the Status table as you go.

## Rules of this project that apply to every change

These are Mickey's standing decisions. They are recorded in CLAUDE.md, and are repeated here so you don't have to
find them.

- **Tests.** From the repository root:
  `PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 ../.venv/bin/python scripts/run_tests.py` (about 2 minutes; each test file runs
  in its own process; there is no pytest). The gate is the summary line "0 failed, 0 skipped". A skipped file is a
  failure: it usually means a paper's PDF wasn't found.
- **Reference replays must stay byte-identical.** Recorded model answers in `runs/reference/*` and `runs/*_auto` are
  replayed through the real pipeline and must reproduce their stored CSVs exactly. If your change alters an output
  on purpose, regenerate the reference with a checker that proves only the intended cells changed (CLAUDE.md
  describes this several times; search it for "regenerated").
- **Changes to the app's data packs** also need `python scripts/check_test_robustness.py` (about 6 minutes).
- **Requests to Claude must not change by accident.** The schemas and prompts sent to Anthropic models are tuned
  and measured. A change meant for local models has to leave Claude's requests identical; there are tests for
  this, and the replays would not catch it, because they don't look at requests.
- **Money and the local server.** Live runs with Claude cost money (typically $0.02–0.30 a paper, up to about $1.85
  for the longest). Live runs on the local model need Mickey's Windows PC to be running (Ollama at
  `http://192.168.1.129:11434`; check with `parameter-extract --list-local-models`). Ask Mickey before either,
  with an estimate of the cost or time.
- **Keys and privacy.** The API key lives only in `RunConfig` and the keychain; never read
  `settings.ANTHROPIC_API_KEY` in new code, never write a key to a file or a log. Set
  `PARAMETER_EXTRACTOR_NO_KEYCHAIN=1` in tests and ad-hoc scripts. The local model server has no authentication and
  is for the local network only.
- **`runs/` is local and never pushed** (it is in `.gitignore`; its audits contain the papers' text).
- **Wording.** The user-facing term is "data pack". A "step" is one model request per paper. The pressure unit
  stays bar. The Standard model profile stays the default.
- **Flags.** Mickey prefers too many flags to too few. Reduce noise by grouping flags, never by dropping them.
- **Review before writing.** A new variable or compound outside a pack's vocabulary is never written to the dataset
  until the user accepts it. Assumed values are flagged and never included automatically.
- **Leave these alone unless Mickey asks:** gold-standard validation (off on purpose; he is building the curated
  set), `PaperDataTemplate.xlsx` (frozen), code signing / notarization, the Windows build, triage as a gate.
- **After a round of code changes:** build both apps (`packaging/build_macos.sh` and
  `packaging/build_macos.sh --dev`) and run each with `--self-check`; add a dated section to the current month's `docs/history/YYYY-MM.md`
  saying what was built, what was measured and what was decided (and its line in `docs/history/README.md`); commit
  and push to the current branch. Commit messages end with the attribution line your session gives you.
  A docs-only change needs no build.

## Already measured and decided: don't propose these again

Each was built, measured live, and switched off or dropped. Only new evidence would reopen one.

| Idea | Result | Where |
|---|---|---|
| Table grids (cells read locally, the model maps them) as a cost saving | +6% cost, no accuracy gain; off | `eval/table_grids_2026-11-07.md` |
| Pre-parse (a cheap pass switches off parameters a paper lacks) | −3% cost, accuracy 97.5% → 89.7%; not wired in | `eval/preparse_2026-11-08.md` |
| Figure suggestions on the cached paper | costs more from the second figure on; off | CLAUDE.md, 2026-11-03 |
| Pooling one paper's parallel steps into one batch | slower than one-request batches for a single paper | CLAUDE.md, 2026-10-27 |
| "Balanced" profile for exoplanets | worse than Economy on both measures | CLAUDE.md, 2026-10-22 |
| Shared cached step instructions for single papers | +6% for one paper; on only in queues | `eval/shared_instructions_2026-11-07.md` |
| Trigger thresholds beyond `min_hits` | a false trigger costs ~$0.01, a miss loses values; not added | `eval/organics_heldout_2026-11-09.md` |
| pix2tex / pix2text for equations | inaccurate, or 1.8 GB of dependencies | CLAUDE.md, 2026-10-15 |

Considered in this review and left out, with the reason:

- *Automatic digitizing of supplementary figures in unattended runs.* They are skipped on purpose: one supplement
  had 90 figures, mostly spectra, and each suggestion costs $0.07–0.13.
- *Continuous integration on GitHub.* The replay tests need the papers' PDFs and `runs/`, neither of which is in the
  repository, so most of the suite would skip on a fresh clone. P2 has to be settled first.
- *Wrapping the R calculators in `../Calculators/`.* The columns they fill (ionic strength, pKa, WORM) were removed
  from the prebiotic pack's template on 2026-10-22.
- *A mixed profile (Claude plans the rows, the local model extracts).* The paper would go to Anthropic anyway, which
  removes the main reason to run locally.

## The suggestions

Effort: S = under half a day, M = one to two days, L = several days. "Live" says whether judging the result needs
paid Claude runs or the local server. Update Status as you go: `proposed` → `accepted` / `declined` / `postponed` →
`done (commit)` or `measured, not kept`.

| ID | Suggestion | Area | Effort | Live | Status |
|---|---|---|---|---|---|
| E1 | Local models: send the paper first, so the server reads it once per paper | Efficiency | M | local server | done, measured: kept (reading -40 to -55%; paper-first needed priming on hybrid models) |
| E2 | Local models: a per-model setting for thinking | Efficiency | S | local server | done, measured: setting kept, default unchanged (thinking off loses values on qwen) |
| E3 | Local models: know the real context and use the room better | Efficiency | S–M | local server | parts 1-2 done (spill flag checked live, calibrated estimate); part 3 postponed |
| E4 | Paper queues in batch mode: shared batches, more papers in flight | Efficiency | M | Claude (small) | postponed |
| W1 | Resume a failed or cancelled run; rebuild a dataset from saved answers | Workflow | M–L | no | done (c9733fa) |
| W2 | Corrections and "checked" marks in the results window | Workflow | L | no | done (corrections + checked marks; single cells) |
| W3 | Open a previous run in the window | Workflow | S–M | no | done (5335f6b) |
| W4 | Cost and time estimate before a run starts | Workflow | M | no | postponed |
| W5 | Command line: scope flags; a notification when a long run ends | Workflow | S | no | postponed |
| W6 | Keep the local-model test scripts in the repository | Workflow | S | no | done (79666a5) |
| F1 | Units: read "uL/min" and other ASCII spellings of µ | Functionality | S | no | done (fcb3c1a) |
| F2 | Local models: table image size per model | Functionality | S–M | local server | postponed |
| F3 | A free second reading of table values from the PDF's text layer | Functionality | L | no | done: built (flags only; coverage extended first); 'not in its row' tier on trial |
| P1 | Split CLAUDE.md into a short guide and a dated history | Upkeep | M | no | done (caf1db3, 47f1b77) |
| P2 | Back up the reference runs | Upkeep | S | no | done (76318c4) |
| P3 | Bring README, package metadata and a stale comment up to date | Upkeep | S | no | done (57fb3b5) |
| P4 | A main branch and version tags | Upkeep | S | no | done (6914f67, tag v0.3.0); `main` force-pushed over GitHub's initial commit on Mickey's OK |

**Mickey's answers (2026-11-11):** F1, P3, W6, P4, P1 and P2 accepted and done (F1: a bare "um" is read by the
column; P1: write-ups go to `docs/history/`; P2: dated archives in `../Backups/`; P4: v0.3.0). The rest are meant to
be implemented later; postponed for now. Open from P4: the remote already has a `main` branch (GitHub's initial
commit, only a Python `.gitignore`), so the local `main` wasn't pushed; replacing it needs a force push and is
Mickey's call, as is making `main` the default branch on GitHub. (Later the same day: `main` force-pushed on his OK;
W3 and W1 accepted and done, W1 writing a resumed run into a new folder that names the old one.) Earlier suggested order for the rest: E1 (with E2
and E3 parts 1–2 in one local-server session), W3 → W1 (rebuild first) → W2, the F3 prototype, then E4, W4, W5, F2.

A sensible order if Mickey accepts most of them: F1 and P3 (quick, no risk), P2 (protects everything else), P1
(makes every later session cheaper), then E1 (the largest measurable gain), W1, W2, and the rest.

---

### E1. Local models: send the paper first, so the server reads it once per paper

**What.** Change the layout of requests to local model servers so that every step of a paper starts with the same
text: a constant system line, then the paper (text and table images), and only then the step's instructions and its
answer schema. Record the server's timing figures per request, and keep the model loaded between steps.

**Why.** A local server has no prompt caching in the Anthropic sense, but Ollama and llama.cpp keep the processed
prompt of the previous request and reuse the part that is identical *from the start*. Today nothing is identical
from the start: `local_models.send` puts the step's own system prompt and its JSON Schema first, and the paper sits
inside the step's prompt. So the server reads the whole paper again for every step. Measured on teng2023
(`docs/local_model_notes.md`, issue 5): six requests of 82–87K tokens each, about 3–4 minutes of reading per request
before any output, 34 minutes for the paper. With the paper first, the requests after the first should only need to
read their own instructions (a few thousand tokens). The expected saving is roughly 10–15 of the 34 minutes on a
paper of that length, and less on short papers. This is an estimate that has to be measured.

Checked in the code on 2026-11-11: `local_models.py` sends no `keep_alive`, has no setting for thinking, and reads
only `prompt_eval_count` / `eval_count` from the server's answer (no durations).

**How.**

1. Read `local_models.send` (about 80 lines) and, in `api_client.py`, `PaperContext`, `_paper_blocks` and the two
   paths of `call_structured`. The cached path for Claude already builds a paper-first request: the paper blocks,
   then "YOUR TASK: …" with the paper's place in the prompt replaced by a marker (`PAPER_ABOVE`). Local runs don't
   take it, because `RunConfig.__post_init__` switches prompt caching off for the local provider.
2. Let local runs use that layout without its Claude-only parts (no tool list, no `cache_control`, no "answer by
   calling the tool" sentence). In `local_models.send`, make the system message a constant and move the schema and
   the "answer with one JSON object" instruction to the end of the user message.
3. Send the same images, in the same order, in every step of a paper, so the prefix stays identical. A step that
   reads a different text (paper details read page 1 only) simply doesn't benefit.
4. Keep `num_ctx` constant per model (it is today); changing it makes Ollama reload the model.
5. Send `keep_alive` (for example 30 minutes) with Ollama requests, so the model isn't unloaded between papers.
6. Read `prompt_eval_duration`, `eval_duration` and `load_duration` from Ollama's final chunk, store them in the
   step's audit, and show reading time and writing time in the Summary tab. Don't use `prompt_eval_count` to judge
   reuse: depending on the server version it counts either the whole prompt or only the newly read part.
7. Keep one paper's steps together. With one request at a time and several papers in a queue, requests from
   different papers would alternate and each would evict the other's prefix. `paper_queue.py` extracts 3 papers at
   once for any provider (`DIRECT_PARALLEL`); for the local provider use the server's "requests at once" setting
   instead (normally 1).
8. For OpenAI-compatible servers the same layout helps (llama.cpp reuses prefixes by default, vLLM has automatic
   prefix caching); no extra parameter should be needed, but say in the notes which servers were actually tried.

**Verify.** Offline: the fake-server tests in `tests/test_local_models.py` still reproduce eder1994's reference CSV
byte for byte, plus a new test that two steps of one paper send an identical prefix up to the end of the paper, and
a test that Claude's requests are unchanged. Live (ask first): eder1994 and teng2023 on `qwen3.8:27b`, compared with
the recorded results (eder1994 100% of the reference in 4.5–7 minutes; teng2023 2,130 archive matches, 18 differing,
0 missing, 34 minutes). The scripts are in `runs/local_models/` (see W6). Keep the change only if the results hold
and the time drops; report reading time per step before and after.

**Risk.** The model sees its instructions after the paper instead of before. That is the layout Claude's requests
already use and it is the usual advice for long documents, but a 27B model may behave differently: the live
comparison decides. Update `docs/local_model_notes.md` (issue 5) with the outcome either way.

### E2. Local models: a per-model setting for thinking

**What.** A setting per local model ("Thinking: as the model decides / off") passed to Ollama as its `think`
parameter, and a measurement of whether the results hold with thinking off.

**Why.** Both models on Mickey's server reason for about 1,000 tokens before each answer
(`docs/local_model_notes.md`, issue 4). The reasoning counts against the answer's room in the context (issue 11: the
longest teng2023 step used 120–125K of 131K) and adds time to each of the 6–8 requests of a paper. The answers are
constrained to a schema and carry their own short notes, so the reasoning may not be buying accuracy. That is a
question for a measurement.

**How.** Add the field to the per-model settings in `local_models.py` (`LocalSettings`, stored in
`<app data>/local_models.json`) and to the models table in `gui/local_models_panel.py`. Send `"think": false` only
when the user chose "off"; check in Ollama's current API documentation how `think` combines with `format`, and what
the OpenAI-compatible servers offer (leave them alone if nothing standard exists). Default: unchanged behaviour.

**Verify.** Live (ask first): eder1994 with thinking off, scored with `scripts/eval_references.py --score`; if it
holds at 100%, teng2023 as well. Report time and the output token count with and without. Keep the setting either
way, since it is the user's choice; recommend a default only from the measurement.

### E3. Local models: know the real context and use the room better

**What.** Three small things that address the same problem, that a long paper plus a long answer barely fits:

1. *Warn when the model doesn't fit on the GPU.* After the first request of a run, ask Ollama which models are loaded
   (`GET /api/ps`) and compare the memory on the GPU with the model's total size. If part of the model is on the CPU,
   add a run note and a flag saying that the context length set for this model is too large for the GPU and what
   that costs in speed. In "Test connection", label the reported context as the model's maximum, not as a
   recommendation.
2. *Calibrate the token estimate.* The check before sending uses characters / 3.5 plus 600 per image. After the first
   answer the server has reported the real prompt size; use the ratio for the run's later requests, so the room
   left for the answer is computed from real numbers.
3. *Make room when a request wouldn't fit.* Before refusing a request, try the paper without its reference list
   (and with layout spaces collapsed, as the exoplanet pack already does), and say so in a run note and a flag.

**Why.** `/api/show` reports the model's architectural maximum (262,144 for both models), but only 131,072 / 81,920
fit in 24 GB; above that, layers move to the CPU and output fell from about 30 to 6.5 tokens a second (notes,
issue 3). A user who enters the reported number gets a run five times slower with no explanation. Issue 11: a paper
5–10% longer than teng2023 would be refused or cut off today.

**How.** (1) is a request plus a comparison in `local_models.py`; check the field names against the server (`size`,
`size_vram` at the time of writing). (2) is a per-run factor kept on the run context. (3): there is no function
that removes the reference list from the text that is sent, but the list is already located in two places
(`stages/optional.py`, where trigger words are counted "outside the reference list", and
`stages/figure_planner.py`); move that detection into one helper and reuse it. The reference list is needed when a
paper reproduces other papers' data (the `cited_data` flags quote it), so use (3) only when the request would
otherwise not fit, never by default.

**Verify.** Offline tests with the fake servers: a spill reported by `/api/ps` produces the flag; a request over
the context is retried without references and noted; Claude runs are untouched.

### E4. Paper queues in batch mode: shared batches, more papers in flight

**What.** When a paper queue runs in batch mode (half price), collect the requests of all papers that are ready
into shared batches, and let many more papers be in flight at once than today's 12.

**Why.** In batch mode each request waits a few minutes in Anthropic's queue, and a paper has two dependent
phases (the row plan, then the other steps), so every paper takes about 5–6 minutes of waiting however small it
is. The wait doesn't grow with the number of requests in a batch, so throughput comes from how many papers wait at
the same time. The focused search already works this way (`api_client.BatchCollector`, 64 papers at once): a retry
of 76 papers went from an estimated 46 minutes to 11.5. The full-extraction queue doesn't: checked on 2026-11-11,
`paper_queue.py` has no collector and uses `BATCH_PARALLEL = 12`, so 100 papers take roughly nine rounds of 5–6
minutes. CLAUDE.md (2026-10-27) names this as the remaining lever for many full runs.

Note the difference from the idea in the "already measured" table: pooling the steps of a *single* paper was
slower. The gain here is from more papers waiting together; the collector's job is to keep the number of separate
batches down.

**How.** Give the queue's run contexts a shared `BatchCollector` in batch mode (see how `focused_search.py` does it
around its lines 300 and 546) and raise the number of papers in flight (try 48–64). Two things to check: the queue
reads papers on one thread, because the PDF parser keeps one shared document open, so with many papers in flight
the local reading may become the limit: measure it, and only then consider reading in worker processes. And batch
mode uses the 1-hour cache; make sure the queue's shared instructions and warm-up still behave as designed (the
warm-up is skipped in batch mode today).

**Verify.** `tests/test_paper_queue.py` and `tests/test_batch_and_credits.py` offline. Live (ask first; Economy
profile, about $0.02 a paper): the same 12 papers as a batch queue before and after, comparing wall-clock time and
cost, with identical outputs apart from run-to-run variance.

---

### W1. Resume a failed or cancelled run; rebuild a dataset from saved answers

**What.** Two uses of one mechanism:

- *Resume.* When a run stops part-way (network failure, out of credits, Cancel, a crash), a second attempt reuses
  the answers already saved in the run folder and asks the model only for the missing steps. The same for a
  queue: restart it from its folder and only unfinished papers run.
- *Rebuild.* Build a run's dataset again from its saved answers without any model request, after the user has
  changed something local: accepted variables, a pack's formulas or calculations, compound names, a correction
  (W2).

**Why.** Every step's answer is already written to the run folder as `<step>.output.json` with an audit, and the
test suite already rebuilds whole datasets from such folders (`tests/test_pipeline_offline.make_replay`). The app
itself can't (checked on 2026-11-11: no resume option in `pipeline.py`, `api_client.py`, `cli.py`,
`paper_queue.py` or `RunConfig`; `api_client._send_resuming` only retries a dropped connection within one request):
a run that fails at its last step has to be paid for again in full, and the error messages can only
say "running the paper again usually works". Queues are the worse case: checked on 2026-11-11, `paper_queue.py`
only ever creates a fresh queue folder, so a 50-paper queue stopped at paper 40 starts from paper 1. The focused
search has "Retry failed papers"; the full extraction has nothing like it. Rebuilding also removes the main reason
to re-run a paper today, which is that a local setting changed.

**How.**

1. Give each request a fingerprint (a hash of the model, the prompt text, the schema and the image list) and store
   it in the step's audit.
2. `RunConfig.resume_from` (a run folder). In `call_structured`, before sending: if that folder has a saved answer
   for this step whose fingerprint matches, load and validate it, record the step as reused (no tokens, no cost)
   and return it. A mismatch (the pack or the prompt changed) means the step is asked again; say so in a run note.
3. Decide with Mickey whether a resumed run continues in the same folder or writes a new one that links to the
   old (the current rule is that a run never overwrites; a new folder with the reused answers copied in keeps that
   rule).
4. Queue: `PaperQueue` takes an existing queue folder, reads its `papers.csv`, keeps finished papers as they are and
   resumes the others.
5. Front ends: the command line gets `--resume RUN_OR_QUEUE_DIR` and `--rebuild RUN_DIR`; the window offers "Resume"
   in the failure message and after a cancelled run, and "Rebuild" on an opened run (W3).
6. `pipeline.finish` is about 330 lines in one function. Rebuilding is easier to get right if it is first split
   into named phases (rows, calculations, review, flags, files) with no change in behaviour, checked by the
   replays. Do that as its own commit.

Digitized figures and review decisions are already saved with a run (`fig-N.digitized.json`, the registry); make
sure a rebuild reads them and doesn't ask again.

**Verify.** Offline: a replay that fails at a chosen step, then resumes and reproduces the reference CSV byte for
byte with only the missing steps requested; a rebuild of each reference run with no request at all; a queue
stopped after its first paper and resumed.

### W2. Corrections and "checked" marks in the results window

**What.** Let the reviewer finish the review inside the app: edit a wrong value in the "Extracted data" tab, and
mark an entry in "Things to check" as checked. Save both with the run and carry them into the files.

**Why.** The app's stated purpose is to speed up extraction "NOT to replace human review of the output", and it
produces many flags on purpose. But the review has nowhere to go: the results table is read-only (checked on 2026-11-11: `gui/main_window.py` sets `NoEditTriggers` on
`rows_table` where the results tabs are built, in `_build_results`) and no code stores a state for a flag. A reviewer therefore corrects values in a spreadsheet, where the link to the quote, page and flag is
lost, and can't see which of 40 flags they have already dealt with. Corrections made in the app would also be
exactly the material for the curated answer set Mickey is building: a corrected run is a checked answer for that
paper. That is a possible later use and his decision; don't connect it to the gold-standard code.

**How.**

1. A `corrections.json` in the run folder: for each corrected cell the row id, column, old value, new value, time
   and an optional note. Apply it at the end of `finish` (so a rebuild, W1, keeps it): the cell's provenance gets
   origin "corrected", the observations file keeps the extracted value in its own column, and the wide CSV has the
   corrected value.
2. Window: double-click to edit a cell, corrected cells in their own colour with the extracted value in the hover
   text, "Revert". Validate against the column's data type and unit as the review window does (`value_types.coerce`).
3. Flags: a checkbox per flag, state in `flags_checked.json`, the tab title showing "Things to check (12 of 40
   left)", a filter for unchecked. A checked flag stays in every file: this is the reviewer's state, and nothing
   is dropped.
4. Keep the first version to single cells. Deleting or adding rows is a separate question.

**Verify.** Offline window tests in the style of `tests/test_gui_offline.py` (pump events with `processEvents` and
`time.sleep`; never `QTest.qWait`, which blocks the worker thread). Check the drawing natively as well, not only
offscreen: a past header-painting bug was invisible offscreen.

### W3. Open a previous run in the window

**What.** File > "Open a results folder…": load a finished run (or a queue folder) into the results tabs: data,
things to check, summary, figures, tables, equations.

**Why.** Results are shown only for the run that just finished in this session. After closing the app, a run can
only be looked at as files, without the hover provenance, the flag groups or the figure views. Runs on the local
model take half an hour and batch runs are left to finish on their own, so coming back later is the normal case.
W1's "Rebuild" and W2's corrections both need a way to open a run.

**How.** The window already fills its tabs from a result object, and after a queue it shows the selected paper's
results, so part of this exists: `MainWindow.show_result(result)` in `gui/main_window.py` and its helpers
`_fill_rows`, `_fill_flags`, `_fill_figures`, `_fill_tables`, `_fill_equations` and `_fill_summary`; the queue's
side is in `gui/multi_runs.py`. Nothing builds a result from a run folder yet (checked on 2026-11-11). Add a
function that builds the same result object from a run folder (`run_summary.json`, the CSVs, the flags file,
`new_variables.json`, `tables.json`, `equations.json`, figure files), and report clearly when a folder is from an
older version and a part is missing.

**Verify.** Open each folder under `runs/reference/` in an offline window test.

### W4. Cost and time estimate before a run starts

**What.** Next to the Run button, an estimate for the current selection: "about $0.25 and 1–2 minutes for this
paper", "about $4–6 for these 23 papers", or for a local model "about 30 minutes".

**Why.** Users bring their own API key, and cost per paper varies almost a hundredfold with the model profile,
the paper's length, passes and batch mode ($0.01 to $1.85 in the recorded runs). Today the cost is shown only
afterwards. The project has measured everything needed for an estimate, and counting a prompt's tokens through
the API is free. Nothing in the code does either yet (checked on 2026-11-11: no use of `count_tokens`, no estimate
function except the local models' context check).

**How.** Estimate locally, without a request: input tokens from the paper's size (characters and table images, as
`local_models.estimate_tokens` does, with a factor per provider), times the cache prices in `pricing.py` (one
write, one read per further step), plus output tokens per step from experience. For that experience, keep a
small table of tokens per step and per row from past runs (`run_summary.json` files in the user's output folder,
falling back to bundled averages per data pack). Give a range, not a number, and say it is an estimate. For a
queue, estimate from file sizes before the papers are read. For local models, estimate time from the server's
measured reading and writing speeds (E1 records them).

**Verify.** A script that compares the estimate with the recorded cost of every run under `runs/`; the estimate's
range should contain the real cost for most of them. Report the hit rate to Mickey.

### W5. Command line: scope flags; a notification when a long run ends

**What.** (a) `--only-compounds NAME[,NAME…]` and `--only-analysis FAMILY[,…]` for `RunConfig.scopes`, which the
window can set and the command line can't (checked on 2026-11-11: `cli.py` has no scope option; CLAUDE.md,
2026-11-08, says "CLI: no flags yet"). (b) A system notification when a run, queue or focused search ends while
the window is in the background.

**Why.** (a) Parity: scripted runs can't narrow a run to a few compounds. (b) Local runs take 30 minutes and
batch runs 5–10; people switch away.

**How.** (a) Two options in `cli.py` mapped to `scopes`, names checked against `scopes.groups(pack, registry)`, with
a list in `--list-parameters`. (b) `QSystemTrayIcon.showMessage` or the platform's notification call when the main
window isn't active; a setting to turn it off; nothing when the window is in front.

### W6. Keep the local-model test scripts in the repository

**What.** Move the scripts that ran the local-model tests into `scripts/` as one documented tool, for example
`scripts/check_local_model.py MODEL [--context N] [--paper eder1994|teng2023]`, which runs the paper on the local
server, scores it against the reference and prints the comparison used in `docs/local_model_notes.md`.

**Why.** `run_eder1994_local.py`, `run_teng2023_local.py` and `archive_summary.py` live in `runs/local_models/`, and
`runs/` is never pushed, so they exist only on Mickey's Mac. The notes' "Checklist for trying another model" depends
on them, and a second model (`gemma4:31b`) is installed and untested. E1, E2 and F2 all need the same comparison.

**How.** Read the three scripts, fold them into one with the paths as arguments (the papers and reference runs
stay where they are), and point the notes' checklist at it. No model request is needed to write it; running it
needs the server.

---

### F1. Units: read "uL/min" and other ASCII spellings of µ

**What.** Read a compound unit written with a plain "u" for micro ("uL/min", "ug/mL") wherever its "µ" form is
known.

**Why.** Checked on 2026-11-11: `units.parse_quantity("50 uL/min")` and `"0.5 ul/min"` return nothing, while
`"50 µL/min"` works; `"5 ug/mL"` returns nothing too. The simple forms already work (`uL`, `ul`, `uM`, `ug`,
`umol`, `umol/L`, and `uL min-1`): the gaps are compound units with a slash. The alias table in `units.py` lists
spellings one by one. Models and PDFs both produce the ASCII form, and a value whose unit isn't read becomes a flag and a manual
fix. It showed up in the local-model run's analysis settings.

**How.** In the unit lookup in `units.py`, when a unit isn't found, try it with a leading "u" replaced by "µ", for
the whole unit and for the part before a "/" or a space. Accept the result only if it is a known unit, which leaves real units that start with "u" alone. Start
by writing a table of ASCII forms and what each returns now, so the tests cover the gaps and nothing that works
changes. One thing to raise with Mickey and not change on your own: `"5 um"` currently reads as 5 µM (micromolar),
because the chemistry table ignores case there, while lengths in µm exist as column units (`_um`). Ask him which
reading he wants for a bare "um" before touching it. The same lookup serves the astronomy
table, where "m" and "u" mean other things: apply the rule to the chemistry table only.

**Verify.** Unit tests for each form; the full suite, since unit parsing touches every replay.

### F2. Local models: table image size per model

**What.** A per-model setting for the largest image side a local model reads well, used when table pages are cut
into pieces for that model.

**Why.** Table pages are cut so that no piece exceeds 1,568 pixels, because that is where the Anthropic API starts
to scale images down (`ingestion/table_tiles.py`; before the cutting, Claude misread superscripts in dense
tables). Local vision models have other limits, and some scale every image to under 1,000 pixels, which would undo
the cutting. The 18 values that still differ on teng2023 with `qwen3.8:27b` are all uncertainties from dense
tables (notes, issue 12), the same kind of misreading Claude had before the pieces.

**How.** Add `max_image_px` to the per-model settings (default 1,568, so nothing changes), pass it to the table
cutting for local runs, and document where to find a model's input resolution. Smaller pieces mean more images
and more prompt tokens, which works against the context (E3), so this is a trade-off to measure, not a default
to change blindly.

**Verify.** Live (ask first): teng2023 on the local model with two piece sizes, comparing the count of differing
uncertainties and the prompt size. Offline: Claude's images are unchanged (the replays of table-image file names
cover this).

### F3. A free second reading of table values from the PDF's text layer

**What.** After extraction, compare each value the model read from a table with the same cell as read locally
from the PDF's text layer, and flag the cells where the two disagree.

**Why.** Misread table cells are the main remaining source of wrong values for both Claude and local models, and
they are the hardest for a reviewer to notice, because a wrong number looks as plausible as a right one. The app
already has a local table reader (`ingestion/table_grid.py`), built as a cost saving, measured, and switched off
because it saved nothing. As a second opinion it costs nothing per paper and would turn "check every cell
against the paper" into "check these few cells". It fits Mickey's preference for more flags, grouped.

**Limits to state plainly.** It can't work on scanned papers (no text layer; eder1994 is one) or where the reader
can't make a grid. It will raise false flags where the grid is wrong. Whether it catches enough to be worth
having is unknown.

**How.** Start with a prototype and a measurement, not the feature. Take the recorded answers of the reference
runs and the known misreadings (teng2023's 18 differing uncertainties on the local run in `runs/local_models/`;
the cases listed in CLAUDE.md under "Dense table pages cut into pieces"), run the grid reader on those PDFs, and
count: how many table values can be matched to a grid cell by table, row label and column label; how many of the
known errors would have been flagged; how many correct values would have been flagged wrongly. The chemistry
step's table answers name their row and column, which makes matching straightforward; the configurable steps give
a source text ("Table 3, row …, column …") that needs looser matching. Only if the prototype catches a useful
share with few false alarms, build it: a `table_cross_check` flag kind, grouped per table, with both readings in
the text.

**Verify.** The prototype's counts are the result to report. Stop there if they are poor.

---

### P1. Split CLAUDE.md into a short guide and a dated history

**What.** Keep `CLAUDE.md` as a short guide to the current state (aim for under 20 KB): what the app is, the map of
the code, the rules above, how to test and build, the decisions that still hold, and an index of the history.
Move the dated sections, unchanged, into `docs/history/` (one file per month or per theme), with one index line
each.

**Why.** CLAUDE.md is about 240 KB and is loaded into every agent session before any work starts. That is a large
share of a session's context on every turn, it is the likely cause of the session that ran out of context during
this review, and it costs money and time in every session. Much of it describes states that later sections
replace ("SUPERSEDED", "DONE below"), which a new reader has to untangle. Its real value, that decisions and
measurements are never redone, survives a move: the history stays searchable in the repository.

**How.** This changes one of Mickey's working habits (a CLAUDE.md section per round), so agree on the new habit
first: a round's write-up goes to the history file, and CLAUDE.md changes only where a current fact changed. Then:
move the sections verbatim with `git mv`-style commits so nothing is rewritten in the same step; write the short
guide from the current state of the code, checking each statement against the code rather than against older
sections; put the "already measured and decided" list into the guide; add the index. Have Mickey read the guide
before the old file is trimmed.

**Verify.** Every section heading of the old file appears in the index; a search for any decision's keyword finds
it in `docs/history/`.

### P2. Back up the reference runs

**What.** A regular backup of `runs/reference/`, the `runs/*_auto` folders and `runs/local_models/` to somewhere
other than the working copy.

**Why.** These folders are the project's regression base: recorded live answers that cost money to make, that
most of the test suite replays, and that every "byte-identical" check depends on. They are excluded from git on
purpose (they contain the papers' text), so they are in no remote. The one full backup noted in CLAUDE.md is from
2026-10-12, before any of them existed. Whether Mickey's machine is backed up some other way is unknown: ask.

**How.** Offer the choices and let him pick: a script that writes a dated archive to `../Backups/` (as the first
backup did), a private repository for `runs/` alone, or confirmation that his machine backup covers it. If a
script: `scripts/backup_runs.py`, excluding figure crops that can be regenerated, with a note in the guide to run
it after re-recording a reference.

### P3. Bring README, package metadata and a stale comment up to date

**What and why.** Checked on 2026-11-11:

- `README.md` still describes the first prototype: "prebiotic peptide-synthesis papers", "validated on one paper
  only", "A desktop app is planned". The app now has a window, two data packs, modules, queues, focused search and
  local models. It is the first thing a new user or collaborator reads.
- `pyproject.toml`: the description says the same, and the version is still 0.1.0. (The package name and the
  license are open decisions of Mickey's before a public release; remind him, don't choose.)
- `ingestion/crossref_lookup.py`: the docstring says the lookup hasn't been confirmed against the live service. It
  was confirmed on 2026-10-12 and is used by the paper-details step.

**How.** Rewrite the README for people who use the app: what it does, install, the window's five steps, data packs,
costs and privacy (papers are sent to Anthropic unless a local model is used), the command line, where results
go. Take the wording from the window's "Getting started" text and from `packs/_template/README.md` so the terms
match. Show Mickey the draft before committing.

### P4. A main branch and version tags

**What.** Make the current state the repository's main branch, tag it, and tag later states that Mickey would
want to return to.

**Why.** Checked on 2026-11-11: all work since October is on one branch, `flexible-variables`, the only branch on
the remote; the local `master` is far behind and was never pushed; the one tag recorded in CLAUDE.md is from
2026-10-14. The branch's name no longer describes its content, and there are no named restore points for a
month of large changes. Built apps can't be tied to a state of the code.

**How.** Mickey's decision, and partly his to do on GitHub (the default branch). Propose: create `main` at the
current head and push it, set it as the default, tag `v0.3.0` (or his numbering), keep `flexible-variables` until
he is sure, and from then on tag whenever both apps are built for use. Put the version into the built app's
About text and `run_summary.json`, so a results folder says which version made it.

---

## How to present the summary

Mickey is a scientist who built this app with agents; he knows the project's features well and its code less.
Write for him, not for a developer.

- Start with one short paragraph: how many suggestions, in which areas, and which two or three you would do first
  and why.
- Then one entry per suggestion, grouped as above (efficiency, workflow, functionality, upkeep): what would change
  for him or for a user, why it is worth it (with the number it rests on, where there is one), how much work it
  is, and whether it needs a paid run or the local server. Two to four sentences each. Leave the implementation
  detail in this file; he can ask.
- Say clearly which suggestions are measure-first (E1, E2, E4, F2, F3) and could end with "measured, not kept".
- Before you present, confirm the claims marked "confirm" or "check" above against the code, and correct the
  summary where the code says otherwise. Say so if you dropped or changed a suggestion for that reason.
- End by asking which to accept. A numbered list he can answer with IDs is enough; mention the decisions that are
  his alone (P1's change of habit, P2's choice of backup, P4, and where W1 writes a resumed run).

## How to implement an accepted suggestion

1. Mark it `accepted` in the table. Read the code the suggestion names, in ranges, and check that its description
   still matches; the code changes quickly.
2. If it is measure-first, do the smallest thing that gives the measurement, report the numbers, and let Mickey
   decide whether to keep it.
3. Write tests with the change, in the project's style: each test file starts with `import _isolation`, uses
   temporary folders only, and takes facts about the app's data packs from `tests/pack_facts.py` instead of
   listing their steps or columns.
4. Run the full suite, and the robustness check if a data pack changed. Fix a failure at its cause.
5. Build both apps and run `--self-check` if code changed.
6. Write the round up in `docs/history/` (decided under P1), update any document the change makes
   wrong (`docs/local_model_notes.md` for the local-model suggestions), mark the suggestion `done` with the commit,
   commit and push.
7. Tell Mickey what was done, what was measured, and anything you found on the way that he should know, including
   things that didn't work.
