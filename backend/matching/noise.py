from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from matching.description_normalize import canonical_description, tokenize_description
from matching.normalizer import fold_whitespace

logger = logging.getLogger("quoteiq.matching")

# Extend this list for additional RFQ boilerplate. Do not add product-identifying
# terms such as voltage, whip, end, lighting, switch, module, or color words.
NOISE_WORDS: frozenset[str] = frozenset(
    {
        "PLEASE",
        "QUOTE",
        "QUOTATION",
        "PRICING",
        "PRICE",
        "PRICES",
        "PROVIDE",
        "NEEDED",
        "NEED",
        "WANT",
        "WANTED",
        "REQUIRE",
        "REQUIRED",
        "REQUIREMENT",
        "QTY",
        "QUANTITY",
        "PIECE",
        "PIECES",
        "PCS",
        "EACH",
        "EA",
        "UNITS",
        "UNIT",
        "OF",
        "FOR",
        "THE",
        "A",
        "AN",
        "TO",
        "FROM",
        "AND",
    }
)

PROTECTED_PRODUCT_TERMS: frozenset[str] = frozenset(
    {
        "HIGH",
        "VOLTAGE",
        "LOW",
        "END",
        "WHIP",
        "LIGHTING",
        "SWITCH",
        "MODULE",
        "BLACK",
        "WHITE",
        "RED",
        "LEFT",
        "RIGHT",
        "MALE",
        "FEMALE",
    }
)

assert NOISE_WORDS.isdisjoint(PROTECTED_PRODUCT_TERMS)

_TOKEN_SPAN = re.compile(r"[A-Za-z0-9]+(?:/[A-Za-z0-9]+)*")
_VOLTAGE_FOLLOW = re.compile(r"(?i)^(V|VAC|VDC|KV|VOLT|VOLTS|VOLTAGE)\b")

# Group 1 is always the numeric quantity.
QUANTITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bneed\s+(\d+)\s*[-–]\s*"),
    re.compile(r"(?i)\bneed\s+(\d+)\b"),
    re.compile(r"(?i)\bplease\s+provide\s+(\d+)\b"),
    re.compile(r"(?i)\bprovide\s+(\d+)\b"),
    re.compile(r"(?i)\bquote\s+(\d+)\b"),
    re.compile(r"(?i)\b(?:qty|quantity)\s*[:=]?\s*(\d+)\b"),
    re.compile(r"(?i)\b(\d+)\s+(?:pcs|pieces|ea|each|units|unit)\b"),
    re.compile(r"(?i)\b(\d+)\s+of\b"),
)


def _number_is_protected(text: str, number_start: int, number_end: int) -> bool:
    """True when the digits are product attributes (120V, 120 volts, 10/3), not qty."""
    window = text[max(0, number_start - 1) : min(len(text), number_end + 2)]
    if re.search(r"\d+V", window, re.IGNORECASE) or "/" in window:
        return True
    attached = text[number_end : number_end + 8]
    if attached[:1].upper() == "V" and (
        len(attached) == 1 or not attached[1].isalpha() or attached.upper().startswith("VOLT")
    ):
        return True
    return bool(_VOLTAGE_FOLLOW.match(text[number_end:].lstrip()))


def extract_quantity_from_text(raw_text: str | None) -> int | float | None:
    text = fold_whitespace(raw_text)
    if not text:
        return None
    for pattern in QUANTITY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if _number_is_protected(text, match.start(1), match.end(1)):
            continue
        return int(match.group(1))
    return None


def strip_quantity_phrases(text: str) -> str:
    updated = fold_whitespace(text)
    if not updated:
        return ""
    for pattern in QUANTITY_PATTERNS:
        current = updated

        def _replace(match: re.Match[str], current: str = current) -> str:
            if _number_is_protected(current, match.start(1), match.end(1)):
                return match.group(0)
            return " "

        updated = pattern.sub(_replace, current)
    return fold_whitespace(updated)


def remove_noise_words(text: str | None) -> str:
    """Drop whole RFQ tokens only. Never substring-replace inside product words."""
    source = fold_whitespace(text)
    if not source:
        return ""
    kept: list[str] = []
    for match in _TOKEN_SPAN.finditer(source):
        if match.group(0).upper() in NOISE_WORDS:
            continue
        kept.append(match.group(0))
    return fold_whitespace(" ".join(kept))


def strip_quantity_and_noise(text: str | None) -> str:
    return remove_noise_words(strip_quantity_phrases(fold_whitespace(text)))


@dataclass(frozen=True)
class ProductSearchText:
    original: str
    extracted_quantity: int | float | None
    after_quantity_removal: str
    after_noise_removal: str
    after_terminology: str
    tokens: tuple[str, ...]

    def as_debug_dict(self) -> dict[str, object]:
        return {
            "original_input": self.original,
            "extracted_quantity": self.extracted_quantity,
            "after_noise_removal": self.after_noise_removal,
            "after_terminology_normalization": self.after_terminology,
            "tokens": [token.lower() for token in self.tokens],
        }


def prepare_product_search_text(raw_text: str | None) -> ProductSearchText:
    original = fold_whitespace(raw_text)
    quantity = extract_quantity_from_text(original)
    after_quantity = strip_quantity_phrases(original)
    after_noise = remove_noise_words(after_quantity)
    tokens = tuple(tokenize_description(after_noise))
    after_terminology = canonical_description(after_noise)
    prepared = ProductSearchText(
        original=original,
        extracted_quantity=quantity,
        after_quantity_removal=after_quantity,
        after_noise_removal=after_noise,
        after_terminology=after_terminology,
        tokens=tokens,
    )
    logger.debug(
        "product search text original=%r qty=%s after_noise=%r terminology=%r tokens=%s",
        prepared.original,
        prepared.extracted_quantity,
        prepared.after_noise_removal,
        prepared.after_terminology,
        prepared.tokens,
    )
    return prepared
