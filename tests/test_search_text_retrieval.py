from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import create_engine, text

from catalog.postgres_repository import PostgresCatalogRepository, product_from_postgres_row
from matching.matcher import ProductMatcher, _rerank_by_dimension_match
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
                "orderablepartnumber TEXT, "
                "preferredflag TEXT)"
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


def test_retrieval_keeps_fraction_sizes_literal_not_decimal() -> None:
    # search_text is a raw generated column, never unit-normalized -- a
    # fraction size must stay "1/2" here to match the catalog's own literal
    # text ("MSC5090KON 1/2\" SQUEEZE CONNECTORS..."). Converting it to
    # "0.5 IN" (which scoring *does* want, for consistent token comparison
    # against the candidate's own unit-normalized text) would search for a
    # substring the catalog's raw text never contains, silently excluding
    # every fraction-size row from retrieval.
    from catalog.search_query import retrieval_search_string, retrieval_search_token_groups

    groups = retrieval_search_token_groups('1/2" STL FLEX CONN')
    flat = {variant for group in groups for variant in group}
    assert "1/2" in flat
    assert "0.5" not in flat

    normalized = retrieval_search_string('1/2" STL FLEX CONN')
    assert "1/2" in normalized
    assert "0.5" not in normalized


def test_retrieval_strips_leading_zero_from_whole_number_sizes() -> None:
    # Confirmed live: 'Coupling: 02" PVC...' never matched the catalog's own
    # "2" literally -- apply_units=False keeps a fraction like "1/2" literal
    # on purpose, but that also means a bare leading zero on a whole number
    # never goes through unit normalization (which strips it via int()) the
    # way scoring's own tokenize_description() does.
    from catalog.search_query import retrieval_search_string, retrieval_search_token_groups

    normalized = retrieval_search_string('02" PVC COUPLING')
    assert "02" not in normalized.split()
    assert "2" in normalized.split()

    groups = retrieval_search_token_groups('02" PVC COUPLING')
    flat = {variant for group in groups for variant in group}
    assert "02" not in flat

    # A fraction size must still be untouched -- no leading zero to strip.
    assert "1/2" in retrieval_search_string('1/2" PVC COUPLING').split()


def test_retrieval_keeps_a_genuine_bare_whole_number_size_required() -> None:
    # Confirmed live: "4\" GRC STRUT CLAMP" and "3\" GRC STRUT CLAMP" used to
    # retrieve identically -- a single bare digit was always dropped as
    # probable noise, on the assumption it was a mixed fraction's leftover
    # whole part (e.g. "1" in "1 1/2\""). That's true when it's immediately
    # followed by a fraction, but "4" here is the query's only, genuine
    # size and dropping it lost all size information from retrieval.
    from catalog.search_query import retrieval_search_token_groups

    groups = retrieval_search_token_groups('4" GRC STRUT CLAMP')
    flat = {variant for group in groups for variant in group}
    assert "4" in flat


def test_retrieval_still_drops_mixed_fraction_leading_whole_part() -> None:
    # Companion case: "1" in "1 1/2\"" (and "1-5/8") is immediately followed
    # by the fraction that already carries the real size -- must stay
    # dropped, not suddenly become a second, redundant required position.
    from catalog.search_query import retrieval_search_token_groups

    for query in ('1 1/2" GRC (GALV)', "1-5/8 CHANNEL"):
        groups = retrieval_search_token_groups(query)
        flat = {variant for group in groups for variant in group}
        assert "1" not in flat


def test_scoring_tokenization_still_converts_fraction_to_decimal() -> None:
    # The retrieval-side fix above must not regress scoring, which needs
    # both the query and the candidate's raw text unit-normalized the same
    # way for token comparison to work at all.
    from matching.description_normalize import tokenize_description

    tokens = tokenize_description('1/2" STL FLEX CONN')
    assert "0.5" in tokens
    assert "IN" in tokens


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


def test_partial_search_text_sql_orders_by_word_similarity_with_similarity_tiebreak() -> None:
    # Confirmed live: "4\" GRC STRUT CLAMP" tied 200+ generic pipe-clamp rows
    # at the exact same match_count (this query never satisfies the strict
    # all-tokens search, so it always falls to this partial tier) -- with no
    # secondary ORDER BY at all, which of those 200+ ties survives the LIMIT
    # cutoff is arbitrary (Postgres's own GROUP BY/hash order), not a
    # reflection of which one actually reads closest. The genuinely correct
    # 4" clamp had the single highest word_similarity of the whole tied
    # group, yet was excluded entirely. Same tiebreak signal the strict-AND
    # tier already uses (see test_search_text_sql_orders_by_word_similarity_
    # with_similarity_tiebreak above).
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    repository = PostgresCatalogRepository(engine)
    sql = repository.partial_search_text_sql([("abc",), ("def",), ("ghi",)], 2)
    assert "match_count DESC" in sql
    assert "word_similarity(:rank_normalized, search_text)" in sql
    word_sim_pos = sql.index("word_similarity(")
    plain_sim_pos = sql.index("similarity(", word_sim_pos + len("word_similarity("))
    assert word_sim_pos < plain_sim_pos


def test_partial_search_text_sql_falls_back_to_match_count_only_on_sqlite() -> None:
    repository = _sqlite_catalog()
    sql = repository.partial_search_text_sql([("abc",), ("def",), ("ghi",)], 2)
    assert "ORDER BY match_count DESC " in sql
    assert "word_similarity" not in sql


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
                "orderablepartnumber TEXT, "
                "preferredflag TEXT)"
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


def test_search_text_candidates_matches_fraction_size_against_raw_catalog_text() -> None:
    # Regression test: a query fraction size (e.g. "1/2") must still find a
    # catalog row that spells the same size the same way, not get rewritten
    # to a decimal form ("0.5 IN") the row's raw text never contains.
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
                "orderablepartnumber TEXT, "
                "preferredflag TEXT)"
            )
        )
        row = (2180287, "MSC5090KON", "MSC5090KON", 'MSC5090KON 1/2" SQUEEZE CONNECTORS - 90 DEGREE', None)
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
    hits = repository.search_text_candidates('1/2" STL FLEX CONN', limit=100)
    codes = {item.product_code for item in hits}
    assert "MSC5090KON" in codes


def _sqlite_from_rows(rows: list[tuple[int, str, str, str, str]]) -> PostgresCatalogRepository:
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
                "orderablepartnumber TEXT, "
                "preferredflag TEXT)"
            )
        )
        for row_id, code, name, description, description2 in rows:
            search_text = " ".join(part.lower() for part in (code, name, description, description2))
            connection.execute(
                text(
                    'INSERT INTO productmaster '
                    '(id, "Productcode", name, description, description2, search_text, orderablepartnumber) '
                    "VALUES (:id, :code, :name, :description, :description2, :search_text, NULL)"
                ),
                {
                    "id": row_id,
                    "code": code,
                    "name": name,
                    "description": description,
                    "description2": description2,
                    "search_text": search_text,
                },
            )
    return PostgresCatalogRepository(engine, retrieval_limit=100)


def test_strict_hit_is_merged_with_partial_match_single_coincidental_hit() -> None:
    # Regression test: confirmed live for "3/4\" EMT STL SS CPLG" -- strict
    # AND found exactly one row, a specialty EMT-to-RIGID transition
    # coupling whose text happens to abbreviate "Steel" as "STL" the same
    # way the query does, while the genuinely correct plain EMT-to-EMT
    # coupling spells "Steel" out in full and only satisfies partial
    # matching. Before this fix, the single coincidental strict hit
    # short-circuited retrieval and the genuine match was never even
    # considered by scoring.
    repository = _sqlite_from_rows(
        [
            (1, "ERSS75KON", "ERSS75KON", '3/4"STL SET SCREW TO RIGID SET SCREW COUPLING', "EMT"),
            (2, "SK75RKON", "SK75RKON", '3/4"EMT SET SCREW COUPLING Steel Zinc Plated', "EMT Coupling"),
        ]
    )
    hits = repository.search_text_candidates('3/4" EMT STL SS CPLG', limit=100)
    codes = {item.product_code for item in hits}
    assert "ERSS75KON" in codes
    assert "SK75RKON" in codes


def test_strict_hit_is_merged_with_partial_match_several_coincidental_hits() -> None:
    # Regression test: confirmed live for "1 1/2\" STL FLEX CONN" -- strict
    # AND found FOUR rows this time (an unrelated Liquidtight-Tubular-Steel
    # connector family whose own catalog product codes happen to embed
    # "STL"), not just one -- a fixed hit-count threshold tuned to rescue
    # the single-hit case above was still too low to also catch this one.
    # The genuinely correct plain flex connector ("Squeeze Connectors",
    # Malleable Iron) again never satisfies "stl" literally and needs the
    # partial-match tier regardless of how many strict hits already exist.
    repository = _sqlite_from_rows(
        [
            (1, "LT150STLKON", "LT150STLKON", '1-1/2" LIQUIDTIGHT TUBULAR STEEL', "Steel Connector"),
            (2, "LT150STL-ICKON", "LT150STL-ICKON", '1-1/2" LQTIGHT TUBULAR STEEL INSULATED', "Steel Connector"),
            (3, "LT50STLKON", "LT50STLKON", '1/2" LIQUIDTIGHT TUBULAR STEEL', "Steel Connector"),
            (4, "LT50STL-ICKON", "LT50STL-ICKON", '1/2" LIQUIDTIGHT TUBULAR STEEL INSULATED', "Steel Connector"),
            (5, "MSC150KON", "MSC150KON", '1-1/2" SQUEEZE CONNECTORS', "Malleable Iron Connector"),
        ]
    )
    hits = repository.search_text_candidates('1 1/2" STL FLEX CONN', limit=100)
    codes = {item.product_code for item in hits}
    assert "LT150STLKON" in codes
    assert "MSC150KON" in codes


def test_partial_match_skipped_when_strict_and_saturates_the_pool() -> None:
    # Confirmed live via performance profiling of the 135-line regression
    # baseline: the slowest lines were all common, generic multi-word
    # queries (e.g. "4\" PVC 90 DEG ELBOW") where strict AND alone already
    # filled the entire requested pool -- yet the always-also-try-partial-
    # match behavior above still ran the (far more expensive) partial
    # query, even though merged[:cap] truncates to the same result either
    # way once strict AND is already full. That one skip cut DB time on
    # these lines from ~2.3s to ~150-200ms. Uses a small `limit` here so a
    # genuinely saturated strict-AND pool is easy to construct in a tiny
    # fixture -- ROW3 (matching only 2 of 3 required positions) must NOT
    # surface, since it would only be found via the (skipped) partial tier.
    repository = _sqlite_from_rows(
        [
            (1, "ROW1", "ROW1", "STEEL WIDGET CONNECTOR", "match"),
            (2, "ROW2", "ROW2", "STEEL WIDGET CONNECTOR TWO", "match"),
            (3, "ROW3", "ROW3", "STEEL WIDGET", "partial only, missing CONNECTOR"),
        ]
    )
    hits = repository.search_text_candidates("STEEL WIDGET CONNECTOR", limit=2)
    codes = {item.product_code for item in hits}
    assert codes == {"ROW1", "ROW2"}
    assert "ROW3" not in codes


def test_partial_match_still_runs_when_strict_and_does_not_saturate() -> None:
    # The companion case: when strict AND does NOT fill the pool, the
    # saturation skip above must not apply -- partial-match still needs to
    # run, exactly as the two coincidental-hit regression tests above
    # already prove for a *small* (not merely non-saturated) strict count.
    # This uses a strict count comfortably below the limit but still more
    # than one, to isolate the saturation check specifically.
    repository = _sqlite_from_rows(
        [
            (1, "ROW1", "ROW1", "STEEL WIDGET CONNECTOR", "match"),
            (2, "ROW2", "ROW2", "STEEL WIDGET CONNECTOR TWO", "match"),
            (3, "ROW3", "ROW3", "STEEL WIDGET", "partial only, missing CONNECTOR"),
        ]
    )
    hits = repository.search_text_candidates("STEEL WIDGET CONNECTOR", limit=100)
    codes = {item.product_code for item in hits}
    assert codes == {"ROW1", "ROW2", "ROW3"}


def test_partial_match_with_bare_digit_position_finds_rows_missing_it() -> None:
    # Regression test for the trigram-indexable/non-indexable split in
    # partial_search_text_sql (see MIN_TRIGRAM_INDEXABLE_LENGTH): a bare
    # digit position ("2") can't use the trigram index, so it's checked
    # separately from the indexable "steel"/"locknut" positions -- but must
    # still behave as just one more OR'd position contributing at most 1 to
    # match_count, not a hard requirement. min_required for 3 positions at
    # 0.6 overlap is 2, so a row satisfying any 2 of the 3 (in any
    # combination) must still be found.
    repository = _sqlite_from_rows(
        [
            (1, "ALL3", "ALL3", "2 STEEL LOCKNUT", "matches all three positions"),
            (2, "NO_DIGIT", "NO_DIGIT", "STEEL LOCKNUT", "matches only the two indexable positions"),
            (3, "ONLY_DIGIT", "ONLY_DIGIT", "2", "matches only the non-indexable position"),
        ]
    )
    hits = repository.search_text_candidates("2 STEEL LOCKNUT", limit=100)
    codes = {item.product_code for item in hits}
    assert "ALL3" in codes
    assert "NO_DIGIT" in codes
    assert "ONLY_DIGIT" not in codes


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

    # search_text_candidates always merges in a second, internal
    # partial-match query alongside the strict-AND one (see the comment
    # above PARTIAL_MATCH_MIN_TOKENS in postgres_repository.py) -- 2
    # physical queries for this one logical search, plus 1 for
    # lookup_productcode, all outside connection_scope so each opens its
    # own connection.
    repository.search_text_candidates("BRP 120 volts whip end extension cable", limit=100)
    repository.lookup_productcode("333479")
    assert connect_calls == 3


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


def test_matcher_requests_a_larger_sql_pool_than_it_scores() -> None:
    # The matcher asks SQL for a wider pool (search_text_rerank_pool_limit)
    # than it actually scores (search_text_candidate_limit) -- SQL's own
    # trigram ranking has no concept of "size", so _rerank_by_dimension_match
    # needs enough of a pool to find a genuine same-size candidate that a
    # same-family tie pushed past a plain 30-row cutoff (confirmed live: "4\"
    # GRC STRUT CLAMP" tied 16+ stainless variants across every size before
    # even reaching the dozens of finish-code variants of the correct part).
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
    assert search.search_text_candidates.call_args.kwargs["limit"] == 150


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


def _size_product(code: str, description: str) -> object:
    product = product_from_postgres_row(productcode=code, name=code, description=description)
    assert product is not None
    return product


def test_rerank_by_dimension_match_promotes_a_genuine_same_size_candidate() -> None:
    # Confirmed live: "4\" GRC STRUT CLAMP" retrieved 16+ stainless "STRUT
    # CLMP" variants across every size before the genuinely correct 4"
    # candidate at all -- SQL's own trigram ranking has no notion of "size".
    wrong_size = _size_product("WRONG34", '3/4" SS316 STRUT CLMP Stainless Steel')
    right_size = _size_product("RIGHT4", '4" SS316 STRUT CLMP Stainless Steel')
    ranked = _rerank_by_dimension_match('4" GRC STRUT CLAMP', [wrong_size, wrong_size, right_size], limit=2)
    assert ranked[0].product_code == "RIGHT4"


def test_rerank_by_dimension_match_is_stable_within_groups() -> None:
    # A stable sort: the existing SQL ordering must survive fully intact
    # *within* the "matches"/"doesn't match" groups -- this only ever moves
    # the dividing line between them.
    first = _size_product("A4", "4 IN CLAMP A")
    second = _size_product("B4", "4 IN CLAMP B")
    ranked = _rerank_by_dimension_match('4" CLAMP', [first, second], limit=2)
    assert [item.product_code for item in ranked] == ["A4", "B4"]


def test_rerank_by_dimension_match_only_promotes_a_confirmed_same_size() -> None:
    # A candidate with no extractable size at all has nothing to positively
    # confirm a match with, so it sorts behind a candidate that does --
    # same as a genuinely different size would (see extract_dimensions()'s
    # own unit-mark requirement, in the docstring above).
    no_size = _size_product("NOSIZE", "GENERIC CLAMP NO DIMENSION GIVEN")
    right_size = _size_product("RIGHT4", '4" CLAMP')
    ranked = _rerank_by_dimension_match('4" CLAMP', [no_size, right_size], limit=2)
    assert [item.product_code for item in ranked] == ["RIGHT4", "NOSIZE"]


def test_rerank_by_dimension_match_truncates_to_limit() -> None:
    products = [_size_product(f"P{i}", "4 IN CLAMP") for i in range(5)]
    ranked = _rerank_by_dimension_match('4" CLAMP', products, limit=3)
    assert len(ranked) == 3


def test_rerank_by_dimension_match_passes_through_when_query_has_no_size() -> None:
    products = [_size_product(f"P{i}", "4 IN CLAMP") for i in range(3)]
    ranked = _rerank_by_dimension_match("GENERIC CLAMP", products, limit=2)
    assert [item.product_code for item in ranked] == ["P0", "P1"]
