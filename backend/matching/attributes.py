from __future__ import annotations

import re
from collections.abc import Iterable

from matching.tokenizer import tokenize_description

VOLTAGE_RE = re.compile(r"\b(\d+)\s*V\b")
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


def extract_attributes(value: str | None) -> frozenset[str]:
    """Extract comparable product attributes from free text.

    Attributes include voltages, wire sizes, significant tokens, and known
    multi-word phrases. New tokens in future catalogs are picked up automatically.
    """
    from matching.normalizer import normalize_text

    attributes: set[str] = set()
    normalized = normalize_text(value)
    tokens = tokenize_description(value)
    token_set = set(tokens)

    for match in VOLTAGE_RE.finditer(normalized):
        attributes.add(f"voltage:{match.group(1)}V")

    for match in WIRE_SIZE_RE.finditer(normalized):
        attributes.add(f"size:{match.group(0)}")

    joined = " ".join(tokens)
    for phrase in KNOWN_PHRASES:
        phrase_tokens = phrase.split()
        if phrase_tokens and all(part in token_set for part in phrase_tokens):
            if _tokens_contain_phrase(tokens, phrase_tokens):
                attributes.add(f"phrase:{phrase}")

    for token in tokens:
        if len(token) >= 3:
            attributes.add(f"token:{token}")

    if "DBL" in joined.split() or "DBL" in token_set:
        attributes.add("token:DBL")
    return frozenset(attributes)


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
        elif kind == "phrase":
            labels.append(f"Product type matched: {value}")
        elif kind == "token":
            labels.append(f"{value} attribute matched")
        elif kind == "size":
            labels.append(f"Size matched: {value}")
    return labels
