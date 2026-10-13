"""
Everything ONE run needs, passed in explicitly rather than read from module
globals. A front end builds a RunConfig from whatever the user entered (the
GUI's key field, output folder picker, ...); the CLI builds one from
config/settings.py and config/.env via RunConfig.from_settings().

Nothing in the pipeline reads the API key from the environment itself --
that's what lets a GUI accept a key at run time.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

from parameter_extractor.config import settings


@dataclass
class RunConfig:
    api_key: str
    output_dir: Path
    models: Dict[str, str] = field(default_factory=lambda: dict(settings.MODELS))
    max_tokens: int = settings.MAX_TOKENS
    rasterize_table_pages: bool = settings.RASTERIZE_TABLE_PAGES
    table_raster_dpi: int = settings.TABLE_RASTER_DPI
    confidence_flag_below: Optional[str] = settings.CONFIDENCE_FLAG_BELOW
    confidence_drop_below: Optional[str] = settings.CONFIDENCE_DROP_BELOW
    paper_prefix: str = "001"

    @classmethod
    def from_settings(cls, **overrides) -> "RunConfig":
        """Defaults for the command line: key from config/.env or the shell,
        output under runs/. Any field can be overridden by keyword."""
        values = dict(api_key=settings.ANTHROPIC_API_KEY, output_dir=settings.RUNS_DIR)
        values.update(overrides)
        return cls(**values)

    def model_for(self, stage: str) -> str:
        return self.models.get(stage, self.models["chemistry"])

    def to_public_dict(self) -> dict:
        """For run_summary.json -- everything except the key."""
        d = asdict(self)
        d.pop("api_key")
        d["output_dir"] = str(self.output_dir)
        return d
