from __future__ import annotations

import re

from matching.category_defaults import (
    decode_label_marker_token,
    interchangeable_qualifier_variants,
    is_leading_label_marker,
    reduce_bare_category_tokens,
    reduce_tray_filler_tokens,
)
from matching.noise import strip_quantity_and_noise
from matching.terminology import token_variants
from matching.tokenizer import tokenize_description


_LEADING_ZERO_RE = re.compile(r"^0+(\d)")


def _restore_label_tokens(tokens: list[str]) -> list[str]:
    """Expand a leading-label marker token back into its literal words, in
    place of the marker -- used for retrieval's *first* attempt, where the
    label word should be treated exactly like any other required word (see
    catalog.postgres_repository.search_text_candidates: most labels really
    are spelled out in the matching catalog family -- e.g. "Coupling:" --
    and requiring it there is a genuine, useful discriminator, not noise;
    dropping it unconditionally, as retrieval used to, let an unrelated PVC
    elbow fitting tie a genuine coupling on token overlap and outrank it.
    Only the confirmed cases (Conduit:, Cable Tray:) where the label is
    never actually excluded need it dropped -- and only as a fallback once
    requiring it finds nothing at all, not by default."""
    expanded: list[str] = []
    for token in tokens:
        decoded = decode_label_marker_token(token)
        expanded.extend(decoded if decoded is not None else [token])
    return expanded


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


def retrieval_search_string(query: str, *, restore_label: bool = True) -> str:
    """Lowercased retrieval string. Python still owns synonym/unit/noise handling.

    apply_units=False: `search_text` is a raw generated column, never unit-
    normalized, so a fraction size like "1/2" must stay literal here instead
    of being rewritten to "0.5 IN" -- which the catalog's own text would
    never contain.

    restore_label: see retrieval_search_token_groups.
    """
    cleaned = strip_quantity_and_noise(query)
    raw_tokens = [token for token in tokenize_description(cleaned, apply_units=False) if token]
    raw_tokens = _restore_label_tokens(raw_tokens) if restore_label else [
        token for token in raw_tokens if not is_leading_label_marker(token)
    ]
    tokens = [_strip_leading_zero(token.lower()) for token in raw_tokens]
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


def retrieval_search_token_groups(
    query: str, *, limit: int = 8, restore_label: bool = True
) -> list[tuple[str, ...]]:
    """Expand each retrieval-worthy query token to every catalog spelling it
    could stand for (e.g. "cbl" -> ("cable", "cables", "cbl")).

    ``search_text`` stores raw, uncanonicalized catalog text, while query tokens
    are canonicalized (e.g. "cable" -> "cbl") for scoring purposes. Retrieval
    must search for any equivalent spelling so a synonym never zeroes out
    candidates that only differ in which spelling the catalog happened to use.

    restore_label: a leading "<Category>:" RFQ label (see
    matching.category_defaults) is usually a genuinely useful, literal
    catalog word -- confirmed live, unconditionally dropping "Coupling:"
    let an unrelated PVC elbow fitting tie a genuine coupling on token
    overlap and outrank it. So by default (True) the label's real words are
    restored and required exactly like any other query word. Only
    catalog.postgres_repository.search_text_candidates passes False, and
    only as a fallback once that default search finds nothing at all --
    the confirmed rescue case (e.g. "Conduit:" over an Innerduct family
    that never spells "conduit" out).
    """
    cleaned = strip_quantity_and_noise(query)
    # apply_units=False: see retrieval_search_string -- a fraction size must
    # stay literal ("1/2", not "0.5 IN") to match the catalog's raw text.
    # _strip_leading_zero: "02\"" must still match the catalog's own "2".
    raw_tokens = tokenize_description(cleaned, apply_units=False)
    raw_tokens = _restore_label_tokens(raw_tokens) if restore_label else [
        token for token in raw_tokens if not is_leading_label_marker(token)
    ]
    tokens = [_strip_leading_zero(token) for token in raw_tokens]
    distinctive = [token for token in tokens if _is_distinctive(token)]
    if not distinctive:
        distinctive = [token for token in tokens if token]
    # A bare category word's own implied default wording (e.g. "conduit" for
    # "EMT") must not become a second *required* AND term: a genuine plain
    # EMT conduit stick's own catalog text doesn't necessarily happen to
    # spell out that exact word (see reduce_bare_category_tokens).
    distinctive = reduce_bare_category_tokens(distinctive)
    # Same treatment for cable-tray-specific filler words ("ladder", and
    # "wide"/"long" right after a dimension) -- see
    # matching.category_defaults.reduce_tray_filler_tokens.
    distinctive = reduce_tray_filler_tokens(distinctive)
    # A repeated word must occupy only one required token *position*, not
    # one per occurrence -- confirmed live: restoring a leading label whose
    # own word coincidentally repeats later in the line ("Cable Tray:
    # Ladder Tray...", "tray" both as the label and the body's own noun)
    # produced two separate "tray" positions from one real signal. The
    # partial-match SQL (postgres_repository.partial_search_text_sql)
    # counts *distinct token positions* satisfied, so a single literal
    # "tray" substring in an unrelated candidate's text satisfied both
    # positions at once -- letting an unrelated cable product clear the
    # 60% overlap floor on "cable"+"tray" alone, without needing to also
    # match either dimension, and outrank the genuine tray family. A
    # catalog row's real content shouldn't count more just because the
    # customer's own phrasing happened to repeat a word.
    seen: set[str] = set()
    deduped: list[str] = []
    for token in distinctive:
        upper = token.upper()
        if upper in seen:
            continue
        seen.add(upper)
        deduped.append(token)
    distinctive = deduped
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
