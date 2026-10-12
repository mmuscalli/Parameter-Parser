Empty on purpose.

Drop your curated "most certain and exhaustive" paper subset here (as a CSV
shaped like PaperDataTemplate.xlsx, or a format of your choosing) when it's
ready, then:

1. Set `USE_GOLD_STANDARD = True` and `GOLD_STANDARD_PATH` in `config/settings.py`
   if the filename differs from `curated_subset.csv`.
2. Set `ENABLED = True` at the top of `validation/gold_standard_eval.py`.
3. Implement `load_gold_standard()` and `score_paper()` in that file against
   your subset's actual columns.

Nothing else in the pipeline needs to change.
