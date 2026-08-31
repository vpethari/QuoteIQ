from __future__ import annotations

from fastapi.testclient import TestClient

from matching.matcher import ProductMatcher
from matching.models import MatchStatus
from matching.selection import apply_user_selection, apply_user_selection_payload
from tests.test_confidence_engine import _line, _pg_product, _rr_catalog


def test_exact_productcode_is_automatic_match() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("RR 2BA KR"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "RR 2BA KR"
    assert result.selection_type == "AUTOMATIC"
    assert result.match_type == "AUTOMATIC"
    assert "Exact Productcode" in (result.match_type_label or "")
    payload = result.to_api_dict()
    assert payload["selection_type"] == "AUTOMATIC"
    assert payload["candidates"][0]["rank"] == 1
    assert payload["candidates"][0]["productcode"] == "RR 2BA KR"


def test_rr2ba_returns_both_candidates_for_review() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("RR2BA"))
    payload = result.to_api_dict()
    codes = [item["productcode"] for item in payload["candidates"]]
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert {"RR 2BA KL", "RR 2BA KR"} <= set(codes)
    assert payload["selection_type"] is None
    assert len(payload["candidates"]) <= 3


def test_review_returns_at_most_three_ranked_candidates() -> None:
    catalog = [
        _pg_product(1, "W1", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
        _pg_product(2, "W2", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
        _pg_product(3, "W3", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
        _pg_product(4, "W4", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
    ]
    result = ProductMatcher(catalog).match_line(_line("120V LIGHTING WHIP W/PAULEX"))
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.candidate_count == 3
    assert len(result.candidates) == 3
    scores = [item.score for item in result.candidates]
    assert scores == sorted(scores, reverse=True)
    ranks = [item.rank for item in result.candidates]
    assert ranks == [1, 2, 3]


def test_candidates_are_sorted_by_confidence_descending() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("RR 2BA KR"))
    scores = [item.score for item in result.candidates]
    assert scores == sorted(scores, reverse=True)


def test_manual_selection_marks_user_selected_match() -> None:
    matcher = ProductMatcher(_rr_catalog())
    result = matcher.match_line(_line("RR2BA"))
    original = result.overall_match_score
    payload = apply_user_selection_payload(result.to_api_dict(), "RR 2BA KR", quote_line_id=result.quote_line_id)
    selected = apply_user_selection(result, "RR 2BA KR")
    assert selected.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert selected.matched_part_number == "RR 2BA KR"
    assert selected.match_type == "USER_SELECTED"
    assert selected.selection_type == "USER_SELECTED"
    assert selected.original_confidence == original
    assert selected.overall_match_score == original
    assert selected.requested_description == "RR2BA"
    assert selected.quantity == 1
    assert payload["match_type"] == "USER_SELECTED"
    assert payload["matched_part_number"] == "RR 2BA KR"
    assert payload["match_status"] == "HIGH_CONFIDENCE"
    assert payload["original_confidence"] == original


def test_no_match_has_no_candidates() -> None:
    result = ProductMatcher(_rr_catalog()).match_line(_line("PURPLE BANANA ENCLOSURE"))
    assert result.match_status == MatchStatus.NO_MATCH
    assert result.candidates == []
    assert result.candidate_count == 0
    assert result.to_api_dict()["candidates"] == []


def test_select_endpoint_updates_review_result() -> None:
    from app.main import app, get_matcher

    matcher = ProductMatcher(_rr_catalog())
    app.dependency_overrides[get_matcher] = lambda: matcher
    client = TestClient(app)
    try:
        preview = client.post("/api/matching/preview", json={"description": "RR2BA", "quantity": 1})
        assert preview.status_code == 200
        body = preview.json()
        assert body["match_status"] == "REVIEW_REQUIRED"
        selected = client.post(
            "/api/quote/match/select",
            json={
                "quote_line_id": body["quote_line_id"],
                "productcode": "RR 2BA KR",
                "result": body,
            },
        )
        assert selected.status_code == 200
        payload = selected.json()
        assert payload["match_status"] == "HIGH_CONFIDENCE"
        assert payload["match_type"] == "USER_SELECTED"
        assert payload["matched_part_number"] == "RR 2BA KR"
        assert payload["requested_description"] == "RR2BA"
        assert payload["original_confidence"] == body["original_confidence"]
    finally:
        app.dependency_overrides.clear()
