from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from catalog.excel_loader import load_catalog_records, load_matchable_products, load_quote_lines
from matching.attributes import extract_attributes
from matching.matcher import ProductMatcher, decide_match_status, match_quote
from matching.models import MatchingConfig, MatchStatus, ProductRecord, QuoteLine
from matching.normalizer import canonical_text, normalize_text
from matching.scoring import (
    calculate_exact_score,
    calculate_final_score,
    calculate_fuzzy_score,
    calculate_score_gap,
    calculate_token_score,
    clamp_score,
)
from matching.tokenizer import tokenize_description

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "Atkorepartsfile.xlsx"
QUOTE_PATH = ROOT / "data" / "inputfile.xlsx"

FAMILY_IDS = {
    "PP_DBL_EXT_CBL",
    "F4_LTG_CBL",
    "MECH-GATOR",
    "GS_RMC_NPL_HDG",
    "F4_WIP_END_EXT_CBL",
    "F4_DIST_CBL",
    "F3+_DBL_DIST_CBL",
    "F3+_DBL_EXT_CBL",
    "F4_SW_MOD",
    "F4_WIP_END_LTG_CBL",
    "MECH-FLOCOAT",
    "F4_EXT_CBL",
}


@pytest.fixture(scope="module")
def catalog_records() -> list[ProductRecord]:
    return load_catalog_records(CATALOG_PATH)


@pytest.fixture(scope="module")
def matcher(catalog_records: list[ProductRecord]) -> ProductMatcher:
    return ProductMatcher(catalog_records)


def test_catalog_counts(catalog_records: list[ProductRecord]) -> None:
    products = [item for item in catalog_records if item.record_type == "product"]
    families = [item for item in catalog_records if item.record_type == "family"]
    assert len(products) == 50
    assert len(families) == 12


def test_exact_unique_match(matcher: ProductMatcher) -> None:
    result = matcher.match_description("10/3 MCT")
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2EB40-B-SC"
    assert result.matching_percentage == 100.0
    assert any("Exact" in reason for reason in result.match_reasons)


def test_duplicate_description_requires_review(matcher: ProductMatcher) -> None:
    result = matcher.match_description("120V LIGHTING WHIP W/PAULEX", quantity=5)
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    part_numbers = {item.official_part_number for item in result.candidates}
    assert {"1LBP-W", "1LCP-W"} <= part_numbers
    assert any("same description" in reason.lower() for reason in result.match_reasons)


def test_abbreviation_difference(matcher: ProductMatcher) -> None:
    result = matcher.match_description("120V LTG WHIP")
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "1LC-W"
    assert canonical_text("120V LTG WHIP") == canonical_text("120V LIGHTING WHIP")


def test_case_and_whitespace_difference(matcher: ProductMatcher) -> None:
    result = matcher.match_description("  10/3   mct  ")
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2EB40-B-SC"
    assert normalize_text("  10/3   mct  ") == "10/3 MCT"


def test_attribute_matching() -> None:
    attrs = extract_attributes("120V LIGHTING WHIP W/PAULEX")
    assert "voltage:120V" in attrs
    assert "token:PAULEX" in attrs
    assert "phrase:LIGHTING WHIP" in attrs
    assert calculate_token_score("120V SWITCH MODULE", "120V SWITCH MODULE") == 100.0


def test_no_match(matcher: ProductMatcher) -> None:
    result = matcher.match_description("PURPLE BANANA ENCLOSURE")
    assert result.match_status == MatchStatus.NO_MATCH
    assert result.matched_part_number is None


def test_low_confidence_does_not_become_high(matcher: ProductMatcher) -> None:
    result = matcher.match_description("CABLE")
    assert result.match_status in {MatchStatus.NO_MATCH, MatchStatus.REVIEW_REQUIRED}
    assert result.match_status != MatchStatus.HIGH_CONFIDENCE
    assert result.matched_part_number is None


def test_ambiguous_switch_module(matcher: ProductMatcher) -> None:
    result = matcher.match_description("120V SWITCH MODULE", quantity=10)
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert {item.official_part_number for item in result.candidates} >= {"1SA", "1SC"}


def test_family_rows_never_appear_as_candidates(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    family_ids = {item.salsify_id for item in catalog_records if item.record_type == "family"}
    assert FAMILY_IDS <= family_ids
    result = matcher.match_description("120V LIGHTING CABLE")
    candidate_ids = {item.salsify_id for item in result.candidates}
    assert candidate_ids.isdisjoint(family_ids)
    for family_id in FAMILY_IDS:
        assert matcher.match_description(family_id).matched_part_number != family_id


def test_scores_stay_between_0_and_100(matcher: ProductMatcher) -> None:
    queries = [
        "10/3 MCT",
        "120V LIGHTING WHIP W/PAULEX",
        "277V LIGHTING CABLE",
        "zzzz-not-a-product",
    ]
    for query in queries:
        result = matcher.match_description(query)
        assert 0 <= result.matching_percentage <= 100
        for candidate in result.candidates:
            assert 0 <= candidate.score <= 100
            assert 0 <= candidate.score_percentage <= 100
    assert 0 <= clamp_score(-5) <= 100
    assert clamp_score(140) == 100


def test_candidate_ranking_is_deterministic(matcher: ProductMatcher) -> None:
    first = matcher.match_description("120V LIGHTING WHIP W/PAULEX")
    second = matcher.match_description("120V LIGHTING WHIP W/PAULEX")
    assert [item.official_part_number for item in first.candidates] == [
        item.official_part_number for item in second.candidates
    ]
    scores = [item.score for item in first.candidates]
    assert scores == sorted(scores, reverse=True)


def test_score_gap_calculated_correctly() -> None:
    top, second, gap = calculate_score_gap([80.0, 92.5, 40.0])
    assert top == 92.5
    assert second == 80.0
    assert gap == 12.5
    top_only, none_second, none_gap = calculate_score_gap([100.0])
    assert top_only == 100.0
    assert none_second is None
    assert none_gap is None


def test_match_explanations_generated(matcher: ProductMatcher) -> None:
    result = matcher.match_description("120V LIGHTING WHIP W/PAULEX")
    assert result.match_reasons
    assert any("PAULEX" in reason or "Voltage" in reason or "same description" in reason for reason in result.match_reasons)
    assert all(candidate.match_reasons for candidate in result.candidates[:2])


def test_quote_with_multiple_line_items(matcher: ProductMatcher) -> None:
    lines = load_quote_lines(QUOTE_PATH)
    assert [(line.requested_description, line.quantity) for line in lines] == [
        ("120V LIGHTING WHIP W/PAULEX", 5),
        ("277V LIGHTING CABLE", 20),
        ("120V SWITCH MODULE", 10),
    ]
    results = match_quote(lines, load_matchable_products(CATALOG_PATH))
    assert len(results) == 3
    for result, line in zip(results, lines, strict=True):
        assert result.source_file == "inputfile.xlsx"
        assert result.source_sheet == "Sheet1"
        assert result.source_row == line.source_row
        assert result.requested_description == line.requested_description
        assert result.quantity == line.quantity
        assert result.match_status == MatchStatus.REVIEW_REQUIRED
        assert result.matched_part_number is None


def test_tokenize_and_final_score_helpers() -> None:
    assert tokenize_description("120V LTG WHIP W/PAULEX") == ["120", "V", "LIGHTING", "WHIP", "PAULEX"]
    assert calculate_exact_score("10/3 MCT", "10/3 MCT") == 100
    assert calculate_fuzzy_score("ABC", "ABC") == 100
    final = calculate_final_score(100, 100, 100, 100)
    assert final == 100


def test_decide_status_uses_config_not_highest_score_alone() -> None:
    config = MatchingConfig()
    status = decide_match_status(
        top_score=99.0,
        second_score=98.8,
        score_gap=0.2,
        exact_unique=False,
        duplicate_top=True,
        candidate_count=2,
        config=config,
    )
    assert status == MatchStatus.REVIEW_REQUIRED


def test_matching_api(catalog_records: list[ProductRecord]) -> None:
    from app.main import app, get_matcher

    matcher = ProductMatcher(catalog_records)
    app.dependency_overrides[get_matcher] = lambda: matcher
    client = TestClient(app)
    try:
        health = client.get("/health")
        assert health.status_code == 200
        preview = client.post(
            "/api/matching/preview",
            json={"description": "120V LIGHTING WHIP W/PAULEX", "quantity": 5},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["match_status"] == "REVIEW_REQUIRED"
        assert body["matched_part_number"] is None
        quote = client.post(
            "/api/matching/quote",
            json={
                "lines": [
                    {
                        "source_file": "inputfile.xlsx",
                        "source_sheet": "Sheet1",
                        "source_row": 2,
                        "requested_description": "120V SWITCH MODULE",
                        "quantity": 10,
                    }
                ]
            },
        )
        assert quote.status_code == 200
        assert quote.json()["count"] == 1
        assert quote.json()["results"][0]["match_status"] == "REVIEW_REQUIRED"
        missing = client.post("/api/matching/preview", json={"description": ""})
        assert missing.status_code == 422
        empty_quote = client.post("/api/matching/quote", json={})
        assert empty_quote.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_quote_file_api(catalog_records: list[ProductRecord]) -> None:
    from app.main import app, get_matcher

    app.dependency_overrides[get_matcher] = lambda: ProductMatcher(catalog_records)
    client = TestClient(app)
    try:
        response = client.post(
            "/api/matching/quote",
            json={"source_path": str(QUOTE_PATH)},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 3
        statuses = {item["match_status"] for item in payload["results"]}
        assert statuses == {"REVIEW_REQUIRED"}
    finally:
        app.dependency_overrides.clear()
