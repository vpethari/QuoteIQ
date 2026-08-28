from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import create_engine, text

from catalog.postgres_repository import PostgresCatalogRepository, product_from_postgres_row
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, QuoteLine


def _line(text_value: str) -> QuoteLine:
    return QuoteLine("quote.xlsx", "Sheet1", 2, text_value, 1)


def _sqlite_catalog() -> PostgresCatalogRepository:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE productmaster ('
                "id INTEGER, "
                '"Productcode" TEXT, '
                "name TEXT, "
                "description TEXT, "
                "description2 TEXT, "
                "search_text TEXT)"
            )
        )
        rows = [
            (333427, "B1EB5-W", "B1EB5-W", "BRP 120V WHIP END EXT CBL", "BRP 120V WHIP END EXT CBL"),
            (333478, "333478", "RR 2BA KL", "RR 2BA KL", None),
            (333479, "333479", "RR 2BA KR", "RR 2BA KR", None),
            (1, "NOISE", "UNRELATED", "PURPLE BANANA ENCLOSURE", None),
        ]
        for row in rows:
            search_text = " ".join(str(part).lower() for part in row[1:] if part)
            connection.execute(
                text(
                    'INSERT INTO productmaster '
                    '(id, "Productcode", name, description, description2, search_text) '
                    "VALUES (:id, :code, :name, :description, :description2, :search_text)"
                ),
                {
                    "id": row[0],
                    "code": row[1],
                    "name": row[2],
                    "description": row[3],
                    "description2": row[4],
                    "search_text": search_text,
                },
            )
    return PostgresCatalogRepository(engine, retrieval_limit=100)


def test_search_text_candidates_are_limited_and_relevant() -> None:
    repository = _sqlite_catalog()
    hits = repository.search_text_candidates("BRP 120 volts whip end extension cable", limit=100)
    codes = {item.product_code for item in hits}
    assert "B1EB5-W" in codes
    assert "NOISE" not in codes
    assert len(hits) <= 100


def test_search_text_sql_targets_search_text_column() -> None:
    repository = _sqlite_catalog()
    sql = repository.search_text_sql(3)
    assert '"search_text"' in sql
    assert "LIMIT :limit" in sql


def test_search_text_sql_does_not_inspect_schema() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    repository = PostgresCatalogRepository(engine)

    def _fail_inspect() -> set[str]:
        raise AssertionError("search SQL must not inspect productmaster schema")

    repository.column_names = _fail_inspect  # type: ignore[method-assign]
    sql = repository.search_text_sql(3)
    assert '"search_text"' in sql
    assert "similarity(" in sql


def test_identifier_search_sql_uses_compact_column_on_postgres() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    repository = PostgresCatalogRepository(engine)
    sql = repository.identifier_search_sql(1)
    assert '"identifier_search"' in sql
    assert "replace(" not in sql
    assert repository.lookup_productcode("B1EB5-W") == []


def test_matcher_uses_catalog_search_instead_of_full_product_list() -> None:
    product = product_from_postgres_row(
        productcode="B1EB5-W",
        name="B1EB5-W",
        description="BRP 120V WHIP END EXT CBL",
        description2="BRP 120V WHIP END EXT CBL",
    )
    assert product is not None
    search = MagicMock()
    search.fetch_identifier_candidates.return_value = []
    search.search_text_candidates.return_value = [product]
    search.lookup_productcode.return_value = []
    matcher = ProductMatcher([], catalog_search=search)
    result = matcher.match_line(_line("BRP 120 volts whip end extension cable"))
    assert search.search_text_candidates.called
    assert matcher.products == []
    assert result.matched_part_number == "B1EB5-W"
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}


def test_matcher_requests_thirty_search_text_candidates() -> None:
    product = product_from_postgres_row(
        productcode="B1EB5-W",
        name="B1EB5-W",
        description="BRP 120V WHIP END EXT CBL",
        description2="BRP 120V WHIP END EXT CBL",
    )
    assert product is not None
    search = MagicMock()
    search.fetch_identifier_candidates.return_value = []
    search.search_text_candidates.return_value = [product]
    search.lookup_productcode.return_value = []
    matcher = ProductMatcher([], catalog_search=search)
    matcher.match_line(_line("BRP 120 volts whip end extension cable"))
    search.search_text_candidates.assert_called()
    assert search.search_text_candidates.call_args.kwargs["limit"] == 30


def test_identifier_retrieval_keeps_existing_limit() -> None:
    product = product_from_postgres_row(
        productcode="333479",
        name="RR 2BA KR",
        description="RR 2BA KR",
    )
    assert product is not None
    search = MagicMock()
    search.lookup_productcode.return_value = []
    search.fetch_identifier_candidates.return_value = [product]
    search.search_text_candidates.return_value = []
    matcher = ProductMatcher([], catalog_search=search)
    matcher.match_line(_line("RR 2BA KR"))
    search.fetch_identifier_candidates.assert_called()
    assert search.fetch_identifier_candidates.call_args.kwargs["limit"] == 100


def test_lookup_productcode_does_not_rewrite_values() -> None:
    repository = _sqlite_catalog()
    hits = repository.lookup_productcode("333479")
    assert [item.product_code for item in hits] == ["333479"]
    assert all("," not in item.product_code for item in hits)
