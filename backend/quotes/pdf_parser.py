from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pdfplumber

from matching.normalizer import fold_whitespace
from matching.request_text import extract_quantity_from_text
from quotes.models import LineItem, QuoteParseError
from quotes.parse_diagnostics import record_parse_warning
from quotes.validation import TOTAL_PATTERN

_MIN_LINE_LENGTH = 2
_HEADER_WORDS = frozenset({"DESCRIPTION", "QTY", "QUANTITY", "UNIT", "PRICE", "NOTES", "SPEC"})

# pdfplumber's plain text extraction collapses a table's column gap down to a
# single space, so "3/4\" EMT CONDUIT   5,723" and "3/4\" EMT CONDUIT 5,723"
# are indistinguishable -- there is no positional signal left to split
# columns on. A trailing, purely-numeric, whitespace-separated token is
# still a strong quantity signal for tabular PDF exports specifically
# (unlike free text, where a trailing number is often part of the
# description -- this stays local to the PDF parser, not the shared
# extract_quantity_from_text used elsewhere).
_TRAILING_QUANTITY_RE = re.compile(r"^(.*\S)\s+(\d{1,3}(?:,\d{3})+|\d+)$")


def parse_pdf_quote_file(path: str | Path, source_name: str | None = None) -> list[LineItem]:
    """Treat each non-boilerplate line of PDF text as one quote line item.

    PDF quote layouts vary too widely (tables, narrative "Label: value"
    text, bare lists) to reconstruct columns reliably. Instead, each line
    is handed to the same free-text interpretation the matching engine
    already applies to messy Excel/customer text -- it only needs a
    description string, so column reconstruction is unnecessary.
    """
    pdf_path = Path(path)
    display_name = source_name or pdf_path.name
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_lines = [_page_lines(page) for page in pdf.pages]
    except QuoteParseError:
        raise
    except Exception as exc:
        raise QuoteParseError("Unable to read PDF document.") from exc

    if not any(pages_lines):
        raise QuoteParseError("PDF has no extractable text.")

    boilerplate = _repeated_across_pages(pages_lines)

    items: list[LineItem] = []
    row_number = 0
    found_quantity_column = False
    for page_index, lines in enumerate(pages_lines, start=1):
        for line in lines:
            row_number += 1
            if not _is_candidate_line(line, boilerplate):
                continue
            description, quantity = _split_trailing_quantity(line)
            if quantity is not None:
                found_quantity_column = True
            else:
                quantity = extract_quantity_from_text(description)
            items.append(
                LineItem(
                    source_file=display_name,
                    source_sheet=f"Page {page_index}",
                    source_row=row_number,
                    requested_description=description,
                    quantity=quantity,
                    requested_part_number=None,
                )
            )
    if not items:
        raise QuoteParseError("No quote line items were found in the PDF.")
    if not found_quantity_column:
        record_parse_warning(
            f'Could not detect a clear quantity column in "{display_name}" -- '
            "quantities were inferred from line text where possible."
        )
    return items


def _page_lines(page: object) -> list[str]:
    text = page.extract_text() or ""  # type: ignore[attr-defined]
    return [fold_whitespace(line) for line in text.splitlines() if fold_whitespace(line)]


def _repeated_across_pages(pages_lines: list[list[str]]) -> frozenset[str]:
    """Lines printed on every page are header/footer boilerplate, not items."""
    if len(pages_lines) < 2:
        return frozenset()
    counts = Counter(line for lines in pages_lines for line in set(lines))
    return frozenset(line for line, count in counts.items() if count == len(pages_lines))


def _split_trailing_quantity(line: str) -> tuple[str, int | None]:
    match = _TRAILING_QUANTITY_RE.match(line)
    if not match:
        return line, None
    description, quantity_text = match.group(1), match.group(2)
    try:
        return description, int(quantity_text.replace(",", ""))
    except ValueError:
        return line, None


def _is_candidate_line(line: str, boilerplate: frozenset[str]) -> bool:
    if len(line) < _MIN_LINE_LENGTH:
        return False
    if line in boilerplate:
        return False
    words = line.upper().split()
    if words and all(word in _HEADER_WORDS for word in words):
        return False
    if TOTAL_PATTERN.search(line):
        return False
    if line.isdigit():  # bare page number
        return False
    return True
