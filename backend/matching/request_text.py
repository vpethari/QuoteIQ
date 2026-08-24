from __future__ import annotations

import re
from dataclasses import dataclass

from matching.normalizer import fold_whitespace, normalize_part_number

_SALSIFY_IN_TEXT = re.compile(
    r"(?<![A-Za-z0-9])NA1-[A-Za-z0-9]+(?:[-+/_.][A-Za-z0-9]+)*",
    re.IGNORECASE,
)
_QTY_PATTERNS = (
    re.compile(r"(?i)\bneed\s+(\d+)\s*[-–]\s*"),
    re.compile(r"(?i)\bneed\s+(\d+)\b"),
    re.compile(r"(?i)\bplease\s+provide\s+(\d+)\b"),
    re.compile(r"(?i)\bprovide\s+(\d+)\b"),
    re.compile(r"(?i)\bquote\s+(\d+)\b"),
    re.compile(r"(?i)\b(?:qty|quantity)\s*[:=]?\s*(\d+)\b"),
    re.compile(r"(?i)\b(\d+)\s+(?:pcs|pieces|ea|each)\b"),
    re.compile(r"(?i)\b(\d+)\s+of\b"),
)
_BOILERPLATE = re.compile(
    r"(?i)\b(please|provide|need|quote|of|pcs|pieces|ea|each|qty|quantity)\b"
)
_SEPARATORS = re.compile(r"[\s,;:]+")


@dataclass(frozen=True)
class InterpretedRequest:
    raw_text: str
    lookup_identifiers: tuple[str, ...] = ()
    description_text: str = ""
    quantity_from_text: int | float | None = None
    has_identifier: bool = False
    has_description: bool = False
    extracted_salsify_ids: tuple[str, ...] = ()
    extracted_catalog_numbers: tuple[str, ...] = ()


def extract_quantity_from_text(raw_text: str | None) -> int | float | None:
    text = fold_whitespace(raw_text)
    if not text:
        return None
    for pattern in _QTY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        number = int(match.group(1))
        start, end = match.span(1)
        window = text[max(0, start - 1) : min(len(text), end + 2)]
        if re.search(r"\d+V", window, re.IGNORECASE) or "/" in window:
            continue
        return number
    return None


def interpret_customer_text(
    raw_text: str | None,
    *,
    explicit_part_number: str | None = None,
    salsify_keys: tuple[str, ...] | list[str] = (),
    official_keys: tuple[str, ...] | list[str] = (),
) -> InterpretedRequest:
    raw = fold_whitespace(raw_text)
    explicit = fold_whitespace(explicit_part_number) or None
    haystack = raw.upper()
    occupied = [False] * len(haystack)
    salsify_hits: list[str] = []
    official_hits: list[str] = []

    for key in sorted({item for item in salsify_keys if item}, key=len, reverse=True):
        for start, end, original in _find_key_spans(haystack, key):
            if _span_taken(occupied, start, end):
                continue
            _mark(occupied, start, end)
            salsify_hits.append(raw[start:end] if raw else original)

    for match in _SALSIFY_IN_TEXT.finditer(haystack):
        if _span_taken(occupied, match.start(), match.end()):
            continue
        _mark(occupied, match.start(), match.end())
        salsify_hits.append(raw[match.start() : match.end()] if raw else match.group(0))

    for key in sorted({item for item in official_keys if item}, key=len, reverse=True):
        for start, end, original in _find_key_spans(haystack, key):
            if _span_taken(occupied, start, end):
                continue
            _mark(occupied, start, end)
            official_hits.append(raw[start:end] if raw else original)

    if explicit:
        explicit_key = normalize_part_number(explicit)
        salsify_keyset = {normalize_part_number(item) for item in salsify_keys if item}
        if explicit_key in salsify_keyset or explicit_key.startswith("NA1-"):
            if not any(normalize_part_number(item) == explicit_key for item in salsify_hits):
                salsify_hits.insert(0, explicit)
        elif explicit_key:
            if not any(normalize_part_number(item) == explicit_key for item in official_hits):
                official_hits.insert(0, explicit)

    masked = "".join(" " if flag else haystack[index] for index, flag in enumerate(occupied))
    quantity = extract_quantity_from_text(raw)
    description = _description_from_remainder(masked)

    if explicit and (not raw or normalize_part_number(raw) == normalize_part_number(explicit)):
        description = ""

    lookup = [*salsify_hits, *official_hits]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in lookup:
        key = normalize_part_number(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return InterpretedRequest(
        raw_text=raw,
        lookup_identifiers=tuple(deduped),
        description_text=description,
        quantity_from_text=quantity,
        has_identifier=bool(deduped),
        has_description=bool(description),
        extracted_salsify_ids=tuple(dict.fromkeys(salsify_hits)),
        extracted_catalog_numbers=tuple(dict.fromkeys(official_hits)),
    )


def _find_key_spans(haystack: str, key: str) -> list[tuple[int, int, str]]:
    pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(key)}(?![A-Z0-9])", re.IGNORECASE)
    return [(match.start(), match.end(), match.group(0)) for match in pattern.finditer(haystack)]


def _span_taken(occupied: list[bool], start: int, end: int) -> bool:
    return any(occupied[start:end])


def _mark(occupied: list[bool], start: int, end: int) -> None:
    for index in range(start, end):
        occupied[index] = True


def _description_from_remainder(masked: str) -> str:
    without_qty = masked
    for pattern in _QTY_PATTERNS:
        without_qty = pattern.sub(" ", without_qty)
    without_qty = _BOILERPLATE.sub(" ", without_qty)
    cleaned = _SEPARATORS.sub(" ", without_qty).strip(" -/,.")
    return fold_whitespace(cleaned)
