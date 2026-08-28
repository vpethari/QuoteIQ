from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from ai.models import AIDecision, AIReasoningResult, CandidateEvaluation, FinalMatchResult
from ai.provider import MockAIReasoningProvider
from ai.service import AIMatchingService, AIPolicyConfig, InMemoryAuditStore
from catalog.excel_loader import load_catalog_records
from matching.matcher import ProductMatcher
from matching.models import MatchCandidate, MatchResult, MatchStatus, QuoteLine
from output.csv_writer import render_csv, render_csv_bytes
from output.pipeline import process_quote_to_csv
from output.rows import csv_row_from_final_result, csv_row_from_match_result, format_matching_percentage
from output.schema import CSV_COLUMNS
from quotes.models import QuoteParseError
from quotes.parser import parse_quote_file

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "Atkorepartsfile.xlsx"
QUOTE_PATH = ROOT / "data" / "inputfile.xlsx"


def _write_xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()
    return path


def _parse_csv(payload: bytes) -> list[dict[str, str]]:
    text = payload.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_header_order() -> None:
    text = render_csv([])
    header = next(csv.reader(io.StringIO(text)))
    assert tuple(header) == CSV_COLUMNS


def test_confident_match_produces_part_number() -> None:
    result = FinalMatchResult(
        requested_description="10/3 MCT",
        quantity=1,
        matched_part_number="2EB40-B-SC",
        matched_description="10/3 MCT",
        matched_salsify_id="NA1-2EB40-B-SC",
        deterministic_score=100,
        ai_confidence=95,
        final_confidence=95,
        match_status="CONFIDENT_MATCH",
        reasoning_summary="Exact normalized description match; unique catalog product.",
        candidate_count=1,
        candidate_details=[
            {
                "official_part_number": "2EB40-B-SC",
                "description": "10/3 MCT",
                "salsify_id": "NA1-2EB40-B-SC",
                "deterministic_score": 100,
            }
        ],
    )
    row = csv_row_from_final_result(result)
    assert row["Matched Atkore Part Number"] == "2EB40-B-SC"
    assert row["Matched Salsify ID"] == "NA1-2EB40-B-SC"
    assert row["Confidence"] == "HIGH"
    assert row["Matching Percentage"] == "95"


def test_review_and_no_match_blank_part_number() -> None:
    review = MatchResult(
        source_file="inputfile.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description="120V LIGHTING WHIP W/PAULEX",
        quantity=5,
        matched_part_number="1LBP-W",
        matched_description="120V LIGHTING WHIP W/PAULEX",
        matched_salsify_id="NA1-1LBP-W",
        matching_percentage=100,
        confidence_level="REVIEW_REQUIRED",
        match_status=MatchStatus.REVIEW_REQUIRED,
        candidate_count=3,
        candidates=[
            MatchCandidate("1LAP-W", "120V LTG WHIP W/PAULEX", "NA1-1LAP-W", 100, 100),
            MatchCandidate("1LBP-W", "120V LIGHTING WHIP W/PAULEX", "NA1-1LBP-W", 100, 100),
        ],
        match_reasons=["Multiple Atkore products have the same description"],
        top_score=100,
        second_score=100,
        score_gap=0,
    )
    review_row = csv_row_from_match_result(review)
    assert review_row["Matched Atkore Part Number"] == ""
    assert review_row["Confidence"] == "REVIEW"
    none = csv_row_from_final_result(
        FinalMatchResult(
            requested_description="UNKNOWN",
            quantity=1,
            match_status="NO_MATCH",
            deterministic_score=12,
            final_confidence=12,
            reasoning_summary="No sufficiently similar Atkore product found.",
            candidate_count=0,
        )
    )
    assert none["Matched Atkore Part Number"] == ""
    assert none["Confidence"] == "LOW"


def test_csv_escaping_commas_quotes_unicode() -> None:
    rows = [
        {
            "Source File": "q.xlsx",
            "Source Sheet": "Sheet1",
            "Source Row": "2",
            "Requested Description": 'CABLE, 6" WHIP café',
            "Quantity": "3",
            "Matched Atkore Part Number": "",
            "Matched Atkore Description": "",
            "Matching Percentage": "87",
            "Confidence": "REVIEW",
            "Match Status": "REVIEW_REQUIRED",
            "Match Reason": 'Said "review"',
            "Candidate Count": "2",
            "Top Candidates": "1LA (80); 1LB (79)",
        }
    ]
    parsed = _parse_csv(render_csv_bytes(rows))
    assert parsed[0]["Requested Description"] == 'CABLE, 6" WHIP café'
    assert parsed[0]["Match Reason"] == 'Said "review"'
    assert parsed[0]["Matching Percentage"] == "87"
    assert "%" not in parsed[0]["Matching Percentage"]


def test_numeric_matching_percentage_and_candidates() -> None:
    assert format_matching_percentage(100.0) == "100"
    assert format_matching_percentage(94.0) == "94"
    assert "%" not in format_matching_percentage(87.5)
    result = MatchResult(
        source_file="a.xlsx",
        source_sheet="S",
        source_row=1,
        requested_description="x",
        quantity=1,
        matched_part_number=None,
        matched_description=None,
        matched_salsify_id=None,
        matching_percentage=100,
        confidence_level="REVIEW_REQUIRED",
        match_status=MatchStatus.REVIEW_REQUIRED,
        candidate_count=3,
        candidates=[
            MatchCandidate("1LAP-W", "d", "id1", 100, 100),
            MatchCandidate("1LBP-W", "d", "id2", 100, 100),
            MatchCandidate("1LCP-W", "d", "id3", 100, 100),
        ],
        match_reasons=["tie"],
        top_score=100,
        second_score=100,
        score_gap=0,
    )
    row = csv_row_from_match_result(result)
    assert row["Top Candidates"] == "1LAP-W (100); 1LBP-W (100); 1LCP-W (100)"
    assert row["Candidate Count"] == "3"


def test_excel_quote_parser_blank_and_totals(tmp_path: Path) -> None:
    path = _write_xlsx(
        tmp_path / "quote.xlsx",
        ["Name", "Qty"],
        [
            ["120V SWITCH MODULE", 10],
            [None, None],
            ["Subtotal", 99],
            ["277V LIGHTING CABLE", 20],
        ],
    )
    items = parse_quote_file(path)
    assert [(item.requested_description, item.quantity, item.source_row) for item in items] == [
        ("120V SWITCH MODULE", 10, 2),
        ("277V LIGHTING CABLE", 20, 5),
    ]


def test_parser_alternate_headers(tmp_path: Path) -> None:
    path = _write_xlsx(
        tmp_path / "desc.xlsx",
        ["Product", "Quantity"],
        [["Widget", 2]],
    )
    items = parse_quote_file(path)
    assert items[0].requested_description == "Widget"
    assert items[0].quantity == 2


def test_missing_description_and_quantity_columns(tmp_path: Path) -> None:
    missing_desc = _write_xlsx(tmp_path / "no-desc.xlsx", ["Foo", "Bar"], [["A", "B"]])
    with pytest.raises(QuoteParseError, match="customer text"):
        parse_quote_file(missing_desc)
    name_without_qty = _write_xlsx(tmp_path / "no-qty.xlsx", ["Name", "Other"], [["A", 1]])
    items = parse_quote_file(name_without_qty)
    assert items[0].requested_description == "A"
    assert items[0].quantity is None


def test_invalid_quantity_and_workbook(tmp_path: Path) -> None:
    bad_qty = _write_xlsx(tmp_path / "bad-qty.xlsx", ["Name", "Qty"], [["Cable", "not-a-number"]])
    with pytest.raises(QuoteParseError, match="Invalid quantity"):
        parse_quote_file(bad_qty)
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"not an excel file")
    with pytest.raises(QuoteParseError, match="Unable to read"):
        parse_quote_file(junk)


def test_current_inputfile_parser() -> None:
    items = parse_quote_file(QUOTE_PATH)
    assert len(items) == 3
    assert items[0].requested_description == "120V LIGHTING WHIP W/PAULEX"


def test_invented_part_cannot_enter_csv() -> None:
    result = FinalMatchResult(
        requested_description="10/3 MCT",
        quantity=1,
        matched_part_number=None,
        match_status="REVIEW_REQUIRED",
        deterministic_score=100,
        final_confidence=40,
        reasoning_summary="AI selected a part number that was not in the candidate list",
        validation_rejected=True,
        candidate_count=1,
        candidate_details=[
            {
                "official_part_number": "2EB40-B-SC",
                "deterministic_score": 100,
            }
        ],
    )
    row = csv_row_from_final_result(result)
    assert row["Matched Atkore Part Number"] == ""
    assert "FAKE" not in row["Top Candidates"]


def test_complete_pipeline_ai_disabled() -> None:
    catalog = load_catalog_records(CATALOG_PATH)
    matcher = ProductMatcher(catalog)
    payload = process_quote_to_csv(QUOTE_PATH, matcher, use_ai=False)
    rows = _parse_csv(payload)
    assert len(rows) == 3
    for row in rows:
        assert row["Match Status"] == "REVIEW_REQUIRED"
        assert row["Matched Atkore Part Number"] == ""
        assert row["Confidence"] == "REVIEW"
        assert row["Top Candidates"]
        assert row["Matching Percentage"] == "86"
        assert row["Part Number Match %"] == "N/A"
        assert row["Description Match %"] == "100"
        assert row["Overall Match %"] == "86"
        assert row["Requested Part Number"] == ""


def test_complete_pipeline_mock_ai() -> None:
    catalog = load_catalog_records(CATALOG_PATH)
    matcher = ProductMatcher(catalog)
    service = AIMatchingService(
        matcher,
        catalog,
        MockAIReasoningProvider(),
        AIPolicyConfig(),
        InMemoryAuditStore(),
    )
    payload = process_quote_to_csv(
        QUOTE_PATH, matcher, use_ai=True, ai_service=service
    )
    rows = _parse_csv(payload)
    assert len(rows) == 3
    for row in rows:
        assert row["Match Status"] == "REVIEW_REQUIRED"
        assert row["Matched Atkore Part Number"] == ""


def test_quote_process_api_and_csv_export(tmp_path: Path) -> None:
    from app.main import app, get_ai_provider, get_matcher, get_settings

    catalog = load_catalog_records(CATALOG_PATH)
    matcher = ProductMatcher(catalog)
    app.dependency_overrides[get_matcher] = lambda: matcher
    app.dependency_overrides[get_ai_provider] = lambda: MockAIReasoningProvider()
    client = TestClient(app)
    try:
        with QUOTE_PATH.open("rb") as handle:
            response = client.post(
                "/api/quote/process",
                files={"file": ("inputfile.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"use_ai": "false"},
            )
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "QuoteIQ_results.csv" in response.headers["content-disposition"]
        rows = _parse_csv(response.content)
        assert len(rows) == 3
        assert all(row["Matched Atkore Part Number"] == "" for row in rows)

        with QUOTE_PATH.open("rb") as handle:
            ai_response = client.post(
                "/api/quote/process",
                files={"file": ("inputfile.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"use_ai": "true"},
            )
        assert ai_response.status_code == 200
        ai_rows = _parse_csv(ai_response.content)
        assert all(row["Match Status"] == "REVIEW_REQUIRED" for row in ai_rows)
        assert all(row["Matched Atkore Part Number"] == "" for row in ai_rows)

        export = client.post(
            "/api/output/csv",
            json={
                "results": [
                    {
                        "requested_description": "10/3 MCT",
                        "quantity": 1,
                        "match_status": "CONFIDENT_MATCH",
                        "matched_part_number": "2EB40-B-SC",
                        "matched_description": "10/3 MCT",
                        "matching_percentage": 100,
                        "candidate_count": 1,
                        "candidates": [
                            {
                                "official_part_number": "2EB40-B-SC",
                                "score": 100,
                            }
                        ],
                    }
                ]
            },
        )
        assert export.status_code == 200
        exported = _parse_csv(export.content)
        assert exported[0]["Matched Atkore Part Number"] == "2EB40-B-SC"

        settings = get_settings()
        original_max = settings.quote_upload_max_bytes
        settings.quote_upload_max_bytes = 16
        try:
            too_big = client.post(
                "/api/quote/process",
                files={"file": ("quote.xlsx", b"0123456789abcdef0123", "application/octet-stream")},
                data={"use_ai": "false"},
            )
            assert too_big.status_code == 413
        finally:
            settings.quote_upload_max_bytes = original_max

        xls = client.post(
            "/api/quote/process",
            files={"file": ("quote.xls", b"abc", "application/vnd.ms-excel")},
            data={"use_ai": "false"},
        )
        assert xls.status_code == 400
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_validated_part_number_only_invented_ai_not_in_csv() -> None:
    catalog = load_catalog_records(CATALOG_PATH)
    matcher = ProductMatcher(catalog)
    canned = AIReasoningResult(
        decision=AIDecision.CONFIDENT_MATCH,
        selected_part_number="FAKE-999",
        confidence_percentage=99,
        reasoning_summary="invented",
        candidate_evaluations=[
            CandidateEvaluation(official_part_number="FAKE-999", assessment="bad", score=99)
        ],
    )
    service = AIMatchingService(
        matcher,
        catalog,
        MockAIReasoningProvider(canned=canned),
        AIPolicyConfig(),
        InMemoryAuditStore(),
    )
    payload = process_quote_to_csv(QUOTE_PATH, matcher, use_ai=True, ai_service=service)
    text = payload.decode("utf-8-sig")
    assert "FAKE-999" not in text
    rows = _parse_csv(payload)
    assert all(row["Matched Atkore Part Number"] == "" for row in rows)


def test_quote_process_results_json_endpoint() -> None:
    from app.main import app, get_ai_provider, get_matcher

    catalog = load_catalog_records(CATALOG_PATH)
    matcher = ProductMatcher(catalog)
    app.dependency_overrides[get_matcher] = lambda: matcher
    app.dependency_overrides[get_ai_provider] = lambda: MockAIReasoningProvider()
    client = TestClient(app)
    try:
        with QUOTE_PATH.open("rb") as handle:
            response = client.post(
                "/api/quote/process/results",
                files={
                    "file": (
                        "inputfile.xlsx",
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                data={"use_ai": "false"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["summary"] == {
            "total": 3,
            "matched": 0,
            "review_required": 3,
            "no_match": 0,
        }
        assert len(body["results"] ) == 3
        first = body["results"][0]
        assert first["match_status"] == "REVIEW_REQUIRED"
        assert first["matched_part_number"] is None
        assert first["candidates"]
        assert "official_part_number" in first["candidates"][0]
    finally:
        app.dependency_overrides.clear()

