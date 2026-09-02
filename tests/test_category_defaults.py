from __future__ import annotations

from matching.category_defaults import (
    candidate_color_conflicts,
    default_color_for_query,
    expand_bare_category_query,
    expand_hole_count,
    expand_known_phrases,
    mentions_no_spring,
    mentions_stainless,
    normalize_strut_catalog_codes,
    unrequested_specialty_marker,
    wants_spring_nut,
)
from matching.description_normalize import expand_query_for_retrieval, tokenize_description
from matching.matcher import ProductMatcher
from matching.models import MatchingConfig, ProductRecord, ScoreBreakdown
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


def test_expand_query_for_retrieval_chains_all_expansions() -> None:
    expanded = expand_query_for_retrieval('1" PVC')
    assert "SCH40 BE CONDUIT GRAY" in expanded


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

    def lookup_productcode(self, identifier: str, limit: int | None = None) -> list[ProductRecord]:
        return []

    def fetch_identifier_candidates(self, query: str, limit: int | None = None) -> list[ProductRecord]:
        return []

    def search_text_candidates(self, query: str, limit: int | None = None) -> list[ProductRecord]:
        self.search_text_queries.append(query)
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
