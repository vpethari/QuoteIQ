from __future__ import annotations

import re

from matching.category_defaults import interchangeable_qualifier_variants, reduce_bare_category_tokens
from matching.noise import strip_quantity_and_noise
from matching.terminology import token_variants
from matching.tokenizer import tokenize_description


_LEADING_ZERO_RE = re.compile(r"^0+(\d)")


def _strip_leading_zero(token: str) -> str:
    """A whole-number size written with a leading zero ("02\"") never
    matches the catalog's own "2" literally -- apply_units=False keeps a
    fraction like "1/2" literal on purpose (see retrieval_search_string),
    but that also means a bare leading zero on a whole number never goes
    through unit normalization (which already strips it via int()) the
    way scoring's own tokenize_description() does. Only touches a token
    that's purely digits (never "1/2" or "1-1/2", which have no leading
    zero to strip in the first place)."""
    if token.isdigit():
        return _LEADING_ZERO_RE.sub(r"\1", token)
    return token


def retrieval_search_string(query: str) -> str:
    """Lowercased retrieval string. Python still owns synonym/unit/noise handling.

    apply_units=False: `search_text` is a raw generated column, never unit-
    normalized, so a fraction size like "1/2" must stay literal here instead
    of being rewritten to "0.5 IN" -- which the catalog's own text would
    never contain.
    """
    cleaned = strip_quantity_and_noise(query)
    tokens = [
        _strip_leading_zero(token.lower()) for token in tokenize_description(cleaned, apply_units=False) if token
    ]
    if tokens:
        return " ".join(tokens)
    return cleaned.lower().strip()


def _is_distinctive(token: str) -> bool:
    """A single stray digit (e.g. "1" left over from splitting "1-5/8") matches
    almost every catalog row and adds no discriminating power, so it needs a
    higher bar than a plain length check: digit-only tokens must be at least
    2 characters (keeps real sizes like "36"/"144"), everything else just
    needs to not be a 1-2 character fragment.
    """
    bare = token.replace(".", "", 1)
    if bare.isdigit():
        return len(bare) >= 2
    return len(token) >= 3


def retrieval_search_token_groups(query: str, *, limit: int = 8) -> list[tuple[str, ...]]:
    """Expand each retrieval-worthy query token to every catalog spelling it
    could stand for (e.g. "cbl" -> ("cable", "cables", "cbl")).

    ``search_text`` stores raw, uncanonicalized catalog text, while query tokens
    are canonicalized (e.g. "cable" -> "cbl") for scoring purposes. Retrieval
    must search for any equivalent spelling so a synonym never zeroes out
    candidates that only differ in which spelling the catalog happened to use.
    """
    cleaned = strip_quantity_and_noise(query)
    # apply_units=False: see retrieval_search_string -- a fraction size must
    # stay literal ("1/2", not "0.5 IN") to match the catalog's raw text.
    # _strip_leading_zero: "02\"" must still match the catalog's own "2".
    tokens = [_strip_leading_zero(token) for token in tokenize_description(cleaned, apply_units=False)]
    distinctive = [token for token in tokens if _is_distinctive(token)]
    if not distinctive:
        distinctive = [token for token in tokens if token]
    # A bare category word's own implied default wording (e.g. "conduit" for
    # "EMT") must not become a second *required* AND term: a genuine plain
    # EMT conduit stick's own catalog text doesn't necessarily happen to
    # spell out that exact word (see reduce_bare_category_tokens).
    distinctive = reduce_bare_category_tokens(distinctive)
    # "CONDUITLBL" is a synthetic marker (see
    # matching.category_defaults._mark_leading_conduit_label) standing in
    # for a leading "Conduit:" section label -- the customer's own stated
    # product category, real intent, so PHRASE_EXPANSIONS puts "CONDUIT"
    # back for scoring. But it's never itself a literal catalog word, so it
    # must never be a retrieval search term at all, required or otherwise.
    distinctive = [token for token in distinctive if token.upper() != "CONDUITLBL"]
    # Some qualifier words are only interchangeable next to a specific other
    # word (e.g. "conduit"/"hanger" next to "clamp") -- OR the equivalent
    # spelling in at that one token position rather than requiring either
    # specific one, so a genuine match filed under the other name isn't
    # excluded by the AND search (see interchangeable_qualifier_variants).
    qualifier_variants = interchangeable_qualifier_variants(distinctive)
    limited = distinctive[:limit]
    groups = []
    for token in limited:
        variants = {variant.lower() for variant in token_variants(token)}
        extra = qualifier_variants.get(token.upper())
        if extra:
            variants |= {word.lower() for word in extra}
        groups.append(tuple(variants))
    return groups
