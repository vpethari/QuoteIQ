from __future__ import annotations

import re

"""Seed data dictionary: what a bare material/category word means when a
customer gives no other product-type noun to go on.

This is deliberately separate from ``matching.terminology``'s synonym table.
Terminology maps *equivalent spellings* of the same word (CBL == CABLE);
this maps a *missing* word the customer left implicit ("PVC" alone almost
always means "PVC CONDUIT" in practice, not a PVC fitting/box/strap/washer).

Keep this list small and evidence-based -- add an entry only once you've
confirmed it from real usage (how these bare queries actually got resolved),
not by guessing. An entry that's wrong for even a meaningful minority of
cases will silently misdirect matching for every query that hits it.
"""

CATEGORY_DEFAULTS: dict[str, str] = {
    "PVC": "SCH40 BE CONDUIT GRAY",
    "EMT": "CONDUIT",
    "GRC": "GALVANIZED RIGID CONDUIT",
    "LT": "LIQUID TIGHT",
    # Bare "STRUT"/"CHANNEL" with no length or finish given -- the catalog's
    # strut channel line is overwhelmingly stocked in 10' lengths with a
    # Pre-Galvanized (PG) finish, so that's the safest default absent any
    # other qualifier.
    "STRUT": "10 FT PG",
    "CHANNEL": "10 FT PG",
}

# Unit markers that tokenize_description() produces from a size expression
# (e.g. "1\"" -> "1", "IN") -- these describe the *number* before them, not
# the product, so they must not count as a second descriptive word (see
# _is_descriptive_token) or as ordinary vocabulary in plain token overlap
# (see scoring._token_prepared): whether one appears depends only on whether
# that particular row happens to write its size with an explicit unit or not
# (this catalog is inconsistent about it), not on any real content difference.
UNIT_MARKER_TOKENS = frozenset({"IN", "FT", "V", "AMP"})


def _is_descriptive_token(token: str) -> bool:
    """True for a real product-describing word; false for a bare
    size/number ("1", "3/4") or a unit marker ("IN", "FT") attached to one.
    """
    if token in UNIT_MARKER_TOKENS:
        return False
    return any(character.isalpha() for character in token)


def _bare_category_redundant_extras(tokens: list[str]) -> tuple[str, list[str]] | None:
    """If `tokens` is a size plus a single bare category word, optionally
    with extra words that are already part of that category's own default
    phrase, return (category, extra_tokens); otherwise None.

    e.g. "1\" PVC" -> ("PVC", []); "1 1/2\" GRC GALV" -> ("GRC", ["GALV"])
    since GRC already implies "galvanized"; but "1\" PVC COUPLING" -> None,
    since "coupling" isn't part of the PVC default and so is a genuinely
    different, more specific request the customer actually typed.
    """
    from matching.description_normalize import tokenize_description

    descriptive = [token for token in tokens if _is_descriptive_token(token)]
    category_matches = [token for token in descriptive if token.upper() in CATEGORY_DEFAULTS]
    if len(category_matches) != 1:
        return None
    category = category_matches[0].upper()
    default_tokens = {token.upper() for token in tokenize_description(CATEGORY_DEFAULTS[category])}
    extra = [token for token in descriptive if token.upper() != category]
    if any(token.upper() not in default_tokens for token in extra):
        return None
    return category, extra


def expand_bare_category_query(query: str, tokens: list[str]) -> str:
    """Append the implied qualifier when the query is a size plus a bare
    category word, optionally with extra words that are already part of that
    category's own default phrase -- e.g. "1\" PVC" -> "1\" PVC SCH40 BE
    CONDUIT GRAY", and "1 1/2\" GRC GALV" also expands (GRC already implies
    "galvanized"), but "1\" PVC COUPLING" does not, since "coupling" isn't
    part of the PVC default and so is a genuinely different, more specific
    request the customer actually typed. Without this allowance, a customer
    who redundantly names an attribute the category already implies (adding
    "GALV" to "GRC") would silently lose the whole default expansion instead
    of just being a little repetitive.
    """
    match = _bare_category_redundant_extras(tokens)
    if match is None:
        return query
    category, _extra = match
    return f"{query} {CATEGORY_DEFAULTS[category]}"


def reduce_bare_category_tokens(tokens: list[str]) -> list[str]:
    """Drop redundant extra words from a bare-category-plus-own-default query
    (see _bare_category_redundant_extras) before they become *required*
    retrieval tokens -- e.g. "EMT CONDUIT" only needs "EMT" to be eligible,
    since "conduit" is already what EMT implies. Confirmed live: a genuine
    plain 3/4" EMT conduit stick's own catalog text never happens to say
    "conduit" (it spells out "Electrical Metallic Tubing" instead), so
    requiring both words as a strict AND silently excluded it from
    retrieval entirely, leaving only unrelated straps/couplings that
    happened to literally contain "conduit" in their own text.
    """
    match = _bare_category_redundant_extras(tokens)
    if match is None:
        return tokens
    _category, extra = match
    if not extra:
        return tokens
    extra_upper = {token.upper() for token in extra}
    return [token for token in tokens if token.upper() not in extra_upper]


# Same idea as CATEGORY_DEFAULTS, but for color: when a category is sold in
# several color variants and the customer names no color, this is the
# industry-standard/most-common one to assume -- e.g. PVC conduit defaults
# to gray. Same rule applies: add an entry only once it's confirmed, since a
# wrong default here would silently rank the wrong color first.
DEFAULT_COLORS: dict[str, str] = {
    "PVC": "GRAY",
}

_COLOR_WORDS = frozenset(
    {"GRAY", "GREY", "ORANGE", "WHITE", "BUFF", "BROWN", "GREEN", "BLACK", "RED", "BLUE", "YELLOW", "PURPLE"}
)


def query_mentions_color(tokens: list[str]) -> bool:
    return any(token in _COLOR_WORDS for token in tokens)


def default_color_for_query(tokens: list[str]) -> str | None:
    """If the query names a category with a known default color and doesn't
    specify a color itself, return that default (e.g. PVC -> GRAY)."""
    if query_mentions_color(tokens):
        return None
    for token in tokens:
        color = DEFAULT_COLORS.get(token.upper())
        if color:
            return color
    return None


def candidate_color_conflicts(tokens: list[str], default_color: str) -> bool:
    """True when a candidate's `tokens` name a color other than `default_color`
    (the assumed default for a category the customer's query implied but left
    unstated) -- e.g. a customer's bare "PVC" implies gray, so a candidate
    explicitly labeled "ORANGE" is very likely a different, unrequested part.
    """
    token_set = {token.upper() for token in tokens}
    return bool((token_set & _COLOR_WORDS) - {default_color.upper()})


# Stainless steel and plain (zinc-plated) steel are separate, non-interchangeable
# product lines that happen to share most of their descriptive vocabulary --
# e.g. "1/2\" EMT ONE HOLE STRAP" comes in both a Steel Zinc Plated part and a
# near-identically-worded Stainless Steel - 316 part. Because the plain part's
# query word "STEEL" is also a substring of "STAINLESS STEEL" (both canonicalize
# to the same STL token), nothing about token overlap tells them apart, and the
# stainless part's extra grade wording ("316", "#4 Polished Finish") gave it no
# particular disadvantage either -- so it could silently outrank the correct,
# far more commonly ordered plain-steel part on pure word-overlap noise, at no
# lower confidence than a real, uncontested match.
#
# Checked against each field's *raw* text (not the canonicalized token set,
# where "STAINLESS" and the catalog's own "SS" abbreviation collapse to the
# same token) because this catalog also uses "SS" to mean "Set Screw" in
# unrelated contexts (see PHRASE_EXPANSIONS above) -- "STAINLESS" as a whole
# word is the one unambiguous signal for this specific material distinction.
_STAINLESS_MARKER = "STAINLESS"


def mentions_stainless(raw_text: str) -> bool:
    return _STAINLESS_MARKER in raw_text.upper()


# Same shape of problem again, for "with spring" vs. "no spring" channel
# nuts: the catalog spells the two variants of the same size "Strut Channel
# Nut, 1/2\"-13, No Spring" and "..., With Standard Spring" -- both contain
# the literal word "spring", so plain word overlap can't tell a query that
# wants one from a candidate that is explicitly the other. Unlike the
# stainless/specialty checks above, this needs a *negation* phrase match
# ("no spring") rather than a plain marker word, since "spring" alone is the
# word both variants share.
_NO_SPRING_MARKER = "NO SPRING"


def wants_spring_nut(tokens: list[str]) -> bool:
    token_set = {token.upper() for token in tokens}
    return {"SPRING", "NUT"} <= token_set


def mentions_no_spring(raw_text: str) -> bool:
    return _NO_SPRING_MARKER in raw_text.upper()


# Same shape of problem as stainless-vs-plain-steel, for fitting shape/grade
# instead of material: a plain fitting or a standard-length stick of conduit
# and a product that is actually something else -- a 90-degree elbow, a
# multi-standard "Super Fitting" adapter, a coupling that transitions EMT to
# threaded rigid/IMC/GRC conduit, or a short pre-cut nipple -- share almost
# all their wording (the conduit type, steel, the size), because the catalog
# also gives the elbow/adapter/nipple's own matching end the word "coupling"
# or names its conduit type the same way a plain stick does. A query that
# names only the plain product ("EMT STL COMP CPLG", or a bare "1 1/2\" GRC"
# meaning the standard 10' stick) never says "elbow", "super fitting", a
# second conduit type like "rigid", or "nipple", so a candidate carrying one
# of these markers the query never asked for is very likely a different, more
# specialized part than the one requested, even though it scores as a strong
# text match otherwise. Add a marker here only once a real case like this one
# confirms it -- same evidence bar as the rest of this file.
_SPECIALTY_VARIANT_MARKERS: tuple[str, ...] = (
    "ELBOW",
    "SUPER FITTING",
    "RIGID",
    "THREADED",
    "IMC",
    "GRC",
    "NIPPLE",
)


def _word_present(text_upper: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text_upper) is not None


def unrequested_specialty_marker(query_raw: str, candidate_raw: str) -> str | None:
    """The first specialty-variant marker present in the candidate's text but
    absent from the query's, or None if there isn't one.

    A marker doesn't count as unrequested if it's already implied by a
    category the query names -- e.g. "RIGID" is part of what "GRC" itself
    means (see CATEGORY_DEFAULTS), so a query for "1 1/2\" GRC 90 DEG ELBOW"
    doesn't need to spell out "rigid" for a genuine GRC elbow's own "Galvanized
    Rigid Conduit" wording to not count against it. Without this, the marker
    meant to catch a conduit-type *mismatch* (an EMT query landing on a
    rigid-transition fitting) instead penalizes the correct GRC-family part
    for describing its own, requested category.
    """
    query_upper = query_raw.upper()
    candidate_upper = candidate_raw.upper()
    implied_categories = [abbrev for abbrev in CATEGORY_DEFAULTS if _word_present(query_upper, abbrev)]
    for marker in _SPECIALTY_VARIANT_MARKERS:
        if marker not in candidate_upper or _word_present(query_upper, marker):
            continue
        if any(marker in CATEGORY_DEFAULTS[category].upper() for category in implied_categories):
            continue
        return marker
    return None


# Some abbreviation pairs only mean something specific when read *together*
# -- read separately, each one has a different, more generic meaning (e.g.
# "SS" alone commonly reads as "stainless steel", but in "STL SS" here it
# means "SET SCREW", a connector type, not a material). Keyed by the set of
# trigger tokens (order-independent, all must be present); the expansion is
# appended, not a replacement, so the original words stay searchable too.
PHRASE_EXPANSIONS: dict[frozenset[str], str] = {
    frozenset({"STL", "SS"}): "STEEL SET SCREW",
    # "Conduit clamp" and "hanger clamp" are filed as separate catalog lines
    # (conduit clamp brackets/parallel conduit clamps vs. J-hangers), but
    # customers use the two names interchangeably for the same intent.
    # Appending the other wording here helps *scoring* rank whichever term
    # the catalog happens to use -- but retrieval also needs its own fix
    # (see _INTERCHANGEABLE_QUALIFIERS below): confirmed live, a bare
    # "CONDUIT CLAMP" query retrieves 46 candidates and zero of them are the
    # "Hanger Rod Beam Clamp" line, since that line's own text never says
    # "conduit" -- a strict AND search excluded it before scoring ever saw it.
    frozenset({"CONDUIT", "CLAMP"}): "HANGER CLAMP",
    frozenset({"HANGER", "CLAMP"}): "CONDUIT CLAMP",
    # "Spring nut" is this catalog's strut channel nut *with* a spring
    # (retaining clip) fitted, as opposed to its "no spring" sibling of the
    # same size -- the catalog literally spells both "Strut Channel Nut,
    # 1/2"-13, No Spring" and "..., With Standard Spring" for the same size,
    # so plain word overlap alone can't tell them apart (both contain the
    # word "spring"). See wants_spring_nut/mentions_no_spring below for the
    # conflict check that actually excludes the wrong ("No Spring") one.
    frozenset({"SPRING", "NUT"}): "CHANNEL NUT WITH SPRING",
    # "GRC hub"/"Myers hub" (Myers is a brand name for this fitting, not a
    # word this catalog's own text ever uses) is what this catalog calls a
    # "Conduit Hub" -- confirmed live: "grc hub" and "myers hub" both get
    # zero catalog hits on their own, while "conduit hub" finds the exact
    # rigid-conduit hub family (e.g. NHUB100-ICKON, "1\" Conduit Hubs With
    # Insulated Throat"). Triggers on GRC+HUB alone (MYERS being present or
    # not doesn't change which candidate is meant) since GRC already means
    # rigid conduit -- see CATEGORY_DEFAULTS.
    frozenset({"GRC", "HUB"}): "CONDUIT HUB",
    # JOINER->FITTING is a real synonym (see terminology.py's FITTING group)
    # rather than a phrase expansion here: retrieval itself requires the
    # literal word to appear in the catalog text, so this needs to work as a
    # token-level canonicalization, not a string appended only for scoring.
}


def expand_known_phrases(query: str, tokens: list[str]) -> str:
    """Append the full meaning of any known multi-word abbreviation
    combination found in the query (see PHRASE_EXPANSIONS)."""
    token_set = {token.upper() for token in tokens}
    for trigger, expansion in PHRASE_EXPANSIONS.items():
        if trigger <= token_set:
            query = f"{query} {expansion}"
    return query


# Retrieval-side companion to the CONDUIT/HANGER CLAMP entries in
# PHRASE_EXPANSIONS above: these two qualifier words are only interchangeable
# next to this specific anchor ("clamp") -- everywhere else in this catalog
# "conduit" and "hanger" mean unrelated things, so this can't be a blanket
# terminology.py synonym. Dropping the qualifier entirely (like
# reduce_bare_category_tokens does for a category's own implied word) would
# also be wrong here: "clamp" alone is far too generic a retrieval anchor
# (pipe clamps, ground clamps, beam clamps of every kind), so the fix is to
# OR the two qualifier spellings together at that one token position instead
# of requiring either specific one.
_INTERCHANGEABLE_QUALIFIERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("CLAMP", frozenset({"CONDUIT", "HANGER"})),
)


def interchangeable_qualifier_variants(tokens: list[str]) -> dict[str, frozenset[str]]:
    """For each token in `tokens` that's an interchangeable qualifier for an
    anchor word also present, return the full set of equivalent qualifier
    words retrieval should OR in at that token's position (see
    _INTERCHANGEABLE_QUALIFIERS)."""
    token_set = {token.upper() for token in tokens}
    extra: dict[str, frozenset[str]] = {}
    for anchor, qualifiers in _INTERCHANGEABLE_QUALIFIERS:
        if anchor not in token_set:
            continue
        for token in qualifiers & token_set:
            extra[token] = qualifiers
    return extra


# "1-H"/"2-H" (hole count on a strap) can't be handled the same way as
# PHRASE_EXPANSIONS above: appending "ONE HOLE" while leaving the original
# "1"/"H" tokens in place still leaves a bare "1" as a required retrieval
# token, which doesn't match the catalog's spelled-out "ONE HOLE STRAP" text
# at all (no bare digit anywhere in it) -- it has to actually *replace* the
# abbreviation, not just add to it.
_HOLE_COUNT_RE = re.compile(r"\b([12])[\s-]?H\b", re.IGNORECASE)
_HOLE_COUNT_WORDS = {"1": "ONE", "2": "TWO"}


def expand_hole_count(query: str) -> str:
    """Replace a "1-H"/"1H"/"1 H" hole-count abbreviation with its spelled-
    out form ("ONE HOLE"), matching how this catalog actually writes strap
    descriptions.
    """

    def _replace(match: re.Match[str]) -> str:
        word = _HOLE_COUNT_WORDS.get(match.group(1).upper())
        return f"{word} HOLE" if word else match.group(0)

    return _HOLE_COUNT_RE.sub(_replace, query)


# Strut/channel catalog numbers never use a dash in this catalog (P1000,
# P1036, N3300, RP1000T, ...) but customers commonly write them with one
# ("P-1000", "P-1036") -- confirmed live: "P-1000 STRUT" gets zero catalog
# hits, "P1000 STRUT" gets 15. Scoped to a short letter prefix (1-3 letters)
# immediately followed by a dash and 3-5 digits so it never touches an
# unrelated dashed identifier that starts with a digit (e.g. "2EB40-B-SC").
#
# A *finish-code* suffix glued directly onto the number ("P-1036GR") needs
# splitting, not just merging -- the catalog spells that same part
# "P1036     GR" (the finish code as its own, whitespace-separated token),
# so gluing them into one "P1036GR" token would still fail to match; a space
# has to go back in between. But a trailing letter isn't always a finish
# code split off from a shared base part -- "P2072" and "P2072A" are two
# different physical products in this catalog (confirmed: different
# dimensions), so "P-2072A" must become the single token "P2072A", not
# "P2072 A" -- splitting off a real base-code letter that way pointed
# retrieval at the wrong product family entirely. Only split when the
# trailing letters are one of this catalog's actual finish codes.
_FINISH_CODES = frozenset({"EG", "HG", "PL", "PG", "DF", "GR", "SS", "ST", "AL", "ZD", "EA", "EV"})

# Must run on the *raw* input before interpret_customer_text() touches it:
# that step's own noise-word retokenization doesn't include "-" in what it
# keeps, so by the time a description reaches scoring the dash is already
# gone (turned into a plain space, e.g. "P-1036GR" -> "P 1036GR"), and this
# regex would no longer find anything to normalize.
_STRUT_CODE_DASH_RE = re.compile(r"\b([A-Za-z]{1,3})-(\d{3,5})([A-Za-z]{1,3})?\b")


def normalize_strut_catalog_codes(query: str) -> str:
    """Strip the dash from a "letter-prefix - digits[-suffix]" strut/channel
    catalog number so it matches the catalog's own no-dash spelling, splitting
    out a glued finish-code suffix as its own token only when it's actually
    one of this catalog's recognized finish codes."""

    def _replace(match: re.Match[str]) -> str:
        prefix, digits, suffix = match.group(1), match.group(2), match.group(3)
        if suffix and suffix.upper() in _FINISH_CODES:
            return f"{prefix}{digits} {suffix}"
        return match.group(0).replace("-", "")

    return _STRUT_CODE_DASH_RE.sub(_replace, query)


# Whichever side (customer or catalog) spells a term out in full, the query
# has to end up matching what the *catalog* actually uses -- not just have
# the other spelling appended for scoring -- since retrieval itself requires
# the literal word to appear in the catalog text. Must run on the raw input
# before interpret_customer_text(), same as normalize_strut_catalog_codes,
# since retrieval (not just scoring) needs to see the catalog's own spelling
# already in place.
_ACRONYM_PHRASES: dict[re.Pattern[str], str] = {
    # Customer spells it out; catalog abbreviates: "Electrical Metallic
    # Tubing" -> "EMT".
    re.compile(r"\bELECTRICAL\s+METALLIC\s+TUBING\b", re.IGNORECASE): "EMT",
    # Customer abbreviates; catalog spells it out (e.g. "SC75RKON 3/4"EMT
    # SET SCREW CONNECTOR"): "SS CONN" -> "SET SCREW CONNECTOR". "SS" isn't
    # a substring of "SET SCREW" (no adjacent double-S), so this needs a
    # real replacement, the same way "SS" alone can't just be a blanket
    # synonym for "set screw" -- it commonly means "stainless steel"
    # instead (see mentions_stainless) -- so this is scoped to the specific
    # "SS CONN" pairing, not bare "SS".
    re.compile(r"\bSS\s+CONN\b", re.IGNORECASE): "SET SCREW CONNECTOR",
    # "COMP CONN" already appears literally in some catalog rows' description
    # (e.g. "CCR-75KON 3/4"RAINTIGHT COMP CONN"), so retrieval isn't blind to
    # it the way SS CONN was -- but the abbreviation scores weakly against
    # SET SCREW connectors that share the same generic EMT/CONN wording
    # (confirmed live: "3/4\" EMT STL COMP CONN" top-matched SC75RKON, a set
    # screw connector, at 53%, ahead of the genuine EMT compression
    # connector at 40%). Expanding to the full words lets it score strongly
    # against description2's fully-spelled "... Compression Connector ..."
    # text instead of competing on a weak 4-letter abbreviation.
    re.compile(r"\bCOMP\s+CONN\b", re.IGNORECASE): "COMPRESSION CONNECTOR",
}


def expand_acronym_phrases(query: str) -> str:
    """Replace an abbreviated or spelled-out phrase with whichever form the
    catalog actually uses (see _ACRONYM_PHRASES)."""
    for pattern, replacement in _ACRONYM_PHRASES.items():
        query = pattern.sub(replacement, query)
    return query


def normalize_raw_customer_text(query: str) -> str:
    """Every raw-text normalization that must run before
    interpret_customer_text() touches the line (see normalize_strut_catalog_codes
    and expand_acronym_phrases for why each one needs this stage)."""
    query = normalize_strut_catalog_codes(query)
    query = expand_acronym_phrases(query)
    return query
