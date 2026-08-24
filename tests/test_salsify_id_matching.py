from __future__ import annotations

from pathlib import Path

import pytest

from openpyxl import Workbook

from catalog.excel_loader import load_catalog_records
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.normalizer import normalize_part_number
from quotes.parser import parse_quote_file

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "Atkorepartsfile.xlsx"


@pytest.fixture(scope="module")
def catalog_records() -> list[ProductRecord]:
    return load_catalog_records(CATALOG_PATH)


@pytest.fixture(scope="module")
def matcher(catalog_records: list[ProductRecord]) -> ProductMatcher:
    return ProductMatcher(catalog_records)


def _line(part: str, description: str = "", quantity: int = 5) -> QuoteLine:
    return QuoteLine(
        source_file="q.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description=description,
        quantity=quantity,
        requested_part_number=part,
    )


def test_salsify_id_blank_description_matches_official_part(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("NA1-2DDDA10-HV", ""))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.matched_part_number != "NA1-2DDDA10-HV"
    assert result.matching_percentage == 100
    assert result.overall_match_score == 100
    assert result.match_reasons[0] == "Exact Salsify ID match"
    assert result.matched_salsify_id == "NA1-2DDDA10-HV"
    assert result.detected_salsify_id == "NA1-2DDDA10-HV"
    assert result.detected_part_number is None
    assert result.customer_raw_text == ""


def test_normalizer_never_strips_na1_prefix() -> None:
    assert normalize_part_number("NA1-2DDDA10-HV") == "NA1-2DDDA10-HV"
    assert normalize_part_number("NA1-2DDDA10-HV") != "2DDDA10-HV"
    assert normalize_part_number("  na1-2ddda10-hv ") == "NA1-2DDDA10-HV"


def test_salsify_and_official_resolve_to_same_product(matcher: ProductMatcher) -> None:
    by_salsify = matcher.match_line(_line("NA1-2DDDA10-HV", ""))
    by_official = matcher.match_line(_line("2DDDA10-HV", ""))
    assert by_salsify.matched_part_number == by_official.matched_part_number == "2DDDA10-HV"
    assert by_salsify.matched_salsify_id == by_official.matched_salsify_id == "NA1-2DDDA10-HV"
    assert by_salsify.match_status == MatchStatus.EXACT_MATCH
    assert by_official.match_status == MatchStatus.EXACT_MATCH
    assert by_salsify.detected_salsify_id == "NA1-2DDDA10-HV"
    assert by_official.detected_part_number == "2DDDA10-HV"
    assert by_official.detected_salsify_id is None
    result = matcher.match_line(_line("NA1-2DDDA10-HV", "HIGH VOLTAGE"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert "Exact Salsify ID match" in result.match_reasons


def test_catalog_loader_preserves_salsify_and_parses_official(
    catalog_records: list[ProductRecord],
) -> None:
    product = next(item for item in catalog_records if item.salsify_id == "NA1-2DDDA10-HV")
    assert product.salsify_id == "NA1-2DDDA10-HV"
    assert product.official_part_number == "2DDDA10-HV"
    assert product.record_type == "product"
    assert not product.salsify_id.startswith("2DDDA10")


def test_official_catalog_number_blank_description(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("2DDDA10-HV", ""))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.matching_percentage == 100
    assert result.match_reasons[0] == "Exact Atkore part number match"


def test_salsify_id_whitespace_and_case(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line(" na1-2ddda10-hv ", ""))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "2DDDA10-HV"


def test_unknown_salsify_id_is_no_match(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("NA1-DOES-NOT-EXIST", ""))
    assert result.match_status == MatchStatus.NO_MATCH
    assert result.matched_part_number is None


def test_family_id_is_not_an_atkore_part(matcher: ProductMatcher) -> None:
    result = matcher.match_line(_line("F3+_DBL_DIST_CBL", ""))
    assert result.matched_part_number is None
    assert result.matched_part_number != "F3+_DBL_DIST_CBL"
    assert result.match_status in {MatchStatus.NO_MATCH, MatchStatus.REVIEW_REQUIRED}


def test_quote_parser_keeps_part_number_when_description_blank(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Qty", "Part Number"])
    sheet.append(["", 5, "NA1-2DDDA10-HV"])
    path = tmp_path / "salsify-only.xlsx"
    workbook.save(path)
    workbook.close()
    items = parse_quote_file(path)
    assert len(items) == 1
    assert items[0].requested_part_number == "NA1-2DDDA10-HV"
    assert items[0].requested_description == ""
    assert items[0].quantity == 5


def test_normalize_keeps_salsify_prefix() -> None:
    assert normalize_part_number("NA1-2DDDA10-HV") == "NA1-2DDDA10-HV"
    assert normalize_part_number("2DDDA10-HV") == "2DDDA10-HV"
    assert normalize_part_number("NA1-2DDDA10-HV") != normalize_part_number("2DDDA10-HV")


def test_name_column_salsify_id_matches(matcher: ProductMatcher) -> None:
    result = matcher.match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="NA1-1EEC",
            quantity=5,
            requested_part_number=None,
        )
    )
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "1EEC"
    assert result.requested_description == "NA1-1EEC"
    assert "Exact Salsify ID match" in result.match_reasons


def test_name_column_official_catalog_number_matches(matcher: ProductMatcher) -> None:
    result = matcher.match_description("1EEC")
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "1EEC"


def test_name_column_description_still_used_when_not_an_identifier(matcher: ProductMatcher) -> None:
    result = matcher.match_description("120V LIGHTING WHIP W/PAULEX")
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None


def test_name_column_salsify_quote_file(tmp_path: Path, matcher: ProductMatcher) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Qty"])
    sheet.append(["NA1-1EEC", 5])
    sheet.append(["120V LIGHTING WHIP W/PAULEX", 5])
    path = tmp_path / "name-mixed.xlsx"
    workbook.save(path)
    workbook.close()
    items = parse_quote_file(path)
    results = matcher.match_quote(items)
    assert results[0].match_status == MatchStatus.EXACT_MATCH
    assert results[0].matched_part_number == "1EEC"
    assert results[1].match_status == MatchStatus.REVIEW_REQUIRED
    assert results[1].matched_part_number is None

