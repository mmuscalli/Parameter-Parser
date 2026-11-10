"""
Offline tests for the fixes from the 'Sam Papers' handoff round (2026-11-03; 11 prebiotic RNA / nucleotide papers):
Roman-numeral and Extended Data table captions, citations not taken for captions, full-width tables whose columns
gap at the page middle, publisher stamps left out of the text, a supplier not taken for an abbreviation, 'detected'
kept under a number type, wet-dry sets found by their description, grouped flags, ranges in their own column,
lengths in nt / µm, unprinted years. No API calls.

Run with: python tests/test_sam_papers.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SAM = ROOT.parent / "Paper Files" / "Test Paper List" / "Sam Papers"

import pack_facts as pf  # noqa: E402
from parameter_extractor import packs


def test_table_captions():
    from parameter_extractor.ingestion.data_location import location
    from parameter_extractor.ingestion.pdf_parser import TABLE_CAPTION_RE
    from parameter_extractor.ingestion.table_finder import TABLE_RE, table_name, table_number
    got = {t: (table_number(m) if (m := TABLE_RE.match(t)) else None)
           for t in ("TableI.ImpAand", "TableIV.Oligomer", "TableImpA", "Table2.X", "TableS1.Y", "TableA1.Z",
                     "ExtendedDataTable1|Soret")}
    assert got == {"TableI.ImpAand": ("", 1, "I"), "TableIV.Oligomer": ("", 4, "IV"), "TableImpA": None,
                   "Table2.X": ("", 2, "2"), "TableS1.Y": ("S", 1, "1"), "TableA1.Z": ("A", 1, "1"),
                   "ExtendedDataTable1|Soret": ("ED", 1, "1")}
    assert table_name("ED", "1") == "Extended Data Table 1" and table_name("", "IV") == "Table IV"
    captions = ["Table I. ImpA and 9:1 ImpA", "Table III. Compositions", "Table 2. Results of", "  Table 3 Yields",
                "Extended Data Table 1 | Experimentally determined", "text. Table 2. Concentrations of"]
    citations = ["see Supplementary Table 1. Nucleobases vide", "Table 1) in each individual heat flux chamber",
                 "are shown in Table 1. Dipeptide yields", "presented in Table 2. The logK values"]
    assert all(TABLE_CAPTION_RE.search(c) for c in captions)
    assert not any(TABLE_CAPTION_RE.search(c) for c in citations)
    assert [location(s) for s in ("Table I, ImpA row", "Table IV, dimers", "table i think")] == \
        ["Table. I", "Table. IV", "Text: table i think"]


def test_image_labels():
    from parameter_extractor.api_client import _piece_label
    assert "Page 3, Table IV" in _piece_label(Path("x/page-3-tableIV.jpg"))
    assert "Page 24, Extended Data Table 1" in _piece_label(Path("x/page-24-tableED1.jpg"))


def test_full_width_table_and_stamps():
    """liu2026 Table 1's columns gap at the page middle (only 2 of 6 were cropped); the PNAS / ACS margin stamp
    ('Downloaded from ... by <reader> ... IP address') was read backwards into the text."""
    liu, song = SAM / "Liu et al. - 2026 - Origins of Size-Dependent Kinetics in Microdroplets.pdf", \
        SAM / "Song et al. - 2024 - Wet–dry cycles cause nucleic acid monomers to polymerize into long chains.pdf"
    if not liu.is_file() or not song.is_file():
        print("SKIP: needs the Sam Papers PDFs"); return
    import tempfile
    from PIL import Image
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    from parameter_extractor.ingestion.table_finder import find_tables
    with tempfile.TemporaryDirectory() as tmp:
        t = find_tables(str(liu), [7], Path(tmp))
        assert [x["table_id"] for x in t] == ["Table 1"] and Image.open(t[0]["image"]).size[0] > 1200
    text = parse_pdf(str(song)).text
    assert "Downloaded" not in text and "dedaolnwoD" not in text and "IP address" not in text


def test_abbreviations_and_detected():
    from parameter_extractor.names import abbreviations_in
    from parameter_extractor.value_types import coerce
    text = "200 mM d-ribose (Wako), adenosine 5'-phosphorimidazolide (ImpA) and ribose cyclic phosphate (RCP)"
    assert abbreviations_in(text, ["d-ribose", "adenosine 5'-phosphorimidazolide", "ribose cyclic phosphate"]) == \
        {"adenosine 5'-phosphorimidazolide": "ImpA", "ribose cyclic phosphate": "RCP"}
    assert coerce("detected", "number") == ("detected", "") and coerce("detected", "integer") == ("detected", "")


def test_wet_dry_sets_by_description():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.schemas.structure_plan import PlannedSample, PlannedSet, StructurePlan
    from parameter_extractor.stages.optional import load_specs
    spec = pf.module_step("wet_dry")                         # the Wet-dry module's step
    s = lambda label, varies, kind="Independent": PlannedSet(
        set_label=label, set_type=kind, varying_condition_summary=varies, source_table_or_section="Table 1",
        samples=[PlannedSample(sample_label="G", source="Table 1")])
    plan = StructurePlan(experiment_sets=[s("This work: 5-10 wet-dry cycles", "initial pH 10-11"),
                                          s("Dry phase", "pH 10, 18 h"), s("Rajamani", "5-7 dry−wet cycles, 90 C")],
                         n_rows=3)
    assert spec.triggered(plan) and spec.target_sets(plan) == ["This work: 5-10 wet-dry cycles", "Rajamani"]
    assert not spec.triggered(StructurePlan(experiment_sets=[s("Dry phase", "pH 10")], n_rows=1))


def test_grouped_flags():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.pipeline import _cited_data_flags
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    from parameter_extractor.schemas.structure_plan import PlannedSample, PlannedSet, StructurePlan
    from parameter_extractor.validation.plausibility_checks import check_extraction
    koh = lambda st: SoluteEntry(name="KOH", phase="aq", role="initial", set_label=st, concentration_value=None,
                                 concentration_unit_raw=None, quote="KOH", source="Table 1", confidence="high")
    chem = ChemistryExtraction(solutes=[koh("A"), koh("B"), koh("C")])
    from parameter_extractor.schemas.methodology import empty_methodology
    flags = [f for f in check_extraction(empty_methodology("p"), chem) if f.kind == "concentration_not_stated"]
    assert len(flags) == 1 and "3 sets" in flags[0].message
    ref = "Rout et al. 2025 (ref. 16)"
    sets = [PlannedSet(set_label=x, set_type="Independent", varying_condition_summary="", source_table_or_section="T1",
                       data_source=ref, samples=[PlannedSample(sample_label="G", source="T1")]) for x in ("KOH", "KOH + Val")]
    flags = _cited_data_flags(StructurePlan(experiment_sets=sets, n_rows=2))
    assert len(flags) == 1 and "Sets 'KOH', 'KOH + Val' (2 rows) are reproduced" in flags[0].message


def test_values_and_units():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
    from parameter_extractor.ingestion.new_variables import group_new_variables, stored_value
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.schemas.row_schema import ExtractedRow
    from parameter_extractor.schemas.variables import NewVariable
    from parameter_extractor.variable_categories import by_id, check_format
    assert [unit_for_column(c) for c in ("chamber_thickness_um", "tube_length_mm", "x_cm", "max_length_nt",
                                         "initial_X_aq_mM")] == ["µm", "mm", "cm", "nt", "mM"]
    assert check_format(by_id("product_properties"), "149 nt") == (149.0, "nt", "")
    nv = lambda value, column, rid: NewVariable(kind="parameter", name="maximum oligomer length", alias_name="maximum "
                                                "oligomer length", proposed_column=column, value_text=value,
                                                row_ids=[rid], category="product_properties", origin="conditions")
    groups = group_new_variables([nv("10 nt", "max_len_nt", "r1"), nv("6-13 nt", "max_len_range_nt", "r2")])
    assert [g.proposed_column for g in groups] == ["max_len_nt", "max_len_range_nt"]
    # a chemistry range arrives formatted already ('68.6:79.1' %): kept, not 'not converted'
    rng = NewVariable(kind="species", name="RNA oligomers", alias_name="sampled RNA oligomers range %",
                      proposed_column="sampled_RNA_oligomers_aq_range_%yield", value_text="68.6:79.1", unit="%",
                      row_ids=["r1"], origin="chemistry")
    assert stored_value(rng, "sampled_RNA_oligomers_aq_range_%yield", "number") == ("68.6:79.1", "range")
    row = ExtractedRow(full_id="r1", set_id="s", sample_id="r1", set_type="Independent", entry_number=1,
                       paper_title="t", authors=["A"], year_published=0, journal_published="",
                       experiment_type="Batch", solution_type="Wet")
    assert row_to_template_dict(row)["year_published"] is None


def test_species_without_amount_not_reviewed():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.new_variables import collect_new_variables
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    from parameter_extractor.schemas.methodology import empty_methodology
    e = lambda name, v: SoluteEntry(name=name, phase="aq", role="initial", set_label="A", concentration_value=v,
                                    concentration_unit_raw="mM" if v else None, concentration_mM=v, quote=name,
                                    source="Table 1", confidence="high")
    found = collect_new_variables(empty_methodology("p"), ChemistryExtraction(solutes=[e("POPC", None), e("ImpZ", 5.0)]),
                                  VariableRegistry(None), None)
    assert [v.name for v in found] == ["ImpZ"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All Sam-papers round tests passed.")
