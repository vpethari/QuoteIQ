from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from matching.category_defaults import CATEGORY_DEFAULTS
from matching.models import ProductRecord
from matching.normalizer import fold_whitespace

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_THOUSANDS_GROUPED = re.compile(r"^\d{1,3}(,\d{3})+$")
_TRAILING_DOT_ZERO = re.compile(r"^([+-]?\d+)\.0+$")
PARTIAL_HEADLINE = "Partial Productcode / Name Match"
_PROSE_TOKENS = frozenset(
    {
        "LIGHTING",
        "WHIP",
        "CABLE",
        "SWITCH",
        "MODULE",
        "CONDUIT",
        "HEAD",
        "EXT",
        "END",
        "DOUBLE",
        "VOLTAGE",
    }
    # Bare category/material words (PVC, EMT, GRC, LT, STRUT, CHANNEL) are
    # short and alphabetic like a real code fragment, so a query like
    # "1 PVC" was passing is_product_code_query() and getting routed to
    # identifier-substring search instead of description search -- "1" and
    # "PVC" both look code-shaped in isolation, but together they're a bare
    # description, not a part number.
    | frozenset(CATEGORY_DEFAULTS)
)


def productcode_as_text(value: object | None) -> str:
    """Return Productcode as a string. Never thousands-group, never keep float .0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return str(value).strip()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return format(value.quantize(Decimal(1)), "f")
        return format(value, "f")
    text = str(value).strip()
    if not text:
        return ""
    if _THOUSANDS_GROUPED.fullmatch(text):
        return text.replace(",", "")
    dotted = _TRAILING_DOT_ZERO.fullmatch(text)
    if dotted:
        return dotted.group(1)
    return text


def normalize_code_text(value: str | None) -> str:
    """Uppercase, trim, and collapse whitespace for Productcode/name comparison."""
    return fold_whitespace(productcode_as_text(value)).upper()


def compact_code(value: str | None) -> str:
    return _NON_ALNUM.sub("", normalize_code_text(value))


def code_tokens(value: str | None) -> list[str]:
    text = normalize_code_text(value)
    if not text:
        return []
    return [token for token in text.split(" ") if token]


def compact_token(token: str) -> str:
    return _NON_ALNUM.sub("", token.upper())


def is_generic_code_token(token: str) -> bool:
    compact = compact_token(token)
    if any(character.isdigit() for character in compact):
        return False
    return len(compact) <= 2


def is_product_code_query(query: str | None) -> bool:
    tokens = code_tokens(query)
    if not tokens or len(tokens) > 6:
        return False
    return not any(token in _PROSE_TOKENS for token in tokens)


def field_is_code_like(value: str | None) -> bool:
    """True for compact catalog identifiers, not prose descriptions."""
    tokens = code_tokens(value)
    if not tokens or len(tokens) > 8:
        return False
    if any(token in _PROSE_TOKENS for token in tokens):
        return False
    compact = compact_code(value)
    return bool(compact) and any(character.isdigit() for character in compact)


def embedded_query_hits(query: str | None, catalog_value: str | None) -> list[str]:
    """Query tokens found as substrings of the catalog compact alphanumeric form."""
    catalog_compact = compact_code(catalog_value)
    if not catalog_compact:
        return []
    hits: list[str] = []
    for token in code_tokens(query):
        compact = compact_token(token)
        if len(compact) >= 2 and compact in catalog_compact:
            hits.append(token)
    return hits


def identifier_retrieval_hit(query: str | None, product: ProductRecord) -> bool:
    """True when Productcode/name/description compact text contains distinctive query tokens."""
    distinctive = [token for token in code_tokens(query) if not is_generic_code_token(token) and len(compact_token(token)) >= 2]
    if not distinctive:
        return False
    blobs = [
        compact_code(product.product_code),
        compact_code(product.name),
        compact_code(product.description),
        compact_code(product.description2),
    ]
    matched = 0
    for token in distinctive:
        compact = compact_token(token)
        if any(compact and compact in blob for blob in blobs):
            matched += 1
    generic_hits = 0
    for token in code_tokens(query):
        if is_generic_code_token(token) and any(compact_token(token) in blob for blob in blobs if blob):
            generic_hits += 1
    if matched == 0:
        return False
    if len(code_tokens(query)) == 1:
        return len(compact_token(code_tokens(query)[0])) >= 4
    return matched + generic_hits >= 2 or matched >= 2 or (matched == 1 and len(compact_token(distinctive[0])) >= 4)


PARTIAL_MAX = 78.0
NORMALIZED_HEADLINE = "Normalized Productcode Match"
EXACT_IDENTITY_TYPES = frozenset({"exact", "normalized_exact"})
IDENTITY_MATCH_TYPES = frozenset({"exact", "normalized_exact", "partial"})


def _identifier_payload(
    *,
    score: float,
    match_type: str,
    headline: str,
    matching_tokens: list[str],
    extra: list[str],
    query_norm: str,
    query_compact: str,
    catalog_norm: str,
    catalog_compact: str,
) -> dict[str, Any]:
    return {
        "score": score,
        "match_type": match_type,
        "matching_tokens": matching_tokens,
        "additional_catalog_tokens": extra,
        "query_normalized": query_norm,
        "query_compact": query_compact,
        "catalog_normalized": catalog_norm,
        "catalog_compact": catalog_compact,
        "headline": headline,
    }


def score_product_code_identifier(query: str | None, catalog_value: str | None) -> tuple[float, dict[str, Any]]:
    """Exact / normalized / partial Productcode identity. Partial is never ~100%."""
    query_norm = normalize_code_text(query)
    catalog_norm = normalize_code_text(catalog_value)
    empty = _identifier_payload(
        score=0.0,
        match_type="none",
        headline="",
        matching_tokens=[],
        extra=[],
        query_norm=query_norm,
        query_compact=compact_code(query_norm),
        catalog_norm=catalog_norm,
        catalog_compact=compact_code(catalog_norm),
    )
    if not query_norm or not catalog_norm:
        return 0.0, empty

    query_tokens = code_tokens(query_norm)
    catalog_tokens = code_tokens(catalog_norm)
    extra = [token for token in catalog_tokens if compact_token(token) not in compact_code(query_norm)]
    query_compact = compact_code(query_norm)
    catalog_compact = compact_code(catalog_norm)

    if query_norm == catalog_norm or (query_compact and query_compact == catalog_compact):
        normalized_only = query_norm != catalog_norm
        match_type = "normalized_exact" if normalized_only else "exact"
        headline = NORMALIZED_HEADLINE if normalized_only else "Exact Productcode Match"
        evidence = _identifier_payload(
            score=100.0,
            match_type=match_type,
            headline=headline,
            matching_tokens=[f"{token} → {token}" for token in query_tokens] or [query_compact],
            extra=extra,
            query_norm=query_norm,
            query_compact=query_compact,
            catalog_norm=catalog_norm,
            catalog_compact=catalog_compact,
        )
        return 100.0, evidence

    if len(query_tokens) == 1 and is_generic_code_token(query_tokens[0]):
        return 0.0, empty
    if len(query_compact) < 4:
        return 0.0, empty

    matching_tokens: list[str] = []
    if catalog_compact.startswith(query_compact) and len(query_compact) < len(catalog_compact):
        ratio = len(query_compact) / len(catalog_compact)
        score = round(min(PARTIAL_MAX, 38.0 + 42.0 * ratio), 4)
        matching_tokens = [f"{query_compact} → {catalog_compact} (prefix)"]
    else:
        hits = embedded_query_hits(query_norm, catalog_norm)
        distinctive_hits = [token for token in hits if not is_generic_code_token(token)]
        eligible = [token for token in query_tokens if len(compact_token(token)) >= 2]
        if not distinctive_hits:
            return 0.0, empty
        coverage = len(hits) / max(len(eligible), 1)
        if coverage < 0.67:
            return 0.0, empty
        score = round(min(PARTIAL_MAX, 36.0 + 32.0 * coverage - 6.0 * min(len(extra), 3)), 4)
        for token in hits:
            compact = compact_token(token)
            host = next((item for item in catalog_tokens if compact in compact_token(item)), catalog_compact)
            matching_tokens.append(f"{token} → {host}")
        if score < 40.0:
            return 0.0, empty

    evidence = _identifier_payload(
        score=score,
        match_type="partial",
        headline=PARTIAL_HEADLINE,
        matching_tokens=matching_tokens,
        extra=extra,
        query_norm=query_norm,
        query_compact=query_compact,
        catalog_norm=catalog_norm,
        catalog_compact=catalog_compact,
    )
    return score, evidence
