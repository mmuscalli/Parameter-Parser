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
# the archive's own bookkeeping, not values a paper reports: counts of the archive's holdings, its
# controversy flag, the reference's publication month -- never counted as "not extracted"
ARCHIVE_ONLY = {"pl_controv_flag", "pl_pubdate", "releasedate", "rowupdate", "pl_nnotes", "pl_nespec",
                "pl_ntranspec", "pl_ndispec", "st_nphot", "st_nrvc", "st_nspec", "sy_pnum", "sy_snum",
                "sy_mnum", "default_flag", "soltype"}
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


def papers_planets(records: List[dict], archive_rows: List[dict], reference: str) -> List[dict]:
    """The archive's parameter sets from this paper for planets the rows don't name (filed under another name)."""
    named = {_key(r.get("pl_name")) for r in records if r.get("pl_name")}
    return [a for a in archive_rows if _same_reference(a.get("pl_refname", ""), reference)
            and _key(a.get("pl_name")) not in named]


def planet_sets(rec: dict, archive_rows: List[dict], from_paper: List[dict]):
    """(the archive's parameter sets of the row's planet, found by its orbital period): by name; else -- a planet the
    archive files under another name -- the one of this paper's planets with the same period (within 1%)."""
    name = rec.get("pl_name")
    sets = [a for a in archive_rows if _key(a.get("pl_name")) == _key(name)] if name else []
    period = _number(rec.get("pl_orbper"))
    if not sets and period:
        alias = [a for a in from_paper if _number(a.get("pl_orbper"))
                 and abs(_number(a["pl_orbper"]) - period) <= PERIOD_MATCH * period]
        if len(alias) == 1:
            return [a for a in archive_rows if a.get("pl_name") == alias[0]["pl_name"]], True
    return sets, False


def compare(records: List[dict], archive_rows: List[dict], reference: str) -> List[dict]:
    """Per extracted row: which archive parameter set it was compared with, and each
    column's outcome (match / differs / not extracted)."""
    report = []
    from_paper = papers_planets(records, archive_rows, reference)      # this paper's planets under other names
    for rec in records:
        name = rec.get("pl_name")
        if not name:
            continue
        entry = {"pl_name": name, "reference": reference}
        if rec.get("pl_fitlabel"):                      # one row per solution: each is compared
            entry["solution"] = rec["pl_fitlabel"]
        sets, by_period = planet_sets(rec, archive_rows, from_paper)
        if by_period:
            entry["archive_name"] = sets[0]["pl_name"]
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
                if base != column and _number(archived) == 0 and recorded_values(rec, base):
                    matches.append(column)          # '+0.000/-0.000' printed: a zero uncertainty isn't written
                elif (column.startswith(("pl_", "st_")) and not column.endswith("lim")
                      and column not in ARCHIVE_ONLY):
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
                # what the archive's set has but the adopted solution's row doesn't, and this row gives
                # (teng2023: K and M sin i are in the RV-only fit's row, not the joint fit's)
                given = set(e["matches"]) | {d["column"] for d in e["differs"]}
                moved = [c for c in best["not_extracted"] if c in given]
                if moved:
                    best["not_extracted"] = [c for c in best["not_extracted"] if c not in moved]
                    best.setdefault("in_other_solution", {})[e["solution"]] = moved


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
    return {"report": report, "error": "", "rows": archive_rows}


# ---- catalogue facts filled from the archive (calculation 'archive_values'; Mickey, 2026-11-19) ---------------------
# What the archive knows about a planet and its star that papers seldom state and no step asks for: catalogue names,
# position, motion and brightness, the detection-method flags, where and when the discovery was published. Fetched
# for the check anyway (archive_rows.json), so filled where a row has none -- marked as the archive's, never the
# paper's. Planet and star parameters are not: those are the paper's to give (and the check's to compare).
FILL_COLUMNS = {"hd_name", "hip_name", "tic_id", "gaia_dr2_id", "gaia_dr3_id", "ra", "rastr", "dec", "decstr",
                "glat", "glon", "elat", "elon", "cb_flag", "disc_pubdate", "disc_locale", "rv_flag", "pul_flag",
                "ptv_flag", "tran_flag", "ast_flag", "obm_flag", "micro_flag", "etv_flag", "ima_flag", "dkin_flag",
                "ttv_flag", "sy_refname"}
_FILL_PATTERN = re.compile(r"^sy_(?:pm|pmra|pmdec|[a-z0-9]+mag)(?:err[12])?$")       # proper motion, magnitudes


def fillable(column: str) -> bool:
    """A column the archive fills when no step does (FILL_COLUMNS, sy_ magnitudes and proper motions)."""
    return column in FILL_COLUMNS or bool(_FILL_PATTERN.match(column))


def source_set(rec: dict, archive_rows: List[dict], reference: str, from_paper: List[dict]) -> Optional[dict]:
    """The parameter set to take a row's catalogue facts from: this paper's, else the archive's default, else any."""
    sets, _ = planet_sets(rec, archive_rows, from_paper)
    return next((a for a in sets if _same_reference(a.get("pl_refname", ""), reference)), None) or \
        next((a for a in sets if str(a.get("default_flag")) == "1"), None) or (sets[0] if sets else None)


def fill_values(records: List[dict], archive_rows: List[dict], reference: str, columns: List[str]) -> List[tuple]:
    """[(row index, column, value, the set's reference)] for each empty cell of `columns` the archive has a value for:
    numbers as numbers, text without its HTML."""
    from_paper = papers_planets(records, archive_rows, reference)
    out = []
    for i, rec in enumerate(records):
        chosen = source_set(rec, archive_rows, reference, from_paper)
        if chosen is None:
            continue
        for column in columns:
            archived = chosen.get(column)
            if rec.get(column) not in (None, "") or archived in (None, ""):
                continue
            number = _number(archived)
            out.append((i, column, number if number is not None and column not in ("hd_name", "hip_name", "tic_id",
                                                                                    "gaia_dr2_id", "gaia_dr3_id")
                        else _strip_html(archived), _strip_html(chosen.get("pl_refname", ""))))
    return out
