from __future__ import annotations

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
