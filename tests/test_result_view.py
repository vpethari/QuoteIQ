from __future__ import annotations

import pytest

from ai.models import FinalMatchResult
from matching.models import MatchCandidate, MatchResult, MatchStatus
from output.result_view import normalize_result


def _match_result(**overrides: object) -> MatchResult:
    defaults: dict[str, object] = dict(
        source_file="quote.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description="10/3 MCT",
        quantity=1,
        matched_part_number="2EB40-B-SC",
        matched_description="10/3 MCT",
        matched_salsify_id="NA1-2EB40-B-SC",
        matched_orderable_part_number="ORD-2EB40",
        matching_percentage=100,
        confidence_level="EXACT_MATCH",
        match_status=MatchStatus.EXACT_MATCH,
        candidate_count=1,
        candidates=[
            MatchCandidate("2EB40-B-SC", "10/3 MCT", "NA1-2EB40-B-SC", 100, 100, orderable_part_number="ORD-2EB40"),
        ],
        match_reasons=["Exact match"],
        top_score=100,
        second_score=None,
        score_gap=None,
        quote_line_id="quote.xlsx|Sheet1|2|10/3 MCT",
        original_confidence=100.0,
        selection_type="AUTOMATIC",
        match_type="AUTOMATIC",
        match_type_label="Automatic — Exact Productcode",
        raw_row={"Name": "10/3 MCT", "Qty": "1"},
    )
    defaults.update(overrides)
    return MatchResult(**defaults)


def test_normalize_result_gates_matched_fields_for_review_required() -> None:
    # A candidate can be pre-populated on the object before a status flip,
    # so the view must gate on status, not merely on whether the fields
    # happen to hold a value.
    result = _match_result(match_status=MatchStatus.REVIEW_REQUIRED, confidence_level="REVIEW_REQUIRED")
    view = normalize_result(result)
    assert view.matched_part_number is None
    assert view.matched_description is None
    assert view.matched_salsify_id is None
    assert view.matched_orderable_part_number is None
    assert view.match_status == "REVIEW_REQUIRED"


def test_normalize_result_match_result_matched_row() -> None:
    view = normalize_result(_match_result())
    assert view.match_status == "EXACT_MATCH"
    assert view.matched_part_number == "2EB40-B-SC"
    assert view.matched_orderable_part_number == "ORD-2EB40"
    assert view.quote_line_id == "quote.xlsx|Sheet1|2|10/3 MCT"
    assert view.original_confidence == 100.0
    assert view.match_type_label == "Automatic — Exact Productcode"
    assert view.candidate_count == 1
    assert view.candidates == [
        {
            "official_part_number": "2EB40-B-SC",
            "orderable_part_number": "ORD-2EB40",
            "description": "10/3 MCT",
            "salsify_id": "NA1-2EB40-B-SC",
            "score": 100,
            "match_reasons": [],
            "name": None,
        }
    ]


def test_normalize_result_final_match_result() -> None:
    result = FinalMatchResult(
        source_file="quote.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description="10/3 MCT",
        quantity=1,
        matched_part_number="2EB40-B-SC",
        matched_description="10/3 MCT",
        matched_salsify_id="NA1-2EB40-B-SC",
        matched_orderable_part_number="ORD-2EB40",
        deterministic_score=100,
        ai_confidence=95,
        final_confidence=95,
        match_status="CONFIDENT_MATCH",
        reasoning_summary="AI confirmed",
        candidate_count=1,
        candidate_details=[
            {"official_part_number": "2EB40-B-SC", "orderable_part_number": "ORD-2EB40", "score": 95}
        ],
        quote_line_id="quote.xlsx|Sheet1|2|10/3 MCT",
        original_confidence=100.0,
        selection_type="AUTOMATIC",
        match_type="AUTOMATIC",
        match_type_label="Automatic — AI Confirmed",
    )
    view = normalize_result(result)
    assert view.match_status == "CONFIDENT_MATCH"
    assert view.matched_part_number == "2EB40-B-SC"
    assert view.matching_percentage == 95
    assert view.match_type_label == "Automatic — AI Confirmed"
    assert view.candidates[0]["orderable_part_number"] == "ORD-2EB40"


def test_normalize_result_raw_json_payload_round_trip() -> None:
    # The shape serialize_process_result() itself produces, round-tripped
    # back in as a plain dict (the "Full Results" re-download path).
    payload = {
        "source_row": 2,
        "requested_description": "10/3 MCT",
        "quantity": 1,
        "match_status": "EXACT_MATCH",
        "matched_part_number": "2EB40-B-SC",
        "matched_orderable_part_number": "ORD-2EB40",
        "matching_percentage": 100,
        "candidates": [{"official_part_number": "2EB40-B-SC", "orderable_part_number": "ORD-2EB40", "score": 100}],
        "raw_row": {"Name": "10/3 MCT", "Qty": "1"},
        "match_type_label": "Automatic — Exact Productcode",
    }
    view = normalize_result(payload)
    assert view.matched_part_number == "2EB40-B-SC"
    assert view.matched_orderable_part_number == "ORD-2EB40"
    assert view.match_type_label == "Automatic — Exact Productcode"
    assert view.raw_row == {"Name": "10/3 MCT", "Qty": "1"}


def test_normalize_result_raw_json_payload_gates_on_status() -> None:
    payload = {
        "requested_description": "UNKNOWN WIDGET",
        "match_status": "REVIEW_REQUIRED",
        "matched_part_number": "SHOULD-NOT-SHOW",
    }
    view = normalize_result(payload)
    assert view.matched_part_number is None


def test_normalize_result_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError):
        normalize_result(object())
