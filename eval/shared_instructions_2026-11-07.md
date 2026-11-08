# Shared, cached step instructions -- evaluation (2026-11-07)

Question (Mickey, structural change (2) of the cost discussion): can the instructions that are the same for every
paper be paid once per queue instead of once per paper?

## What was built

- A request's cached prefix is tools -> system -> messages. Before, the cache marker sat after the paper, so the
  tool list (~9.7K tokens, prebiotic) was stored again for every paper and each step's instructions (~2-5K tokens)
  were sent uncached after the paper.
- Now (`RunConfig.shared_instructions`): the system prompt holds the shared line plus EVERY paper-reading step's
  static instructions (`PaperContext.instructions`, built by each step's `prompt_text` with the structure plan's
  place marked `PLAN_MARK`), with its own cache marker -- tools + instructions are one prefix, identical for every
  paper of a pack and settings. Each step's request then says "Follow the instructions for step X" plus its
  structure plan (`PaperContext.task_for`); a prompt that doesn't match its stored instructions is sent whole, as
  before. Prebiotic block: ~15K tokens of instructions + 9.7K of tools; exoplanets ~8.5K + 7.7K.
- Queues: the first paper's extraction goes alone until its structure plan is back (the prefix is then cached), the
  rest follow (`PaperQueue._warm`; not in batch mode). Measured cost: +22 s on a 5-paper queue (81 -> 103 s).

## Results (Standard, live, 5 prebiotic reference papers as one queue, 3 at a time; cold caches)

| | input-side cost | output cost | total |
|---|---|---|---|
| off (before) | $0.739 | $0.577 | $1.317 |
| on, without the warm-up (3 papers started together, each wrote the prefix) | $0.695 | $0.625 | $1.320 |
| on, with the warm-up | **$0.504 (-32%)** | $0.584 | **$1.088 (-17%)** |

Per paper after the first: input-side $0.06-0.11 instead of $0.12-0.18. A single paper on its own: $0.331 off,
$0.350 on (+6% -- the block is cached for one paper only). Accuracy is unchanged (same instructions; the scores
differ only by run-to-run variance).

## Defaults

`shared_instructions=None` (automatic): on in paper queues, off for single runs. A user who runs many single papers
one after another within 5 minutes would also gain; not measured.

## Also in this round

Mickey (2026-11-07): data a review reproduces from other publications become rows again (source-marked in `ds` ->
original_data_reference + cited_data flags), accepted by default; only a paper with no results at all is skipped.
truman2024 back to 4-11 rows (95.5% on one run).
