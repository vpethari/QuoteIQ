from __future__ import annotations

import re
from typing import Any

from quotes.models import QuoteParseError

TOTAL_PATTERN = re.compile(
    r"\b(sub[- ]?total|grand\s+total|\btotals?\b)\b",
    re.IGNORECASE,
)

DESCRIPTION_ALIASES = (
    "name",
    "description",
    "product",
    "item",
    "material",
    "requested description",
    "product description",
    "desc",
    "line description",
)

QUANTITY_ALIASES = (
    "qty",
    "quantity",
    "qty.",
    "qty ordered",
    "order qty",
    "units",
    "qty units",
)

PART_NUMBER_ALIASES = (
    "part number",
    "part #",
    "part#",
    "part no",
    "part no.",
    "partnumber",
    "customer part number",
    "customer part#",
    "customer pn",
    "customer part",
    "vendor part number",
    "vendor part#",
    "vendor pn",
    "manufacturer part number",
    "manufacturer part#",
    "mpn",
    "item number",
    "item #",
    "item no",
    "catalog number",
    "catalog #",
    "sku",
)


def normalize_header(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def compact_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_header(value))


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def is_total_row(values: list[Any]) -> bool:
    for value in values:
        if isinstance(value, str) and TOTAL_PATTERN.search(value):
            return True
    return False


def parse_quantity(value: Any, *, excel_row: int) -> int | float | None:
    if is_blank(value):
        return None
    if isinstance(value, bool):
        raise QuoteParseError(f"Invalid quantity on row {excel_row}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    text = str(value).strip().replace(",", "")
    try:
        number = float(text)
    except ValueError as exc:
        raise QuoteParseError(f"Invalid quantity on row {excel_row}") from exc
    if number.is_integer():
        return int(number)
    return number


def resolve_column(headers: dict[str, int], aliases: tuple[str, ...], field_name: str) -> int:
    index = resolve_optional_column(headers, aliases)
    if index is None:
        raise QuoteParseError(
            f"Could not identify the {field_name} column. "
            f"Expected a header such as: {', '.join(aliases[:8])}."
        )
    return index


def resolve_optional_column(headers: dict[str, int], aliases: tuple[str, ...]) -> int | None:
    by_normalized = {normalize_header(name): index for name, index in headers.items()}
    by_compact = {compact_header(name): index for name, index in headers.items()}
    for alias in aliases:
        if alias in by_normalized:
            return by_normalized[alias]
        compact = compact_header(alias)
        if compact and compact in by_compact:
            return by_compact[compact]
    return None
