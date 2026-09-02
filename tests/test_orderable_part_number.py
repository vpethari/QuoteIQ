from __future__ import annotations

from catalog.postgres_repository import product_from_postgres_row
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.selection import apply_user_selection_payload
from output.api_results import serialize_process_result


def _pg_product(
    row_id: int,
    name: str,
    description: str | None,
    description2: str | None = None,
    orderablepartnumber: object = None,
) -> ProductRecord:
    record = product_from_postgres_row(
        productcode=row_id,
        name=name,
        description=description,
        description2=description2,
        row_id=row_id,
        orderablepartnumber=orderablepartnumber,
    )
    assert record is not None
    return record


def _line(text: str) -> QuoteLine:
    return QuoteLine("quote.xlsx", "Sheet1", 2, text, 1)


def test_product_from_postgres_row_sets_orderable_part_number() -> None:
    record = product_from_postgres_row(
        productcode=1057068,
        name="8104",
        description="PVC SCH40 1 x 10 UL BE 4010010",
        orderablepartnumber="8104-ORD",
    )
    assert record is not None
    assert record.orderable_part_number == "8104-ORD"


def test_matched_orderable_part_number_flows_through_automatic_match() -> None:
    catalog = [
        _pg_product(1, "B1EB5-W", "BRP 120V WHIP END EXT CBL", orderablepartnumber="ORD-B1EB5-W"),
    ]
    result = ProductMatcher(catalog).match_line(_line("B1EB5-W BRP 120V WHIP END EXT CBL"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"
    assert result.matched_orderable_part_number == "ORD-B1EB5-W"

    payload = serialize_process_result(result)
    assert payload["matched_orderable_part_number"] == "ORD-B1EB5-W"


def test_orderable_part_number_absent_when_no_winner() -> None:
    catalog = [
        _pg_product(1, "WHIP-A", "WHIP FAMILY", orderablepartnumber="ORD-A"),
        _pg_product(2, "WHIP-B", "WHIP FAMILY", orderablepartnumber="ORD-B"),
    ]
    result = ProductMatcher(catalog).match_line(_line("WHIP FAMILY"))
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert result.matched_orderable_part_number is None
    codes = {item.official_part_number: item.orderable_part_number for item in result.candidates}
    assert codes.get("WHIP-A") == "ORD-A"
    assert codes.get("WHIP-B") == "ORD-B"


def test_manual_selection_carries_orderable_part_number() -> None:
    catalog = [
        _pg_product(1, "WHIP-A", "WHIP FAMILY", orderablepartnumber="ORD-A"),
        _pg_product(2, "WHIP-B", "WHIP FAMILY", orderablepartnumber="ORD-B"),
    ]
    result = ProductMatcher(catalog).match_line(_line("WHIP FAMILY"))
    payload = serialize_process_result(result)
    assert payload["match_status"] == "REVIEW_REQUIRED"

    updated = apply_user_selection_payload(payload, "WHIP-B")
    assert updated["matched_part_number"] == "WHIP-B"
    assert updated["matched_orderable_part_number"] == "ORD-B"
