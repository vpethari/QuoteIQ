from __future__ import annotations

from sqlalchemy import create_engine, text

from catalog.postgres_repository import PostgresCatalogRepository
from matching.matcher import ProductMatcher
from matching.models import QuoteLine

# Settings.catalog_table: productmaster
ACTUAL_TABLE_NAME = "productmaster"


def test_select_limit_5_reaches_existing_matcher() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE TABLE {ACTUAL_TABLE_NAME} ("
                "id INTEGER, "
                '"Productcode" TEXT, '
                "name TEXT, "
                "description TEXT, "
                "description2 TEXT, "
                "record_type TEXT, "
                "orderablepartnumber TEXT)"
            )
        )
        connection.execute(
            text(
                f"INSERT INTO {ACTUAL_TABLE_NAME} "
                '(id, "Productcode", name, description, description2, record_type, orderablepartnumber) VALUES '
                "(333427, 'B1EB5-W', 'B1EB5-W', 'BRP 120V WHIP END EXT CBL', "
                "'BRP 120V WHIP END EXT CBL', 'product', 'ORD-B1EB5-W'), "
                "(1, 'PP_DBL_EXT_CBL', '-', NULL, NULL, 'family', NULL), "
                "(900001, 'NA1-2DDDA10-HV', 'NA1-2DDDA10-HV', 'HIGH VOLTAGE', 'HV CABLE', 'product', NULL)"
            )
        )

    repository = PostgresCatalogRepository(engine, table=ACTUAL_TABLE_NAME)
    sample = repository.fetch_sample_rows(limit=5)
    assert len(sample) == 3
    assert all(set(row) == {"productcode", "name", "description", "description2"} for row in sample)
    assert {row["productcode"] for row in sample} == {
        "B1EB5-W",
        "PP_DBL_EXT_CBL",
        "NA1-2DDDA10-HV",
    }

    loaded = repository.load_products()
    assert {item.product_code for item in loaded} == {"B1EB5-W", "NA1-2DDDA10-HV"}
    assert all(item.product_code != "333427" for item in loaded)
    assert all(item.official_part_number != item.catalog_row_id for item in loaded)
    assert all(item.product_code.startswith("NA1-") or item.product_code == "B1EB5-W" for item in loaded)
    by_code = {item.product_code: item for item in loaded}
    assert by_code["B1EB5-W"].orderable_part_number == "ORD-B1EB5-W"
    assert by_code["NA1-2DDDA10-HV"].orderable_part_number is None

    matcher = ProductMatcher(loaded)
    result = matcher.match_line(
        QuoteLine(
            source_file="quote.xlsx",
            source_sheet="Sheet1",
            source_row=2,
            requested_description="B1EB5-W",
            quantity=1,
        )
    )
    assert result.matched_part_number == "B1EB5-W"
    na1 = matcher.match_line(
        QuoteLine(
            source_file="quote.xlsx",
            source_sheet="Sheet1",
            source_row=3,
            requested_description="NA1-2DDDA10-HV",
            quantity=1,
        )
    )
    assert na1.matched_part_number == "NA1-2DDDA10-HV"


def test_fetch_identifier_candidates_uses_substring_tokens() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE TABLE {ACTUAL_TABLE_NAME} ("
                "id INTEGER, "
                '"Productcode" TEXT, '
                "name TEXT, "
                "description TEXT, "
                "description2 TEXT, "
                "orderablepartnumber TEXT)"
            )
        )
        connection.execute(
            text(
                f"INSERT INTO {ACTUAL_TABLE_NAME} "
                '(id, "Productcode", name, description, description2, orderablepartnumber) VALUES '
                "(1, 'RR 2BA KR', 'RR 2BA KR', 'RR 2BA KR', NULL, NULL), "
                "(2, 'RR 2B KR', 'RR 2B KR', 'RR 2B KR', NULL, NULL), "
                "(3, 'B1EB5-W', 'B1EB5-W', 'BRP 120V WHIP END EXT CBL', NULL, NULL)"
            )
        )
    repository = PostgresCatalogRepository(engine, table=ACTUAL_TABLE_NAME)
    hits = repository.fetch_identifier_candidates("RR 2B BA")
    assert "RR 2BA KR" in {item.product_code for item in hits}
    assert "B1EB5-W" not in {item.product_code for item in hits}
    assert repository.fetch_identifier_candidates("RR") == []
