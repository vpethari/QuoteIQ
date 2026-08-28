from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from matching.tokenizer import tokenize_description
from matching.units import extract_amperages, extract_dimensions, extract_voltages

WIRE_SIZE_RE = re.compile(r"\b\d+/\d+\b")

# Seed hints from the current catalog language. Additional tokens are extracted
# from the description itself so this is not limited to the examples below.
KNOWN_PHRASES: tuple[str, ...] = (
    "SWITCH MODULE",
    "LIGHTING WHIP",
    "LIGHTING CABLE",
    "EXT CABLE",
    "EXT WHIP",
    "DBL HEAD",
    "DBL END",
    "WHIP END",
    "ISO GROUND",
)


def _known_phrase_token_lists() -> list[tuple[str, list[str]]]:
    cached = getattr(_known_phrase_token_lists, "_cached", None)
    if cached is not None:
        return cached
    lists = [(phrase, tokenize_description(phrase)) for phrase in KNOWN_PHRASES]
    _known_phrase_token_lists._cached = lists  # type: ignore[attr-defined]
    return lists


def attributes_from_parts(value: str | None, normalized: str, tokens: Sequence[str]) -> frozenset[str]:
    """Build attribute tags from already-normalized text and tokens."""
    attributes: set[str] = set()
    token_list = list(tokens)
    token_set = set(token_list)

    for spec in extract_voltages(value):
        attributes.add(f"voltage:{spec.magnitude_key()}")
    for index, token in enumerate(token_list):
        nxt = token_list[index + 1] if index + 1 < len(token_list) else ""
        if token.isdigit() and nxt == "V":
            attributes.add(f"voltage:{token}V")

    for spec in extract_dimensions(value):
        attributes.add(f"size:{_fraction_label(spec.inches, spec.unit)}")
    for match in WIRE_SIZE_RE.finditer(normalized):
        attributes.add(f"size:{match.group(0)}")
    for spec in extract_amperages(value):
        attributes.add(f"amperage:{spec.magnitude_key()}")

    joined = " ".join(token_list)
    for phrase, phrase_tokens in _known_phrase_token_lists():
        if phrase_tokens and all(part in token_set for part in phrase_tokens):
            if _tokens_contain_phrase(token_list, phrase_tokens):
                attributes.add(f"phrase:{phrase}")

    for token in token_list:
        if len(token) >= 3:
            attributes.add(f"token:{token}")

    if "DBL" in joined.split() or "DBL" in token_set:
        attributes.add("token:DBL")
    return frozenset(attributes)


def extract_attributes(value: str | None) -> frozenset[str]:
    """Extract comparable product attributes from free text.

    Attributes include voltages, wire sizes, significant tokens, and known
    multi-word phrases. New tokens in future catalogs are picked up automatically.
    """
    from matching.normalizer import normalize_text

    normalized = normalize_text(value)
    tokens = tokenize_description(value)
    return attributes_from_parts(value, normalized, tokens)


def _fraction_label(value, unit: str = "IN") -> str:
    from fractions import Fraction

    amount = Fraction(value)
    if amount.denominator == 1:
        return f"{amount.numerator}{unit}"
    as_float = float(amount)
    text = f"{as_float:.4f}".rstrip("0").rstrip(".")
    return f"{text}{unit}"


def _tokens_contain_phrase(tokens: list[str], phrase_tokens: list[str]) -> bool:
    size = len(phrase_tokens)
    for index in range(0, len(tokens) - size + 1):
        if tokens[index : index + size] == phrase_tokens:
            return True
    return False


def attribute_labels(attributes: Iterable[str]) -> list[str]:
    labels: list[str] = []
    for item in sorted(attributes):
        kind, _, value = item.partition(":")
        if kind == "voltage":
            labels.append(f"Voltage matched: {value}")
        elif kind == "amperage":
            labels.append(f"Amperage matched: {value}")
        elif kind == "phrase":
            labels.append(f"Product type matched: {value}")
        elif kind == "token":
            labels.append(f"{value} attribute matched")
        elif kind == "size":
            labels.append(f"Size matched: {value}")
    return labels
