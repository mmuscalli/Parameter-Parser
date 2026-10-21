"""
Check extracted exoplanet rows against the NASA Exoplanet Archive.

The archive keeps every published parameter set of a planet (table `ps`, one
row per planet and reference). The right one to compare with is the set whose
PLANETARY PARAMETER reference (pl_refname) is the paper being extracted (Mickey,
2026-10-20 -- not necessarily the default set, nor the discovery paper). It is
fetched from the archive's public TAP service (no key), compared column by
column, and the archive rows are saved in the run folder (archive_rows.json)
so the comparison can be replayed offline.

Planets are matched by name in the archive's style (Greek letters as "eps",
"omi", ...; case-insensitive), else -- for a planet the archive files under
another name (41 Lyn b = HD 81688 b) -- by orbital period among the archive's
planets from this paper. Only columns the archive took from this paper are
compared: st_* when its st_refname is the paper, sy_* likewise (usually Gaia
or TICv8, so not), disc_* likewise; the others are listed as from another
reference.

Every value the row records counts: its own and each posterior mode's (a
bimodal inclination's prograde / retrograde values) -- a match on any is a
match (`matched_mode` says which -- a mode or another method's estimate). Differences where the paper's value is
kept on purpose (Mickey, 2026-10-21) are `minor`, not `differs`: names worded
differently (NAME_COLUMNS sharing a word) and uncertainties within 20%.
A value matches when it agrees to within the paper's rounding: 0.5% relative,
or half the last printed digit (archive zero-padding ignored), whichever is
larger. Text values match case-insensitively. Fails soft: no network -> a
note, never a failed run.
"""
from __future__ import annotations
import csv
import io
import json
import re
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional

TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
TIMEOUT_SEC = 30
REL_TOLERANCE = 0.005
SKIP = {"pl_name", "hostname", "pl_letter", "pl_refname", "st_refname", "sy_refname", "disc_refname"}
PERIOD_MATCH = 0.01                 # alias fallback: orbital periods within 1%
# column prefix -> the archive column naming the reference those values came from
REFERENCE_OF = {"st_": "st_refname", "sy_": "sy_refname", "disc_": "disc_refname"}
_GREEK = {"α": "alf", "β": "bet", "γ": "gam", "δ": "del", "ε": "eps", "ζ": "zet", "η": "eta", "θ": "tet",
          "ι": "iot", "κ": "kap", "λ": "lam", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omi", "π": "pi",
          "ρ": "rho", "σ": "sig", "τ": "tau", "υ": "ups", "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "ome"}


def _strip_html(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


def archive_name(name: str) -> str:
    """A planet name as the archive writes it: 'ε Tau b' -> 'eps Tau b', 'o UMa b' -> 'omi UMa b'."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    name = "".join(_GREEK.get(ch, ch) for ch in name)
    return re.sub(r"^o(?= [A-Z][A-Za-z]{2}\b)", "omi", name)       # Latin 'o' for omicron, as in 'o UMa'


def _key(name: str) -> str:
    """Host case-insensitive, companion letter not: 'HD 5608 b' is the planet, 'HD 5608 B' a star."""
    host, _, letter = archive_name(name).rpartition(" ")
    return f"{host.lower()} {letter}" if host else letter.lower()


def _sql(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def fetch_parameter_sets(planet_names: List[str], reference: str = "") -> List[dict]:
    """Every published parameter set of these planets (archive table ps), and every
    parameter set from this reference (planets the archive names differently)."""
    names = ",".join(_sql(n) for n in sorted({archive_name(n) for n in planet_names} | set(planet_names)))
    query = f"select * from ps where pl_name in ({names})"
    if reference:
        query += f" or pl_refname like {_sql('%' + reference + '%')}"
    url = f"{TAP_URL}?{urllib.parse.urlencode({'query': query, 'format': 'csv'})}"
    req = urllib.request.Request(url, headers={"User-Agent": "ParameterExtractor"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


ANGLES = {"pl_orblper", "pl_projobliq", "pl_trueobliq"}       # degrees, the same modulo 360


def _same_text(a, b) -> bool:
    """Case, '_' / '-' / spaces, and a bracketed abbreviation don't matter: 'BJD_TDB' = 'BJD-TDB',
    'Transiting Exoplanet Survey Satellite' = 'Transiting Exoplanet Survey Satellite (TESS)'."""
    norm = lambda t: re.sub(r"[\s_\-]+", " ", _strip_html(t).lower()).strip()
    bare = lambda t: re.sub(r"\s*\([^)]*\)", "", norm(t)).strip()
    return norm(a) == norm(b) or (bare(a) == bare(b) and bool(bare(a)))


def _matches(extracted, archived, column: str = "") -> bool:
    a, b = _number(extracted), _number(archived)
    if a is None or b is None:
        return _same_text(extracted, archived)
    if column in ANGLES:
        a = b + ((a - b + 180) % 360 - 180)
    printed = str(archived).strip()
    digits = len(printed.split(".")[1].rstrip("0")) if "." in printed else 0
    return abs(a - b) <= max(REL_TOLERANCE * abs(b), 0.5 * 10 ** -digits, 1e-9)


def _same_reference(archive_ref: str, reference: str) -> bool:
    return _strip_html(archive_ref).lower() == reference.strip().lower()


def compare(records: List[dict], archive_rows: List[dict], reference: str) -> List[dict]:
    """Per extracted row: which archive parameter set it was compared with, and each
    column's outcome (match / differs / not extracted)."""
    report = []
    named = {_key(r.get("pl_name")) for r in records if r.get("pl_name")}
    from_paper = [a for a in archive_rows if _same_reference(a.get("pl_refname", ""), reference)
                  and _key(a.get("pl_name")) not in named]           # this paper's planets under other names
    for rec in records:
        name = rec.get("pl_name")
        if not name:
            continue
        sets = [a for a in archive_rows if _key(a.get("pl_name")) == _key(name)]
        entry = {"pl_name": name, "reference": reference}
        if rec.get("pl_fitlabel"):                      # one row per solution: each is compared
            entry["solution"] = rec["pl_fitlabel"]
        period = _number(rec.get("pl_orbper"))
        if not sets and period:
            alias = [a for a in from_paper if _number(a.get("pl_orbper"))
                     and abs(_number(a["pl_orbper"]) - period) <= PERIOD_MATCH * period]
            if len(alias) == 1:
                sets = [a for a in archive_rows if a.get("pl_name") == alias[0]["pl_name"]]
                entry["archive_name"] = alias[0]["pl_name"]
                entry["matched_by"] = "orbital period"
        if sets and sets[0]["pl_name"] != name:
            entry.setdefault("archive_name", sets[0]["pl_name"])
        chosen = next((a for a in sets if _same_reference(a.get("pl_refname", ""), reference)), None)
        entry["archive_references"] = sorted({_strip_html(a.get("pl_refname")) for a in sets})
        if chosen is None:
            entry["status"] = "no archive parameter set for this reference" if sets else "planet not in the archive"
            report.append(entry)
            continue
        entry["status"] = "compared"
        entry["default_flag"] = chosen.get("default_flag")
        matches, differs, missing, elsewhere, minor, via_mode = [], [], [], {}, [], {}
        for column, archived in chosen.items():
            if column in SKIP or column.endswith(("str", "reflink")) or archived in ("", None):
                continue
            ref_col = next((c for prefix, c in REFERENCE_OF.items() if column.startswith(prefix)), None)
            if ref_col and chosen.get(ref_col) and not _same_reference(chosen[ref_col], reference):
                elsewhere.setdefault(_strip_html(chosen[ref_col]), []).append(column)
                continue
            values = recorded_values(rec, column)        # the value, then each posterior mode's
            base = _base_column(column)
            if base != column and base in via_mode:      # errors / limit of the estimate the value matched
                values = [x for x in values if x[0] == via_mode[base]] or values
            if not values:
                if column.startswith(("pl_", "st_")) and not column.endswith("lim"):
                    missing.append(column)
                continue
            hit = next((label for label, value in values if _matches(value, archived, column)), None)
            if hit is not None:
                matches.append(column)
                if hit:
                    via_mode[column] = hit
                continue
            extracted = values[0][1]
            item = {"column": column, "extracted": extracted, "archive": _number(archived) or _strip_html(archived)}
            why = _minor(column, extracted, archived)
            if why:
                minor.append(dict(item, why=why))
            else:
                differs.append(item)
        entry.update(matches=matches, differs=differs, not_extracted=missing, from_other_references=elsewhere)
        if minor:
            entry["minor"] = minor
        if via_mode:
            entry["matched_mode"] = via_mode
        report.append(entry)
    _mark_archive_solution(report)
    return report


# names of things, where the paper's and the archive's wording can differ for the same thing
# ('1.88 m reflector' / '1.88 m Telescope'): the paper's is kept and it isn't a difference
NAME_COLUMNS = ("disc_facility", "disc_telescope", "disc_instrument", "disc_locale", "pl_tsystemref")
UNCERTAINTY_MINOR = 0.2           # uncertainties within 20% of each other: the paper's is kept
_STOP = {"the", "and", "of", "for", "telescope", "observatory", "spectrograph", "m"}


def _base_column(column: str) -> str:
    return column[:-4] if column.endswith(("err1", "err2")) else column[:-3] if column.endswith("lim") else column


def recorded_values(rec: dict, column: str) -> List[tuple]:
    """[(label, value)] for an archive column: the row's own value ('' label), then the
    matching value of each posterior mode (<col>mode<N>, <col>mode<N>err1, ...) and of each
    other method's estimate (<col>alt<N>, <col>alt<N>err1, <col>alt<N>lim, ...)."""
    out = []
    if rec.get(column) not in (None, ""):
        out.append(("", rec[column]))
    base, suffix = ((column[:-4], column[-4:]) if column.endswith(("err1", "err2")) else
                    (column[:-3], "lim") if column.endswith("lim") else (column, ""))
    for n in range(1, 10):
        value = rec.get(f"{base}mode{n}{suffix}")
        if value not in (None, ""):
            out.append((f"mode {n}: {rec.get(f'{base}mode{n}desc') or ''}".strip(" :"), value))
    for n in range(1, 10):                       # other methods' estimates
        value = rec.get(f"{base}alt{n}{suffix}")
        if value not in (None, ""):
            out.append((f"other estimate {n}: {rec.get(f'{base}alt{n}method') or ''}".strip(" :"), value))
    return out


def _minor(column: str, extracted, archived) -> str:
    """Why a difference is minor (the paper's value kept), or ''."""
    a, b = _number(extracted), _number(archived)
    if a is not None and b is not None:
        if column.endswith(("err1", "err2")) and abs(a - b) <= UNCERTAINTY_MINOR * max(abs(a), abs(b)):
            return "uncertainty within 20% of the archive's"
        return ""
    if column in NAME_COLUMNS:
        words = lambda t: {w for w in re.findall(r"[a-z0-9.]+", _strip_html(t).lower()) if w not in _STOP}
        if words(extracted) & words(archived):
            return "same thing, worded differently"
    return ""


def _mark_archive_solution(report: List[dict]) -> None:
    """A planet with several solution rows (RV-only fit, joint fit, ...) is compared row by row
    with the archive's ONE parameter set for the paper: the row agreeing best is the solution the
    archive took; the others get `archive_solution` naming it (their differences are expected)."""
    by_planet: Dict[str, List[dict]] = {}
    for e in report:
        if e["status"] == "compared" and e.get("solution"):
            by_planet.setdefault(e["pl_name"], []).append(e)
    for entries in by_planet.values():
        if len(entries) < 2:
            continue
        best = min(entries, key=lambda e: (len(e["differs"]), -len(e["matches"])))
        for e in entries:
            if e is not best:
                e["archive_solution"] = best["solution"]


def check(records: List[dict], reference: str, run_dir, fetch: Optional[Callable] = None) -> dict:
    """Fetch (or reuse run_dir/archive_rows.json), compare, write archive_validation.json.
    Returns {"report": [...], "error": "..."}."""
    from pathlib import Path
    run_dir = Path(run_dir)
    saved = run_dir / "archive_rows.json"
    names = [r["pl_name"] for r in records if r.get("pl_name")]
    if not names:
        return {"report": [], "error": "no planet names to look up"}
    try:
        if saved.is_file():
            archive_rows = json.loads(saved.read_text())
        else:
            archive_rows = (fetch or fetch_parameter_sets)(names, reference)
            saved.write_text(json.dumps(archive_rows, indent=1))
    except Exception as e:                     # network, HTTP, parsing: never fail the run
        return {"report": [], "error": f"the NASA Exoplanet Archive couldn't be reached ({type(e).__name__}: {e})"}
    report = compare(records, archive_rows, reference)
    (run_dir / "archive_validation.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return {"report": report, "error": ""}
