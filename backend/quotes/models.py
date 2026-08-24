from __future__ import annotations

from dataclasses import dataclass


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
