from __future__ import annotations

from matching.category_defaults import (
    candidate_color_conflicts,
    default_color_for_query,
    expand_acronym_phrases,
    expand_bare_category_query,
    expand_hole_count,
    expand_known_phrases,
    interchangeable_qualifier_variants,
    mentions_no_spring,
    mentions_stainless,
    normalize_raw_customer_text,
    normalize_strut_catalog_codes,
    reduce_bare_category_tokens,
    unrequested_specialty_marker,
    wants_spring_nut,
)
from matching.description_normalize import expand_query_for_retrieval, tokenize_description
from matching.matcher import ProductMatcher
from matching.models import MatchingConfig, ProductRecord, ScoreBreakdown
from matching.productcode import is_product_code_query
from matching.scoring import descriptions_conflict, variant_conflict


def test_expand_bare_category_query_appends_default_for_bare_category() -> None:
    query = '1" PVC'
    tokens = tokenize_description(query)
    expanded = expand_bare_category_query(query, tokens)
    assert "SCH40 BE CONDUIT GRAY" in expanded


def test_expand_bare_category_query_leaves_more_specific_request_untouched() -> None:
    query = '1" PVC COUPLING'
    tokens = tokenize_description(query)
    assert expand_bare_category_query(query, tokens) == query


def test_reduce_bare_category_tokens_drops_implied_default_word() -> None:
    # "conduit" is already what "EMT" implies (CATEGORY_DEFAULTS), so it
    # must not become a second *required* retrieval token -- confirmed live:
    # a genuine plain 3/4" EMT conduit stick's own catalog text never
    # happens to say "conduit" (it spells out "Electrical Metallic Tubing"
    # instead), so requiring both words excluded it from retrieval entirely.
    tokens = tokenize_description("EMT CONDUIT")
    reduced = reduce_bare_category_tokens(tokens)
    assert "CONDUIT" not in reduced
    assert "EMT" in reduced


def test_reduce_bare_category_tokens_keeps_genuinely_specific_request() -> None:
    tokens = tokenize_description("PVC COUPLING")
    assert reduce_bare_category_tokens(tokens) == tokens


def test_flexible_is_a_synonym_for_flex() -> None:
    assert tokenize_description("1/2 FLEXIBLE") == tokenize_description("1/2 FLEX")


def test_cplg_is_a_synonym_for_coupling() -> None:
    # Confirmed live: real steel EMT "SET SCREW COUPLING" products (e.g.
    # SK75RKON) spell "Coupling" out in full and were excluded from
    # retrieval entirely for a "... CPLG" query before this synonym existed
    # -- only the handful of catalog rows that happen to abbreviate it as
    # "CPLG" themselves were reachable.
    assert tokenize_description("3/4 EMT CPLG") == tokenize_description("3/4 EMT COUPLING")


def test_expand_bare_category_query_steel_flex_implies_conduit() -> None:
    query = "STEEL FLEX"
    tokens = tokenize_description(query)
    expanded = expand_bare_category_query(query, tokens)
    assert "CONDUIT" in expanded


def test_reduce_bare_category_tokens_keeps_steel_as_required() -> None:
    # "steel" is a compatible material qualifier, not a redundant word --
    # it must stay a required retrieval token, unlike "conduit" for "EMT".
    tokens = tokenize_description("STEEL FLEX")
    assert reduce_bare_category_tokens(tokens) == tokens


def test_expand_bare_category_query_grc_galv_is_still_bare() -> None:
    # "GALV" is just the customer's own abbreviation of the "Galvanized"
    # that GRC's own CATEGORY_DEFAULTS phrase already spells out -- it must
    # not be treated as a genuinely more specific request. Confirmed live:
    # before adding a GALV/GALVANIZED terminology synonym, "1 GRC (GALV)"
    # matched nothing while bare "1 GRC" correctly matched product 278895.
    query = '1" GRC (GALV)'
    tokens = tokenize_description(query)
    expanded = expand_bare_category_query(query, tokens)
    assert "RIGID CONDUIT" in expanded


def test_reduce_bare_category_tokens_drops_galv_for_grc() -> None:
    tokens = tokenize_description('1" GRC GALV')
    reduced = reduce_bare_category_tokens(tokens)
    assert "GALV" not in reduced
    assert "GRC" in reduced


def test_retrieval_token_groups_drop_implied_default_word() -> None:
    from catalog.search_query import retrieval_search_token_groups

    groups = retrieval_search_token_groups("3/4 EMT CONDUIT")
    flat = {variant for group in groups for variant in group}
    assert "conduit" not in flat
    assert "emt" in flat


def test_interchangeable_qualifier_variants_conduit_hanger_clamp() -> None:
    tokens = ["CONDUIT", "CLAMP"]
    extra = interchangeable_qualifier_variants(tokens)
    assert extra.get("CONDUIT") == frozenset({"CONDUIT", "HANGER"})

    tokens2 = ["HANGER", "CLAMP"]
    extra2 = interchangeable_qualifier_variants(tokens2)
    assert extra2.get("HANGER") == frozenset({"CONDUIT", "HANGER"})

    # Anchor word absent -- nothing to widen.
    assert interchangeable_qualifier_variants(["CONDUIT", "COUPLING"]) == {}


def test_interchangeable_qualifier_variants_flex_squeeze_conn() -> None:
    # This catalog calls flex conduit connectors "Squeeze Connectors" and
    # never mentions "flex"/"flexible" in that family's own text, so a
    # "... FLEX CONN" query's strict AND search excluded it entirely.
    tokens = ["FLEX", "CONN"]
    extra = interchangeable_qualifier_variants(tokens)
    assert extra.get("FLEX") == frozenset({"FLEX", "SQUEEZE"})


def test_expand_known_phrases_flex_conn_appends_squeeze_connector() -> None:
    tokens = tokenize_description("STL FLEX CONN")
    expanded = expand_known_phrases("STL FLEX CONN", tokens)
    assert "SQUEEZE CONNECTOR" in expanded


def test_interchangeable_qualifier_variants_grc_hub() -> None:
    # This catalog's rigid-conduit hub family (NHUB*-ICKON, "Conduit Hubs
    # With Insulated Throat") never says "GRC" anywhere -- confirmed live, a
    # bare "GRC HUB" query's strict AND search excluded that entire family
    # and fell back to plain rigid-conduit sticks instead.
    tokens = ["GRC", "HUB"]
    extra = interchangeable_qualifier_variants(tokens)
    assert extra.get("GRC") == frozenset({"GRC", "CONDUIT"})


def test_expand_known_phrases_grc_hub_appends_conduit_hub() -> None:
    tokens = tokenize_description("3/4 GRC HUB")
    expanded = expand_known_phrases("3/4 GRC HUB", tokens)
    assert "CONDUIT HUB" in expanded


def test_connectors_is_a_synonym_for_connector() -> None:
    assert tokenize_description("SQUEEZE CONNECTORS") == tokenize_description("SQUEEZE CONNECTOR")


def test_degree_is_a_synonym_for_deg() -> None:
    assert tokenize_description("90 DEGREE") == tokenize_description("90 DEG")


def test_retrieval_token_groups_or_conduit_and_hanger_for_clamp() -> None:
    from catalog.search_query import retrieval_search_token_groups

    groups = retrieval_search_token_groups("CONDUIT CLAMP")
    flat_by_position = [set(group) for group in groups]
    assert any({"conduit", "hanger"} <= group for group in flat_by_position)
    assert any(group == {"clamp"} for group in flat_by_position)


def test_retrieval_token_groups_or_conduit_for_grc_hub() -> None:
    from catalog.search_query import retrieval_search_token_groups

    groups = retrieval_search_token_groups("3/4 GRC HUB")
    flat_by_position = [set(group) for group in groups]
    assert any({"grc", "conduit"} <= group for group in flat_by_position)
    assert any(group == {"hub"} for group in flat_by_position)


def test_expand_known_phrases_appends_matched_expansion() -> None:
    query = "STL SS SCREW"
    tokens = tokenize_description(query)
    expanded = expand_known_phrases(query, tokens)
    assert "STEEL SET SCREW" in expanded


def test_expand_hole_count_spells_out_abbreviation() -> None:
    assert "ONE HOLE" in expand_hole_count("1-H STRAP")
    assert "TWO HOLE" in expand_hole_count("2H STRAP")


def test_normalize_strut_catalog_codes_strips_dash() -> None:
    assert normalize_strut_catalog_codes("P-1000 STRUT") == "P1000 STRUT"


def test_normalize_strut_catalog_codes_splits_known_finish_code() -> None:
    assert normalize_strut_catalog_codes("P-1036GR") == "P1036 GR"


def test_normalize_strut_catalog_codes_keeps_base_code_letter_glued() -> None:
    # P2072A is a distinct product from P2072, not a finish-code suffix.
    assert normalize_strut_catalog_codes("P-2072A") == "P2072A"


def test_expand_acronym_phrases_electrical_metallic_tubing_to_emt() -> None:
    assert expand_acronym_phrases("3/4\" Electrical Metallic Tubing Conduit") == '3/4" EMT Conduit'
    # Case-insensitive, flexible whitespace.
    assert expand_acronym_phrases("electrical  metallic   tubing") == "EMT"


def test_expand_acronym_phrases_ss_conn_to_set_screw_connector() -> None:
    assert expand_acronym_phrases('1/2" EMT STL SS CONN') == '1/2" EMT STL SET SCREW CONNECTOR'
    # Case-insensitive, flexible whitespace.
    assert expand_acronym_phrases("ss  conn") == "SET SCREW CONNECTOR"


def test_expand_acronym_phrases_comp_conn_to_compression_connector() -> None:
    assert expand_acronym_phrases('3/4" EMT STL COMP CONN') == '3/4" EMT STL COMPRESSION CONNECTOR'
    # Case-insensitive, flexible whitespace.
    assert expand_acronym_phrases("comp  conn") == "COMPRESSION CONNECTOR"


def test_expand_acronym_phrases_comp_cplg_to_compression_coupling() -> None:
    assert expand_acronym_phrases('3/4" EMT STL COMP CPLG') == '3/4" EMT STL COMPRESSION COUPLING'
    # Case-insensitive, flexible whitespace.
    assert expand_acronym_phrases("comp  cplg") == "COMPRESSION COUPLING"


def test_expand_acronym_phrases_does_not_touch_bare_ss() -> None:
    # Bare "SS" is ambiguous (often "stainless steel") -- only the specific
    # "SS CONN" pairing is a safe, confirmed replacement.
    assert expand_acronym_phrases("SS316 EMT CONN") == "SS316 EMT CONN"


def test_normalize_raw_customer_text_composes_both_normalizations() -> None:
    result = normalize_raw_customer_text('3/4" Electrical Metallic Tubing P-1036GR')
    assert "EMT" in result
    assert "P1036" in result


def test_expand_query_for_retrieval_chains_all_expansions() -> None:
    expanded = expand_query_for_retrieval('1" PVC')
    assert "SCH40 BE CONDUIT GRAY" in expanded


def test_plastic_is_a_synonym_for_pvc() -> None:
    assert tokenize_description("1\" PLASTIC") == tokenize_description('1" PVC')
    expanded = expand_query_for_retrieval('1" PLASTIC')
    assert "SCH40 BE CONDUIT GRAY" in expanded


def test_joiner_canonicalizes_to_fitting() -> None:
    # A true synonym (terminology.py), not a category_defaults phrase
    # expansion, so retrieval's own token matching benefits too -- not just
    # scoring after the fact.
    assert tokenize_description("STRUT L JOINER") == tokenize_description("STRUT L FITTING")


def test_default_color_for_query_returns_none_when_color_named() -> None:
    tokens = tokenize_description("PVC CONDUIT ORANGE")
    assert default_color_for_query(tokens) is None


def test_default_color_for_query_returns_default_when_unstated() -> None:
    tokens = tokenize_description("PVC CONDUIT")
    assert default_color_for_query(tokens) == "GRAY"


def test_candidate_color_conflicts_true_for_other_color() -> None:
    tokens = tokenize_description("PVC CONDUIT ORANGE")
    assert candidate_color_conflicts(tokens, "GRAY") is True


def test_candidate_color_conflicts_false_for_default_color() -> None:
    tokens = tokenize_description("PVC CONDUIT GRAY")
    assert candidate_color_conflicts(tokens, "GRAY") is False


def test_mentions_stainless() -> None:
    assert mentions_stainless("1/2 EMT STAINLESS STEEL ONE HOLE STRAP") is True
    assert mentions_stainless("1/2 EMT ONE HOLE STRAP") is False


def test_wants_spring_nut_and_mentions_no_spring() -> None:
    tokens = tokenize_description("1/2 STRUT CHANNEL NUT WITH SPRING")
    assert wants_spring_nut(tokens) is True
    assert mentions_no_spring('Strut Channel Nut, 1/2"-13, No Spring') is True


def test_unrequested_specialty_marker_flags_unrequested_elbow() -> None:
    marker = unrequested_specialty_marker("1 1/2 GRC", "1 1/2 GALVANIZED RIGID CONDUIT 90 DEG ELBOW")
    assert marker == "ELBOW"


def test_unrequested_specialty_marker_flags_unrequested_coupling() -> None:
    # Bare "GRC" means the plain 10' conduit stick -- a coupling is a
    # genuinely different, more specific fitting, the same way an elbow or
    # nipple is (confirmed live: a coupling slightly outranked the correct
    # plain conduit stick, 91.7% vs 90.0%, purely for spelling "GRC" out
    # more explicitly in its own catalog text).
    marker = unrequested_specialty_marker('3/4" GRC', "3/4 Coupling, Galvanized Rigid Conduit, GRC, Galvanized Steel")
    assert marker == "COUPLING"


def test_unrequested_specialty_marker_none_when_coupling_requested() -> None:
    # An explicit "GRC COUPLING" request must not penalize a genuine
    # coupling candidate for being one.
    marker = unrequested_specialty_marker(
        '1 1/2" GRC COUPLING', '1 1/2" GRC COUPLING DOMESTIC Steel Electrogalvanized'
    )
    assert marker is None


def test_unrequested_specialty_marker_none_when_coupling_requested_via_cplg() -> None:
    # "CPLG" is a real terminology synonym for "COUPLING" (see
    # terminology.py), so a query that abbreviates it must not be treated as
    # never having asked for a coupling. Confirmed live: before this fix,
    # every genuine steel EMT coupling candidate for "3/4 EMT STL SS CPLG"
    # scored an identical, capped 40% -- description_conflict_max -- because
    # the raw-text check only recognized the literal word "COUPLING".
    marker = unrequested_specialty_marker(
        '3/4" EMT STL SS CPLG', 'SK75RKON 3/4"EMT SET SCREW COUPLING Steel Zinc Plated'
    )
    assert marker is None


def test_unrequested_specialty_marker_flags_unrequested_strap() -> None:
    # A strap's own text always describes what it's FOR ("... Strap For EMT
    # Conduit"), so it shares more literal wording with a bare "EMT CONDUIT"
    # query than the genuine tubing stick does (the stick spells out
    # "Electrical Metallic Tubing" and never says "conduit" at all).
    # Confirmed live: a strap (SE75-1KON, 89.3%) outranked the actual conduit
    # stick 898303 (63.1%) for "3/4\" EMT CONDUIT" before this fix.
    marker = unrequested_specialty_marker(
        '3/4" EMT CONDUIT', 'SE75-1KON 3/4" ONE HOLE STRAP FOR EMT CONDUIT Steel Zinc Plated'
    )
    assert marker == "STRAP"


def test_unrequested_specialty_marker_none_when_strap_requested() -> None:
    marker = unrequested_specialty_marker(
        '1/2" EMT 1-H STEEL STRAP', 'SE50-1KON 1/2" ONE HOLE STRAP FOR EMT CONDUIT Steel Zinc Plated'
    )
    assert marker is None


def test_unrequested_specialty_marker_flags_unrequested_connector() -> None:
    # Same shape of problem for connectors: confirmed live, even after the
    # STRAP fix, "3/4\" EMT CONDUIT" still top-ranked a Set Screw Connector
    # (SC75RKON, 68.75%) over the genuine conduit stick 898303 (63.07%).
    marker = unrequested_specialty_marker(
        '3/4" EMT CONDUIT', 'SC75RKON 3/4"EMT SET SCREW CONNECTOR Steel Zinc Plated'
    )
    assert marker == "CONN"


def test_unrequested_specialty_marker_none_when_connector_requested() -> None:
    # Whether the query spells it out or abbreviates it, a genuine connector
    # request must not be penalized for being one -- the marker uses the
    # canonical "CONN" (see terminology.py) specifically so both forms work.
    for query in ('1/2" EMT STL SS CONN', "1/2 EMT SET SCREW CONNECTOR"):
        marker = unrequested_specialty_marker(
            query, 'SC50RKON 1/2"EMT SET SCREW CONNECTOR Steel Zinc Plated'
        )
        assert marker is None


def test_unrequested_specialty_marker_none_when_implied_by_category() -> None:
    # "RIGID" is already implied by the query's own "GRC", so it isn't unrequested.
    marker = unrequested_specialty_marker("1 1/2 GRC 90 DEG ELBOW", "1 1/2 GALVANIZED RIGID CONDUIT 90 DEG ELBOW")
    assert marker is None


def test_variant_conflict_true_for_stainless_mismatch() -> None:
    assert variant_conflict("1/2 EMT ONE HOLE STRAP", "1/2 EMT STAINLESS STEEL ONE HOLE STRAP") is True


def test_variant_conflict_false_for_matching_material() -> None:
    assert variant_conflict("1/2 EMT ONE HOLE STRAP", "1/2 EMT STEEL ONE HOLE STRAP") is False


def test_variant_conflict_true_for_no_spring_when_spring_wanted() -> None:
    assert variant_conflict(
        "1/2 STRUT CHANNEL NUT WITH SPRING", 'Strut Channel Nut, 1/2"-13, No Spring'
    ) is True


def test_variant_conflict_does_not_flag_color_alone() -> None:
    # variant_conflict deliberately excludes the color-default check: a color
    # word elsewhere in catalog_text (e.g. a cable's own conductor colors)
    # doesn't reliably mean "different-colored variant of the same product,"
    # and treating it as a hard conflict capped too many legitimate
    # candidates to the same score in production. default_color_for_query /
    # candidate_color_conflicts remain available as standalone helpers.
    assert variant_conflict('1" PVC CONDUIT', '1" PVC CONDUIT ORANGE') is False


def test_descriptions_conflict_flags_variant_mismatch() -> None:
    breakdown = ScoreBreakdown(exact=0.0, token=90.0, fuzzy=90.0, attribute=0.0, final=90.0)
    assert descriptions_conflict(
        "1/2 EMT ONE HOLE STRAP",
        "1/2 EMT STAINLESS STEEL ONE HOLE STRAP",
        breakdown,
        MatchingConfig(),
    ) is True


class _RecordingCatalogSearch:
    """Minimal catalog_search double that just records what query string it
    was asked to retrieve with, so tests can assert retrieval never sees the
    category-defaults-expanded query (see the retrieval-vs-scoring split in
    ProductMatcher._score_description_candidates)."""

    def __init__(self) -> None:
        self.search_text_queries: list[str] = []
        self.rank_queries: list[str | None] = []

    def lookup_productcode(self, identifier: str, limit: int | None = None) -> list[ProductRecord]:
        return []

    def fetch_identifier_candidates(self, query: str, limit: int | None = None) -> list[ProductRecord]:
        return []

    def search_text_candidates(
        self, query: str, limit: int | None = None, *, rank_query: str | None = None
    ) -> list[ProductRecord]:
        self.search_text_queries.append(query)
        self.rank_queries.append(rank_query)
        return []


def test_retrieval_query_is_not_expanded_but_scoring_query_is() -> None:
    # Regression test: expand_query_for_retrieval() must never reach the
    # catalog_search retrieval call. Postgres full-text search ANDs every
    # distinct query token together, so appending category-default words
    # (e.g. "1\" PVC" -> "...SCH40 BE CONDUIT GRAY") to the *retrieval* query
    # can silently zero out results that a narrower query would have found.
    catalog_search = _RecordingCatalogSearch()
    matcher = ProductMatcher([], catalog_search=catalog_search)
    matcher.match_description('1" PVC')
    assert catalog_search.search_text_queries
    assert all("SCH40" not in query.upper() for query in catalog_search.search_text_queries)
    assert all("GRAY" not in query.upper() for query in catalog_search.search_text_queries)


def test_retrieval_ranking_hint_is_the_expanded_query() -> None:
    # The expanded query is safe (and useful) as a *ranking* hint even though
    # it must never narrow eligibility: pg_trgm's similarity() favors short
    # catalog text over a longer, more precise row that actually spells out
    # the implied default wording, so ranking against the expanded query
    # counteracts that bias without touching which rows are eligible.
    catalog_search = _RecordingCatalogSearch()
    matcher = ProductMatcher([], catalog_search=catalog_search)
    matcher.match_description('1" PVC')
    assert catalog_search.rank_queries
    assert any("SCH40" in (query or "").upper() for query in catalog_search.rank_queries)


def test_matcher_ranks_plain_steel_over_unrequested_stainless_variant() -> None:
    # Regression test: score_product_fields returns a frozen ScoreBreakdown --
    # capping a conflicting candidate's score must replace it, not mutate it
    # in place (that raised dataclasses.FrozenInstanceError in production).
    products = [
        ProductRecord(
            salsify_id="PLAIN-1",
            official_part_number="PLAIN-1",
            description="1/2 EMT ONE HOLE STRAP STEEL ZINC PLATED",
            record_type="product",
        ),
        ProductRecord(
            salsify_id="STAINLESS-1",
            official_part_number="STAINLESS-1",
            description="1/2 EMT ONE HOLE STRAP STAINLESS STEEL 316 #4 POLISHED FINISH",
            record_type="product",
        ),
    ]
    matcher = ProductMatcher(products)
    result = matcher.match_description("1/2 EMT ONE HOLE STRAP")
    assert result.candidate_count == 2
    by_part = {item.official_part_number: item.score for item in result.candidates}
    assert by_part["PLAIN-1"] > by_part["STAINLESS-1"]


def test_bare_category_queries_are_not_treated_as_product_codes() -> None:
    # A bare "<size> <category>" description (e.g. "1 PVC") is short and
    # alphabetic, so it used to pass is_product_code_query() and get routed
    # to identifier-substring search instead of description search --
    # producing near-random hits instead of the real SCH40 conduit stick.
    for category in ("PVC", "EMT", "GRC", "LT", "STRUT", "CHANNEL"):
        assert is_product_code_query(f"1 {category}") is False


def test_real_identifier_queries_are_still_treated_as_product_codes() -> None:
    assert is_product_code_query("B1EB5-W") is True
    assert is_product_code_query("2EB40-B-SC") is True
