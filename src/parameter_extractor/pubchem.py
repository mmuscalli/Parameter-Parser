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
from typing import Dict, Optional

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
MIN_INTERVAL_SEC = 0.25
TIMEOUT_SEC = 10
SPECIES_CIDS = Path(__file__).resolve().parent / "schemas" / "species_cids.json"


@dataclass(frozen=True)
class Compound:
    cid: int
    title: str = ""
    formula: str = ""

    @property
    def url(self) -> str:
        return f"https://pubchem.ncbi.nlm.nih.gov/compound/{self.cid}"


def query_name(name: str) -> str:
    """The form of a name to send: the model sometimes writes names like column
    names ("ribose_1,2-cyclic_phosphate")."""
    return " ".join(name.replace("_", " ").split())


def _cache_key(name: str) -> str:
    return query_name(name).lower()


def template_species_cids() -> Dict[int, str]:
    """CID -> template species name, for the template species whose identity
    was confirmed (schemas/species_cids.json, built by scripts/build_species_cids.py)."""
    if not SPECIES_CIDS.is_file():
        return {}
    from parameter_extractor.names import match_species
    data = json.loads(SPECIES_CIDS.read_text())
    # in the app's naming (the template's DKP_Gly is cyclo_Gly-Gly)
    return {int(v["cid"]): (match_species(name) or (name,))[0] for name, v in data["species"].items()}


class PubChem:
    def __init__(self, cache_path: Optional[Path] = None, fetch=None):
        """`fetch(name) -> Optional[Compound]` replaces the network call (tests)."""
        self.cache_path = Path(cache_path) if cache_path else None
        self._fetch = fetch or self._fetch_online
        self.unavailable_reason: str = ""
        self._last_call = 0.0
        self._cache: Dict[str, Optional[dict]] = {}
        self._dirty = False
        if self.cache_path and self.cache_path.is_file():
            try:
                self._cache = json.loads(self.cache_path.read_text()).get("names", {})
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
        self.cache_path.write_text(json.dumps({"names": self._cache}, indent=1, sort_keys=True))
        self._dirty = False
