"""
Rows only from tables and digitized figures by default (Mickey, 2026-11-12: text results were mostly passing remarks --
"experiments with X gave peptides up to length Y" -- making rows with little context that could repeat a table's data).
RunConfig.rows_from_text (Options: "Make rows from results in the body text too"; CLI --rows-from-text) turns the
earlier rule back on: text results with complete conditions get rows. The row-plan prompts carry both rules as optional
sections (stages/prompt_loader.apply_sections); with the option on, the prompt is the one sent before 2026-11-12.

Run with: python tests/test_rows_from_text.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)


def test_sections_keep_or_drop_text_exactly():
    from parameter_extractor.stages.prompt_loader import apply_sections
    text = "a\n{{#X}}\nwhen on\n{{/X}}\n{{^X}}\nwhen off\n{{/X}}\nb{{#X}} (inline){{/X}}.\nc\n"
    assert apply_sections(text, {"X": True}) == "a\nwhen on\nb (inline).\nc\n"
    assert apply_sections(text, {"X": False}) == "a\nwhen off\nb.\nc\n"
    assert apply_sections(text, {}) == apply_sections(text, {"X": False})        # not given = off
    assert apply_sections("no markers {here}\n", {"X": True}) == "no markers {here}\n"


def test_row_plan_prompt_follows_the_option():
    from parameter_extractor import packs
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.stages.structure_planner import prompt_text
    assert RunConfig.from_settings(api_key="x").rows_from_text is False                 # the default
    packs.activate("prebiotic_chemistry")
    on, off = prompt_text("PAPER", True), prompt_text("PAPER", False)
    assert all("{{#" not in t and "{{^" not in t and "{{/" not in t for t in (on, off))
    assert "get rows too, but ONLY when the" in on and "get rows too" not in off
    assert "ONLY for results given in the paper's TABLES" in off
    assert "(or a text result with complete conditions)" in on and "text result with complete" not in off
    packs.activate("_template")                                                       # the shared prompt
    on, off = prompt_text("PAPER", True), prompt_text("PAPER", False)
    assert "results stated in\n  the text or a caption together with" in on
    assert "Rows come only from the paper's TABLES" in off and "together with the conditions" not in off


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All rows-from-text tests passed.")
