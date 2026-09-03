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
                "search_text TEXT, "
                "orderablepartnumber TEXT)"
            )
        )
        rows = [
            (333427, "B1EB5-W", "B1EB5-W", "BRP 120V WHIP END EXT CBL", "BRP 120V WHIP END EXT CBL", "ORD-B1EB5-W"),
            (333478, "333478", "RR 2BA KL", "RR 2BA KL", None, None),
            (333479, "333479", "RR 2BA KR", "RR 2BA KR", None, None),
            (1, "NOISE", "UNRELATED", "PURPLE BANANA ENCLOSURE", None, None),
        ]
        for row in rows:
            search_text = " ".join(str(part).lower() for part in row[1:5] if part)
            connection.execute(
                text(
                    'INSERT INTO productmaster '
                    '(id, "Productcode", name, description, description2, search_text, orderablepartnumber) '
                    "VALUES (:id, :code, :name, :description, :description2, :search_text, :orderablepartnumber)"
                ),
                {
                    "id": row[0],
                    "code": row[1],
                    "name": row[2],
                    "description": row[3],
                    "description2": row[4],
                    "search_text": search_text,
                    "orderablepartnumber": row[5],
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
    sql = repository.search_text_sql([1, 1, 1])
    assert '"search_text"' in sql
    assert "LIMIT :limit" in sql


def test_search_text_sql_does_not_inspect_schema() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    repository = PostgresCatalogRepository(engine)

    def _fail_inspect() -> set[str]:
        raise AssertionError("search SQL must not inspect productmaster schema")

    repository.column_names = _fail_inspect  # type: ignore[method-assign]
    sql = repository.search_text_sql([1, 1, 1])
    assert '"search_text"' in sql
    assert "similarity(" in sql


def test_search_text_sql_orders_by_word_similarity_with_similarity_tiebreak() -> None:
    # Plain similarity() is a ratio over the two full strings' combined
    # trigram counts, so it systematically favors short catalog rows over a
    # longer, more precise row that's actually the better match (confirmed
    # live: a correct 3" flex conduit row scored 0.078 vs. an unrelated
    # fitting's 0.145). word_similarity() scores the best-matching substring
    # instead, fixing that -- but it can then tie a long, mostly-unrelated
    # row against a short, genuinely on-topic one (both can contain the same
    # matching phrase), so plain similarity() is kept as the tiebreaker,
    # which does still penalize the extra unrelated length.
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    repository = PostgresCatalogRepository(engine)
    sql = repository.search_text_sql([1, 1, 1])
    assert "word_similarity(:rank_normalized," in sql
    word_sim_pos = sql.index("word_similarity(")
    plain_sim_pos = sql.index("similarity(", word_sim_pos + len("word_similarity("))
    assert word_sim_pos < plain_sim_pos


def test_search_text_sql_ors_synonym_variants_within_a_token_position() -> None:
    repository = _sqlite_catalog()
    sql = repository.search_text_sql([3, 1])
    assert "(" in sql and ") OR (" not in sql
    assert sql.count(":tok0_") == 3
    assert sql.count(":tok1_") == 1


def test_search_text_candidates_matches_spelled_out_cable_against_raw_catalog_text() -> None:
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
                "search_text TEXT, "
                "orderablepartnumber TEXT)"
            )
        )
        # Catalog text spells "CABLE" out in full; the query token canonicalizes
        # to "cbl" for scoring, but retrieval must still find this row.
        row = (1915974, "1915974", "NMAHCTC 24", '24" CABLE TRAY LOWER COVER', None)
        search_text = " ".join(str(part).lower() for part in row[1:] if part)
        connection.execute(
            text(
                'INSERT INTO productmaster '
                '(id, "Productcode", name, description, description2, search_text, orderablepartnumber) '
                "VALUES (:id, :code, :name, :description, :description2, :search_text, NULL)"
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
    repository = PostgresCatalogRepository(engine, retrieval_limit=100)
    hits = repository.search_text_candidates('Cable Tray: 24" Lower Cover', limit=100)
    codes = {item.product_code for item in hits}
    # Identity now comes from `name` ("NMAHCTC 24"), not the internal
    # Productcode value (1915974) -- name is the real orderable identifier.
    assert "NMAHCTC 24" in codes


def test_connection_scope_reuses_one_connection_across_searches() -> None:
    """Each search pays a pool checkout (pool_pre_ping does a live round-trip
    to validate the connection); connection_scope() lets one line's several
    sequential searches share a single checkout instead of one each."""
    repository = _sqlite_catalog()
    connect_calls = 0
    original_connect = repository.engine.connect

    def counting_connect(*args: object, **kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        return original_connect(*args, **kwargs)

    repository.engine.connect = counting_connect  # type: ignore[method-assign]

    with repository.connection_scope():
        repository.search_text_candidates("BRP 120 volts whip end extension cable", limit=100)
        repository.lookup_productcode("333479")
    assert connect_calls == 1


def test_without_connection_scope_each_search_opens_its_own_connection() -> None:
    repository = _sqlite_catalog()
    connect_calls = 0
    original_connect = repository.engine.connect

    def counting_connect(*args: object, **kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        return original_connect(*args, **kwargs)

    repository.engine.connect = counting_connect  # type: ignore[method-assign]

    repository.search_text_candidates("BRP 120 volts whip end extension cable", limit=100)
    repository.lookup_productcode("333479")
    assert connect_calls == 2


def test_matcher_shares_one_connection_per_line() -> None:
    """match_line touches the catalog more than once per line (identifier
    lookup, description search); it should reuse one connection for all of
    them rather than checking one out per call."""
    repository = _sqlite_catalog()
    connect_calls = 0
    original_connect = repository.engine.connect

    def counting_connect(*args: object, **kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        return original_connect(*args, **kwargs)

    repository.engine.connect = counting_connect  # type: ignore[method-assign]

    matcher = ProductMatcher([], catalog_search=repository)
    matcher.match_line(_line("BRP 120 volts whip end extension cable"))
    assert connect_calls == 1


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
    # lookup_productcode is an exact identifier lookup against `name` now
    # (Productcode is internal-only and never searched); verify the matched
    # identifier text comes back exactly as stored, with no reformatting.
    repository = _sqlite_catalog()
    hits = repository.lookup_productcode("B1EB5-W")
    assert [item.product_code for item in hits] == ["B1EB5-W"]
    assert all("," not in item.product_code for item in hits)


def test_lookup_productcode_falls_back_to_compact_match_for_spaced_names() -> None:
    """A query whose spacing/case doesn't match the stored name exactly (but
    is identical once whitespace/case/punctuation are stripped) must still
    resolve via the compact-match fallback. Regression test: compact_expr
    upper-cased the DB side while compact_code() also upper-cases the query,
    but an earlier version of this fallback lower-cased the DB side while
    still comparing to an upper-cased :compact param, so it could never match
    a name containing letters (only ever exercised digits-only Productcodes
    before, where case is a no-op)."""
    repository = _sqlite_catalog()
    hits = repository.lookup_productcode("rr2bakr")
    assert [item.product_code for item in hits] == ["RR 2BA KR"]
