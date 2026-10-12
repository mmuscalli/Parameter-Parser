"""
Central place for pipeline configuration. Nothing here should require code
changes elsewhere when you tune it -- that's the point of keeping it separate.
"""
from pathlib import Path
import os

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv not installed yet; ANTHROPIC_API_KEY must be set some other way

ROOT = Path(__file__).resolve().parent.parent

PROMPTS_DIR = ROOT / "prompts"
SCHEMAS_DIR = ROOT / "schemas"
RUNS_DIR = ROOT / "runs"
EVAL_DIR = ROOT / "eval"

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
}

MAX_TOKENS = 64000  # streamed (api_client.py); eder1994 chemistry alone overflowed 16000

# --- Validation / gold-standard scoring -------------------------------------
# Left OFF until the curated "most certain and exhaustive" paper subset exists.
# See validation/gold_standard_eval.py.
USE_GOLD_STANDARD = False
GOLD_STANDARD_PATH = EVAL_DIR / "gold_standard" / "curated_subset.csv"  # not created yet

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
    base = "EORE-extraction-pipeline/0.1 (https://github.com/; mailto:{})"
    return base.format(CROSSREF_CONTACT_MAILTO or "no-contact-set@example.invalid")


# --- Table-page rasterization -------------------------------------------------
# Two-column OCR'd tables (see eder1994's Tables 1/2) routinely garble row
# order in plain text extraction. Pages whose text matches a "Table N"
# caption get rasterized and handed to the model as images alongside the
# text for the stages that most depend on table precision.
TABLE_RASTER_DPI = 150
RASTERIZE_TABLE_PAGES = True
