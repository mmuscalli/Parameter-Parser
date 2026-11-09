"""
Chemical identity lookup on PubChem (PUG REST,
https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest): name -> CID, title, formula.

Used to recognise that two different names are the same compound -- "2'-CMP",
"cytidine 2'-monophosphate" and "2'-cytidylic acid" all resolve to CID 101544
-- so a species lands in the column already used for it, whatever the paper
calls it. names.py's deterministic rules run first (offline, and they know
the template's own conventions); PubChem is the fallback for everything else.

- Only exact CID equality is ever used to map a name. PubChem distinguishes
  charge/protonation states and hydrates (UMP vs UMP2-), so the template's
  distinctions survive. A name PubChem doesn't know (e.g. "ribose
  1,2-cyclic phosphate") is simply left as it is.
- Results, including "not found", are cached on disk (app data folder), so a
  name is looked up once per machine.
- Fails soft: no network or a PubChem outage turns lookups off for the rest
  of the run (one note), never fails the extraction.
- Only species names are sent -- nothing else from the paper.
PubChem asks for at most 5 requests/second; we stay under that.
"""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
import re
from typing import Dict, List, Optional

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
MIN_INTERVAL_SEC = 0.25
TIMEOUT_SEC = 10


@dataclass(frozen=True)
class Compound:
    cid: int
    title: str = ""
    formula: str = ""

    @property
    def url(self) -> str:
        return f"https://pubchem.ncbi.nlm.nih.gov/compound/{self.cid}"


# PubChem's name search mishandles Greek letters: 'α-aminobutyric acid' -> GABA (gamma!), 'β-alanine' / 'α-ketoglutarate'
# -> nothing; spelled out, all are found (organics test set, 2026-11-09)
GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ω": "omega", "κ": "kappa",
         "λ": "lambda", "μ": "mu", "σ": "sigma", "Α": "alpha", "Β": "beta", "Γ": "gamma", "Δ": "delta", "Ω": "omega"}


def query_name(name: str) -> str:
    """The form of a name to send: the model sometimes writes names like column
    names ("ribose_1,2-cyclic_phosphate"); Greek letters spelled out."""
    name = "".join(GREEK.get(ch, ch) for ch in name)
    return " ".join(name.replace("_", " ").split())


def _cache_key(name: str) -> str:
    return query_name(name).lower()


def template_species_cids() -> Dict[int, str]:
    """CID -> template species name, for the template species whose identity
    was confirmed (the active pack's species_cids.json, built by scripts/build_species_cids.py)."""
    from parameter_extractor.packs import current
    path = current().species_cids_path
    if path is None or not path.is_file():
        return {}
    from parameter_extractor.names import match_species
    data = json.loads(path.read_text())
    # in the app's naming (the template's DKP_Gly is cyclo_Gly-Gly)
    return {int(v["cid"]): (match_species(name) or (name,))[0] for name, v in data["species"].items()}


# synonyms worth offering as a column name: not registry numbers or database codes (Mickey, 2026-11-03)
_CODE = re.compile(r"^\d+-\d+-\d$|^(UNII|EINECS|CHEBI|CHEMBL|DTXSID|DTXCID|NSC|SCHEMBL|MFCD|AKOS|ZINC|HSDB|BRN|"
                   r"AI3|EC|CAS|InChI|SMR|MLS|HMS|BDBM|NCGC|CCRIS|FEMA|RTECS|KS|AC|AS|BP|CS|SY|DB|HY|Q|D)"
                   r"[-: ]?\w*\d", re.IGNORECASE)
MAX_SYNONYMS = 25


def useful_synonyms(names, limit: int = MAX_SYNONYMS) -> List[str]:
    """PubChem's synonyms, best first, without registry numbers, database codes and very long systematic names;
    case-insensitive duplicates dropped."""
    out, seen = [], set()
    for n in names or []:
        n = " ".join(str(n).split())
        if (not n or len(n) > 50 or _CODE.match(n) or re.fullmatch(r"[\d\W]+", n) or n.lower() in seen
                or re.fullmatch(r"[A-Z0-9]{8,12}", n) and re.search(r"\d", n)      # UNII-style codes
                or re.match(r"\w+:\w", n) or re.fullmatch(r"[A-Z]{14}-[A-Z]{10}-[A-Z]", n)):  # prefixes, InChIKeys
            continue
        seen.add(n.lower())
        out.append(n)
        if len(out) >= limit:
            break
    return out


class PubChem:
    def __init__(self, cache_path: Optional[Path] = None, fetch=None):
        """`fetch(name) -> Optional[Compound]` replaces the network call (tests)."""
        self.cache_path = Path(cache_path) if cache_path else None
        self._fetch = fetch or self._fetch_online
        self.unavailable_reason: str = ""
        self._last_call = 0.0
        self._cache: Dict[str, Optional[dict]] = {}
        self._synonyms: Dict[str, List[str]] = {}       # CID -> useful synonyms (also cached on disk)
        self._dirty = False
        if self.cache_path and self.cache_path.is_file():
            try:
                data = json.loads(self.cache_path.read_text())
                self._cache = data.get("names", {})
                self._synonyms = data.get("synonyms", {})
            except (OSError, ValueError):
                self._cache = {}

    def lookup(self, name: str) -> Optional[Compound]:
        key = _cache_key(name)
        if not key:
            return None
        if key in self._cache:
            hit = self._cache[key]
            return Compound(**{k: hit[k] for k in ("cid", "title", "formula")}) if hit else None
        if self.unavailable_reason:
            return None
        try:
            found = self._fetch(query_name(name))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            self.unavailable_reason = f"PubChem could not be reached ({getattr(e, 'reason', e)})"
            return None
        self._cache[key] = dict(asdict(found), checked=date.today().isoformat()) if found else None
        self._dirty = True
        return found

    def lookup_checked(self, name: str) -> Optional[Compound]:
        """`lookup`, but a CODE ('ImpA', 'RCP', 'p2A' -- compound_setup.is_abbreviation) counts only when PubChem lists it
        among the compound's names: PubChem's first hit for a code is often another compound (ImpA -> isopropyl
        methylphosphonate). Used by every path that identifies compounds (normalize_chemistry, Find compounds)."""
        found = self.lookup(name)
        if found is None:
            return None
        from parameter_extractor.compound_setup import is_abbreviation
        if is_abbreviation(name.strip()) and name.strip() != found.title and name.strip() not in self.synonyms(found.cid):
            return None
        return found

    def synonyms(self, cid: int) -> List[str]:
        """A compound's names on PubChem (useful_synonyms); [] when unknown or PubChem can't be reached."""
        key = str(int(cid))
        if key in self._synonyms:
            return list(self._synonyms[key])
        if self.unavailable_reason or not cid:
            return []
        wait = MIN_INTERVAL_SEC - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()
        req = urllib.request.Request(f"{BASE}/compound/cid/{key}/synonyms/JSON", headers={"User-Agent": "ParameterExtractor"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                info = json.load(resp)["InformationList"]["Information"][0]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                self.unavailable_reason = f"PubChem could not be reached ({e})"
                return []
            info = {}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as e:
            self.unavailable_reason = f"PubChem could not be reached ({getattr(e, 'reason', e)})"
            return []
        found = useful_synonyms(info.get("Synonym", []))
        self._synonyms[key] = found
        self._dirty = True
        return list(found)

    def _fetch_online(self, name: str) -> Optional[Compound]:
        wait = MIN_INTERVAL_SEC - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()
        # POST, so names with '/' or other URL-unsafe characters work
        data = urllib.parse.urlencode({"name": name}).encode()
        req = urllib.request.Request(f"{BASE}/compound/name/property/Title,MolecularFormula/JSON", data=data,
                                     headers={"User-Agent": "ParameterExtractor"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                props = json.load(resp)["PropertyTable"]["Properties"]
        except urllib.error.HTTPError as e:
            if e.code == 404:                  # PUGREST.NotFound: no compound by that name
                return None
            raise
        if not props:
            return None
        first = props[0]          # PubChem lists the best match first
        return Compound(cid=int(first["CID"]), title=first.get("Title", ""),
                        formula=first.get("MolecularFormula", ""))

    def save(self) -> None:
        if not (self.cache_path and self._dirty):
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({"names": self._cache, "synonyms": self._synonyms}, indent=1,
                                              sort_keys=True))
        self._dirty = False
