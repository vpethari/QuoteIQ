from __future__ import annotations

from pathlib import Path

import pytest

from catalog.excel_loader import load_catalog_records
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.normalizer import (
    canonical_text,
    fold_whitespace,
    normalize_part_number,
    normalize_text,
    part_numbers_equivalent,
)
from matching.tokenizer import tokenize_description

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "Atkorepartsfile.xlsx"


@pytest.fixture(scope="module")
def catalog_records() -> list[ProductRecord]:
    return load_catalog_records(CATALOG_PATH)


@pytest.fixture(scope="module")
def matcher(catalog_records: list[ProductRecord]) -> ProductMatcher:
    return ProductMatcher(catalog_records)


def test_part_number_trim_and_case() -> None:
    assert normalize_part_number(" 1LAP-W ") == "1LAP-W"
    assert normalize_part_number("1lap-w") == "1LAP-W"
    assert part_numbers_equivalent(" 1LAP-W ", "1LAP-W")
    assert part_numbers_equivalent("1lap-w", "1LAP-W")


def test_part_number_nbsp() -> None:
    assert normalize_part_number("1LAP-W\u00a0") == "1LAP-W"
    assert part_numbers_equivalent("1LAP-W\u00a0", "1LAP-W")


def test_salsify_id_is_not_collapsed_to_catalog_number_in_normalizer() -> None:
    assert normalize_part_number("NA1-1LAP-W") == "NA1-1LAP-W"
    assert normalize_part_number("1LAP-W") == "1LAP-W"
    assert not part_numbers_equivalent("NA1-1LAP-W", "1LAP-W")


def test_slash_part_number_preserved_and_distinct() -> None:
    assert normalize_part_number("1EAG/A") == "1EAG/A"
    assert normalize_part_number("1EAG / A") == "1EAG/A"
    assert normalize_part_number("1EAG/A") != normalize_part_number("1EAG-A")
    assert normalize_part_number("1EAG/A") != normalize_part_number("1EAGA")


def test_hyphenated_part_number_preserved() -> None:
    assert normalize_part_number("2EB40-B-SC") == "2EB40-B-SC"
    assert "-" in normalize_part_number("2EB40-B-SC")
    assert part_numbers_equivalent(" 2EB40-B-SC ", "2EB40-B-SC")


def test_description_extra_whitespace_and_nbsp() -> None:
    assert fold_whitespace("  120V   LIGHTING   WHIP  ") == "120V LIGHTING WHIP"
    assert normalize_text("  120V   LIGHTING   WHIP  ") == "120V LIGHTING WHIP"
    assert normalize_text("120V\u00a0LIGHTING WHIP") == "120V LIGHTING WHIP"
    assert canonical_text("  10/3   MCT  ") == canonical_text("10/3 MCT")


def test_slash_spacing_in_descriptions() -> None:
    assert canonical_text("120V LIGHTING WHIP W / PAULEX") == canonical_text(
        "120V LIGHTING WHIP W/PAULEX"
    )


def test_ltg_lighting_synonym_still_works() -> None:
    assert tokenize_description("120V LTG WHIP") == tokenize_description("120V LIGHTING WHIP")
    assert canonical_text("120V LTG WHIP") == canonical_text("120V LIGHTING WHIP")
    assert "LIGHTING" in tokenize_description("120V LTG WHIP W/PAULEX")


def test_exact_part_number_beats_description_ambiguity(matcher: ProductMatcher) -> None:
    ambiguous = "120V LIGHTING WHIP W/PAULEX"
    without_pn = matcher.match_description(ambiguous)
    assert without_pn.match_status == MatchStatus.REVIEW_REQUIRED
    assert without_pn.matched_part_number is None

    with_pn = matcher.match_line(
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description=ambiguous,
            quantity=5,
            requested_part_number="NA1-1LAP-W",
        )
    )
    assert with_pn.match_status == MatchStatus.EXACT_MATCH
    assert with_pn.matched_part_number == "1LAP-W"
    assert with_pn.part_number_match is True


def test_conflicting_part_number_and_description_requires_review(matcher: ProductMatcher) -> None:
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
    assert result.part_number_match is True
    assert any("conflict" in reason.lower() for reason in result.match_reasons)


def test_family_rows_never_matched(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    families = [item for item in catalog_records if item.record_type == "family"]
    assert families
    for family in families:
        by_pn = matcher.match_line(
            QuoteLine(
                source_file="q.xlsx",
                source_sheet="Sheet1",
                source_row=2,
                requested_description="10/3 MCT",
                quantity=1,
                requested_part_number=family.salsify_id,
            )
        )
        assert by_pn.matched_part_number != family.salsify_id
        assert by_pn.matched_salsify_id != family.salsify_id
        by_desc = matcher.match_description(family.salsify_id)
        assert by_desc.matched_part_number != family.salsify_id
        for candidate in by_desc.candidates:
            assert candidate.salsify_id != family.salsify_id
            assert candidate.official_part_number != family.salsify_id
