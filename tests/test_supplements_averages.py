"""
Offline tests for supplementary information read with a paper (ingestion/supplements.py) and for averaged
results (set type "Average", '<name>_avg_<unit>' columns). No API calls; the PDFs are generated here.

Run with: python tests/test_supplements_averages.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor.ingestion.supplements import drop_supplements, find_supplements, is_supplement_name, \
    main_paper_for


def _pdf(path: Path, pages):
    """A small PDF with one line of text per page (pypdfium2 can't write text, so a minimal PDF by hand)."""
    objs, kids = [], []
    font = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        kids.append(len(objs) + 2)
        objs.append(None)                                  # the page, filled below
    body = ["<< /Type /Catalog /Pages 2 0 R >>", None, font] + objs
    n_pages = len(pages)
    page_ids = [4 + 2 * i + 1 for i in range(n_pages)]
    body[1] = f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {n_pages} >>"
    for i in range(n_pages):
        body[3 + 2 * i + 1] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                               f"/Resources << /Font << /F1 3 0 R >> >> >>")
    out, offsets = "%PDF-1.4\n", []
    for i, obj in enumerate(body, start=1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{i} 0 obj\n{obj}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(body) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(body) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))


def test_supplement_names_and_folding():
    assert all(is_supplement_name(f"x{s}", "x") for s in ("_SI", " SI", "-ESI", "_supplementary", "_SI2",
                                                          "_Supporting Information", ".supp"))
    assert not any(is_supplement_name(s, "x") for s in ("xsi", "x_site", "x2", "y_SI"))
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name in ("paper.pdf", "paper_SI.pdf", "other.pdf", "lonely_SI.pdf"):
            (d / name).write_bytes(b"%PDF")
        assert find_supplements(d / "paper.pdf") == [d / "paper_SI.pdf"] and find_supplements(d / "other.pdf") == []
        assert main_paper_for(d / "paper_SI.pdf") == d / "paper.pdf" and main_paper_for(d / "lonely_SI.pdf") is None
        kept, folded = drop_supplements([d / "paper.pdf", d / "paper_SI.pdf", d / "other.pdf", d / "lonely_SI.pdf"])
        assert kept == [d / "paper.pdf", d / "other.pdf", d / "lonely_SI.pdf"] and folded == [d / "paper_SI.pdf"]


def test_a_supplement_is_read_after_the_paper():
    from parameter_extractor.api_client import _piece_label
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _pdf(d / "paper.pdf", ["Main page one text here", "Main page two Table 1 results"])
        _pdf(d / "paper_SI.pdf", ["SI page one methods", "Table S1 extra results 42"])
        parsed = parse_pdf(str(d / "paper.pdf"))
        parsed.add_supplement(parse_pdf(str(d / "paper_SI.pdf")), d / "paper_SI.pdf")
        assert parsed.page_count == 4 and len(parsed.page_texts) == 4
        assert "SUPPLEMENTARY INFORMATION (paper_SI.pdf)" in parsed.page_texts[2] and "42" in parsed.text
        assert [parsed.page_label(p) for p in (1, 2, 3, 4)] == [1, 2, "S1", "S2"]
        assert 4 in parsed.table_pages                         # the SI's table page, renumbered after the paper's
        assert _piece_label(Path("x/SI/page-2.jpg")).startswith("Supplementary information, page S2")
        assert _piece_label(Path("x/page_images/page-2.jpg")) == ""


def test_averages_have_their_own_columns_and_set_type():
    from parameter_extractor.ingestion.flatten_to_template import (column_for_solute, proposed_column_for_solute,
                                                                    species_alias_name, with_average)
    from parameter_extractor.registry import is_peptide_column
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    from parameter_extractor.schemas.structure_plan import PlannedSet
    assert with_average("sampled_2peptide_Gly_mM") == "sampled_2peptide_Gly_avg_mM"
    assert with_average("sampled_2peptide_Gly_%yield") == "sampled_2peptide_Gly_avg_%yield"
    assert with_average("max_oligomer_length_nt") == "max_oligomer_length_avg_nt"
    assert with_average("sampled_2peptide_Gly_avg_mM") == "sampled_2peptide_Gly_avg_mM"   # not twice
    avg = SoluteEntry(name="2peptide_Gly", role="sampled", phase="aq", concentration_value=1.2,
                      concentration_unit_raw="mM", quote="q", source="s", confidence="high", average=True)
    single = avg.model_copy(update={"average": False})
    assert column_for_solute(avg) == "sampled_2peptide_Gly_avg_mM" and is_peptide_column(column_for_solute(avg))
    assert column_for_solute(single) == "sampled_2peptide_Gly_mM"
    assert species_alias_name(avg) == "sampled 2peptide_Gly avg" and avg.variable != single.variable
    assert proposed_column_for_solute(avg.model_copy(update={"name": "ribose"})) == "sampled_ribose_aq_avg_mM"
    c = ChemistryExtraction.model_validate({"tables": [{"src": "Table 1", "c": "high", "cols": [
        {"nm": "Gly", "r": "sampled", "ph": "aq", "u": "mM", "lbl": "mean Gly (mM)", "avg": True}],
        "rows": [{"set": "A", "sample": "s", "row": "1", "v": ["2.5"]}]}]})
    assert c.solutes[0].average
    assert PlannedSet(set_label="A", set_type="Average", varying_condition_summary="", source_table_or_section="",
                      samples=[]).set_type == "Average"


def test_digitized_averages():
    """Riggi2023-style bars of averages: an averaged y axis -> '_avg' column, set type Average."""
    from parameter_extractor.ingestion.figure_rows import build_figure_rows
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.figures import (AxisCalibration, AxisVariable, CalibrationPoint,
                                                     DigitizedFigure, DigitizedPanel, DigitizedPoint, DigitizedSeries)
    from parameter_extractor.schemas.methodology import empty_methodology
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    y_cal = AxisCalibration(p1=CalibrationPoint(px=0, py=100, value=0), p2=CalibrationPoint(px=0, py=0, value=10))
    panel = DigitizedPanel(y_cal=y_cal, x=AxisVariable(label="mineral", column=None),
                           y=AxisVariable(label="avg. % Gly-Gly", column="sampled_2peptide_Gly_%yield", average=True))
                                                            # bars of categories: no x calibration
    fig = DigitizedFigure(figure_id="Fig. 2", number=2, page=7, caption="c", render_scale=1.0, page_image="",
                          panels=[panel], series=[
        DigitizedSeries(label="kaolinite", points=[DigitizedPoint(px=50, py=60)])])
    meta = PaperMetadata(paper_id="p", paper_title="t", authors=["A"], year_published=2023, journal_published="j")
    rows, problems, new_vars = build_figure_rows([fig], meta, empty_methodology("p"), "001", 1, 1,
                                                 registry=VariableRegistry(None))
    assert not problems and rows[0].set_type == "Average"
    assert rows[0].species_mM == {} and rows[0].extra.get("sampled_2peptide_Gly_avg_%yield") == 4.0


def test_axes_no_column_fits_are_named_from_their_labels():
    """mizuuchi2019 Fig. 1: 'Relative RNA concentration' (averaged) against 'Length (nt)' -- no column fits
    either axis; the series still gives rows, and both values go to the review under label-based names."""
    from parameter_extractor.ingestion.figure_rows import axis_column_from_label, build_figure_rows
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.figures import (AxisCalibration, AxisVariable, CalibrationPoint,
                                                     DigitizedFigure, DigitizedPanel, DigitizedPoint, DigitizedSeries)
    from parameter_extractor.schemas.methodology import empty_methodology
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    assert axis_column_from_label("avg. max. linear oligomer length", average=True) == "max_linear_oligomer_length"
    assert axis_column_from_label("Length (nt)") == "length_nt"
    cal = lambda a, b: AxisCalibration(p1=CalibrationPoint(px=a[0], py=a[1], value=a[2]),
                                       p2=CalibrationPoint(px=b[0], py=b[1], value=b[2]))
    panel = DigitizedPanel(x_cal=cal((0, 100, 0), (100, 100, 24)), y_cal=cal((0, 100, 0), (0, 0, 2)),
                           x=AxisVariable(label="Length (nt)", column=None),
                           y=AxisVariable(label="Relative RNA concentration", column=None, average=True))
    fig = DigitizedFigure(figure_id="Fig. 1", number=1, page=2, caption="c", render_scale=1.0, page_image="",
                          panels=[panel], series=[DigitizedSeries(label="Pyrite", initial_temperature_C=22,
                                                                  points=[DigitizedPoint(px=50, py=50)])])
    meta = PaperMetadata(paper_id="p", paper_title="t", authors=["A"], year_published=2019, journal_published="j")
    rows, problems, new_vars = build_figure_rows([fig], meta, empty_methodology("p"), "001", 1, 1,
                                                 registry=VariableRegistry(None))
    assert len(rows) == 1 and not problems and rows[0].set_type == "Average"
    assert {(v.kind, v.proposed_column, v.value) for v in new_vars} == {
        ("figure_axis", "length_nt", 12.0), ("figure_axis", "relative_RNA_concentration_avg", 1.0)}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All supplement / average tests passed.")
