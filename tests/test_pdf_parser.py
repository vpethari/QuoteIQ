from __future__ import annotations

from pathlib import Path

import pytest
from fpdf import FPDF

from quotes.models import QuoteParseError
from quotes.parse_diagnostics import collect_parse_warnings, start_parse_diagnostics
from quotes.pdf_parser import parse_pdf_quote_file


def _build_pdf(path: Path, pages: list[list[str]]) -> None:
    """Each page is a list of text lines, printed one per row."""
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for lines in pages:
        pdf.add_page()
        for line in lines:
            pdf.cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def test_each_clean_description_line_becomes_one_item(tmp_path: Path) -> None:
    path = tmp_path / "quote.pdf"
    _build_pdf(
        path,
        [
            ["DESCRIPTION", '3/4" EMT CONDUIT', '1" EMT CONDUIT', '1 1/2" PVC TERM ADAPTER'],
        ],
    )
    items = parse_pdf_quote_file(path, source_name="quote.pdf")
    descriptions = [item.requested_description for item in items]
    # A single-page PDF has no cross-page repetition to filter "DESCRIPTION"
    # by, so this test isolates the per-line extraction itself; boilerplate
    # filtering across pages is covered separately below.
    assert descriptions == ['3/4" EMT CONDUIT', '1" EMT CONDUIT', '1 1/2" PVC TERM ADAPTER']
    assert all(item.source_file == "quote.pdf" for item in items)
    assert all(item.requested_part_number is None for item in items)


def test_boilerplate_repeated_on_every_page_is_filtered(tmp_path: Path) -> None:
    path = tmp_path / "quote.pdf"
    _build_pdf(
        path,
        [
            ["Atkore Internal Use", "DESCRIPTION", '3/4" EMT CONDUIT', "Atkore Internal Use"],
            ["Atkore Internal Use", "DESCRIPTION", '1" EMT CONDUIT', "Atkore Internal Use"],
        ],
    )
    items = parse_pdf_quote_file(path, source_name="quote.pdf")
    descriptions = [item.requested_description for item in items]
    assert descriptions == ['3/4" EMT CONDUIT', '1" EMT CONDUIT']
    assert "Atkore Internal Use" not in descriptions
    assert "DESCRIPTION" not in descriptions
    assert items[0].source_sheet == "Page 1"
    assert items[1].source_sheet == "Page 2"


def test_total_rows_and_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "quote.pdf"
    _build_pdf(
        path,
        [
            [
                '3/4" EMT CONDUIT',
                "",
                "Grand Total",
                '1" EMT CONDUIT',
                "Subtotal",
            ]
        ],
    )
    items = parse_pdf_quote_file(path, source_name="quote.pdf")
    descriptions = [item.requested_description for item in items]
    assert descriptions == ['3/4" EMT CONDUIT', '1" EMT CONDUIT']


def test_quantity_embedded_in_line_is_extracted(tmp_path: Path) -> None:
    path = tmp_path / "quote.pdf"
    _build_pdf(path, [["6 FT FIXTURE WHIP"]])
    items = parse_pdf_quote_file(path, source_name="quote.pdf")
    assert len(items) == 1
    assert items[0].requested_description == "6 FT FIXTURE WHIP"


def test_trailing_column_quantity_is_split_from_description(tmp_path: Path) -> None:
    """pdfplumber collapses a table's column gap to a single space, so a
    tabular PDF export renders "DESCRIPTION QTY" as one glued line -- the
    trailing numeric token must be split out as quantity, not left polluting
    the description used for matching."""
    path = tmp_path / "quote.pdf"
    _build_pdf(path, [['3/4" EMT CONDUIT 5,723', '1" EMT CONDUIT 610']])
    items = parse_pdf_quote_file(path, source_name="quote.pdf")
    by_desc = {item.requested_description: item.quantity for item in items}
    assert by_desc['3/4" EMT CONDUIT'] == 5723
    assert by_desc['1" EMT CONDUIT'] == 610


def test_multiword_header_line_is_filtered(tmp_path: Path) -> None:
    """A tabular PDF's "Description" and "Qty" column headers can render as
    one glued line ("DESCRIPTION QTY"), not just single header words."""
    path = tmp_path / "quote.pdf"
    _build_pdf(path, [["DESCRIPTION QTY", '3/4" EMT CONDUIT 5,723']])
    items = parse_pdf_quote_file(path, source_name="quote.pdf")
    descriptions = [item.requested_description for item in items]
    assert descriptions == ['3/4" EMT CONDUIT']


def test_multipart_dimension_is_not_mistaken_for_a_trailing_quantity(tmp_path: Path) -> None:
    """"PVC J-BOX 8x8x4" must not have its trailing "4" stripped as a
    quantity -- "8x8x4" isn't purely numeric, so it's not a candidate split
    point. A genuine trailing quantity appended after it must still split
    out correctly without touching the dimension."""
    path = tmp_path / "quote.pdf"
    _build_pdf(path, [["PVC J-BOX 8x8x4", "PVC J-BOX 12x12x6 22"]])
    items = parse_pdf_quote_file(path, source_name="quote.pdf")
    assert len(items) == 2
    by_desc = {item.requested_description: item.quantity for item in items}
    assert by_desc["PVC J-BOX 8x8x4"] is None
    assert by_desc["PVC J-BOX 12x12x6"] == 22


def test_empty_pdf_raises_quote_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.output(str(path))
    with pytest.raises(QuoteParseError):
        parse_pdf_quote_file(path, source_name="empty.pdf")


def test_missing_file_raises_quote_parse_error(tmp_path: Path) -> None:
    with pytest.raises(QuoteParseError):
        parse_pdf_quote_file(tmp_path / "no-such.pdf", source_name="no-such.pdf")


def test_bare_page_number_lines_are_filtered(tmp_path: Path) -> None:
    path = tmp_path / "quote.pdf"
    _build_pdf(path, [['3/4" EMT CONDUIT', "1"]])
    items = parse_pdf_quote_file(path, source_name="quote.pdf")
    descriptions = [item.requested_description for item in items]
    assert descriptions == ['3/4" EMT CONDUIT']


def test_warns_when_no_quantity_column_is_detected(tmp_path: Path) -> None:
    """No line has a trailing numeric column -- quantities (if any) only come
    from free-text extraction, which is much less reliable than a real
    column, so the caller should be told the parse is less certain."""
    path = tmp_path / "quote.pdf"
    _build_pdf(path, [["6 FT FIXTURE WHIP", "SOME OTHER ITEM"]])
    start_parse_diagnostics()
    parse_pdf_quote_file(path, source_name="quote.pdf")
    warnings = collect_parse_warnings()
    assert len(warnings) == 1
    assert "quantity column" in warnings[0]


def test_no_warning_when_a_quantity_column_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "quote.pdf"
    _build_pdf(path, [['3/4" EMT CONDUIT 5,723', '1" EMT CONDUIT 610']])
    start_parse_diagnostics()
    parse_pdf_quote_file(path, source_name="quote.pdf")
    assert collect_parse_warnings() == []
