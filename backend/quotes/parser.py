from __future__ import annotations

import warnings
import zipfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from matching.models import QuoteLine
from matching.normalizer import fold_whitespace
from matching.productcode import productcode_as_text
from matching.request_text import extract_quantity_from_text
from quotes.models import LineItem, QuoteParseError
from quotes.validation import (
    DESCRIPTION_ALIASES,
    PART_NUMBER_ALIASES,
    QUANTITY_ALIASES,
    is_blank,
    is_total_row,
    parse_quantity,
    resolve_optional_column,
)


def parse_quote_file(path: str | Path, source_name: str | None = None) -> list[LineItem]:
    workbook_path = Path(path)
    display_name = source_name or workbook_path.name
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Unknown extension is not supported")
            workbook = load_workbook(workbook_path, data_only=True, read_only=True)
    except (InvalidFileException, OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise QuoteParseError("Unable to read Excel workbook.") from exc

    try:
        if not workbook.sheetnames:
            raise QuoteParseError("Workbook has no worksheets.")
        sheet = workbook[workbook.sheetnames[0]]
        rows = list(sheet.iter_rows(values_only=True))
        sheet_name = sheet.title
    finally:
        workbook.close()

    if not rows:
        raise QuoteParseError("Workbook is empty.")

    header_row_index, headers = _find_header_row(rows)
    description_idx = _resolve_raw_text_column(headers)
    if description_idx is None:
        raise QuoteParseError(
            "Could not identify a customer text column. Expected a header such as Name or Description."
        )
    quantity_idx = resolve_optional_column(headers, QUANTITY_ALIASES)
    part_idx = resolve_optional_column(headers, PART_NUMBER_ALIASES)

    items: list[LineItem] = []
    for offset, raw in enumerate(rows[header_row_index + 1 :]):
        excel_row = header_row_index + 2 + offset
        values = list(raw or ())
        if _row_blank(values):
            continue
        if is_total_row(values):
            continue
        raw_description = _cell(values, description_idx)
        description = "" if is_blank(raw_description) else fold_whitespace(productcode_as_text(raw_description))
        quantity = None
        if quantity_idx is not None:
            quantity = parse_quantity(_cell(values, quantity_idx), excel_row=excel_row)
        if quantity is None:
            quantity = extract_quantity_from_text(description)
        requested_part = None
        if part_idx is not None:
            raw_part = _cell(values, part_idx)
            if not is_blank(raw_part):
                requested_part = fold_whitespace(productcode_as_text(raw_part)) or None
        if not description and not requested_part:
            continue
        items.append(
            LineItem(
                source_file=display_name,
                source_sheet=sheet_name,
                source_row=excel_row,
                requested_description=description,
                quantity=quantity,
                requested_part_number=requested_part,
            )
        )
    if not items:
        raise QuoteParseError("No quote line items were found.")
    return items


def line_items_to_quote_lines(items: list[LineItem]) -> list[QuoteLine]:
    return [
        QuoteLine(
            source_file=item.source_file,
            source_sheet=item.source_sheet,
            source_row=item.source_row,
            requested_description=item.requested_description,
            quantity=item.quantity,
            requested_part_number=item.requested_part_number,
        )
        for item in items
    ]


def _find_header_row(rows: list[tuple]) -> tuple[int, dict[str, int]]:
    for index, raw in enumerate(rows[:20]):
        values = list(raw or ())
        filled = [str(v).strip() for v in values if not is_blank(v)]
        if len(filled) < 1:
            continue
        headers = {
            str(value).strip(): col
            for col, value in enumerate(values)
            if not is_blank(value)
        }
        if _resolve_raw_text_column(headers) is None:
            continue
        return index, headers
    raise QuoteParseError(
        "Could not identify a customer text column in the workbook."
    )


def _resolve_raw_text_column(headers: dict[str, int]) -> int | None:
    index = resolve_optional_column(headers, DESCRIPTION_ALIASES)
    if index is not None:
        return index
    qty = resolve_optional_column(headers, QUANTITY_ALIASES)
    pn = resolve_optional_column(headers, PART_NUMBER_ALIASES)
    remaining = [col for _name, col in headers.items() if col not in {qty, pn}]
    if len(remaining) == 1:
        return remaining[0]
    if len(headers) == 1:
        return next(iter(headers.values()))
    return None


def _cell(values: list[object], index: int) -> object:
    if index >= len(values):
        return None
    return values[index]


def _row_blank(values: list[object]) -> bool:
    return all(is_blank(value) for value in values)
