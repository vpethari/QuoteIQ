from __future__ import annotations

import re

from matching.category_defaults import (
    expand_bare_category_query,
    expand_hole_count,
    expand_known_phrases,
)
from matching.models import ProductRecord
from matching.normalizer import fold_whitespace, normalize_text
from matching.terminology import (
    EVIDENCE_LABELS,
    NORMALIZED_DESCRIPTION_REASON,
    TOKEN_SYNONYMS,
    canonicalize_token,
    is_synonym_token,
)

from matching.units import (
    apply_unit_normalization,
    extract_dimensions,
    extract_voltages,
    voltages_conflict,
)

_TOKEN_RE = re.compile(r"[A-Z0-9]+(?:\.[0-9]+)?(?:/[A-Z0-9]+)*")
_SIZE_RE = re.compile(r"^\d+/\d+$")
_ATTACHED_UNIT = re.compile(r"^(\d+)(VAC|VDC|KV|V|A)$")
_BOX_DIM_RE = re.compile(r"^(\d+(?:X\d+){1,2})(FT|IN)?$")

STOPWORDS = frozenset(
    {
        "WITH",
        "AND",
        "THE",
        "A",
        "AN",
        "OF",
        "FOR",
        "TO",
        "X",
    }
)
INHERENT_STOPWORDS = STOPWORDS | {"W"}

ABBREV_REASON = NORMALIZED_DESCRIPTION_REASON


def split_attached_unit(token: str) -> list[str]:
    if token == "VAC":
        return ["V", "AC"]
    if token == "VDC":
        return ["V", "DC"]
    match = _ATTACHED_UNIT.fullmatch(token)
    if not match:
        return [token]
    number, unit = match.group(1), match.group(2)
    if unit == "VAC":
        return [number, "V", "AC"]
    if unit == "VDC":
        return [number, "V", "DC"]
    if unit == "A":
        # Bare "A" collides with the stopword for the article "a" and would be
        # silently dropped; "AMP" keeps the amperage unit visible as a token.
        return [number, "AMP"]
    return [number, unit]


def raw_description_tokens(value: str | None, *, apply_units: bool = True) -> list[str]:
    """Uppercase tokens before synonym mapping, with 120V split to 120|V."""
    source = apply_unit_normalization(value) if apply_units else value
    normalized = normalize_text(source)
    if not normalized:
        return []
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(normalized):
        box_match = None if _SIZE_RE.match(raw) else _BOX_DIM_RE.match(raw)
        if _SIZE_RE.match(raw):
            parts = [raw]
        elif box_match:
            # "36X24X18" or "12X12X10FT" (WxHxD enclosure/wireway dims) so each
            # dimension compares against equivalents like `36" X 24" X 18"`.
            parts = box_match.group(1).split("X")
            if box_match.group(2):
                parts.append(box_match.group(2))
        else:
            parts = raw.split("/")
        for part in parts:
            if not part:
                continue
            tokens.extend(split_attached_unit(part))
    return tokens


def tokenize_description(value: str | None, *, apply_units: bool | None = None) -> list[str]:
    """Token-based comparison form for quote text and catalog name/description.

    Productcode-like strings skip measurement rewriting so codes are not parsed as units.
    Pass `apply_units` explicitly to override that auto-detection -- retrieval's SQL
    matches against catalog text that was never unit-normalized (it's a raw generated
    column), so it needs `apply_units=False` to keep a fraction size like "1/2" as a
    literal substring instead of rewriting it to "0.5 IN", which would never match.
    """
    from matching.productcode import field_is_code_like

    if apply_units is None:
        apply_units = not (
            field_is_code_like(value)
            and not extract_voltages(value)
            and not extract_dimensions(value)
        )
    tokens: list[str] = []
    for raw in raw_description_tokens(value, apply_units=apply_units):
        mapped = canonicalize_token(raw)
        if mapped in STOPWORDS and raw == mapped:
            continue
        if raw in INHERENT_STOPWORDS and not is_synonym_token(raw) and raw == mapped:
            continue
        tokens.append(mapped)
    return tokens


def canonical_description(value: str | None) -> str:
    return " ".join(tokenize_description(value)).lower()


def expand_query_for_retrieval(value: str | None) -> str:
    """Widen a customer's free-text query with catalog vocabulary the
    customer left implicit, so retrieval finds catalog rows that carry it
    (see matching.category_defaults for the evidence behind each expansion).

    Order matters: hole-count spelling runs first since it's pure text
    rewriting; phrase expansion adds explicit synonym wording next; bare-
    category expansion runs last so it only fires once nothing else has
    already broadened the query with a qualifier of its own.
    """
    query = fold_whitespace(value)
    if not query:
        return query
    query = expand_hole_count(query)
    query = expand_known_phrases(query, tokenize_description(query))
    query = expand_bare_category_query(query, tokenize_description(query))
    return query


def catalog_unit_blob(product: ProductRecord) -> str:
    """Name/description text only. Productcode is excluded so codes are not parsed as measurements."""
    parts = [
        product.name or "",
        product.description or "",
        product.description2 or "",
    ]
    return fold_whitespace(" ".join(part for part in parts if part))


def catalog_description_blob(product: ProductRecord) -> str:
    """Text used for description retrieval. Productcode is included for matching only."""
    parts = [
        product.product_code,
        product.name or "",
        product.description or "",
        product.description2 or "",
    ]
    return fold_whitespace(" ".join(part for part in parts if part))


def description_retrieval_hit(query: str | None, product: ProductRecord) -> bool:
    """True when enough normalized description tokens overlap a catalog row."""
    query_tokens = tokenize_description(query)
    distinctive = [
        token
        for token in query_tokens
        if token.replace(".", "", 1).isdigit() or len(token) >= 3
    ]
    if len(distinctive) < 2:
        return False
    if voltages_conflict(query, catalog_unit_blob(product)):
        return False
    catalog_tokens = set(tokenize_description(catalog_description_blob(product)))
    if not catalog_tokens:
        return False
    overlap = [token for token in distinctive if token in catalog_tokens]
    if len(distinctive) >= 4:
        return len(overlap) >= 3
    return len(overlap) >= 2 and len(overlap) / max(len(distinctive), 1) >= 0.5


def abbreviation_evidence(query: str | None, catalog_value: str | None) -> list[str]:
    """Human-readable expanded→catalog mappings that actually helped this pair."""
    raw_query = raw_description_tokens(query, apply_units=False)
    catalog_tokens = set(tokenize_description(catalog_value))
    lines: list[str] = []
    index = 0
    while index < len(raw_query):
        token = raw_query[index]
        nxt = raw_query[index + 1] if index + 1 < len(raw_query) else ""
        if token.isdigit() and canonicalize_token(nxt) == "V":
            if token in catalog_tokens or "V" in catalog_tokens:
                expanded = EVIDENCE_LABELS.get(nxt, nxt.lower())
                for label in (f"{expanded} → V", f"{token} {expanded} → {token}V"):
                    if label not in lines:
                        lines.append(label)
            index += 2
            continue
        mapped = canonicalize_token(token)
        if is_synonym_token(token) and token != mapped and mapped in catalog_tokens:
            expanded = EVIDENCE_LABELS.get(token, token.lower())
            label = f"{expanded} → {mapped}"
            if label not in lines:
                lines.append(label)
        index += 1
    return lines


# Back-compat alias used by older imports/tests.
ABBREVIATION_MAP = TOKEN_SYNONYMS
