from __future__ import annotations

import re

from matching.category_defaults import (
    bare_category_required_word,
    decode_label_marker_token,
    interchangeable_qualifier_variants,
    is_leading_label_marker,
    reduce_bare_category_tokens,
    reduce_tray_filler_tokens,
)
from matching.noise import strip_quantity_and_noise
from matching.terminology import token_variants
from matching.tokenizer import tokenize_description
from matching.units import PLAUSIBLE_FRACTION_DENOMINATORS

_LEADING_ZERO_RE = re.compile(r"^0+(\d)")
_GAUGE_NOTATION_RE = re.compile(r"^(\d{1,2})([/-])(\d{1,2})$")

# Retrieval-only "STL" <-> "STEEL" equivalence -- confirmed live, this
# catalog spells "Steel" out in 13,134 rows and abbreviates it as "STL" in
# only 40, so a customer's "STL" (e.g. "MC PLUS STL 10/3...") required the
# literal abbreviation and never matched any of the 13,134 genuine
# steel-armored rows, returning zero candidates. NOT a matching.terminology
# TOKEN_VARIANTS entry: tokenize_description() applies that table's
# canonicalization globally, and category_defaults.py already has two
# *different* pre-existing behaviors that each depend on one specific raw
# spelling surviving untouched -- PHRASE_EXPANSIONS keys a trigger on the
# literal frozenset({"STL", "SS"}) ("STEEL SET SCREW"), while
# expand_bare_category_query keys another trigger on literal "STEEL FLEX"
# (-> implies conduit). Canonicalizing either spelling away would silently
# break the other's lookup, so this stays scoped to retrieval's own token
# expansion instead, exactly like the gauge-notation variant above.
_STL_STEEL_VARIANTS: dict[str, str] = {"STL": "steel", "STEEL": "stl"}


def _gauge_notation_variant(token: str) -> str | None:
    """A wire-gauge/conductor-count token ("10/3", "12-2") written with the
    "wrong" separator for a given catalog row never matches literally --
    confirmed live, this catalog spells the same "10 AWG, 3 conductor"
    concept as both "10-3" and "10/3" depending on the row (~1,676 rows
    hyphenated, ~7,133 slashed; "MC PLUS STL 10/3..." only found the
    hyphenated "10-3" row once this variant was added). Skipped when the
    second number is a plausible fraction denominator (see
    matching.units.PLAUSIBLE_FRACTION_DENOMINATORS) -- a real dimension
    like "1/2" must never also search for "1-2"."""
    match = _GAUGE_NOTATION_RE.match(token)
    if not match:
        return None
    if int(match.group(3)) in PLAUSIBLE_FRACTION_DENOMINATORS:
        return None
    swapped_sep = "-" if match.group(2) == "/" else "/"
    return f"{match.group(1)}{swapped_sep}{match.group(3)}"


def _restore_label_tokens(tokens: list[str], *, head_noun_only: bool = False) -> list[str]:
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
    requiring it finds nothing at all, not by default.

    head_noun_only: see matching.category_defaults.decode_label_marker_token
    -- the middle fallback tier for a multi-word label, keeping just its
    head noun (e.g. "Tray") required."""
    expanded: list[str] = []
    for token in tokens:
        decoded = decode_label_marker_token(token, head_noun_only=head_noun_only)
        expanded.extend(decoded if decoded is not None else [token])
    return expanded


def _apply_label_mode(tokens: list[str], label_mode: str) -> list[str]:
    if label_mode == "full":
        return _restore_label_tokens(tokens)
    if label_mode == "head_noun":
        return _restore_label_tokens(tokens, head_noun_only=True)
    return [token for token in tokens if not is_leading_label_marker(token)]


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


def retrieval_search_string(query: str, *, label_mode: str = "full") -> str:
    """Lowercased retrieval string. Python still owns synonym/unit/noise handling.

    apply_units=False: `search_text` is a raw generated column, never unit-
    normalized, so a fraction size like "1/2" must stay literal here instead
    of being rewritten to "0.5 IN" -- which the catalog's own text would
    never contain.

    label_mode: see retrieval_search_token_groups.
    """
    cleaned = strip_quantity_and_noise(query)
    raw_tokens = [token for token in tokenize_description(cleaned, apply_units=False) if token]
    raw_tokens = _apply_label_mode(raw_tokens, label_mode)
    tokens = [_strip_leading_zero(token.lower()) for token in raw_tokens]
    if tokens:
        return " ".join(tokens)
    return cleaned.lower().strip()


def _is_distinctive(token: str, *, next_token: str | None = None) -> bool:
    """A single stray digit (e.g. "1" left over from splitting "1 1/2\"" into
    "1", "1/2") matches almost every catalog row and adds no discriminating
    power on its own -- but only when it really is that kind of leftover, not
    when it's the query's only, genuine whole-number size (e.g. "4\"" in "4\"
    GRC STRUT CLAMP"). The two are told apart by what comes right after: a
    mixed-fraction's leading whole part is always immediately followed by
    the fraction itself ("1", then "1/2"); a real bare size never is.

    Confirmed live: dropping "4" unconditionally made "4\" GRC STRUT CLAMP"
    and "3\" GRC STRUT CLAMP" retrieve identically, and the genuinely correct
    4" clamp (P1121-EG) was lost among 200+ other same-family candidates
    tied at the same partial-match count, with no signal left to rank it
    above them -- confirmed the single highest word_similarity of the whole
    tied group, yet excluded from the LIMIT cutoff entirely.
    """
    bare = token.replace(".", "", 1)
    if bare.isdigit():
        if len(bare) >= 2:
            return True
        return not (next_token and "/" in next_token)
    return len(token) >= 3


def retrieval_search_token_groups(
    query: str, *, limit: int = 8, label_mode: str = "full"
) -> list[tuple[str, ...]]:
    """Expand each retrieval-worthy query token to every catalog spelling it
    could stand for (e.g. "cbl" -> ("cable", "cables", "cbl")).

    ``search_text`` stores raw, uncanonicalized catalog text, while query tokens
    are canonicalized (e.g. "cable" -> "cbl") for scoring purposes. Retrieval
    must search for any equivalent spelling so a synonym never zeroes out
    candidates that only differ in which spelling the catalog happened to use.

    label_mode: a leading "<Category>:" RFQ label (see
    matching.category_defaults) is usually a genuinely useful, literal
    catalog word -- confirmed live, unconditionally dropping "Coupling:"
    let an unrelated PVC elbow fitting tie a genuine coupling on token
    overlap and outrank it. So by default ("full") the label's real words
    are restored and required exactly like any other query word. Only
    catalog.postgres_repository.search_text_candidates passes anything
    else, and only as a fallback once that default search finds nothing at
    all:
    - "head_noun" keeps just the label's last word (e.g. "Tray" in "Cable
      Tray") required, dropping only the qualifier ("Cable"/"Coupling
      Category"/etc.) -- tried before ever fully dropping a multi-word
      label. Confirmed live: dropping "Tray" too let an unrelated PVC
      conduit elbow satisfy "90"/"degree"/"bend" alone and surface for
      "Cable Tray: 90 Degree Bend R12\" W36\"".
    - "dropped" removes the label entirely -- the confirmed rescue case
      for a single-word label (e.g. "Conduit:" over an Innerduct family
      that never spells "conduit" out at all). Never used for a
      multi-word label -- see search_text_candidates.
    """
    cleaned = strip_quantity_and_noise(query)
    # apply_units=False: see retrieval_search_string -- a fraction size must
    # stay literal ("1/2", not "0.5 IN") to match the catalog's raw text.
    # _strip_leading_zero: "02\"" must still match the catalog's own "2".
    raw_tokens = tokenize_description(cleaned, apply_units=False)
    raw_tokens = _apply_label_mode(raw_tokens, label_mode)
    tokens = [_strip_leading_zero(token) for token in raw_tokens]
    distinctive = [
        token
        for index, token in enumerate(tokens)
        if _is_distinctive(token, next_token=tokens[index + 1] if index + 1 < len(tokens) else None)
    ]
    if not distinctive:
        distinctive = [token for token in tokens if token]
    # A bare category word's own implied default wording (e.g. "conduit" for
    # "EMT") must not become a second *required* AND term: a genuine plain
    # EMT conduit stick's own catalog text doesn't necessarily happen to
    # spell out that exact word (see reduce_bare_category_tokens).
    distinctive = reduce_bare_category_tokens(distinctive)
    # The flip side of the drop above: a few categories' own default phrase
    # names the ONE word that actually discriminates the genuine product
    # from same-material-but-different-category rows sharing generic words
    # like "PVC"/"Conduit" -- see
    # matching.category_defaults.CATEGORY_DEFAULT_REQUIRED_WORDS for the
    # confirmed, narrowly-scoped evidence (only appends a word for a
    # category actually listed there; every other category is unaffected).
    required_word = bare_category_required_word(distinctive)
    if required_word and required_word.upper() not in {token.upper() for token in distinctive}:
        distinctive.append(required_word)
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
        gauge_variant = _gauge_notation_variant(token)
        if gauge_variant:
            variants.add(gauge_variant.lower())
        stl_steel_variant = _STL_STEEL_VARIANTS.get(token.upper())
        if stl_steel_variant:
            variants.add(stl_steel_variant)
        groups.append(tuple(variants))
    return groups
