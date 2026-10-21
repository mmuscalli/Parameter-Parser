"""
Offline tests for the exoplanet pack: reading sideways (landscape) table pages,
units as printed (rad, JD-2450000, L_sun -> log), the archive's derived
columns (Earth-unit masses, best mass, reference names), and the comparison
with the NASA Exoplanet Archive -- using Mickey's archive export of 11 Com b
(the Teng et al. 2023 parameter set) instead of the network. No API calls.

Run with: python tests/test_exoplanets.py
"""
import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs
from parameter_extractor.calculators import exoplanets as exo
from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.schemas.row_schema import ExtractedRow
from parameter_extractor.units import convert_printed
from parameter_extractor.validation import exoplanet_archive as archive

TENG = ROOT.parent / "Paper Files" / "Paper Lists" / "Teng2023"
PDF, EXPORT = TENG / "teng2023.pdf", TENG / "PS_2026.10.20_17.17.08.csv"


def _row(values: dict) -> ExtractedRow:
    row = ExtractedRow(full_id="001001001", set_id="001001", sample_id="001", set_type="Independent",
                       entry_number=1, paper_title="t", authors=[], year_published=2023,
                       journal_published="j", experiment_type="", solution_type="")
    for k, v in values.items():
        set_row_value(row, k, v)
    return row


def test_pack_and_template():
    pack = packs.activate("exoplanets")
    try:
        assert len(pack.template_columns) == 288 and pack.template_columns[:3] == ["pl_name", "hostname", "pl_letter"]
        assert not pack.uses("chemistry") and pack.uses("archive_validation") and pack.manifest.compact_text
        from parameter_extractor.stages.optional import load_specs
        specs = load_specs()
        assert list(specs) == ["planet_parameters", "stellar_parameters", "system_and_discovery"]
        planet = specs["planet_parameters"]
        assert planet.per == "sample" and "pl_orbpererr1" in planet.output_columns()
        import re
        is_mode = lambda c: re.search(r"(modal_flag|mode\d(err[12]|desc)?|alt\d(err[12]|lim|method)?)$", c)
        assert all(c in pack.template_columns for s in specs.values() for c in s.output_columns() if not is_mode(c))
        from parameter_extractor.registry import standard_columns
        modes = [c for s in specs.values() for c in s.output_columns() if is_mode(c)]
        assert "pl_orbinclmode2err1" in modes and "pl_orbinclmodal_flag" in modes and set(modes) <= set(standard_columns())
        Item, _ = planet.models()
        assert {"err_plus", "err_minus", "limit", "text", "unit", "sample_label"} <= set(Item.model_fields)
    finally:
        packs.activate("prebiotic_chemistry")


def test_units_as_printed():
    assert convert_printed(1.594, "rad", "deg")[0] == 91.32947254
    assert convert_printed(4519.4, "JD-2450000", "JD")[0] == 2454519.4
    assert convert_printed(1.5, "BJD - 2,450,000", "JD", is_error=True)[0] == 1.5      # errors aren't shifted
    assert abs(convert_printed(95.06, "L_sun", "log(L_sun)")[0] - 1.978) < 1e-3
    assert convert_printed(30, "min", "h")[0] == 0.5 and convert_printed(2.4, "km/s", "m/s")[0] == 2400
    assert convert_printed(1, "furlong", "au")[0] is None


def test_derived_columns_and_reference():
    packs.activate("exoplanets")
    try:
        row = _row({"pl_msinij": 15.464, "pl_msinijerr1": 0.123, "pl_msinijerr2": -0.125, "pl_msinijlim": 0,
                    "pl_radj": 1.0, "st_teff": 4874})
        exo.exoplanet_masses([row])
        d = row_to_template_dict(row)
        assert abs(d["pl_msinie"] - 4914.898) < 0.01 and abs(d["pl_msinieerr2"] + 39.73) < 0.01
        assert d["pl_bmassj"] == 15.464 and d["pl_bmassprov"] == "Msini" and d["pl_bmassjerr1"] == 0.123
        assert d["pl_rade"] == 11.2089 and row.provenance["pl_msinie"].origin == "calculated"
        true_mass = _row({"pl_msinij": 15.0, "pl_massj": 16.0})
        exo.exoplanet_masses([true_mass])
        assert row_to_template_dict(true_mass)["pl_bmassprov"] == "Mass"
        authors = ["Huan-Yu Teng", "Bun'ei Sato", "Masayuki Kuzuhara"]
        assert exo.reference_name(authors, 2023) == "Teng et al. 2023"
        assert exo.reference_name(["Y.-J. Liu", "Bun'ei Sato"], 2008) == "Liu & Sato 2008"
        assert exo.reference_name(["TENG, H.-Y."], 2023) == "Teng 2023"
        from types import SimpleNamespace
        exo.reference_names([row], SimpleNamespace(authors=authors, year_published=2023))
        d = row_to_template_dict(row)
        assert d["pl_refname"] == d["st_refname"] == "Teng et al. 2023" and not d.get("disc_refname")
    finally:
        packs.activate("prebiotic_chemistry")


def test_compared_with_the_archive_export():
    if not EXPORT.is_file():
        print(f"SKIP: needs {EXPORT}"); return
    lines = [l for l in EXPORT.read_text().splitlines() if not l.startswith("#")]
    archive_rows = list(csv.DictReader(lines))                      # 11 Com b, Teng et al. 2023 set
    extracted = {"pl_name": "11 Com b", "pl_orbper": 323.21, "pl_orbpererr1": 0.06, "pl_orbpererr2": -0.05,
                 "pl_rvamp": 288.63, "pl_orbeccen": 0.238, "pl_msinij": 15.464, "pl_orblper": 91.32947254,
                 "pl_orbtper": 2454519.4, "st_teff": 4900, "st_spectype": "G8 III"}
    report = archive.compare([extracted], archive_rows, "Teng et al. 2023")[0]
    assert report["status"] == "compared"
    assert {"pl_orbper", "pl_rvamp", "pl_orbeccen", "pl_msinij", "pl_orblper", "pl_orbtper", "st_spectype",
            "pl_orbpererr1", "pl_orbpererr2"} <= set(report["matches"])
    assert [d["column"] for d in report["differs"]] == ["st_teff"]          # 4900 vs 4874
    assert "st_mass" in report["not_extracted"]
    other = archive.compare([extracted], archive_rows, "Liu et al. 2008")[0]
    assert other["status"] == "no archive parameter set for this reference"
    assert other["archive_references"] == ["Teng et al. 2023"]
    with tempfile.TemporaryDirectory() as tmp:                          # fetched once, kept for replays
        calls = []
        out = archive.check([extracted], "Teng et al. 2023", tmp, fetch=lambda n, r: calls.append(n) or archive_rows)
        again = archive.check([extracted], "Teng et al. 2023", tmp, fetch=lambda n, r: calls.append(n) or [])
        assert out["report"] == again["report"] and len(calls) == 1
        down = archive.check([extracted], "Teng et al. 2023", Path(tmp) / "x",
                             fetch=lambda n, r: (_ for _ in ()).throw(OSError("offline")))
        assert "couldn't be reached" in down["error"]


def test_archive_names_angles_and_padding():
    assert archive.archive_name("ε  Tau b") == "eps Tau b" and archive.archive_name("o UMa b") == "omi UMa b"
    assert archive.archive_name("ν Oph c") == "nu Oph c" and archive.archive_name("HD 5608 b") == "HD 5608 b"
    assert archive._key("hd 5608 b") == archive._key("HD 5608 b") != archive._key("HD 5608 B")
    assert archive._matches(1.718873385, "1.7000") and not archive._matches(1.76, "1.7000")   # zero padding
    assert archive._matches(-12.0, "348.0", "pl_orblper") and not archive._matches(-12.0, "348.0")
    rows = [{"pl_name": "HD 81688 b", "pl_refname": "Teng et al. 2023", "pl_orbper": "183.93", "pl_rvamp": "51.3",
             "st_teff": "4789", "st_refname": "Teng et al. 2023", "sy_plx": "11.6", "sy_refname": "TICv8"}]
    e = archive.compare([{"pl_name": "41 Lyn b", "pl_orbper": 184.0, "pl_rvamp": 51.3, "st_teff": 4790,
                          "sy_plx": 11.0}], rows, "Teng et al. 2023")[0]
    assert (e["archive_name"], e["matched_by"], e["status"]) == ("HD 81688 b", "orbital period", "compared")
    assert set(e["matches"]) == {"pl_orbper", "pl_rvamp", "st_teff"} and not e["differs"]
    assert e["from_other_references"] == {"TICv8": ["sy_plx"]}


def test_posterior_modes():
    """Every value the paper records: the overall one, and one per mode of a bimodal posterior."""
    from types import SimpleNamespace
    from parameter_extractor.stages.optional import optional_values
    packs.activate("exoplanets")
    try:
        from parameter_extractor.stages.optional import load_specs
        spec = load_specs()["planet_parameters"]
        Item, Result = spec.models()
        assert "mode" in Item.model_fields and spec.table_images
        item = lambda value, plus, minus, mode: Item.model_validate(dict(
            set_label="HD 14067", sample_label="HD 14067 b", parameter="pl_orbincl", value=value, unit="deg",
            err_plus=plus, err_minus=minus, mode=mode, basis="stated", quote=str(value), source="Table 4",
            confidence="high"))
        conflicts = []
        out = optional_values(spec, Result(parameters=[item(118, 31, -84, ""), item(39, 28, -13, "i < 90 deg"),
                                                       item(141, 12, -23, "i > 90 deg")]),
                              SimpleNamespace(experiment_sets=[]), [], conflicts)
        cols = {k[2]: v.value for k, v in out.items()}
        assert not conflicts and cols["pl_orbincl"] == 118 and cols["pl_orbinclerr2"] == -84
        assert cols["pl_orbinclmodal_flag"] == 1
        assert (cols["pl_orbinclmode1"], cols["pl_orbinclmode1err1"], cols["pl_orbinclmode1desc"]) == (39, 28, "i < 90 deg")
        assert (cols["pl_orbinclmode2"], cols["pl_orbinclmode2desc"]) == (141, "i > 90 deg")
        # the archive took the prograde mode: a match on any recorded value is a match
        rec = {"pl_name": "HD 14067 b", **cols}
        rows = [{"pl_name": "HD 14067 b", "pl_refname": "Teng et al. 2023", "pl_orbincl": "39.0",
                 "pl_orbinclerr1": "28.0", "pl_orbinclerr2": "-13.0", "disc_telescope": "1.88 m Telescope",
                 "disc_instrument": "HIDES Echelle Spectrograph", "st_masserr1": "0.28", "st_mass": "2.16"}]
        e = archive.compare([dict(rec, disc_telescope="1.88 m reflector", disc_instrument="HIDES",
                                  st_masserr1=0.31, st_mass=2.16)], rows, "Teng et al. 2023")[0]
        assert {"pl_orbincl", "pl_orbinclerr1", "pl_orbinclerr2"} <= set(e["matches"]) and not e["differs"]
        assert e["matched_mode"]["pl_orbincl"] == "mode 1: i < 90 deg"
        assert sorted(m["column"] for m in e["minor"]) == ["disc_instrument", "disc_telescope", "st_masserr1"]
        far = archive.compare([dict(rec, st_masserr1=0.5, disc_telescope="Subaru", st_mass=2.16)], rows,
                              "Teng et al. 2023")[0]
        assert sorted(d["column"] for d in far["differs"]) == ["disc_telescope", "st_masserr1"]
    finally:
        packs.activate("prebiotic_chemistry")


def test_estimates_by_other_methods():
    """The paper's adopted value in <col>, other methods' estimates in <col>alt<N> (aa57186-25: a
    rotation period > 13 d from v sin i, 22 +- 3 d from an activity relation, 49 d from a GP)."""
    from types import SimpleNamespace
    from parameter_extractor.stages.optional import load_specs, optional_values
    from parameter_extractor.pipeline import _estimate
    packs.activate("exoplanets")
    try:
        spec = load_specs()["stellar_parameters"]
        assert spec.alternatives and "st_rotpalt3method" in spec.output_columns()
        Item, Result = spec.models()
        mk = lambda value, plus, minus, limit, method: Item.model_validate(dict(
            set_label="TOI-3862", sample_label="", parameter="st_rotp", value=value, unit="d", err_plus=plus,
            err_minus=minus, limit=limit, method=method, basis="stated", quote=str(value), source="Sect. 3",
            confidence="high"))
        conflicts = []
        out = optional_values(spec, Result(parameters=[
            mk(22, 3, -3, "", ""), mk(13, 0, 0, "lower", "v sin i limit"), mk(49, 38, -32, "", "GP fit"),
            mk(22, 3, -3, "", "activity relation")]), SimpleNamespace(experiment_sets=[]), [], conflicts)
        cols = {k[2]: v.value for k, v in out.items()}
        assert not conflicts and (cols["st_rotp"], cols["st_rotperr1"]) == (22, 3)
        assert (cols["st_rotpalt1"], cols["st_rotpalt1lim"], cols["st_rotpalt1method"]) == (13, -1, "v sin i limit")
        assert (cols["st_rotpalt2"], cols["st_rotpalt2method"]) == (49, "GP fit") and "st_rotpalt3" not in cols
        assert _estimate(out, "TOI-3862", "", "st_rotpalt1") == "> 13"
        assert _estimate(out, "TOI-3862", "", "st_rotp") == "22 +3/-3"
        # the archive lists the v sin i limit: matched through the other estimate
        rows = [{"pl_name": "TOI-3862 b", "pl_refname": "Carleo et al. 2026", "st_refname": "Carleo et al. 2026",
                 "st_rotp": "13.00000", "st_rotplim": "-1"}]
        e = archive.compare([{"pl_name": "TOI-3862 b", **cols}], rows, "Carleo et al. 2026")[0]
        assert "st_rotp" in e["matches"] and e["matched_mode"]["st_rotp"] == "other estimate 1: v sin i limit"
        assert "st_rotplim" in e["matches"]          # the limit flag of the estimate that matched, not the adopted
        rows[0]["st_rotplim"] = "1"
        e = archive.compare([{"pl_name": "TOI-3862 b", **cols}], rows, "Carleo et al. 2026")[0]
        assert e["differs"] == [{"column": "st_rotplim", "extracted": -1, "archive": 1.0}]
    finally:
        packs.activate("prebiotic_chemistry")


def test_two_values_for_one_parameter():
    from types import SimpleNamespace
    from parameter_extractor.stages.optional import load_specs, optional_values
    packs.activate("exoplanets")
    try:
        spec = load_specs()["planet_parameters"]
        Item, Result = spec.models()
        item = lambda value, unit, plus, minus, src: Item.model_validate(dict(
            set_label="HD 14067", sample_label="HD 14067 b", parameter="pl_orbper", value=value, unit=unit,
            err_plus=plus, err_minus=minus, basis="stated", quote=str(value), source=src, confidence="high"))
        structure = SimpleNamespace(experiment_sets=[])
        conflicts = []
        out = optional_values(spec, Result(parameters=[item(2725.81, "d", 0, 0, "Table 3"),
                                                       item(7.513, "yr", 0.044, -0.038, "Table 4")]),
                              structure, [], conflicts)
        cols = {k[2]: v.value for k, v in out.items()}
        assert cols["pl_orbper"] == 2725.81 and "pl_orbpererr1" not in cols    # never Table 4's error bars
        assert len(conflicts) == 1 and "Table 4" in conflicts[0].message
        conflicts = []
        out = optional_values(spec, Result(parameters=[item(323.21, "d", 0, 0, "Table 3"),
                                                       item(323.2, "d", 0.06, -0.05, "text")]), structure, [], conflicts)
        assert not conflicts and {k[2] for k in out} >= {"pl_orbper", "pl_orbpererr1"}   # same value: errors added
    finally:
        packs.activate("prebiotic_chemistry")


def test_heavy_companions_are_flagged():
    rows = [_row({"pl_name": "HD 5608 B", "pl_bmassj": 121.2}), _row({"pl_name": "11 Com b", "pl_bmassj": 15.464})]
    msgs = exo.companion_masses(rows)
    assert len(msgs) == 1 and msgs[0].startswith("HD 5608 B") and "low-mass star" in msgs[0]


def test_sideways_tables_are_read_upright():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    p = parse_pdf(str(PDF))
    assert p.page_rotations == {5: 90, 9: 90}
    assert p.table_pages[5][0].startswith("Table 1. Stellar parameters")
    assert p.table_pages[9][0].startswith("Table 3. Orbital parameters")


def test_dense_table_pages_are_cut_into_readable_pieces():
    """A table page bigger than the API reads unscaled is cropped and cut at white space; a
    piece continuing to the right repeats the row labels."""
    from PIL import Image, ImageDraw
    from parameter_extractor.ingestion.table_tiles import MAX_SIDE, TOLERANCE, tile
    from parameter_extractor.api_client import _piece_label
    small = Image.new("RGB", (1200, 900), "white")
    ImageDraw.Draw(small).text((100, 100), "Table 1", fill="black")
    assert len(tile(small)) == 1 and tile(small)[0].size[0] < 300                  # cropped to the content
    wide = Image.new("RGB", (3000, 1200), "white")
    d = ImageDraw.Draw(wide)
    for row in range(20):
        d.rectangle((20, 40 + row * 50, 220, 60 + row * 50), fill="black")          # row labels
        for col in range(10):
            x = 400 + col * 250
            d.rectangle((x, 40 + row * 50, x + 150, 60 + row * 50), fill="black")
    pieces = tile(wide)
    assert len(pieces) == 2 and all(max(p.size) <= MAX_SIDE * TOLERANCE for p in pieces)
    import numpy as np
    assert (np.asarray(pieces[1].convert("L"))[:, 15:200] < 128).any()           # labels repeated on the left
    assert _piece_label(Path("page-9-2of2.jpg")).startswith("Page 9, piece 2 of 2")
    assert _piece_label(Path("page-9.jpg")) == ""
    if not PDF.is_file():
        print(f"SKIP (teng part): needs {PDF}"); return
    from parameter_extractor.ingestion.pdf_parser import rasterize_pages
    with tempfile.TemporaryDirectory() as tmp:
        images = rasterize_pages(str(PDF), [9], Path(tmp), rotations={9: 90})
        assert [p.name for p in images[9]] == ["page-9-1of2.jpg", "page-9-2of2.jpg"]
        sizes = [Image.open(p).size for p in images[9]]
        assert all(max(sz) <= MAX_SIDE * TOLERANCE for sz in sizes), sizes


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All exoplanet tests passed.")
