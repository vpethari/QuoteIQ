from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from quotes.models import QuoteParseError
from quotes.parse_diagnostics import collect_parse_warnings, start_parse_diagnostics
from quotes.parser import parse_quote_file


def _write_rows(path: Path, rows: list[list[object]]) -> Path:
    """Write rows with no header row at all (unlike _write_xlsx elsewhere)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()
    return path


def test_headerless_description_quantity_dump_is_inferred(tmp_path: Path) -> None:
    """Real customer file: no header row, just description+qty starting on
    row 1 -- must not require a labeled header to parse."""
    path = _write_rows(
        tmp_path / "headerless.xlsx",
        [
            ['3/4" EMT CONDUIT', 5723],
            ['1" EMT CONDUIT', 610],
            ['1/2" EMT STL SS CONN', 3],
        ],
    )
    start_parse_diagnostics()
    items = parse_quote_file(path)
    assert [(item.requested_description, item.quantity, item.source_row) for item in items] == [
        ('3/4" EMT CONDUIT', 5723, 1),
        ('1" EMT CONDUIT', 610, 2),
        ('1/2" EMT STL SS CONN', 3, 3),
    ]
    warnings = collect_parse_warnings()
    assert len(warnings) == 1
    assert "No header row" in warnings[0]


def test_headerless_layout_requires_consistent_shape(tmp_path: Path) -> None:
    """A single ambiguous row isn't enough evidence, and inconsistent column
    positions/both-text or both-numeric rows must not be guessed at."""
    only_one_row = _write_rows(tmp_path / "one-row.xlsx", [["Widget", 5]])
    with pytest.raises(QuoteParseError):
        parse_quote_file(only_one_row)

    both_text = _write_rows(tmp_path / "both-text.xlsx", [["A", "B"], ["C", "D"]])
    with pytest.raises(QuoteParseError):
        parse_quote_file(both_text)

    swapped_columns = _write_rows(
        tmp_path / "swapped.xlsx", [["Widget", 5], [7, "Gadget"]]
    )
    with pytest.raises(QuoteParseError):
        parse_quote_file(swapped_columns)


def test_embedded_section_subheader_rows_are_skipped(tmp_path: Path) -> None:
    """Some quotes repeat a mini "Section Name" / "QTY" header row before
    each section (seen in real customer files) -- these must be skipped
    instead of raising "Invalid quantity", since "QTY" isn't a real value."""
    path = _write_rows(
        tmp_path / "sections.xlsx",
        [
            ["Name", "Qty"],
            ["750MCM HYPRESS 2-HOLE LUG", 492],
            ["MV Termination", "QTY"],
            ["#8-2/0 15KV HV TERMINATION", 18],
            ["Strut", "QTY"],
            ["P-1000 1 5/8 STRUT", 3542],
        ],
    )
    start_parse_diagnostics()
    items = parse_quote_file(path)
    # The whole "Section Name" / "QTY" row is dropped (not just its quantity
    # cell) -- no crash, and no useless description-only noise left behind.
    descriptions = [item.requested_description for item in items]
    assert descriptions == [
        "750MCM HYPRESS 2-HOLE LUG",
        "#8-2/0 15KV HV TERMINATION",
        "P-1000 1 5/8 STRUT",
    ]
    by_desc = {item.requested_description: item.quantity for item in items}
    assert by_desc["#8-2/0 15KV HV TERMINATION"] == 18
    assert by_desc["P-1000 1 5/8 STRUT"] == 3542
    warnings = collect_parse_warnings()
    assert len(warnings) == 1
    assert "repeated a column header" in warnings[0]


def test_clean_headered_file_produces_no_parse_warnings(tmp_path: Path) -> None:
    path = _write_rows(
        tmp_path / "clean.xlsx",
        [["Name", "Qty"], ["750MCM HYPRESS 2-HOLE LUG", 492]],
    )
    start_parse_diagnostics()
    parse_quote_file(path)
    assert collect_parse_warnings() == []


def test_invalid_quantity_still_raises_and_is_not_masked(tmp_path: Path) -> None:
    """The repeated-header skip must not swallow genuine bad data -- only
    exact QUANTITY_ALIASES text (like "QTY") is treated as a stray header."""
    path = _write_rows(
        tmp_path / "bad-qty.xlsx",
        [["Name", "Qty"], ["Cable", "not-a-number"]],
    )
    with pytest.raises(QuoteParseError, match="Invalid quantity"):
        parse_quote_file(path)
