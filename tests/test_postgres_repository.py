from __future__ import annotations

from unittest.mock import MagicMock

from catalog.postgres_repository import PostgresCatalogRepository, product_from_postgres_row
from matching.matcher import ProductMatcher
from matching.models import QuoteLine


def _line(text: str) -> QuoteLine:
    return QuoteLine(
        source_file="quote.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description=text,
        quantity=1,
    )


def test_product_from_row_uses_productcode_not_id() -> None:
    record = product_from_postgres_row(
        productcode="B1EB5-W",
        name="B1EB5-W",
        description="BRP 120V WHIP END EXT CBL",
        description2="BRP 120V WHIP END EXT CBL",
        row_id=333427,
    )
    assert record is not None
    assert record.official_part_number == "B1EB5-W"
    assert record.product_code == "B1EB5-W"
    assert record.catalog_row_id == "333427"
    assert record.official_part_number != "333427"


def test_numeric_productcode_is_kept_as_unformatted_string() -> None:
    record = product_from_postgres_row(
        productcode=333427,
        name="B1EB5-W",
        description="BRP 120V WHIP END EXT CBL",
        description2="BRP 120V WHIP END EXT CBL",
        row_id=1,
    )
    assert record is not None
    assert record.official_part_number == "333427"
    assert record.product_code == "333427"
    assert isinstance(record.product_code, str)
    assert "," not in record.product_code
    assert record.official_part_number != "B1EB5-W"


def test_productcode_from_thousands_formatted_text() -> None:
    from matching.productcode import productcode_as_text

    assert productcode_as_text(333479) == "333479"
    assert productcode_as_text("333,479") == "333479"
    assert productcode_as_text(333479.0) == "333479"
    assert productcode_as_text("B1EB5-W") == "B1EB5-W"
    assert productcode_as_text("NA1-2DDDA10-HV") == "NA1-2DDDA10-HV"
    assert productcode_as_text("0333479") == "0333479"


def test_product_from_row_keeps_na1_prefix() -> None:
    record = product_from_postgres_row(productcode="NA1-2DDDA10-HV", description="HIGH VOLTAGE")
    assert record is not None
    assert record.official_part_number == "NA1-2DDDA10-HV"


def test_family_and_blank_rows_are_excluded() -> None:
    assert product_from_postgres_row(productcode="PP_FAMILY", record_type="family") is None
    assert product_from_postgres_row(productcode="-") is None
    assert product_from_postgres_row(productcode="  ") is None
    assert product_from_postgres_row(productcode=None) is None


def test_repository_load_products_uses_mocked_rows() -> None:
    repository = PostgresCatalogRepository(MagicMock())
    repository._fetch_rows = lambda: [  # type: ignore[method-assign]
        {
            "productcode": "B1EB5-W",
            "name": "B1EB5-W",
            "description": "BRP 120V WHIP END EXT CBL",
            "description2": "BRP 120V WHIP END EXT CBL",
            "row_id": 333427,
            "record_type": "product",
        },
        {
            "productcode": "PP_DBL_EXT_CBL",
            "name": None,
            "description": None,
            "description2": None,
            "row_id": 1,
            "record_type": "family",
        },
    ]
    products = repository.load_products()
    assert len(products) == 1
    assert products[0].product_code == "B1EB5-W"
    assert products[0].catalog_row_id == "333427"

    matcher = ProductMatcher(products)
    result = matcher.match_line(_line("B1EB5-W"))
    assert result.matched_part_number == "B1EB5-W"
    assert result.matched_part_number != "333427"


def test_repository_default_table_is_productmaster() -> None:
    assert PostgresCatalogRepository(MagicMock()).table == "productmaster"


def test_check_connection_mocked_success() -> None:
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value = None
    assert PostgresCatalogRepository(engine).check_connection() is True


def test_check_connection_mocked_failure() -> None:
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("connection refused")
    assert PostgresCatalogRepository(engine).check_connection() is False
