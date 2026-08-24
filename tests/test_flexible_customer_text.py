from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from catalog.excel_loader import load_catalog_records
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.request_text import extract_quantity_from_text, interpret_customer_text
from quotes.parser import parse_quote_file

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "Atkorepartsfile.xlsx"


@pytest.fixture(scope="module")
def catalog_records() -> list[ProductRecord]:
    return load_catalog_records(CATALOG_PATH)


@pytest.fixture(scope="module")
def matcher(catalog_records: list[ProductRecord]) -> ProductMatcher:
    return ProductMatcher(catalog_records)


def _line(text: str, quantity: int | float | None = 5, part: str | None = None) -> QuoteLine:
    return QuoteLine(
        source_file="q.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description=text,
        quantity=quantity,
        requested_part_number=part,
    )


def test_extract_examples(matcher: ProductMatcher) -> None:
    interpreted = interpret_customer_text(
        "Need 5 of NA1-2DDDA10-HV HIGH VOLTAGE",
        salsify_keys=tuple(matcher._by_salsify),
        official_keys=tuple(matcher._by_official),
    )
    assert "NA1-2DDDA10-HV" in interpreted.extracted_salsify_ids or interpreted.lookup_identifiers[0].upper() == "NA1-2DDDA10-HV"
    assert interpreted.description_text == "HIGH VOLTAGE"
    assert interpreted.quantity_from_text == 5
    assert "2DDDA10-HV" not in interpreted.lookup_identifiers
    assert all(item.upper().startswith("NA1-") for item in interpreted.extracted_salsify_ids)
    assert extract_quantity_from_text("Need 20 - 277V LIGHTING CABLE") == 20


def test_salsify_id_only(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("NA1-2DDDA10-HV"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.matched_part_number != "NA1-2DDDA10-HV"
    assert result.part_number_match_score == 100
    assert result.description_match_score is None
    assert result.overall_match_score == 100


def test_official_part_number_only(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("2DDDA10-HV"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.part_number_match_score == 100
    assert result.description_match_score is None
    assert result.overall_match_score == 100


def test_description_only(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("HIGH VOLTAGE"))
    assert result.part_number_match_score is None
    assert result.description_match_score is not None
    assert result.overall_match_score == result.description_match_score
    assert result.matched_part_number != "NA1-2DDDA10-HV"


def test_salsify_id_plus_description(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("NA1-2DDDA10-HV HIGH VOLTAGE"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.part_number_match_score == 100
    assert result.description_match_score == 100
    assert result.overall_match_score == 100


def test_official_pn_plus_description(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("2DDDA10-HV HIGH VOLTAGE"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.part_number_match_score == 100
    assert result.description_match_score == 100
    assert result.overall_match_score == 100


def test_free_text_containing_salsify_id(matcher: ProductMatcher) -> None:
    result = matcher.match_description("Need 5 of NA1-2DDDA10-HV HIGH VOLTAGE")
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.matched_salsify_id == "NA1-2DDDA10-HV"
    assert result.detected_salsify_id == "NA1-2DDDA10-HV"
    assert result.customer_raw_text == "Need 5 of NA1-2DDDA10-HV HIGH VOLTAGE"
    assert result.part_number_match_score == 100
    assert result.description_match_score == 100
    assert result.quantity == 5


def test_free_text_containing_official_pn(matcher: ProductMatcher) -> None:
    result = matcher.match_description("Please provide 5 of 2DDDA10-HV, high voltage")
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.part_number_match_score == 100
    assert result.description_match_score == 100
    assert result.quantity == 5


def test_free_text_pn_and_description(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("2DDDA10-HV HIGH VOLTAGE"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"


def test_free_text_quantity_pn_description_does_not_overwrite_qty(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("Need 5 of NA1-2DDDA10-HV HIGH VOLTAGE", quantity=9))
    assert result.quantity == 9
    assert result.matched_part_number == "2DDDA10-HV"


def test_description_duplicate_candidates(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("120V LIGHTING WHIP W/PAULEX"))
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert result.part_number_match_score is None
    assert result.description_match_score == 100
    assert {item.official_part_number for item in result.candidates} >= {"1LAP-W", "1LBP-W", "1LCP-W"}


def test_completely_unknown_free_text(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("zzzxq unique gibberish widget 99999"))
    assert result.match_status == MatchStatus.NO_MATCH
    assert result.matched_part_number is None
    assert result.overall_match_score == 0
    assert result.part_number_match_score is None


def test_missing_identifier_description_only_scores(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("10/3 MCT"))
    assert result.part_number_match_score is None
    assert result.description_match_score == 100
    assert result.overall_match_score == 100
    assert result.matched_part_number == "2EB40-B-SC"


def test_missing_description_identifier_only_scores(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("NA1-2DDDA10-HV"))
    assert result.description_match_score is None
    assert result.part_number_match_score == 100
    assert result.overall_match_score == 100
    assert result.description_match_score != 0


def test_exact_salsify_returns_official_catalog_number(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("NA1-2DDDA10-HV"))
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.matched_salsify_id == "NA1-2DDDA10-HV"


def test_family_rows_never_become_candidates(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    families = [item for item in catalog_records if item.record_type == "family"]
    assert families
    family = families[0]
    result = matcher.match_line(_line(family.salsify_id))
    assert result.matched_part_number != family.salsify_id
    assert all(item.official_part_number != family.salsify_id for item in result.candidates)
    assert all(item.salsify_id != family.salsify_id for item in result.candidates)


def test_na_scores_are_not_treated_as_zero(matcher: ProductMatcher) -> None:
    identifier_only = matcher.match_line(_line("2DDDA10-HV"))
    description_only = matcher.match_line(_line("10/3 MCT"))
    assert identifier_only.description_match_score is None
    assert identifier_only.overall_match_score == 100
    assert description_only.part_number_match_score is None
    assert description_only.overall_match_score == 100


def test_parser_name_only_and_qty_from_text(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name"])
    sheet.append(["Need 20 - 277V LIGHTING CABLE"])
    path = tmp_path / "name-only.xlsx"
    workbook.save(path)
    workbook.close()
    items = parse_quote_file(path)
    assert items[0].requested_description == "Need 20 - 277V LIGHTING CABLE"
    assert items[0].quantity == 20
    assert items[0].requested_part_number is None
