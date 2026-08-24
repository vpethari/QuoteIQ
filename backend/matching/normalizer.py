from __future__ import annotations

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s/]+", re.UNICODE)
_PN_WRAP = re.compile(r"^[\s\"'`(\[{<]+|[\"'`)\]}>.,;:]+$")
_AROUND_SEP = re.compile(r"\s*([/\-_.+])\s*")
_SALSIFY_PREFIX = re.compile(r"^NA1-", re.IGNORECASE)
_UNICODE_HYPHENS = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")

SYNONYMS: dict[str, str] = {
    "LTG": "LIGHTING",
    "LTGS": "LIGHTING",
    "WHIPS": "WHIP",
    "CABLES": "CABLE",
    "MODULES": "MODULE",
    "SWITCHES": "SWITCH",
}


def fold_whitespace(value: str | None) -> str:
    """NFC, map Unicode spaces (including NBSP) to ASCII, collapse, strip.

    Display case is preserved. Used for both quote cells and catalog cells.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = text.translate(_UNICODE_HYPHENS)
    text = "".join(" " if ch.isspace() else ch for ch in text)
    return _WHITESPACE.sub(" ", text).strip()


def normalize_text(value: str | None) -> str:
    """Uppercase comparison form for descriptions.

    `/` is kept so sizes such as `10/3` and connectors such as `W/PAULEX`
    stay intact. Original customer text is never overwritten.
    """
    text = fold_whitespace(value).upper()
    if not text:
        return ""
    text = text.replace("&", " AND ")
    text = _AROUND_SEP.sub(r"\1", text)
    text = _PUNCTUATION.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def normalize_part_number(value: str | None) -> str:
    """Normalize a Salsify ID or official catalog number for exact comparison.

    Meaningful ``-``, ``/``, ``_``, ``.``, and ``+`` are preserved.
    The ``NA1-`` Salsify prefix is NOT stripped here; Salsify IDs and
    official catalog numbers are compared independently.
    """
    text = fold_whitespace(value).upper()
    if not text:
        return ""
    for _ in range(4):
        stripped = _PN_WRAP.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    text = _AROUND_SEP.sub(r"\1", text)
    return _WHITESPACE.sub("", text)


def catalog_number_from_salsify_id(value: str | None) -> str:
    """Derive the catalog-number portion of an ``NA1-`` Salsify ID.

    This is a display/debug helper only. Matching must look up the full
    Salsify ID and the official catalog number independently and must not
    replace ``NA1-2DDDA10-HV`` with ``2DDDA10-HV``.
    """
    text = normalize_part_number(value)
    if _SALSIFY_PREFIX.match(text):
        remainder = _SALSIFY_PREFIX.sub("", text, count=1)
        return remainder
    return ""


def part_numbers_equivalent(left: str | None, right: str | None) -> bool:
    a = normalize_part_number(left)
    b = normalize_part_number(right)
    return bool(a) and a == b


def canonical_text(value: str | None) -> str:
    """Normalized comparison string with synonyms expanded and stopwords removed."""
    from matching.tokenizer import tokenize_description

    return " ".join(tokenize_description(value))
