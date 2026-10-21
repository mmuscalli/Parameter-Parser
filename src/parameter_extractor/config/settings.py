"""
Central place for pipeline configuration. Nothing here should require code
changes elsewhere when you tune it -- that's the point of keeping it separate.

These are DEFAULTS. A run only uses what's in its RunConfig
(config/run_config.py); the GUI builds that from user input, the CLI from
these values via RunConfig.from_settings().
"""
from pathlib import Path
import os

# Files that ship inside the package (found the same way in a source checkout,
# a pip install, or a bundled app).
PACKAGE_DIR = Path(__file__).resolve().parent.parent      # .../parameter_extractor
PROMPTS_DIR = PACKAGE_DIR / "prompts"
SCHEMAS_DIR = PACKAGE_DIR / "schemas"

# Source-checkout locations: <repo>/src/parameter_extractor -> <repo>. Only
# meaningful when running from the repository (CLI/development), never
# relied on by the app itself.
PROJECT_ROOT = PACKAGE_DIR.parent.parent
EVAL_DIR = PROJECT_ROOT / "eval"

# CLI defaults: outputs under ./runs, key from <repo>/config/.env or a .env in
# the current folder or the environment. The GUI supplies both itself.
RUNS_DIR = Path.cwd() / "runs"
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / "config" / ".env")
    load_dotenv(Path.cwd() / ".env")  # doesn't override anything already set
except ImportError:
    pass  # python-dotenv not installed; ANTHROPIC_API_KEY must be set some other way

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Model per stage. Cheap/simple stages (metadata lookup, optional triage) can use a
# smaller/faster model; stages that require careful reading (chemistry,
# methodology) should use a stronger one. Placeholder names -- set to
# whatever's current when you wire up real calls.
MODELS = {
    "triage": "claude-haiku-5-5",
    "structure_planner": "claude-sonnet-5-5",
    "metadata": "claude-haiku-5-5",
    "methodology": "claude-sonnet-5-5",
    "chemistry": "claude-sonnet-5-5",
    "figure_planner": "claude-sonnet-5-5",   # only for figures the user chooses to digitize
    "equations": "claude-sonnet-5-5",        # optional LaTeX conversion; ~2 cents for 13 equations
}

# Stages that depend only on the experiment structure run at the same time (pipeline.extract)
MAX_PARALLEL_STAGES = 6

MAX_TOKENS = 64000  # streamed (api_client.py); eder1994 chemistry alone overflowed 16000

# --- Validation / gold-standard scoring -------------------------------------
# Left OFF until the curated "most certain and exhaustive" paper subset exists.
# See validation/gold_standard_eval.py.
USE_GOLD_STANDARD = False
GOLD_STANDARD_PATH = EVAL_DIR / "gold_standard" / "curated_subset.csv"  # not created yet

# --- Confidence flagging / filtering -----------------------------------------
# Every extracted chemistry value and methodology field carries the model's own
# high/medium/low confidence. These are self-reports, not calibrated
# probabilities -- in the 2026-10-12 eder1994 runs every chemistry value was
# "high", including one mislabelled value -- so they complement the
# structural checks in validation/plausibility_checks.py, not replace them.
#
# Values used in the CSV whose confidence is below CONFIDENCE_FLAG_BELOW are
# listed in plausibility_flags.json. ("high" = flag medium and low.)
CONFIDENCE_FLAG_BELOW = "high"
# Values below CONFIDENCE_DROP_BELOW are left BLANK in the CSV instead of
# written (still listed in the flags). None = never drop. Off by default: a
# blank cell is indistinguishable from "not reported" once the CSV leaves
# this pipeline, so dropping should be a deliberate choice.
CONFIDENCE_DROP_BELOW = None  # e.g. "medium" to drop low-confidence values

# --- Scope for this prototype pass -------------------------------------------
# Figures/scatter-plot digitization isn't implemented yet -- stages should
# skip any value that only exists as a plotted point, not as table/text.
EXTRACT_FIGURE_DATA = False

# --- CrossRef DOI lookup -----------------------------------------------------
# Fallback used only when a paper's own text doesn't state a DOI (common for
# older scanned papers -- see ingestion/crossref_lookup.py). Both thresholds
# are deliberately conservative: a wrong DOI silently attached to a row is
# worse than no DOI.
CROSSREF_MIN_TITLE_SIMILARITY = 0.85  # difflib ratio, 0-1
CROSSREF_MIN_SCORE = 40.0             # CrossRef's own relevance score; scale is
                                       # query-dependent, this floor is a coarse
                                       # sanity check, not a probability

# CrossRef's "polite pool" gives better rate limits to requests whose
# User-Agent includes a contact mailto. Optional -- leave blank to use the
# public pool. Never auto-filled with anyone's personal email; set your own
# here if you want it.
CROSSREF_CONTACT_MAILTO = ""


def crossref_user_agent() -> str:
    base = "parameter-extractor/0.1 (https://github.com/; mailto:{})"
    return base.format(CROSSREF_CONTACT_MAILTO or "no-contact-set@example.invalid")


# --- Table-page rasterization -------------------------------------------------
# Two-column OCR'd tables (see eder1994's Tables 1/2) routinely garble row
# order in plain text extraction. Pages whose text matches a "Table N"
# caption get rasterized and handed to the model as images alongside the
# text for the stages that most depend on table precision.
# 220 dpi + cropping + cutting pages bigger than the API reads unscaled into pieces
# (ingestion/table_tiles.py): superscript uncertainties stay legible (teng2023 Table 3).
TABLE_RASTER_DPI = 220
RASTERIZE_TABLE_PAGES = True
