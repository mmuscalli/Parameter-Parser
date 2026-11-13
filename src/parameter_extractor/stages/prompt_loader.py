from pathlib import Path
from parameter_extractor.config import settings


import re

# {{#NAME}}...{{/NAME}}: kept when the option NAME is on; {{^NAME}}...{{/NAME}}: kept when it is off (2026-11-12, rows
# from body text). Markers alone on their lines (a block) go with their line breaks; markers inside a line (inline)
# leave the line as it is -- so a prompt with its options set reads exactly as if written without the markers.
_BLOCK = re.compile(r"^\{\{([#^])(\w+)\}\}\n(.*?)^\{\{/\2\}\}\n", re.DOTALL | re.MULTILINE)
_INLINE = re.compile(r"\{\{([#^])(\w+)\}\}(.*?)\{\{/\2\}\}", re.DOTALL)


def apply_sections(text: str, sections: dict) -> str:
    """Keep or drop a prompt's optional sections by `sections` ({name: on}); a name not given counts as off."""
    def keep(m) -> str:
        on = bool(sections.get(m.group(2)))
        return m.group(3) if on == (m.group(1) == "#") else ""
    return _INLINE.sub(keep, _BLOCK.sub(keep, text))


def load_prompt(name: str, sections: dict = None, **placeholders: str) -> str:
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

    `sections` ({name: on}) keeps or drops the prompt's {{#name}} / {{^name}} sections (apply_sections) -- before
    the paper text goes in, so a paper's own braces are never read as markers.
    """
    from parameter_extractor.packs import current
    pack = current()
    text = pack.prompt_path(name).read_text()        # the domain pack's own, else the app's
    rules = pack.prompt_rules(name)
    placeholders = {"PACK_RULES": f"\nRules for this research area ({pack.label}):\n{rules.strip()}\n" if rules else "",
                    "RESEARCH_AREA": pack.label.lower(),
                    # rules the pack's modules add to this prompt (the Peptides and oligomers module's naming rules in
                    # the chemistry step's prompt); the line goes when there are none
                    "MODULE_RULES": pack.module_prompt_rules(name) if hasattr(pack, "module_prompt_rules") else "",
                    **placeholders}
    if not placeholders["MODULE_RULES"]:
        text = text.replace("{{MODULE_RULES}}\n", "")
    text = apply_sections(text, sections or {})
    for key, value in placeholders.items():
        text = text.replace("{{" + key + "}}", value)
    return text
