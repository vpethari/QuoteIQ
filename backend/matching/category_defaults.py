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
    # No length default here, unlike EMT/GRC below -- confirmed live this is
    # actively harmful for PVC specifically. This catalog's "PVC ... SCH40"
    # wording isn't exclusive to genuine Schedule 40 electrical conduit --
    # it's shared verbatim by an unrelated PVC pressure/water-plumbing-pipe
    # line (e.g. "PVC PR SCH40 5 x 20 BE ... White Water, Plumbing, & Gas
    # Pipe"), which happens to stock predominantly in 20' lengths. A "20 FT"
    # scoring bonus tips the ranking to that wrong-family 20' row over the
    # genuinely correct SCH40 conduit row even when the conduit row matches
    # every other default word (SCH40/BE/CONDUIT/GRAY) -- confirmed for "5"
    # PVC": with a 20 FT default, the wrong Water/Plumbing/Gas Pipe product
    # (and, prior to requiring SCH40 at retrieval, an equally-20'-stocked
    # unrelated Direct Burial Duct line) tied for the top score; removing
    # the length default collapses all genuine same-family candidates to an
    # honest tie instead (correctly leaving the line for manual length
    # confirmation, since the bare query truly doesn't say).
    "PVC": "SCH40 BE CONDUIT GRAY",
    "EMT": "CONDUIT 10 FT",
    "GRC": "GALVANIZED RIGID CONDUIT 10 FT",
    "LT": "LIQUID TIGHT",
    # Bare "STRUT"/"CHANNEL" with no length or finish given -- the catalog's
    # strut channel line is overwhelmingly stocked in 10' lengths with a
    # Pre-Galvanized (PG) finish, so that's the safest default absent any
    # other qualifier.
    "STRUT": "10 FT PG",
    "CHANNEL": "10 FT PG",
    # Bare "FLEX"/"FLEXIBLE" (see terminology.py's FLEX synonym group) with
    # no connector/coupling qualifier means the conduit itself, not a
    # fitting for it.
    "FLEX": "CONDUIT",
    # Confirmed live: of 88 "Fixture Whip" rows, 56 explicitly say
    # "Metallic Fixture Whip", and the other 32 are also metallic
    # construction -- they just phrase it as "...Interlocked Galvanized
    # Steel Flexible Conduit..." instead of the literal word "metallic".
    # See _COMPATIBLE_QUALIFIER_WORDS below for why "FIXTURE" doesn't
    # disqualify this the way "COUPLING" disqualifies bare "PVC".
    "WHIP": "METALLIC",
}

# Material words that describe *which variant* of a category the customer
# wants, not a different product type -- e.g. "STEEL FLEX" still means "flex
# conduit" (material: steel), unlike "PVC COUPLING" which is a genuinely
# different, more specific product than bare "PVC". These don't disqualify
# the bare-category treatment the way a real product-type qualifier would,
# but they also aren't *redundant* with the default phrase (unlike "GALV"
# for "GRC") -- retrieval must still require them, not drop them.
#
# "FIXTURE" is the same shape of thing for bare "WHIP": "Fixture Whip"
# names *which* whip, not a different product than "Whip", so it must not
# disqualify the WHIP -> METALLIC default the way a genuine product-type
# qualifier would -- but "fixture" itself is real, distinguishing content,
# not redundant with "metallic", so it must stay a required retrieval word,
# not get dropped the way "conduit" is dropped for bare "EMT".
_COMPATIBLE_QUALIFIER_WORDS = frozenset({"STEEL", "FIXTURE"})

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
    with extra words that are either already part of that category's own
    default phrase or a compatible material qualifier (see
    _COMPATIBLE_QUALIFIER_WORDS), return (category, redundant_extra_tokens);
    otherwise None. `redundant_extra_tokens` holds only the extras that
    duplicate the default phrase (safe to drop from a retrieval requirement)
    -- a compatible qualifier like "STEEL" is not included there, since it's
    a real, still-required word, just not a disqualifying one.

    e.g. "1\" PVC" -> ("PVC", []); "1 1/2\" GRC GALV" -> ("GRC", ["GALV"])
    since GRC already implies "galvanized"; "STEEL FLEX" -> ("FLEX", [])
    since "steel" is a compatible material, not a redundant word; but
    "1\" PVC COUPLING" -> None, since "coupling" isn't part of the PVC
    default and so is a genuinely different, more specific request the
    customer actually typed.
    """
    from matching.description_normalize import tokenize_description

    descriptive = [token for token in tokens if _is_descriptive_token(token)]
    category_matches = [token for token in descriptive if token.upper() in CATEGORY_DEFAULTS]
    if len(category_matches) != 1:
        return None
    category = category_matches[0].upper()
    default_tokens = {token.upper() for token in tokenize_description(CATEGORY_DEFAULTS[category])}
    extra = [token for token in descriptive if token.upper() != category]
    if any(
        token.upper() not in default_tokens and token.upper() not in _COMPATIBLE_QUALIFIER_WORDS
        for token in extra
    ):
        return None
    redundant = [token for token in extra if token.upper() in default_tokens]
    return category, redundant


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


# For most categories, the rest of the default phrase (beyond the bare word
# itself) stays a soft scoring/ranking nudge, never a hard retrieval
# requirement -- that's deliberate (see reduce_bare_category_tokens's own
# "conduit" example). But confirmed live: bare "5\" PVC" only ever requires
# "PVC" (and the bare size) at retrieval, and this catalog's own text labels
# utility duct, water/gas pipe, and various PVC fittings ALL as "PVC ...
# Conduit" too (a shared category-classification phrase, not specific to
# genuine electrical conduit) -- so "CONDUIT" from PVC's own default phrase
# doesn't discriminate at retrieval OR scoring. With only "PVC" required,
# the genuine 5" Schedule 40 conduit stick ranked position 183 of ~2,000
# eligible rows on generic text similarity alone, never reaching the scored
# candidate list at all. "SCH40" is the word that actually discriminates --
# present on the genuine Schedule 40 conduit line, absent from Utility
# Duct/Water-Plumbing-Gas Pipe/fitting lines.
#
# Deliberately opt-in and narrow, unlike the rest of a bare category's
# default phrase: add an entry here only once a real case like this one
# confirms the SPECIFIC word needs to be a hard retrieval requirement, not
# a guess applied to every category.
CATEGORY_DEFAULT_REQUIRED_WORDS: dict[str, str] = {
    "PVC": "SCH40",
}


def bare_category_required_word(tokens: list[str]) -> str | None:
    """The extra retrieval-required word implied by a bare category default,
    if any (see CATEGORY_DEFAULT_REQUIRED_WORDS) -- None if the bare-
    category treatment doesn't apply here at all, or this category has no
    such word."""
    match = _bare_category_redundant_extras(tokens)
    if match is None:
        return None
    category, _extra = match
    return CATEGORY_DEFAULT_REQUIRED_WORDS.get(category)


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
    # The comment above already anticipated "a coupling that transitions
    # EMT to threaded rigid/IMC/GRC conduit" as exactly this kind of
    # unrequested-specialty case, but "COUPLING" was never actually added
    # to this list -- confirmed live: a bare "3/4\" GRC" query slightly
    # outranked the correct plain 10' conduit stick with a coupling
    # (91.7% vs 90.0%) purely because the coupling's own text happened to
    # spell "GRC" out more explicitly.
    "COUPLING",
    # Same shape of problem again, but for an accessory rather than a
    # specialty fitting: a strap's own text always describes what it's FOR
    # ("... Strap For EMT Conduit"), so it literally contains the word
    # "conduit" that EMT's own CATEGORY_DEFAULTS expansion adds to the
    # scoring query -- while the genuine EMT tubing stick's own text spells
    # out "Electrical Metallic Tubing" instead and never says "conduit" at
    # all. Confirmed live: a bare "3/4\" EMT CONDUIT" query's top candidate
    # was a one-hole strap (SE75-1KON, 89.3%) outranking the actual conduit
    # stick (898303, 63.1%). A query that explicitly asks for a strap still
    # matches normally -- this only penalizes a strap the query never asked
    # for, the same as every other marker here.
    "STRAP",
    # Same shape of problem for connectors/couplings-with-a-fitting-end vs.
    # the plain tubing itself: confirmed live, even after the STRAP fix
    # above, a bare "3/4\" EMT CONDUIT" query's top candidate was still an
    # accessory -- SC75RKON "3/4\" EMT Set Screw Connector" (68.75%) --
    # outranking the genuine EMT conduit stick, 898303 (63.07%). Uses the
    # canonical "CONN" (see terminology.py's CONN group) rather than
    # "CONNECTOR" so it's recognized whether the query spells it out or
    # abbreviates it -- a query that actually wants a connector (e.g. "...
    # SS CONN") is unaffected either way.
    "CONN",
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
    from matching.terminology import canonicalize_token

    query_upper = query_raw.upper()
    candidate_upper = candidate_raw.upper()
    # Canonicalized single-word check, in addition to the raw phrase check
    # below -- otherwise a query abbreviation with its own terminology
    # synonym (e.g. "CPLG" for "COUPLING") looks like it never asked for a
    # marker it actually did, capping every genuine match to the same
    # unrequested-specialty penalty. Confirmed live: every real steel "...
    # CPLG" coupling candidate for "3/4 EMT STL SS CPLG" scored an identical
    # 40% -- description_conflict_max -- because the raw query text says
    # "CPLG", never the literal word "COUPLING" the marker list checks for.
    query_canonical_words = {canonicalize_token(word) for word in re.findall(r"[A-Za-z]+", query_upper)}
    implied_categories = [abbrev for abbrev in CATEGORY_DEFAULTS if _word_present(query_upper, abbrev)]
    for marker in _SPECIALTY_VARIANT_MARKERS:
        if marker not in candidate_upper:
            continue
        if _word_present(query_upper, marker) or marker in query_canonical_words:
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
    #
    # "Squeeze connector" is what this catalog calls a flex conduit
    # connector (e.g. "MSC5090KON 1/2\" SQUEEZE CONNECTORS - 90 DEGREE")
    # and never mentions "flex"/"flexible" -- retrieval eligibility is
    # already fixed via _INTERCHANGEABLE_QUALIFIERS below, but scoring also
    # needs "squeeze" appended here, the same two-part fix as conduit/hanger
    # clamp, since a candidate's own raw text ("squeeze"/"connectors") won't
    # otherwise overlap the query's "flex"/"conn" at all.
    frozenset({"FLEX", "CONN"}): "SQUEEZE CONNECTOR",
    # A leading "<Category>:" RFQ label (e.g. "Conduit:", "Cable Tray:") is
    # handled separately, by restore_leading_label_words() below, not a
    # fixed entry here -- see _mark_leading_label / normalize_raw_customer_text.
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
    # Same shape of problem for flex conduit connectors: this catalog calls
    # them "Squeeze Connector[s]" (e.g. "MSC5090KON 1/2\" SQUEEZE CONNECTORS
    # - 90 DEGREE") and never mentions "flex"/"flexible" anywhere in that
    # family's own text, so a "... FLEX CONN" query's strict AND search
    # excluded it entirely. "Squeeze" can't be a blanket synonym for "flex"
    # (it's a specific connector *mechanism* name, not interchangeable with
    # "flex" outside this connector context), so this is scoped to the
    # "CONN" anchor the same way conduit/hanger is scoped to "CLAMP".
    ("CONN", frozenset({"FLEX", "SQUEEZE"})),
    # Retrieval-side companion to the GRC+HUB entry in PHRASE_EXPANSIONS
    # above: confirmed live, "GRC HUB" retrieved zero of the actual
    # NHUB*-ICKON "Conduit Hubs With Insulated Throat" family (its own text
    # never says "GRC") -- the strict AND on the literal "grc" token
    # excluded that family before scoring ever saw it, so a bare "GRC HUB"
    # fell back to plain rigid-conduit sticks instead. "GRC" can't be
    # dropped as merely redundant (reduce_bare_category_tokens) since "HUB"
    # isn't part of GRC's own CATEGORY_DEFAULTS phrase, so it's scoped here
    # to the "HUB" anchor instead.
    ("HUB", frozenset({"GRC", "CONDUIT"})),
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
    # Same shape of problem, for couplings: catalog spells this "COMPR CPLG"
    # (e.g. "S20700CC00 3/4 SS316 EMT COMPR CPLG"), not "COMP CPLG" -- "COMP"
    # is already a substring of "COMPR" so retrieval isn't blind to it, but
    # the abbreviation scores weakly against description2's fully-spelled
    # "... Compression Coupling ..." text.
    re.compile(r"\bCOMP\s+CPLG\b", re.IGNORECASE): "COMPRESSION COUPLING",
    # Customer's trade term; catalog's own word is a two-word phrase, so a
    # single-token terminology.py synonym can't bridge them (retrieval/
    # scoring token positions are one word each) -- confirmed live, this
    # catalog never uses "waterfall" or "dropout" (one word) anywhere, only
    # "Drop Out" (e.g. "EGL-12DO EGL TRAY DROP OUT 12\"W").
    re.compile(r"\bWATERFALL\b", re.IGNORECASE): "DROP OUT",
}


def expand_acronym_phrases(query: str) -> str:
    """Replace an abbreviated or spelled-out phrase with whichever form the
    catalog actually uses (see _ACRONYM_PHRASES)."""
    for pattern, replacement in _ACRONYM_PHRASES.items():
        query = pattern.sub(replacement, query)
    return query


# This RFQ format prefixes every line with "<Category>:" -- e.g. "Conduit:
# 2\" Innerduct, Smooth, Orange", "Cable Tray: Ladder Tray, 36\" Wide, 144\"
# Long", "Coupling: 02\" PVC...", "Sweep: 08\" PVC...", "Grounding:
# Compression Crimp...". Each is a genuine statement of the customer's
# intended product category, not a throwaway section header -- it must stay
# in the query (scoring should still credit a candidate whose text happens
# to say the label word), but it also must not become a hard, literal
# retrieval requirement, since a catalog sub-category under a given label
# doesn't always spell the parent label word out in its own text.
# Confirmed live (the first case found): with "conduit" required, "Conduit:
# 2\" Innerduct, Smooth, Orange" needed "conduit" AND "innerduct" AND
# "smooth" AND "orange" all in one catalog row; no Innerduct product's own
# text says "conduit" (or "smooth" -- this catalog only distinguishes
# GenPur/Riser/Plenum/Kortech innerduct types, not wall texture), so at most
# 2 of those 4 tokens could ever match -- below the retrieval fallback's 60%
# overlap floor, producing a hard NO_MATCH despite real 2" orange Innerduct
# products existing. The same shape of bug then reappeared for "Cable
# Tray:" -- confirmed the fix needs to generalize to *any* leading label
# this RFQ format uses, not one hand-picked category at a time.
#
# Generalized as: fold the whole leading "<label words>:" into one opaque
# marker token on the raw text, rather than just remembering "there was a
# colon" -- checking "the label word is the first token" further down the
# pipeline instead was tried and rejected for the Conduit case:
# interpret_customer_text() strips punctuation before retrieval ever runs,
# so the colon itself doesn't survive that far, and a plain word-position
# check collides with a genuine query like "CONDUIT CLAMP" (a real,
# required product-type word that also happens to come first) -- caught
# immediately by the existing test suite. A marker token that can never
# occur naturally has no such ambiguity: it only exists when this exact
# regex fired on the original raw text. Any retrieval token starting with
# the marker prefix is dropped unconditionally (see
# catalog/search_query.py's is_leading_label_marker(), matched generically
# by prefix, not a fixed per-category list) since it is never a real
# catalog word to search for.
#
# The marker glues the label's words together with no separator at all
# ("CABLETRAY", not "CABLE_TRAY") -- tokenize_description()'s own token
# regex only keeps runs of [A-Z0-9] as one token (confirmed live: an
# underscore- or slash-joined marker silently fragments back into separate
# "CABLE"/"TRAY" tokens, defeating the whole point -- only a run with no
# non-alphanumeric separator at all survives as one token). Each word is
# prefixed with its own zero-padded length (e.g. "05CABLE04TRAY") so
# restore_leading_label_words() below can split it back into the original
# words unambiguously (digits are never part of a real word, so a length
# prefix can't be confused with word content) -- this is the same reason a
# plain concatenation like "CABLETRAY" can't just be split back into words
# again: nothing marks where one word ends and the next begins.
#
# retrieval (catalog/search_query.py) drops any QIQLBL-prefixed token
# unconditionally, since it's never a real catalog word to search for.
# Scoring is different: normalize_raw_customer_text() feeds *both* paths
# from the same shared string, so the literal words can't simply be left in
# place there too (retrieval would then require them, right back to the
# original bug) -- restore_leading_label_words() instead decodes the
# marker and appends the plain words, but only in
# description_normalize.expand_query_for_retrieval(), the scoring-only
# expansion step that runs after retrieval has already built its own
# token groups from the un-restored, marker-only string.
#
# Scoped to 1-3 leading words so it only matches this RFQ format's actual
# category-header convention, not any arbitrary sentence that happens to
# contain a colon somewhere -- and anchored to the very start of the line
# (re.match, not search), so a colon anywhere else in the text never
# triggers it.
_LEADING_LABEL_RE = re.compile(r"^\s*([A-Za-z]+(?:\s+[A-Za-z]+){0,2})\s*:\s*")

# Distinctive enough that no real catalog word or customer abbreviation
# could ever collide with it.
_LABEL_MARKER_PREFIX = "QIQLBL"
_LABEL_MARKER_RE = re.compile(rf"\b{_LABEL_MARKER_PREFIX}((?:\d{{2}}[A-Z]+)+)\b")


def _encode_label_words(words: list[str]) -> str:
    return "".join(f"{len(word):02d}{word}" for word in words)


def _decode_label_words(encoded: str) -> list[str]:
    words = []
    position = 0
    while position < len(encoded):
        length = int(encoded[position : position + 2])
        words.append(encoded[position + 2 : position + 2 + length])
        position += 2 + length
    return words


def _mark_leading_label(query: str) -> str:
    match = _LEADING_LABEL_RE.match(query)
    if not match:
        return query
    label_words = match.group(1).upper().split()
    marker = _LABEL_MARKER_PREFIX + _encode_label_words(label_words)
    return f"{marker} {query[match.end():]}"


def is_leading_label_marker(token: str) -> bool:
    return token.upper().startswith(_LABEL_MARKER_PREFIX)


def query_has_leading_label_marker(query: str) -> bool:
    """Cheap check for whether `_mark_leading_label` fired on this query,
    without re-tokenizing it -- the marker, if present, is always the very
    first thing in the string (see _mark_leading_label). Used by
    catalog.postgres_repository.search_text_candidates to decide whether a
    second, label-word-dropped retrieval attempt is worth making at all."""
    return query.lstrip().upper().startswith(_LABEL_MARKER_PREFIX)


def decode_label_marker_token(token: str, *, head_noun_only: bool = False) -> list[str] | None:
    """The literal words a single leading-label marker token stands for, or
    None if `token` isn't one (see catalog.search_query._restore_label_tokens
    -- retrieval's default, label-required search expands the marker back
    into these words in place, rather than dropping it).

    head_noun_only: keep just the label's last word (its head noun -- e.g.
    "Tray" in "Cable Tray") instead of all of them. Confirmed live: "Cable
    Tray: 90 Degree Bend R12\" W36\"" found nothing with the full label
    required, so retrieval fell all the way back to dropping "Tray" too --
    leaving only generic words ("90", "degree", "bend") that match any
    90-degree conduit elbow in the entire catalog, surfacing a completely
    unrelated PVC conduit fitting. "Cable" is a qualifier; "Tray" is the
    actual product-type word and should never be dropped for a multi-word
    label (see catalog.postgres_repository.search_text_candidates, which
    tries this middle tier before ever fully dropping a multi-word label,
    and simply returns nothing rather than fully dropping it)."""
    if not is_leading_label_marker(token):
        return None
    words = _decode_label_words(token.upper()[len(_LABEL_MARKER_PREFIX):])
    return words[-1:] if head_noun_only and words else words


def leading_label_word_count(query: str) -> int:
    """How many words the leading label (if any) decodes to -- 0 if there
    isn't one. Used to decide whether a label is a single word (e.g.
    "Conduit", safe to drop entirely as a last resort -- see
    decode_label_marker_token) or multi-word (e.g. "Cable Tray", where only
    the qualifier should ever be dropped, never the head noun)."""
    marker = query.lstrip()
    if not is_leading_label_marker(marker.split(" ", 1)[0] if marker else ""):
        return 0
    decoded = decode_label_marker_token(marker.split(" ", 1)[0])
    return len(decoded) if decoded else 0


def restore_leading_label_words(query: str) -> str:
    """Append the literal words a leading-label marker (see
    _mark_leading_label) stands for, back onto the query -- for scoring
    credit only (see description_normalize.expand_query_for_retrieval).
    Retrieval drops any marker token unconditionally instead and never
    calls this (see catalog/search_query.py)."""

    def _replace(match: re.Match[str]) -> str:
        return f"{match.group(0)} {' '.join(_decode_label_words(match.group(1)))}"

    return _LABEL_MARKER_RE.sub(_replace, query)


# Confirmed live: "Cable Tray: Ladder Tray, 36\" Wide, 144\" Long" found zero
# candidates even after the leading-label fix above, because the catalog's own
# EGL straight-section text ("EGL TRAY 4\"H X 36\"W X 10'L STR") never says
# "ladder", "wide", or "long" -- it spells dimensions as bare numbers with a
# single-letter code, nothing else. A full catalog search confirms this
# catalog sells exactly one bare "Tray" product line (EGL) -- nothing else
# is filed under a standalone "Tray" name here -- so "ladder" is always
# redundant once "tray" itself is present. "Wide"/"Long" are dropped only
# when they directly follow a dimension number, so a genuine product name
# where one of those words is load-bearing (e.g. "PVC LONG LINE COUPLING",
# where "long" is the first word, not dimension-adjacent) is unaffected.
# Scoped to only fire when "tray" is present at all, so this never touches
# an unrelated query.
#
# "BASKET" is the same shape of thing: confirmed live, "basket"/"wire
# basket"/"wire mesh" appear in zero rows anywhere in this catalog (checked
# every text column directly, not just search_text) -- yet Atkore's own
# published product page for EGL6-20SL-120S1 (an EGL-family part number
# confirmed present in this catalog) describes its accessories as securing
# "to wire basket without any hardware". So "EGL" is this catalog's own
# name for what a customer calls a wire basket tray system -- it just never
# spells "basket" out in its own terse text, same as it never spells out
# "ladder". Confirmed the family this unblocks genuinely has both a T
# fitting (EGL-*-TBR, "EGL TRAY TEE BRIDGE") and a 90-degree elbow
# (EGL#-RADIUS, "EGL TRAY 90 RADIUS") -- "24\" BASKET TRAY 'T' FITTING" and
# "24\" BASKET TRAY 90 DEGREE ELBOW" found zero candidates before this,
# with "basket" as a hard, never-matchable retrieval requirement.
_TRAY_REDUNDANT_WORDS = frozenset({"LADDER", "BASKET"})
_DIMENSION_ADJACENT_FILLER = frozenset({"WIDE", "LONG", "TALL", "DEEP", "HIGH"})


def _looks_like_size_token(token: str) -> bool:
    bare = token.replace(".", "", 1)
    if "/" in bare:
        left, _, right = bare.partition("/")
        return left.isdigit() and right.isdigit()
    return bare.isdigit()


def reduce_tray_filler_tokens(tokens: list[str]) -> list[str]:
    """Drop cable-tray-specific filler words before they become *required*
    retrieval tokens (see the comment above)."""
    upper_tokens = [token.upper() for token in tokens]
    if "TRAY" not in upper_tokens:
        return tokens
    kept: list[str] = []
    for index, token in enumerate(tokens):
        upper = token.upper()
        if upper in _TRAY_REDUNDANT_WORDS:
            continue
        if upper in _DIMENSION_ADJACENT_FILLER and index > 0 and _looks_like_size_token(tokens[index - 1]):
            continue
        kept.append(token)
    return kept


def normalize_raw_customer_text(query: str) -> str:
    """Every raw-text normalization that must run before
    interpret_customer_text() touches the line (see normalize_strut_catalog_codes
    and expand_acronym_phrases for why each one needs this stage)."""
    query = _mark_leading_label(query)
    query = normalize_strut_catalog_codes(query)
    query = expand_acronym_phrases(query)
    return query
