from pathlib import Path
from parameter_extractor.config import settings


def load_prompt(name: str, **placeholders: str) -> str:
    """Load the prompt <name>.md -- the active domain pack's version if it has one,
    else the app's prompts/ -- and substitute {{TOKEN}} placeholders.

    Plain string replace rather than str.format/Jinja: paper text routinely
    contains literal `{`/`}` (equations, references), which would break
    .format(); token replace sidesteps that entirely.
    """
    from parameter_extractor.packs import current
    text = current().prompt_path(name).read_text()        # the domain pack's own, else the app's
    for key, value in placeholders.items():
        text = text.replace("{{" + key + "}}", value)
    return text
