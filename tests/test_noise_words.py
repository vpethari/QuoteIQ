from __future__ import annotations

from catalog.postgres_repository import product_from_postgres_row
from matching.description_normalize import tokenize_description
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.noise import (
    NOISE_WORDS,
    PROTECTED_PRODUCT_TERMS,
    extract_quantity_from_text,
    prepare_product_search_text,
    strip_quantity_and_noise,
)
from output.match_evidence import build_match_evidence


def _pg_product(
    row_id: int,
    productcode: object,
    name: str | None,
    description: str | None,
    description2: str | None = None,
) -> ProductRecord:
    record = product_from_postgres_row(
        productcode=productcode,
        name=name,
        description=description,
        description2=description2,
        row_id=row_id,
    )
    assert record is not None
    return record


def _catalog() -> list[ProductRecord]:
    return [
        _pg_product(
            333427,
            "B1EB5-W",
            "BRP 120V WHIP END EXT CBL",
            "BRP 120V WHIP END EXT CBL",
            "BRP 120V WHIP END EXT CBL",
        ),
        _pg_product(333500, "B277-LC", "BRP 277V LIGHTING CBL", "BRP 277V LIGHTING CBL", None),
        _pg_product(900003, "WHIP-A", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
        _pg_product(900004, "WHIP-B", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
    ]


def _line(text: str, quantity: int | float | None = 1) -> QuoteLine:
    return QuoteLine(
        source_file="quote.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description=text,
        quantity=quantity,
    )


RFQ_CASES = (
    "Please quote 10 pieces of BRP 120 volts whip end extension cable",
    "Qty 10 BRP 120V WHIP END EXT CBL",
    "Please provide pricing for BRP 120V WHIP END EXT CBL",
    "10 pcs BRP 120 volt whip end extension cable",
    "BRP 120V WHIP END EXT CBL",
)

EXPECTED_TOKENS = ["BRP", "120", "V", "WHIP", "END", "EXT", "CBL"]


def test_noise_list_does_not_include_product_terms() -> None:
    assert NOISE_WORDS.isdisjoint(PROTECTED_PRODUCT_TERMS)
    for term in (
        "high",
        "voltage",
        "low",
        "end",
        "whip",
        "lighting",
        "switch",
        "module",
        "black",
        "white",
        "red",
        "left",
        "right",
        "male",
        "female",
    ):
        assert term.upper() not in NOISE_WORDS
        kept = strip_quantity_and_noise(term)
        assert kept.upper() == term.upper()


def test_noise_removal_is_token_based() -> None:
    assert "quoted" not in NOISE_WORDS
    assert strip_quantity_and_noise("quoted BRP cable") == "quoted BRP cable"


def test_terminology_piece_mapping_unchanged() -> None:
    assert tokenize_description("piece") == ["EA"]
    assert tokenize_description("pcs") == ["EA"]


def test_quantity_not_confused_with_voltage() -> None:
    assert extract_quantity_from_text("BRP 120 volts whip end extension cable") is None
    assert extract_quantity_from_text("BRP 120V WHIP END EXT CBL") is None
    assert extract_quantity_from_text("Need 20 - 277V LIGHTING CABLE") == 20
    assert extract_quantity_from_text("Please quote 10 pieces of BRP 120 volts whip end extension cable") == 10


def test_rfq_phrases_share_normalized_search_text() -> None:
    preps = [prepare_product_search_text(text) for text in RFQ_CASES]
    token_sets = [list(item.tokens) for item in preps]
    for tokens in token_sets:
        assert tokens == EXPECTED_TOKENS
    assert {item.after_terminology for item in preps} == {"brp 120 v whip end ext cbl"}
    example = preps[0]
    assert example.original == RFQ_CASES[0]
    assert example.extracted_quantity == 10
    assert example.after_noise_removal == "BRP 120 volts whip end extension cable"
    assert example.after_terminology == "brp 120 v whip end ext cbl"
    assert [token.lower() for token in example.tokens] == [
        "brp",
        "120",
        "v",
        "whip",
        "end",
        "ext",
        "cbl",
    ]


def test_rfq_phrases_match_b1eb5w_and_keep_original_text() -> None:
    matcher = ProductMatcher(_catalog())
    for text in RFQ_CASES:
        result = matcher.match_line(_line(text, quantity=1))
        assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
        assert result.matched_part_number == "B1EB5-W"
        assert result.requested_description == text
        assert result.customer_raw_text == text
        assert result.quantity == 1
        evidence = build_match_evidence(result)
        assert evidence["matched_part_number"] == "B1EB5-W"
        assert "search_normalization" not in evidence
        debug = (result.match_breakdown or {}).get("search_normalization") or {}
        assert debug.get("original_input") == text
        assert debug.get("tokens") == ["brp", "120", "v", "whip", "end", "ext", "cbl"]


def test_extracted_quantity_used_when_quote_qty_missing() -> None:
    result = ProductMatcher(_catalog()).match_line(
        _line("Please quote 10 pieces of BRP 120 volts whip end extension cable", quantity=None)
    )
    assert result.quantity == 10
    assert result.matched_part_number == "B1EB5-W"
    assert result.requested_description.startswith("Please quote")
