from __future__ import annotations

from ai.models import FinalMatchResult
from output.api_results import serialize_process_result
from output.match_evidence import build_match_evidence, evidence_headline
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.matcher import ProductMatcher


def test_headline_examples() -> None:
    assert (
        evidence_headline(
            status="EXACT_MATCH",
            part_number_match=True,
            description_match=True,
            scores={"productcode": 100, "name": 100, "description": 100, "description2": 100},
        )
        == "Exact Productcode + Description Match"
    )
    assert (
        evidence_headline(
            status="HIGH_CONFIDENCE",
            part_number_match=False,
            description_match=True,
            scores={"productcode": 0, "name": 0, "description": 94, "description2": 0},
        )
        == "Description Match"
    )
    assert (
        evidence_headline(
            status="EXACT_MATCH",
            part_number_match=True,
            description_match=False,
            scores={"productcode": 100, "name": 20, "description": 10, "description2": 0},
        )
        == "Exact Productcode Match"
    )
    assert (
        evidence_headline(
            status="REVIEW_REQUIRED",
            part_number_match=False,
            description_match=True,
            scores={"productcode": 0, "name": 0, "description": 100, "description2": 0},
        )
        == "Multiple products have equivalent description matches"
    )
    assert (
        evidence_headline(
            status="NO_MATCH",
            part_number_match=False,
            description_match=False,
            scores={},
        )
        == "No sufficiently similar product found"
    )


def test_serialize_adds_evidence_without_removing_fields() -> None:
    catalog = [
        ProductRecord(
            salsify_id="B1EB5-W",
            official_part_number="B1EB5-W",
            description="BRP 120V WHIP END EXT CBL",
            record_type="product",
            name="B1EB5-W",
            description2="BRP 120V WHIP END EXT CBL",
            catalog_row_id="333427",
        )
    ]
    result = ProductMatcher(catalog).match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="S",
            source_row=2,
            requested_description="B1EB5-W BRP 120V WHIP END EXT CBL",
            quantity=1,
        )
    )
    payload = serialize_process_result(result)
    assert "matched_part_number" in payload
    assert "match_status" in payload
    assert "match_reason" in payload
    assert payload["matched_part_number"] == "B1EB5-W"
    assert payload["matched_part_number"] != "333427"
    evidence = payload["match_evidence"]
    assert evidence["status_label"] == "MATCH"
    assert evidence["matched_part_number"] == "B1EB5-W"
    assert {item["field"] for item in evidence["fields"]} == {
        "Productcode",
        "name",
        "description",
        "description2",
    }
    assert result.match_status == MatchStatus.EXACT_MATCH
    built = build_match_evidence(result)
    assert built["headline"]
    assert "333427" not in str(built)


def test_evidence_overall_percent_matches_top_level_for_ai_no_match() -> None:
    """For NO_MATCH/REVIEW_REQUIRED, serialize_process_result shows
    deterministic_score (raw candidate similarity), not final_confidence
    (AI's own confidence in *rejecting* the match -- often 0 or very low).
    The evidence panel must use the same rule, not blindly prefer
    final_confidence, or it'll show a different, much lower number.
    """
    result = FinalMatchResult(
        requested_description='4" HW FRE CONDUIT',
        deterministic_score=44.0,
        ai_confidence=0.0,
        final_confidence=0.0,
        match_status="NO_MATCH",
        reasoning_summary="No candidate is sufficiently relevant.",
        candidate_count=3,
        ai_enabled=True,
        overall_match_score=None,
    )
    payload = serialize_process_result(result)
    assert payload["overall_match_score"] == 44
    evidence = payload["match_evidence"]
    assert evidence["overall_percent"] == 44.0


def test_evidence_overall_percent_uses_final_confidence_for_confident_match() -> None:
    """For an emitting status (CONFIDENT_MATCH), the top-level display and
    the evidence panel both use final_confidence, not deterministic_score."""
    result = FinalMatchResult(
        requested_description="B1EB5-W",
        matched_part_number="B1EB5-W",
        deterministic_score=100.0,
        ai_confidence=95.0,
        final_confidence=95.0,
        match_status="CONFIDENT_MATCH",
        reasoning_summary="Unique high-scoring candidate.",
        candidate_count=1,
        ai_enabled=True,
        overall_match_score=None,
    )
    payload = serialize_process_result(result)
    assert payload["overall_match_score"] == 95
    evidence = payload["match_evidence"]
    assert evidence["overall_percent"] == 95.0
