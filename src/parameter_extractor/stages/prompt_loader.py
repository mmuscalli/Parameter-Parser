from pathlib import Path
from parameter_extractor.config import settings


def load_prompt(name: str, **placeholders: str) -> str:
    """Load the prompt <name>.md -- the active domain pack's version if it has one,
    else the app's prompts/ -- and substitute {{TOKEN}} placeholders.

    Pack-specific rules without a whole prompt of its own (2026-10-26): a pack's
    prompts/<name>.rules.md fills the shared prompt's {{PACK_RULES}} slot, under a
    "Rules for this research area" heading (nothing when the pack has none), and
    {{RESEARCH_AREA}} is the pack's label. So most packs need no copy of the shared
    prompts -- only the rules that differ.

    Plain string replace rather than str.format/Jinja: paper text routinely
    contains literal `{`/`}` (equations, references), which would break
    .format(); token replace sidesteps that entirely.
    """
    from parameter_extractor.packs import current
    pack = current()
    text = pack.prompt_path(name).read_text()        # the domain pack's own, else the app's
    rules = pack.prompt_rules(name)
    placeholders = {"PACK_RULES": f"\nRules for this research area ({pack.label}):\n{rules.strip()}\n" if rules else "",
                    "RESEARCH_AREA": pack.label.lower(), **placeholders}
    for key, value in placeholders.items():
        text = text.replace("{{" + key + "}}", value)
    return text
