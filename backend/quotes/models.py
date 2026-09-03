from __future__ import annotations

from dataclasses import dataclass, field


class QuoteParseError(ValueError):
    """Raised when a quote workbook cannot be parsed into line items."""


@dataclass(frozen=True)
class LineItem:
    source_file: str
    source_sheet: str
    source_row: int
    requested_description: str
    quantity: int | float | None = None
    requested_part_number: str | None = None
    # The original file's own columns for this row, in their original
    # column order -- lets the "Full Results" export mirror the input file
    # exactly instead of a fixed, re-derived column set. Empty when the
    # source has no real columns to preserve (PDF text, a headerless dump).
    raw_row: dict[str, str] = field(default_factory=dict)
