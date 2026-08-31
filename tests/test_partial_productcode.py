from __future__ import annotations

from catalog.postgres_repository import product_from_postgres_row
from matching.matcher import ProductMatcher
from matching.models import MatchingConfig, MatchStatus, ProductRecord, QuoteLine
from matching.productcode import (
    compact_code,
    embedded_query_hits,
    identifier_retrieval_hit,
    score_product_code_identifier,
)
from matching.request_text import interpret_customer_text
from matching.scoring import score_pair, score_product_fields
from output.match_evidence import build_match_evidence


def _pg_product(
    row_id: int,
    productcode: object,
    name: str | None,
    description: str | None,
    description2: str | None = None,
) -> ProductRecord:
    record = product_from_postgres_row(
        productcode=productcode,
        name=name,
        description=description,
        description2=description2,
        row_id=row_id,
    )
    assert record is not None
    return record


def _line(text: str) -> QuoteLine:
    return QuoteLine(
        source_file="quote.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description=text,
        quantity=1,
    )


def _catalog() -> list[ProductRecord]:
    return [
        _pg_product(333427, "B1EB5-W", "B1EB5-W", "BRP 120V WHIP END EXT CBL", "BRP 120V WHIP END EXT CBL"),
        _pg_product(333477, "RR 2BA KR", "RR 2BA KR", "RR 2BA KR", None),
        _pg_product(333478, "RR 2B KR", "RR 2B KR", "RR 2B KR", None),
        _pg_product(900003, "WHIP-A", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
        _pg_product(900004, "WHIP-B", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
    ]


def _rr_variant_catalog() -> list[ProductRecord]:
    return [
        _pg_product(333478, 333478, "RR 2BA KL", "RR 2BA KL", None),
        _pg_product(333479, 333479, "RR 2BA KR", "RR 2BA KR", None),
        _pg_product(333427, "B1EB5-W", "B1EB5-W", "BRP 120V WHIP END EXT CBL", "BRP 120V WHIP END EXT CBL"),
    ]


def test_partial_productcode_match_rr_2b_ba() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("RR 2B BA"))
    assert result.candidate_count >= 1
    assert result.candidates[0].official_part_number == "RR 2BA KR"
    assert result.candidates[0].score > 0
    assert result.top_score > 0
    assert result.match_status != MatchStatus.NO_MATCH
    assert result.match_status in {
        MatchStatus.EXACT_MATCH,
        MatchStatus.HIGH_CONFIDENCE,
        MatchStatus.REVIEW_REQUIRED,
    }
    if result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}:
        raise AssertionError("partial Productcode match must not be high-confidence MATCH")
    evidence = build_match_evidence(result)
    assert "Partial Productcode / Name Match" in (
        evidence["headline"],
        *(result.match_reasons or []),
    )


def test_rr_2ba_and_exact_and_negatives() -> None:
    matcher = ProductMatcher(_catalog())
    partial = matcher.match_line(_line("RR 2BA"))
    assert partial.match_status != MatchStatus.EXACT_MATCH
    assert partial.match_status != MatchStatus.HIGH_CONFIDENCE
    exact = matcher.match_line(_line("RR 2BA KR"))
    assert exact.match_status == MatchStatus.EXACT_MATCH
    assert exact.matched_part_number == "RR 2BA KR"
    assert matcher.match_line(_line("RR")).match_status == MatchStatus.NO_MATCH
    assert matcher.match_line(_line("XYZ")).match_status == MatchStatus.NO_MATCH


def test_numeric_productcode_still_matches_via_name_or_description() -> None:
    # Productcode (333477) is a purely internal numeric id now -- irrelevant
    # to matching or identity. This verifies a partial text query still finds
    # the row via its name/description text and surfaces the real name-based
    # identifier ("RR 2BA KR"), never the internal numeric id.
    catalog = [
        _pg_product(333477, 333477, "RR 2BA KR", "RR 2BA KR", None),
        _pg_product(1, 1, "OTHER", "OTHER", None),
    ]
    result = ProductMatcher(catalog).match_line(_line("RR 2B BA"))
    assert result.match_status != MatchStatus.NO_MATCH
    assert result.candidates[0].official_part_number == "RR 2BA KR"
    assert result.candidates[0].score > 0


def test_pipeline_trace_previous_failure_was_candidate_floor() -> None:
    """Previous 0% NO_MATCH: description score ~22 was below the old candidate_floor 35 (A)."""
    product = _pg_product(333477, "RR 2BA KR", "RR 2BA KR", "RR 2BA KR", None)
    query = "RR 2B BA"
    matcher = ProductMatcher([product])
    interpreted = interpret_customer_text(
        query,
        official_keys=tuple(matcher._identifier_keys),
    )
    assert interpreted.has_identifier is False
    assert interpreted.has_description is True
    desc_only = score_pair(query, "RR 2BA KR").final
    ident_score, ident = score_product_code_identifier(query, "RR 2BA KR")
    assert ident_score > 0
    assert compact_code(query) == "RR2BBA"
    assert compact_code("RR 2BA KR") == "RR2BAKR"
    assert set(embedded_query_hits(query, "RR 2BA KR")) >= {"RR", "2B", "BA"}
    breakdown, field_scores, _matched, evidence = score_product_fields(query, product)
    assert field_scores["productcode"] > 0
    assert breakdown.final > MatchingConfig().candidate_floor
    assert identifier_retrieval_hit(query, product)
    result = matcher.match_line(_line(query))
    assert result.match_status != MatchStatus.NO_MATCH
    assert evidence.get("match_type") == "partial"
    # A = description-only score was below the old floor of 35; identity scoring still lifts it.
    assert desc_only < 35 <= breakdown.final


def test_existing_exact_and_review_still_hold() -> None:
    matcher = ProductMatcher(_catalog())
    exact = matcher.match_line(_line("B1EB5-W"))
    assert exact.match_status == MatchStatus.EXACT_MATCH
    assert exact.matched_part_number == "B1EB5-W"
    review = matcher.match_line(_line("120V LIGHTING WHIP W/PAULEX"))
    assert review.match_status == MatchStatus.REVIEW_REQUIRED
    assert review.matched_part_number is None


def test_rr2ba_ambiguous_variants_are_review_not_98_match() -> None:
    result = ProductMatcher(_rr_variant_catalog()).match_line(_line("RR2BA"))
    codes = {item.official_part_number for item in result.candidates}
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.candidate_count >= 2
    assert {"RR 2BA KL", "RR 2BA KR"} <= codes
    assert result.top_score < 90
    assert result.overall_match_score is not None
    assert result.overall_match_score < 90
    assert result.matched_part_number is None
    evidence = build_match_evidence(result)
    assert evidence["headline"] == "Multiple possible Productcode matches"
    assert evidence["productcode_match_type"] == "partial"
    for candidate in result.candidates[:2]:
        assert candidate.score != 98
        assert candidate.score < 90


def test_rr_2ba_kl_exact_productcode_match() -> None:
    result = ProductMatcher(_rr_variant_catalog()).match_line(_line("RR 2BA KL"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "RR 2BA KL"
    assert result.overall_match_score == 100
    evidence = build_match_evidence(result)
    assert "Exact Productcode" in evidence["headline"] or "Normalized Productcode" in evidence["headline"]


def test_rr_2ba_kr_exact_productcode_match() -> None:
    result = ProductMatcher(_rr_variant_catalog()).match_line(_line("RR 2BA KR"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "RR 2BA KR"
    compact = ProductMatcher(_rr_variant_catalog()).match_line(_line("RR2BAKR"))
    assert compact.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert compact.matched_part_number == "RR 2BA KR"


def test_rr_2b_ba_partial_with_multiple_variants_is_review() -> None:
    result = ProductMatcher(_rr_variant_catalog()).match_line(_line("RR 2B BA"))
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.match_status not in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    codes = {item.official_part_number for item in result.candidates}
    assert {"RR 2BA KL", "RR 2BA KR"} <= codes
    evidence = build_match_evidence(result)
    assert evidence["headline"] in {
        "Multiple possible Productcode matches",
        "Partial Productcode / Name Match",
    }


def test_unrelated_text_is_no_match() -> None:
    result = ProductMatcher(_rr_variant_catalog()).match_line(_line("PURPLE BANANA ENCLOSURE"))
    assert result.match_status == MatchStatus.NO_MATCH
    assert result.matched_part_number is None


def test_existing_exact_productcode_still_matches() -> None:
    result = ProductMatcher(_rr_variant_catalog()).match_line(_line("B1EB5-W"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "B1EB5-W"
