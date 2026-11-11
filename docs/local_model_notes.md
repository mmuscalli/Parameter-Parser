# Switching from Claude to a local model: pain points

A running record of what changed when the app's steps were answered by a locally hosted model (Ollama) instead of
the default Anthropic models, and what was done about it. It's meant as a checklist for trying other open models:
most of these will come up again with any model of similar size.

Setup so far: `qwen3.8:27b` on an RTX 3090 (24 GB), Ollama 0.40.16, served over the LAN; details in
`local_model_server_report.md`. Runs are kept in `runs/local_models/` (local only). The test runs and their
comparison with the references are one tool, `scripts/check_local_model.py` (see the checklist).

## Results so far

| Paper | Model | Context | Result | Time | Notes |
|---|---|---|---|---|---|
| eder1994 (prebiotic) | gemma3:12b (Mac, 24 GB) | 64K | 31 / 42 rows; yields mislabelled | 33 min | framework check only |
| eder1994 | qwen3.8:27b | 131072 | 42 / 42 rows, 87.2% of the reference | 5.3 min | two text columns empty (issue 1) |
| eder1994 | qwen3.8:27b, text field required | 131072 | 100% | 6.7 min | HPLC numbers as text (issue 2) |
| eder1994 | qwen3.8:27b, both fixes | 131072 | 100% (654 / 654), every analysis setting in its column | 4.5 min | |
| eder1994 | qwen3.8:27b, + `sample` required | 131072 | 100% | 6.9 min | chemistry output 6.2K -> 10.5K tokens |
| eder1994 | qwen3.8:27b, + `mode` / `meth` required | 131072 | 100% | 6.9 min | |
| teng2023 (exoplanets) | qwen3.8:27b | 131072 | 41 rows; 1,984 archive matches, 168 differ | 37 min | planet `sample` left out (issue 9) |
| teng2023 | qwen3.8:27b, + `sample` required | 131072 | 2,126 match, 21 differ, 0 missing | 34 min | modes as conflicts (issue 10) |
| teng2023 | qwen3.8:27b, + `mode` / `meth` required | 131072 | 2,130 match, 18 differ (all uncertainties), 0 missing | 34 min | |

For comparison, Claude Standard (Sonnet) reproduces eder1994's values except wording, for about $0.26 (the reference
itself was made with it), and on teng2023 matches 2,132 archive values with 0 real differences and 27 not extracted,
for about $1.40–1.85. Archive counts are for the 36 rows the archive adopted, against the archive snapshot saved with
the Claude reference run (`scripts/check_local_model.py --paper teng2023`).

## Issues and what was done

### 1. Optional fields get left out

The compact answer formats leave rarely used fields optional, so Claude doesn't spend output tokens on them. Claude
always fills a field when it has something for it; qwen didn't. It named `experiment_type` and `solution_type`,
reasoned "= Batch" in its note, but left the text field (`txt`) out and sent `v = 0`. All 84 misses on eder1994 were
this.

- **Done:** requests to local servers make `txt` required in configurable steps' values (`local_models.LOCAL_REQUIRED`).
  Local runs are free, so the extra tokens don't matter. Claude's requests are unchanged.
- **Done:** a text value that arrives with no text is flagged, quoting the model's note, instead of being skipped.
- **Since then required too:** `sample` (issue 9), `mode` and `meth` (issue 10); see `local_models.LOCAL_REQUIRED`.
- **Still optional, watch for:** `b` basis, `ep` / `em` uncertainties, `lim`, `hi`. On teng2023 qwen filled
  uncertainties for 282 of 293 planet values, so these haven't caused losses yet.

### 2. Making a field required can change what the model writes into it

Requiring `txt` everywhere, including the analysis step's settings, made qwen write EVERY setting as text ("200",
"0.35") and drop the units, because that format doesn't say which settings are text. Six values went to the review.

- **Done:** the requirement applies only where each value is declared text or number (objects with `col`).
- **Done:** the analysis step reads a setting given as a bare number in the text as that number, in the setting's
  unit (noted).
- **Lesson:** a grammar forces a field to exist, not to be used correctly. Test a required-field change on a paper
  that exercises every step.

### 3. The context a server reports isn't the context that fits

Ollama's `/api/show` reports each model's architectural maximum (262,144 for both qwen3.8:27b and gemma4:31b). At that
size the KV cache doesn't fit in 24 GB, and layers move to the CPU: output fell from about 30 to 6.5 tokens/s.

- **Done (server side):** the usable context was measured (131072 / 81920) and is what's entered in the app.
- **Watch for:** the app's "Test connection" shows the reported maximum; enter the measured value, not that one.
  Other apps using the GPU take memory from the same budget.

### 4. Thinking models spend output on reasoning

qwen3.8 and gemma4 reason (about 1K tokens) before the JSON. It counts against the request's output limit and adds
time, but caused no failures so far.

- **Watch for:** steps with long answers near the context limit, where reasoning eats into the room left for the
  answer.

### 5. No prompt caching

With Claude the paper is sent once and read from the cache by every step. A local server reads the whole paper again
for every step: teng2023's six requests each carried 82–87K tokens (about 3–4 minutes of reading each on the 3090,
before any output). A whole paper took 34–37 minutes (eder1994: 4.5–7 minutes). The time scales with paper length
times the number of steps.

### 6. One request at a time

Two parallel requests on one GPU each slowed to 6–8 tokens/s and took longer together than one after the other. The
app's "requests at once" stays at 1 for a single GPU, so parallel steps and passes wait their turn.

### 7. Less open-ended capture

qwen suggested no extra variables on eder1994 (the conditions step's `other` list was empty); Sonnet usually suggests
a few. Values outside the data pack's columns are therefore less likely to be offered for review with a local model.

### 8. Determinism

At temperature 0 qwen gave the same row plan on all three eder1994 runs (identical output token counts), so a re-run
after a fix shows the fix's effect rather than run-to-run variance. Claude varies more between runs.

### 9. The sample (row) of a value gets left out

The same as issue 1, with consequences far beyond one column. In the compact formats a value names its set (a planetary
system) and, optionally, its sample (a planet). qwen made one answer row per planet on teng2023 but left `sample` out
of every one, so every value counted for the whole system. The app keeps the first of two different values for one
place and flags the other, so each system's second planet got the first planet's numbers, and each joint-fit row the
RV fit's: 168 archive differences, 49 conflict flags.

- **Done:** `sample` is required for local servers wherever an answer names a set and a sample. Star-wide values still
  reached every planet of a system (the side effect to watch for, like issue 2); conflict flags fell to 0.
- **Cost:** answers name the sample on every row, so they get longer (eder1994 chemistry 6.2K -> 10.5K tokens).
- **Lesson:** the one-paper-one-row prebiotic test (eder1994) didn't show this, because its values per set are
  mostly the same for every row. A paper with several rows per set that differ (several planets, several solutions)
  is needed to catch it.

### 10. Posterior modes and other estimates come back as conflicts

Teng's Table 4 gives three inclinations for each joint fit (all, prograde, retrograde). Claude marks the second and
third with `mode`; qwen left `mode` out, so they read as conflicting values and the archive's prograde value went
unmatched.

- **Done:** `mode` and `meth` (estimates by another method) are required for local servers in configurable steps'
  values. Afterwards: 4 multimodal flags, 63 other-estimate flags, 0 conflicts.

### 11. Context: the answer shares the window with the paper

Every teng2023 request carried about 86K tokens of paper; the planet step then answered 30–38K tokens, about 120–125K
of the 131K context. A paper 5–10% longer, or a model that reasons longer, would be cut off or refused. The app checks
the prompt against the context before sending, and limits the answer to what's left.

- **Watch for:** long catalogue papers. Options: compact text (on for exoplanets), dropping the reference list, or
  a model / GPU that fits a larger context.

### 12. Dense tables: uncertainties misread

The last 18 teng2023 differences are all uncertainties (periastron time, eccentricity, log g errors) from dense
tables, e.g. 11.3 given as the periastron-time error of several planets. Values themselves all matched. Claude had
the same kind of misreading on this table before table pages were cut into pieces; qwen reads the same pieces less
precisely.

### 13. Model size

A 12B model (gemma3:12b) got the rows and conditions roughly right but mislabelled table values (yields read as
starting concentrations). About 27–31B is where the results became usable.

## Checklist for trying another model

1. Measure the context that fits on the GPU; don't use the reported maximum.
2. Run eder1994 first (short, every prebiotic step, a reference to score against):
   `python scripts/check_local_model.py MODEL --context N`. It prints each step's tokens and time, the share of the
   reference's cells reproduced and the most-missed columns. `--score RUN_DIR` compares a finished run again.
3. Look at empty columns in the scored misses: a column empty on every row usually means a skipped field (issue 1).
4. Look at the review items and analysis flags: numbers that arrived as text (issue 2).
5. Then teng2023 (`--paper teng2023`, ~35 min): several rows per set (issue 9), modes (issue 10), the context
   (issue 11) and uncertainties (12). The tool prints the archive matches; look at `conflicting_values` flags: many
   of them usually mean a field that places values (sample, mode, method) was left out.
6. Any new optional field added to an answer format is a candidate for `local_models.LOCAL_REQUIRED`.
