from __future__ import annotations

import re
from dataclasses import dataclass

from matching.noise import extract_quantity_from_text, strip_quantity_and_noise
from matching.normalizer import fold_whitespace, normalize_part_number

_SALSIFY_IN_TEXT = re.compile(
    r"(?<![A-Za-z0-9])NA1-[A-Za-z0-9]+(?:[-+/_.][A-Za-z0-9]+)*",
    re.IGNORECASE,
)
_SEPARATORS = re.compile(r"[\s,;:]+")
_IDENTIFIER_SEP_CHARS = "-/_.+"
_MAXIMAL_IDENTIFIER_RUN_RE = re.compile(
    rf"[A-Z0-9]+(?:[{re.escape(_IDENTIFIER_SEP_CHARS)}][A-Z0-9]+)*"
)


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

    # salsify_keys/official_keys are already normalize_part_number() output
    # (built once in ProductMatcher.__init__), so wrap them in sets for O(1)
    # membership instead of re-normalizing or scanning them per call.
    salsify_keyset = {item for item in salsify_keys if item}
    official_keyset = {item for item in official_keys if item}

    # Candidate identifier-shaped spans come from the (short) customer text,
    # not from iterating every known catalog key -- catalogs can have tens of
    # thousands of keys, so a per-key regex scan does not scale.
    candidate_spans = _candidate_identifier_spans(haystack)

    for start, end, candidate in candidate_spans:
        if _span_taken(occupied, start, end):
            continue
        if candidate in salsify_keyset:
            _mark(occupied, start, end)
            salsify_hits.append(raw[start:end] if raw else candidate)

    for match in _SALSIFY_IN_TEXT.finditer(haystack):
        if _span_taken(occupied, match.start(), match.end()):
            continue
        _mark(occupied, match.start(), match.end())
        salsify_hits.append(raw[match.start() : match.end()] if raw else match.group(0))

    for start, end, candidate in candidate_spans:
        if _span_taken(occupied, start, end):
            continue
        if candidate in official_keyset:
            _mark(occupied, start, end)
            official_hits.append(raw[start:end] if raw else candidate)

    if explicit:
        explicit_key = normalize_part_number(explicit)
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


def _candidate_identifier_spans(haystack: str) -> list[tuple[int, int, str]]:
    """Every substring of `haystack` a known catalog key could exactly equal.

    A maximal alnum-and-separator run like "B1EB5-W-EXTRA" is split into
    segments at `-/_.+`; every contiguous range of segments (rejoined with
    its original separators) is a candidate, since each such range has a
    non-alnum or string boundary on both sides -- the same condition the
    original per-key regex search required. Longest spans are returned first
    so a full match wins over an embedded shorter one at the same position.
    """
    spans: list[tuple[int, int, str]] = []
    for run_match in _MAXIMAL_IDENTIFIER_RUN_RE.finditer(haystack):
        run_start = run_match.start()
        parts = re.split(f"([{re.escape(_IDENTIFIER_SEP_CHARS)}])", run_match.group(0))
        segments = parts[0::2]
        seps = parts[1::2]
        seg_starts: list[int] = []
        pos = 0
        for index, segment in enumerate(segments):
            seg_starts.append(pos)
            pos += len(segment)
            if index < len(seps):
                pos += len(seps[index])
        for i in range(len(segments)):
            text = segments[i]
            start = run_start + seg_starts[i]
            spans.append((start, start + len(text), text))
            for j in range(i + 1, len(segments)):
                text += seps[j - 1] + segments[j]
                spans.append((start, start + len(text), text))
    spans.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    return spans


def _span_taken(occupied: list[bool], start: int, end: int) -> bool:
    return any(occupied[start:end])


def _mark(occupied: list[bool], start: int, end: int) -> None:
    for index in range(start, end):
        occupied[index] = True


def _description_from_remainder(masked: str) -> str:
    cleaned = _SEPARATORS.sub(" ", masked).strip(" -/,.")
    return strip_quantity_and_noise(cleaned)
