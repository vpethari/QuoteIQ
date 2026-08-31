from __future__ import annotations

from catalog.postgres_repository import product_from_postgres_row
from matching.confidence import decide_match_status
from matching.matcher import ProductMatcher
from matching.models import MatchingConfig, MatchStatus, ProductRecord, QuoteLine
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
    return QuoteLine("quote.xlsx", "Sheet1", 2, text, 1)


def _rr_catalog() -> list[ProductRecord]:
    return [
        _pg_product(333478, 333478, "RR 2BA KL", "RR 2BA KL", None),
        _pg_product(333479, 333479, "RR 2BA KR", "RR 2BA KR", None),
        _pg_product(
            333427,
            333427,
            "B1EB5-W",
            "BRP 120V WHIP END EXT CBL",
            "BRP 120V WHIP END EXT CBL",
        ),
        _pg_product(333500, 333500, "B277-LC", "BRP 277V LIGHTING CBL", None),
        _pg_product(900003, 900003, "WHIP-A", "120V LIGHTING WHIP W/PAULEX", "WHIP FAMILY"),
        _pg_product(900004, 900004, "WHIP-B", "120V LIGHTING WHIP W/PAULEX", "WHIP FAMILY"),
    ]


def test_rr2ba_is_review_not_high_confidence_match() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("RR2BA"))
    codes = {item.official_part_number for item in result.candidates}
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert {"RR 2BA KL", "RR 2BA KR"} <= codes
    assert result.matched_part_number is None
    assert result.overall_match_score is not None
    assert result.overall_match_score <= 86
    assert result.top_score < 90
    for candidate in result.candidates[:2]:
        assert candidate.score < 90
    evidence = build_match_evidence(result)
    assert "Multiple possible Productcode" in evidence["headline"]
    assert evidence["candidate_separation"] == "Ambiguous"
    assert evidence["status_label"] == "REVIEW_REQUIRED"


def test_rr_2ba_kr_exact_productcode_match() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("RR 2BA KR"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "RR 2BA KR"
    assert result.overall_match_score == 100
    evidence = build_match_evidence(result)
    assert "Exact Productcode" in evidence["headline"] or "Normalized Productcode" in evidence["headline"]
    assert evidence["productcode_match_type"] in {"exact", "normalized_exact"}


def test_normalized_productcode_spacing() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("RR2BAKR"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "RR 2BA KR"


def test_partial_productcode_is_never_auto_match() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("RR 2B BA"))
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.match_status not in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}


def test_brp_120_volts_is_normalized_description_match() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("BRP 120 volts whip end extension cable"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"
    evidence = build_match_evidence(result)
    assert "Exact Productcode" not in evidence["headline"]
    assert evidence["headline"] in {"Normalized Description Match", "Description Match"}
    assert evidence["numeric_units"] == "Match"


def test_word_order_description_match() -> None:
    matcher = ProductMatcher(_rr_catalog())
    ordered = matcher.match_line(_line("BRP 120 volts whip end extension cable"))
    shuffled = matcher.match_line(_line("whip end extension cable 120 volts"))
    assert shuffled.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert shuffled.matched_part_number == "B1EB5-W"
    assert abs((ordered.overall_match_score or 0) - (shuffled.overall_match_score or 0)) <= 15


def test_synonym_and_numeric_agreement() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("BRP 120V WHIP END EXT CBL"))
    assert result.matched_part_number == "B1EB5-W"
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}


def test_numeric_conflict_is_not_high_confidence() -> None:
    catalog = [
        _pg_product(
            333427,
            333427,
            "B1EB5-W",
            "BRP 120V WHIP END EXT CBL",
            "BRP 120V WHIP END EXT CBL",
        )
    ]
    result = ProductMatcher(catalog).match_line(_line("BRP 277 volts whip end extension cable"))
    assert result.matched_part_number is None
    assert result.match_status in {MatchStatus.NO_MATCH, MatchStatus.REVIEW_REQUIRED}
    if result.candidates:
        assert result.candidates[0].score <= 40
        assert any("Voltage mismatch" in reason for reason in result.candidates[0].match_reasons)


def test_two_equally_strong_descriptions_are_review() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("120V LIGHTING WHIP W/PAULEX"))
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert result.candidate_count >= 2
    evidence = build_match_evidence(result)
    assert evidence["candidate_separation"] == "Ambiguous"
    assert result.overall_match_score is not None
    assert result.overall_match_score <= 86


def test_small_score_gap_is_review() -> None:
    status = decide_match_status(
        top_score=72,
        second_score=70,
        score_gap=2,
        exact_unique=False,
        duplicate_top=False,
        candidate_count=2,
        config=MatchingConfig(),
        ident_type="none",
    )
    assert status == MatchStatus.REVIEW_REQUIRED


def test_large_score_gap_can_match() -> None:
    status = decide_match_status(
        top_score=98,
        second_score=76,
        score_gap=22,
        exact_unique=False,
        duplicate_top=False,
        candidate_count=2,
        config=MatchingConfig(),
        ident_type="none",
    )
    assert status == MatchStatus.HIGH_CONFIDENCE


def test_no_match_unrelated() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("PURPLE BANANA ENCLOSURE"))
    assert result.match_status == MatchStatus.NO_MATCH
    assert result.matched_part_number is None
