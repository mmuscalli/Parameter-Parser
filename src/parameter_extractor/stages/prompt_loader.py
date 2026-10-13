from pathlib import Path
from parameter_extractor.config import settings


def load_prompt(name: str, **placeholders: str) -> str:
    """Load prompts/<name>.md and substitute {{TOKEN}} placeholders.

    Plain string replace rather than str.format/Jinja: paper text routinely
    contains literal `{`/`}` (equations, references), which would break
    .format(); token replace sidesteps that entirely.
    """
    text = (settings.PROMPTS_DIR / f"{name}.md").read_text()
    for key, value in placeholders.items():
        text = text.replace("{{" + key + "}}", value)
    return text
