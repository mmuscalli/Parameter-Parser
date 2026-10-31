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
from typing import Dict, List, Optional

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
    # Local variable registry (accepted new columns + aliases). None = template
    # columns only -- the GUI and CLI pass registry.default_registry_path().
    registry_path: Optional[Path] = None
    # Terms the user especially wants found ("extraction solvent volume", ...):
    # each gets an explicit found / not-found answer from a targeted search step.
    focus_terms: List[str] = field(default_factory=list)
    # Look up species names on PubChem to recognise synonyms (pubchem.py). Off
    # by default so library use and tests stay offline; the GUI and CLI turn it on.
    use_pubchem: bool = False
    # Convert the labelled equations found in the paper to LaTeX: one small extra API call
    # (stages/equations.py). Finding and cropping them is free and always done.
    equations_to_latex: bool = False
    # Domain pack (packs/): template, vocabulary, prompts and stages of a research area
    pack: str = "prebiotic_chemistry"
    # Online cross-checks a pack offers (exoplanets: the NASA Exoplanet Archive). Off by default
    # so library use and tests stay offline; the GUI and CLI turn it on.
    online_checks: bool = False
    # Optional stages (the domain pack's stages/*.json) by name: "auto" (run when its trigger matches the
    # paper -- the default), "on" (always) or "off" (never)
    optional_stages: Dict[str, str] = field(default_factory=dict)
    pubchem_cache_path: Optional[Path] = None
    # Send the paper (text + table images) first, marked for caching, with the same tool list in
    # every paper-reading step (api_client): the structure planner writes the cache, the later steps
    # read it at 5-10% of the input price. Measured 2026-10-22: Standard runs 26-57% cheaper, accuracy
    # unchanged. (With per-step output schemas the cache can't be shared -- the schema is part of
    # the cache key -- hence tools.)
    prompt_caching: bool = True
    # Which models do the work (settings.MODEL_PROFILES): "standard" (Sonnet 5.5 for every step
    # but the page-1 metadata) or "economy" (Haiku 5.5 for every step)
    model_profile: str = "standard"
    # Send every request through the Message Batches API: half price, but each step waits in
    # Anthropic's batch queue (usually seconds to minutes, at most 24 h). Uses the 1-hour cache.
    batch_mode: bool = False
    # Read a paper's arXiv full text (HTML rendering of the LaTeX source) instead of the local PDF
    # when the PDF names an arXiv ID or DOI that arXiv has (ingestion/arxiv_source.py): ~40% fewer
    # tokens, exact table values, but a PREPRINT (the version read is recorded and flagged). Papers
    # given by identifier instead of a PDF always come from arXiv.
    prefer_arxiv: bool = False
    # Read a paper's supplementary information with it ('<paper>_SI.pdf' next to the PDF, supplements.py)
    include_supplements: bool = True
    # Images kept in the run folder (Mickey, 2026-10-31): a crop of every table (tables/, the Tables tab) and
    # of every digitized figure -- on by default; figures that weren't digitized only with
    # save_all_figure_images (off by default: they're rendered for the review, then removed).
    save_images: bool = True
    save_all_figure_images: bool = False
    # Run the extraction steps after the structure plan this many times (1-3) and keep each value by vote
    # (voting.py): another lever for cheap runs -- Economy with 2-3 passes recovers values a single pass
    # drops at random. Each extra pass adds the cost of those steps again (the paper is read from cache).
    passes: int = 1
    # Suggest new variables (Mickey, 2026-10-26; on by default): open-ended stages also list conditions
    # that have no column, and values with no column are offered in the review. Off: no open-ended
    # capture (~1.5% of a run's tokens), and only assumed values and the user's own search terms are
    # reviewed -- the rest stays out of the CSV (new_variables.json, one summary flag).
    suggest_new_variables: bool = True
    # Developer only (dev_features.py, never in public builds): write model requests to this folder for
    # answers from a Claude Code session instead of calling the API (handoff.py); no API key needed
    handoff_dir: Optional[Path] = None
    # NASA ADS API token: only needed to look up journal ADS bibcodes (2023PASJ...75.1030T)
    ads_token: str = ""
    # arXiv lookups and full texts kept between runs (ingestion/arxiv_source.LookupCache); None = none
    arxiv_cache_dir: Optional[Path] = None

    @classmethod
    def from_settings(cls, **overrides) -> "RunConfig":
        """Defaults for the command line: key from config/.env or the shell,
        output under runs/. Any field can be overridden by keyword."""
        values = dict(api_key=settings.ANTHROPIC_API_KEY, output_dir=settings.RUNS_DIR,
                      ads_token=settings.ADS_API_TOKEN)
        values.update(overrides)
        return cls(**values)

    def model_for(self, stage: str) -> str:
        profile = settings.MODEL_PROFILES.get(self.model_profile, {})
        if stage in profile:
            return profile[stage]
        if "*" in profile and stage not in settings.PROFILE_EXEMPT:
            return profile["*"]
        return self.models.get(stage, self.models["chemistry"])

    def to_public_dict(self) -> dict:
        """For run_summary.json -- everything except the key."""
        d = asdict(self)
        d.pop("api_key")
        d["ads_token"] = "(set)" if self.ads_token else ""
        d["output_dir"] = str(self.output_dir)
        d["registry_path"] = str(self.registry_path) if self.registry_path else None
        d["pubchem_cache_path"] = str(self.pubchem_cache_path) if self.pubchem_cache_path else None
        d["arxiv_cache_dir"] = str(self.arxiv_cache_dir) if self.arxiv_cache_dir else None
        d["handoff_dir"] = str(self.handoff_dir) if self.handoff_dir else None
        return d
