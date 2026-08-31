from __future__ import annotations

from sqlalchemy import create_engine, text

from catalog.postgres_loader import load_catalog_from_postgres, product_from_postgres_row
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.normalizer import part_number_lookup_keys


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


SAMPLE_PRODUCTS = [
    _pg_product(333427, "B1EB5-W", "B1EB5-W", "BRP 120V WHIP END EXT CBL", "BRP 120V WHIP END EXT CBL"),
    _pg_product(333489, "1MD12BZUZ115EB1", "1MD12BZUZ115EB1", "1MD12BZUZ115EB1", None),
    _pg_product(333525, "1MD06AZJZ040V1S", "1MD06AZJZ040V1S", "1MD06AZJZ040V1S", None),
    _pg_product(333567, "G1MD04MMDD05092", "G1MD04MMDD05092", "G1MD04MMDD05092", None),
    _pg_product(333954, "G1MD04MMDD14092", "G1MD04MMDD14092", "G1MD04MMDD14092", None),
    _pg_product(333958, "G1MD04MMDD17092", "G1MD04MMDD17092", "G1MD04MMDD17092", None),
    _pg_product(333569, "G1MD04MMDD07092", "G1MD04MMDD07092", "G1MD04MMDD07092", None),
    _pg_product(333955, "G1MD04MMDD15092", "G1MD04MMDD15092", "G1MD04MMDD15092", None),
    _pg_product(333956, "G1MD04MMDD160", "G1MD04MMDD160", "G1MD04MMDD16092", None),
    _pg_product(333562, "G1MD04MMDD02592", "G1MD04MMDD02592", "G1MD04MMDD02592", None),
    _pg_product(333563, "G1MD04MMDD03092", "G1MD04MMDD03092", "G1MD04MMDD03092", None),
    _pg_product(333572, "G1MD04MMDD08092", "G1MD04MMDD08092", "G1MD04MMDD08092", None),
    _pg_product(900001, "NA1-2DDDA10-HV", "NA1-2DDDA10-HV", "HIGH VOLTAGE", "HV CABLE"),
    _pg_product(900002, 900002, "HV-NAME-1", "ALTERNATE NAME DESC", "SPECIAL HV KIT"),
    _pg_product(900003, "WHIP-A", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
    _pg_product(900004, "WHIP-B", "WHIP FAMILY", "120V LIGHTING WHIP W/PAULEX", None),
]


def _line(text: str, part_number: str | None = None, quantity: int | float | None = 1) -> QuoteLine:
    return QuoteLine(
        source_file="quote.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description=text,
        quantity=quantity,
        requested_part_number=part_number,
    )


def _matcher() -> ProductMatcher:
    return ProductMatcher(SAMPLE_PRODUCTS)


def test_row_id_is_never_the_matched_part_number() -> None:
    result = _matcher().match_line(_line("B1EB5-W"))
    assert result.matched_part_number == "B1EB5-W"
    assert result.matched_part_number != "333427"
    assert "333427" not in {result.matched_part_number, result.matched_salsify_id}


def test_exact_productcode_b1eb5() -> None:
    result = _matcher().match_line(_line("B1EB5-W"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "B1EB5-W"
    assert result.match_breakdown is not None
    assert result.match_breakdown["productcode_score"] == 100


def test_productcode_without_na1_prefix() -> None:
    result = _matcher().match_line(_line("2DDDA10-HV"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "NA1-2DDDA10-HV"
    assert result.matched_part_number.startswith("NA1-")


def test_exact_productcode_with_na1() -> None:
    result = _matcher().match_line(_line("NA1-2DDDA10-HV"))
    assert result.matched_part_number == "NA1-2DDDA10-HV"
    assert result.match_status == MatchStatus.EXACT_MATCH


def test_description_high_voltage() -> None:
    result = _matcher().match_line(_line("HIGH VOLTAGE"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "NA1-2DDDA10-HV"


def test_name_match() -> None:
    result = _matcher().match_line(_line("SPECIAL HV KIT"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "HV-NAME-1"


def test_description2_match() -> None:
    result = _matcher().match_line(_line("HV CABLE"))
    assert result.matched_part_number == "NA1-2DDDA10-HV"


def test_free_text_part_and_description() -> None:
    result = _matcher().match_line(_line("5 pcs NA1-2DDDA10-HV HIGH VOLTAGE", quantity=None))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "NA1-2DDDA10-HV"
    assert result.quantity == 5
    assert result.part_number_match is True


def test_b1eb5_with_description() -> None:
    result = _matcher().match_line(_line("B1EB5-W BRP 120V WHIP END EXT CBL"))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == "B1EB5-W"
    assert result.part_number_match is True
    assert result.description_match is True


def test_description_only_b1eb5() -> None:
    result = _matcher().match_line(_line("BRP 120V WHIP END EXT CBL"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"


def test_part_number_conflicts_with_description() -> None:
    result = _matcher().match_line(_line("B1EB5-W HIGH VOLTAGE"))
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None
    assert result.part_number_match is True
    assert any("conflict" in reason.lower() for reason in result.match_reasons)


def test_unknown_part_number_no_match() -> None:
    result = _matcher().match_line(_line("ZZZ-NOT-A-PRODUCT"))
    assert result.match_status == MatchStatus.NO_MATCH
    assert result.matched_part_number is None


def test_ambiguous_same_description_review() -> None:
    result = _matcher().match_line(_line("120V LIGHTING WHIP W/PAULEX"))
    assert result.match_status == MatchStatus.REVIEW_REQUIRED
    assert result.matched_part_number is None


def test_whitespace_and_case_normalization() -> None:
    result = _matcher().match_line(_line("  b1eb5-w  "))
    assert result.matched_part_number == "B1EB5-W"


def test_productcode_not_assumed_equal_to_description() -> None:
    by_code = _matcher().match_line(_line("G1MD04MMDD160"))
    assert by_code.matched_part_number == "G1MD04MMDD160"
    by_desc = _matcher().match_line(_line("G1MD04MMDD16092"))
    assert by_desc.matched_part_number == "G1MD04MMDD160"
    assert by_desc.matched_part_number != "G1MD04MMDD16092"
    assert by_desc.matched_part_number != "333956"


def test_na1_keys_do_not_rewrite_stored_code() -> None:
    keys = part_number_lookup_keys("NA1-2DDDA10-HV")
    assert "NA1-2DDDA10-HV" in keys
    assert "2DDDA10-HV" in keys
    result = _matcher().match_line(_line("na1-2ddda10-hv"))
    assert result.matched_part_number == "NA1-2DDDA10-HV"


def test_no_fabricated_part_numbers() -> None:
    allowed = {item.product_code for item in SAMPLE_PRODUCTS}
    for query in ("B1EB5-W", "HIGH VOLTAGE", "G1MD04MMDD16092", "SPECIAL HV KIT"):
        result = _matcher().match_line(_line(query))
        if result.matched_part_number:
            assert result.matched_part_number in allowed


def test_sqlite_loader_maps_productcode_not_id() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE productmaster ('
                "id INTEGER, "
                '"Productcode" TEXT, '
                "name TEXT, "
                "description TEXT, "
                "description2 TEXT)"
            )
        )
        connection.execute(
            text(
                'INSERT INTO productmaster (id, "Productcode", name, description, description2) '
                "VALUES (333427, 'B1EB5-W', 'B1EB5-W', 'BRP 120V WHIP END EXT CBL', 'BRP 120V WHIP END EXT CBL')"
            )
        )
    records = load_catalog_from_postgres(engine)
    assert len(records) == 1
    assert records[0].product_code == "B1EB5-W"
    assert records[0].catalog_row_id == "333427"
    matcher = ProductMatcher(records)
    result = matcher.match_line(_line("B1EB5-W"))
    assert result.matched_part_number == "B1EB5-W"
    assert result.matched_part_number != records[0].catalog_row_id


def _numeric_code_catalog() -> list[ProductRecord]:
    # Productcode is internal-only now, so a bare numeric identifier has to
    # live in `name` (the real identity field) to exercise "exact numeric
    # identifier" matching; the old code-like text moves to description.
    return [
        _pg_product(1, 1, "333572", "G1MD04MMDD08092", None),
        _pg_product(2, 2, "333408", "RR 2B KR", None),
        _pg_product(3, 3, "333479", "RR 2BA KR", None),
        _pg_product(4, "B1EB5-W", "B1EB5-W", "BRP 120V WHIP END EXT CBL", "BRP 120V WHIP END EXT CBL"),
        _pg_product(5, "1MD12BZUZ115EB1", "1MD12BZUZ115EB1", "1MD12BZUZ115EB1", None),
        _pg_product(6, "NA1-2DDDA10-HV", "NA1-2DDDA10-HV", "HIGH VOLTAGE", "HV CABLE"),
    ]


def _assert_exact_productcode(query: object, expected: str) -> None:
    import json

    result = ProductMatcher(_numeric_code_catalog()).match_line(_line(str(query)))
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.matched_part_number == expected
    assert isinstance(result.matched_part_number, str)
    assert "," not in result.matched_part_number
    payload = result.to_api_dict()
    assert payload["matched_part_number"] == expected
    assert isinstance(payload["matched_part_number"], str)
    encoded = json.dumps(payload)
    assert json.dumps(expected) in encoded
    assert f"{expected[:3]},{expected[3:]}" not in encoded


def test_exact_numeric_productcode_333572() -> None:
    _assert_exact_productcode(333572, "333572")
    _assert_exact_productcode("333572", "333572")
    _assert_exact_productcode("333,572", "333572")


def test_exact_numeric_productcode_333408() -> None:
    _assert_exact_productcode(333408, "333408")


def test_exact_numeric_productcode_333479() -> None:
    _assert_exact_productcode(333479, "333479")


def test_exact_alphanumeric_productcodes_in_mixed_catalog() -> None:
    _assert_exact_productcode("B1EB5-W", "B1EB5-W")
    _assert_exact_productcode("1MD12BZUZ115EB1", "1MD12BZUZ115EB1")
    _assert_exact_productcode("NA1-2DDDA10-HV", "NA1-2DDDA10-HV")


def test_sqlite_integer_productcode_is_loaded_as_text() -> None:
    # `name` is the identity column now; verify a bare numeric value stored
    # in an INTEGER-typed name column still comes back as clean, unformatted
    # text (this used to be checked against an INTEGER Productcode column).
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE productmaster ("
                "id INTEGER, "
                '"Productcode" TEXT, '
                "name INTEGER, "
                "description TEXT, "
                "description2 TEXT)"
            )
        )
        connection.execute(
            text(
                'INSERT INTO productmaster (id, "Productcode", name, description, description2) '
                "VALUES (1, 'G1MD04MMDD08092', 333572, 'G1MD04MMDD08092', NULL), "
                "(2, 'RR 2B KR', 333408, 'RR 2B KR', NULL)"
            )
        )
    records = load_catalog_from_postgres(engine)
    codes = {item.product_code for item in records}
    assert codes == {"333572", "333408"}
    assert all(isinstance(item.product_code, str) for item in records)
    assert all("," not in item.product_code for item in records)
    matcher = ProductMatcher(records)
    found_572 = matcher.match_line(_line("333572"))
    found_408 = matcher.match_line(_line("333408"))
    assert found_572.match_status == MatchStatus.EXACT_MATCH
    assert found_572.matched_part_number == "333572"
    assert found_408.match_status == MatchStatus.EXACT_MATCH
    assert found_408.matched_part_number == "333408"
