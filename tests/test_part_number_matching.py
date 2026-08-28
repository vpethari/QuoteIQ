from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from ai.models import AIDecision, AIReasoningResult, CandidateEvaluation
from ai.provider import MockAIReasoningProvider
from ai.service import AIMatchingService, AIPolicyConfig, InMemoryAuditStore
from catalog.excel_loader import load_catalog_records
from matching.matcher import ProductMatcher, match_quote
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.normalizer import normalize_part_number, part_numbers_equivalent
from quotes.parser import parse_quote_file

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "Atkorepartsfile.xlsx"
QUOTE_PATH = ROOT / "data" / "inputfile.xlsx"


@pytest.fixture(scope="module")
def catalog_records() -> list[ProductRecord]:
    return load_catalog_records(CATALOG_PATH)


@pytest.fixture(scope="module")
def matcher(catalog_records: list[ProductRecord]) -> ProductMatcher:
    return ProductMatcher(catalog_records)


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


def test_normalize_part_number_case_and_whitespace() -> None:
    assert normalize_part_number("1LAP-W") == "1LAP-W"
    assert normalize_part_number("1lap-w") == "1LAP-W"
    assert normalize_part_number(" 1LAP-W ") == "1LAP-W"
    assert normalize_part_number('"1LAP-W"') == "1LAP-W"
    assert normalize_part_number("NA1-1LAP-W") == "NA1-1LAP-W"
    assert normalize_part_number("1LAP-W\u00a0") == "1LAP-W"
    assert not part_numbers_equivalent("NA1-1LAP-W", "1LAP-W")


def test_exact_part_number_and_exact_description(matcher: ProductMatcher) -> None:
    result = matcher.match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="10/3 MCT",
            quantity=1,
            requested_part_number="2EB40-B-SC",
        )
    )
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2EB40-B-SC"
    assert result.part_number_match_score == 100
    assert result.description_match_score == 100
    assert result.overall_match_score == 100
    assert result.part_number_match is True
    assert "Exact Atkore part number match and compatible" in result.match_reasons[0]


def test_exact_part_number_compatible_abbreviation(matcher: ProductMatcher) -> None:
    result = matcher.match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="120V LTG WHIP",
            quantity=1,
            requested_part_number="1lc-w",
        )
    )
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "1LC-W"
    assert result.part_number_match is True


def test_exact_part_number_conflicting_description(matcher: ProductMatcher) -> None:
    result = matcher.match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="277V SWITCH MODULE",
            quantity=1,
            requested_part_number="1LAP-W",
        )
    )
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert result.part_number_match_score == 100
    assert result.part_number_match is True
    assert any("conflicts" in reason.lower() for reason in result.match_reasons)


def test_part_number_not_found_unique_description(matcher: ProductMatcher) -> None:
    result = matcher.match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="10/3 MCT",
            quantity=1,
            requested_part_number="ZZZ-NOT-IN-CATALOG",
        )
    )
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert result.part_number_match_score == 0
    assert result.part_number_match is False
    assert result.description_match_score == 100
    assert any("was not found" in reason for reason in result.match_reasons)
    assert any(item.official_part_number == "2EB40-B-SC" for item in result.candidates)


def test_no_part_number_unique_description(matcher: ProductMatcher) -> None:
    result = matcher.match_description("10/3 MCT")
    assert result.requested_part_number is None
    assert result.part_number_match_score is None
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2EB40-B-SC"
    assert result.description_match_score == 100
    assert result.overall_match_score == 100


def test_no_part_number_duplicate_description(matcher: ProductMatcher) -> None:
    result = matcher.match_description("120V LIGHTING WHIP W/PAULEX")
    assert result.requested_part_number is None
    assert result.part_number_match_score is None
    assert result.description_match_score == 100
    assert result.overall_match_score is not None
    assert result.overall_match_score <= 86
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert {item.official_part_number for item in result.candidates} >= {
        "1LAP-W",
        "1LBP-W",
        "1LCP-W",
    }


def test_part_hash_column_detected(tmp_path: Path) -> None:
    path = _write_xlsx(
        tmp_path / "part-hash.xlsx",
        ["Name", "Qty", "Part #"],
        [["10/3 MCT", 1, "2EB40-B-SC"]],
    )
    items = parse_quote_file(path)
    assert items[0].requested_part_number == "2EB40-B-SC"


def test_customer_part_number_column_detected(tmp_path: Path) -> None:
    path = _write_xlsx(
        tmp_path / "customer-pn.xlsx",
        ["Description", "Quantity", "Customer Part Number"],
        [["10/3 MCT", 2, "2eb40-b-sc"]],
    )
    items = parse_quote_file(path)
    assert items[0].requested_part_number == "2eb40-b-sc"


def test_part_number_column_absent_is_null(tmp_path: Path) -> None:
    path = _write_xlsx(
        tmp_path / "name-qty.xlsx",
        ["Name", "Qty"],
        [["10/3 MCT", 1]],
    )
    items = parse_quote_file(path)
    assert items[0].requested_part_number is None


def test_family_and_parent_ids_are_not_part_numbers(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    families = [item for item in catalog_records if item.record_type == "family"]
    assert families
    family = families[0]
    result = matcher.match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="10/3 MCT",
            quantity=1,
            requested_part_number=family.salsify_id,
        )
    )
    assert result.matched_part_number != family.salsify_id
    assert result.part_number_match is False
    product = next(item for item in catalog_records if item.official_part_number == "1LAP-W")
    parent_result = matcher.match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="120V LIGHTING WHIP W/PAULEX",
            quantity=1,
            requested_part_number=product.parent_id,
        )
    )
    assert parent_result.matched_part_number is None
    assert parent_result.part_number_match is False


def test_current_inputfile_still_review_required(matcher: ProductMatcher) -> None:
    items = parse_quote_file(QUOTE_PATH)
    assert all(item.requested_part_number is None for item in items)
    results = match_quote(
        [
            QuoteLine(
                source_file=item.source_file,
                source_sheet=item.source_sheet,
                source_row=item.source_row,
                requested_description=item.requested_description,
                quantity=item.quantity,
                requested_part_number=item.requested_part_number,
            )
            for item in items
        ],
        load_catalog_records(CATALOG_PATH),
    )
    assert [(r.match_status, r.matched_part_number, r.part_number_match_score) for r in results] == [
        (MatchStatus.REVIEW_REQUIRED, None, None),
        (MatchStatus.REVIEW_REQUIRED, None, None),
        (MatchStatus.REVIEW_REQUIRED, None, None),
    ]
    whip = next(item for item in results if "PAULEX" in item.requested_description)
    cable = next(item for item in results if "LIGHTING CABLE" in item.requested_description)
    switch = next(item for item in results if "SWITCH MODULE" in item.requested_description)
    assert {item.official_part_number for item in whip.candidates} >= {"1LAP-W", "1LBP-W", "1LCP-W"}
    assert {item.official_part_number for item in cable.candidates} >= {"2LA", "2LB", "2LC"}
    assert {item.official_part_number for item in switch.candidates} >= {"1SA", "1SC"}
    assert whip.description_match_score == 100
    assert whip.overall_match_score is not None
    assert whip.overall_match_score <= 86


def test_ai_cannot_invent_part_number(matcher: ProductMatcher, catalog_records: list[ProductRecord]) -> None:
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
        catalog_records,
        MockAIReasoningProvider(canned=canned),
        AIPolicyConfig(),
        InMemoryAuditStore(),
    )
    result = service.match_line(
        QuoteLine(
            source_file="inputfile.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="120V LIGHTING WHIP W/PAULEX",
            quantity=5,
            requested_part_number=None,
        ),
        use_ai=True,
    )
    assert result.matched_part_number is None
    assert result.match_status == "REVIEW_REQUIRED"
    assert result.matched_part_number != "FAKE-999"

