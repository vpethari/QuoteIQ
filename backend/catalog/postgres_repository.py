from __future__ import annotations

import math
import re
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import bindparam, inspect, text
from sqlalchemy.engine import Connection, Engine

from catalog.search_query import retrieval_search_string, retrieval_search_token_groups
from matching.models import ProductRecord
from matching.normalizer import part_number_lookup_keys
from matching.productcode import compact_code, productcode_as_text
from matching.timing_diag import _ms, _pool_snapshot, active

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FAMILY_PRODUCTCODE_PLACEHOLDER = "-"
PRODUCT_RECORD_TYPE = "product"

# Bound to a real Connection only inside `connection_scope()`. ContextVars are
# per-thread (each ThreadPoolExecutor worker gets its own default context), so
# concurrent AI-mode lines never share a connection with each other.
_active_connection: ContextVar[Connection | None] = ContextVar("_active_connection", default=None)

# Fallback used only when the strict all-tokens-required search finds nothing:
# require most (not all) distinctive query tokens to appear, so catalog text
# that's terser or differently-worded than the customer's phrasing can still
# surface as a review candidate instead of a hard zero.
PARTIAL_MATCH_MIN_OVERLAP = 0.6
PARTIAL_MATCH_MIN_TOKENS = 3


def _quote(identifier: str) -> str:
    if not _IDENT.fullmatch(identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier}")
    return f'"{identifier}"'


def product_from_postgres_row(
    *,
    productcode: object,
    name: object = None,
    description: object = None,
    description2: object = None,
    row_id: object = None,
    record_type: object = None,
    orderablepartnumber: object = None,
) -> ProductRecord | None:
    """productmaster.name is the real, external orderable identifier (what
    customers/external agents quote and order by); Productcode is an
    internal-only surrogate key and is never used for matching or search --
    it's kept only as a last-resort internal reference id below.

    orderablepartnumber is a separate, dedicated column that sometimes
    differs from name (confirmed live: ~11% of rows) -- where present, it's
    the number to actually show/export for ordering, even though name
    remains what's searched and matched against.
    """
    name_text = str(name).strip() if name is not None and str(name).strip() else ""
    if not name_text or name_text == FAMILY_PRODUCTCODE_PLACEHOLDER:
        return None
    internal_id = productcode_as_text(row_id) or productcode_as_text(productcode) or None
    kind = str(record_type).strip().lower() if record_type is not None and str(record_type).strip() else PRODUCT_RECORD_TYPE
    if kind != PRODUCT_RECORD_TYPE:
        return None
    orderable_text = (
        str(orderablepartnumber).strip() if orderablepartnumber is not None and str(orderablepartnumber).strip() else None
    )
    return ProductRecord(
        salsify_id=name_text,
        official_part_number=name_text,
        description=str(description).strip() if description else None,
        record_type=PRODUCT_RECORD_TYPE,
        name=name_text,
        description2=str(description2).strip() if description2 else None,
        catalog_row_id=internal_id,
        orderable_part_number=orderable_text,
    )


class PostgresCatalogRepository:
    """Load catalog products from PostgreSQL without touching the matcher."""

    def __init__(
        self,
        engine: Engine,
        *,
        table: str = "productmaster",
        id_column: str = "id",
        productcode_column: str = "Productcode",
        name_column: str = "name",
        description_column: str = "description",
        description2_column: str = "description2",
        record_type_column: str = "record_type",
        search_text_column: str = "search_text",
        identifier_search_column: str = "identifier_search",
        orderablepartnumber_column: str = "orderablepartnumber",
        retrieval_limit: int = 100,
    ) -> None:
        self.engine = engine
        self.table = table
        self.id_column = id_column
        self.productcode_column = productcode_column
        self.name_column = name_column
        self.description_column = description_column
        self.description2_column = description2_column
        self.record_type_column = record_type_column
        self.search_text_column = search_text_column
        self.identifier_search_column = identifier_search_column
        self.orderablepartnumber_column = orderablepartnumber_column
        self.retrieval_limit = retrieval_limit
        self._cached_column_names: set[str] | None = None

    def _productcode_sql(self) -> str:
        return f"CAST({_quote(self.productcode_column)} AS TEXT)"

    def _is_postgres(self) -> bool:
        return self.engine.dialect.name in {"postgresql", "postgres"}

    def _search_text_expr(self) -> str:
        """search_text is required (migration 20260827_productmaster_search_text)."""
        return _quote(self.search_text_column)

    def _select_catalog_sql(self) -> str:
        """orderablepartnumber is required, same as search_text (both added
        by the same migration) -- not schema-inspected per query, since this
        runs on the hot per-line retrieval path."""
        table_sql = _quote(self.table)
        code_sql = self._productcode_sql()
        name_sql = _quote(self.name_column)
        desc_sql = _quote(self.description_column)
        desc2_sql = _quote(self.description2_column)
        orderable_sql = _quote(self.orderablepartnumber_column)
        return (
            f"SELECT {code_sql} AS productcode, {name_sql} AS name, "
            f"{desc_sql} AS description, {desc2_sql} AS description2, "
            f"{orderable_sql} AS orderablepartnumber "
            f"FROM {table_sql}"
        )

    @contextmanager
    def connection_scope(self):
        """Reuse one pooled connection for every search made inside this
        block, instead of a fresh pool checkout per individual query.

        Each checkout pays a live round-trip to validate the connection
        (``pool_pre_ping``); a single quote line can otherwise trigger several
        sequential searches (identifier lookup, strict text search, partial
        fallback), each paying that round-trip separately. Call this once per
        line being processed. Reentrant: nesting scopes reuses the outermost
        connection rather than opening a second one.
        """
        if _active_connection.get() is not None:
            yield
            return
        from time import perf_counter

        session = active()
        t0 = perf_counter()
        with self.engine.connect() as connection:
            if session is not None:
                session.add(db_connect_ms=_ms(perf_counter() - t0), connect_calls=1)
            token = _active_connection.set(connection)
            try:
                yield
            finally:
                _active_connection.reset(token)

    def _timed_fetch(self, sql, params: dict[str, object], *, search: str) -> list[dict[str, object]]:
        from time import perf_counter

        session = active()
        if session is not None:
            session.add(search=search)

        borrowed = _active_connection.get()
        t0 = perf_counter()
        if borrowed is not None:
            connect_ms = 0.0
            t1 = perf_counter()
            result = borrowed.execute(sql, params)
            query_ms = _ms(perf_counter() - t1)
            t2 = perf_counter()
            rows = [dict(row) for row in result.mappings()]
            map_ms = _ms(perf_counter() - t2)
            connect_calls = 0
        else:
            with self.engine.connect() as connection:
                connect_ms = _ms(perf_counter() - t0)
                t1 = perf_counter()
                result = connection.execute(sql, params)
                query_ms = _ms(perf_counter() - t1)
                t2 = perf_counter()
                rows = [dict(row) for row in result.mappings()]
                map_ms = _ms(perf_counter() - t2)
            connect_calls = 1
        if session is not None:
            session.add(
                db_connect_ms=connect_ms,
                db_query_ms=query_ms,
                db_map_ms=map_ms,
                connect_calls=connect_calls,
                sql_queries=1,
            )
            session.pool_status.append(_pool_snapshot(self.engine))
        return rows

    def _rows_to_products(self, rows: list[dict[str, object]]) -> list[ProductRecord]:
        from time import perf_counter

        session = active()
        t0 = perf_counter()
        records: list[ProductRecord] = []
        for row in rows:
            product = product_from_postgres_row(
                productcode=row.get("productcode"),
                name=row.get("name"),
                description=row.get("description"),
                description2=row.get("description2"),
                row_id=row.get("row_id"),
                record_type=row.get("record_type"),
                orderablepartnumber=row.get("orderablepartnumber"),
            )
            if product is not None:
                records.append(product)
        if session is not None:
            session.add(db_map_ms=_ms(perf_counter() - t0))
        return records

    def search_text_sql(self, token_variant_counts: list[int]) -> str:
        """Candidate retrieval SQL against search_text (or a concat fallback).

        Each entry in ``token_variant_counts`` is the number of equivalent
        spellings (e.g. "cable"/"cables"/"cbl") to OR together for that token
        position; positions are ANDed against each other.
        """
        like_op = "ILIKE" if self._is_postgres() else "LIKE"
        search_expr = self._search_text_expr()
        where_parts = [
            "(" + " OR ".join(f"{search_expr} {like_op} :tok{position}_{variant}" for variant in range(count)) + ")"
            for position, count in enumerate(token_variant_counts)
        ]
        if not where_parts:
            where_parts = [f"{search_expr} {like_op} :normalized"]
        order_sql = "1"
        if self._is_postgres() and token_variant_counts:
            order_sql = f"similarity({search_expr}, :rank_normalized) DESC"
        return (
            f"{self._select_catalog_sql()} "
            f"WHERE {' AND '.join(where_parts)} "
            f"ORDER BY {order_sql} "
            "LIMIT :limit"
        )

    def partial_search_text_sql(self, token_variant_counts: list[int], min_required: int) -> str:
        """Fallback retrieval SQL used only when the strict all-tokens search
        finds nothing: requires at least ``min_required`` of the token
        positions to match (each still OR'd across its own spellings), ranked
        by how many positions matched.

        Built as one indexed single-predicate query per token position, UNIONed
        and grouped, rather than a single scan computing every position's hit
        for every row -- the latter can't use the search_text trigram index and
        is a full table scan per call.
        """
        like_op = "ILIKE" if self._is_postgres() else "LIKE"
        search_expr = self._search_text_expr()
        code_sql = self._productcode_sql()
        name_sql = _quote(self.name_column)
        desc_sql = _quote(self.description_column)
        desc2_sql = _quote(self.description2_column)
        orderable_sql = _quote(self.orderablepartnumber_column)
        table_sql = _quote(self.table)
        branches = [
            "SELECT "
            f"{code_sql} AS productcode, {name_sql} AS name, "
            f"{desc_sql} AS description, {desc2_sql} AS description2, "
            f"{orderable_sql} AS orderablepartnumber, "
            f"{position} AS token_position "
            f"FROM {table_sql} WHERE "
            + " OR ".join(f"{search_expr} {like_op} :tok{position}_{variant}" for variant in range(count))
            for position, count in enumerate(token_variant_counts)
        ]
        return (
            "SELECT productcode, name, description, description2, orderablepartnumber, "
            "COUNT(DISTINCT token_position) AS match_count "
            f"FROM ({' UNION ALL '.join(branches)}) AS hits "
            "GROUP BY productcode, name, description, description2, orderablepartnumber "
            "HAVING COUNT(DISTINCT token_position) >= :min_required "
            "ORDER BY match_count DESC "
            "LIMIT :limit"
        )

    def search_text_candidates(
        self, query: str, limit: int | None = None, *, rank_query: str | None = None
    ) -> list[ProductRecord]:
        """Return a limited candidate set from PostgreSQL search_text.

        `rank_query`, when given, drives only the ORDER BY trigram-similarity
        comparison, not which rows are eligible (that's still `query`). This
        matters for short, bare queries (e.g. "1 PVC"): pg_trgm's similarity()
        is a ratio over combined trigram counts, so it systematically favors
        short catalog text over longer, more precise text -- e.g. "PVC
        KNOCKOUT PLUG 1 KO10 PVC Gray" outranks a genuine "1 in x 10 ft PVC
        Schedule 40 Conduit, Belled End" row purely for being shorter,
        pushing the actually-correct row past the LIMIT before scoring ever
        sees it. Ranking against the category-defaults-expanded query (see
        matching.category_defaults) instead gives rows that spell out the
        implied default wording a comparably-sized string to score against,
        without narrowing which rows are eligible in the first place.
        """
        cap = self.retrieval_limit if limit is None else limit
        token_groups = retrieval_search_token_groups(query)
        normalized = retrieval_search_string(query)
        if not normalized:
            return []
        rank_normalized = retrieval_search_string(rank_query) if rank_query else normalized
        variant_counts = [len(group) for group in token_groups]
        token_params: dict[str, object] = {}
        for position, group in enumerate(token_groups):
            for variant_index, variant in enumerate(group):
                token_params[f"tok{position}_{variant_index}"] = f"%{variant}%"

        sql = text(self.search_text_sql(variant_counts))
        params: dict[str, object] = {
            "limit": cap,
            "normalized": normalized,
            "rank_normalized": rank_normalized,
            **token_params,
        }
        rows = self._timed_fetch(sql, params, search="search_text_candidates")
        products = self._rows_to_products(rows)
        if products or not token_groups:
            return products

        if len(token_groups) >= PARTIAL_MATCH_MIN_TOKENS:
            min_required = math.ceil(len(token_groups) * PARTIAL_MATCH_MIN_OVERLAP)
            if min_required < len(token_groups):
                sql = text(self.partial_search_text_sql(variant_counts, min_required))
                params = {"limit": cap, "normalized": normalized, "min_required": min_required, **token_params}
                rows = self._timed_fetch(sql, params, search="search_text_candidates_partial")
                products = self._rows_to_products(rows)
                if products:
                    return products

        sql = text(self.search_text_sql([]))
        params = {"limit": cap, "normalized": f"%{normalized}%"}
        rows = self._timed_fetch(sql, params, search="search_text_candidates_fallback")
        return self._rows_to_products(rows)

    def _legacy_compact_identifier_blob(self) -> str:
        def compact_expr(column_sql: str) -> str:
            return (
                "replace(replace(replace(upper(coalesce(cast("
                f"{column_sql} as text), '')), ' ', ''), '-', ''), '/', '')"
            )

        name_sql = _quote(self.name_column)
        desc_sql = _quote(self.description_column)
        desc2_sql = _quote(self.description2_column)
        return (
            f"{compact_expr(name_sql)} || {compact_expr(desc_sql)} || {compact_expr(desc2_sql)}"
        )

    def _identifier_search_expr(self) -> str:
        if self._is_postgres():
            return _quote(self.identifier_search_column)
        return self._legacy_compact_identifier_blob()

    def identifier_search_sql(self, token_count: int) -> str:
        """Candidate SQL for compact name/description identifier retrieval."""
        expr = self._identifier_search_expr()
        where_parts = [f"{expr} LIKE :tok{index}" for index in range(token_count)]
        return (
            f"{self._select_catalog_sql()} "
            f"WHERE {' AND '.join(where_parts)} "
            "LIMIT :limit"
        )

    def lookup_productcode(self, identifier: str, limit: int = 20) -> list[ProductRecord]:
        """Exact identifier lookup against productmaster.name -- the real
        orderable part number. Productcode is internal-only and is never
        searched or matched against.
        """
        keys = [key for key in part_number_lookup_keys(identifier) if key]
        if not keys:
            compact = compact_code(identifier)
            if compact:
                keys = [compact]
        if not keys:
            return []
        name_sql = _quote(self.name_column)
        # compact_code() upper-cases (see matching/productcode.py); this must
        # match on the same case or an alphabetic name never matches here --
        # harmless while this compared a digits-only Productcode, but name
        # can contain letters.
        compact_expr = (
            "replace(replace(replace(upper(coalesce("
            f"{name_sql}, '')), ' ', ''), '-', ''), '/', '')"
        )
        query = text(
            f"""
            {self._select_catalog_sql()}
            WHERE {name_sql} IN :keys
               OR lower({name_sql}) IN :lower_keys
               OR {compact_expr} = :compact
            LIMIT :limit
            """
        ).bindparams(bindparam("keys", expanding=True), bindparam("lower_keys", expanding=True))
        rows = self._timed_fetch(
            query,
            {
                "keys": keys,
                "lower_keys": [key.lower() for key in keys],
                "compact": compact_code(identifier),
                "limit": limit,
            },
            search="lookup_productcode",
        )
        return self._rows_to_products(rows)

    def explain_search_text_candidates(self, query: str, limit: int | None = None) -> str:
        """Run EXPLAIN ANALYZE for the candidate retrieval query."""
        cap = self.retrieval_limit if limit is None else limit
        token_groups = retrieval_search_token_groups(query)
        normalized = retrieval_search_string(query)
        sql_body = self.search_text_sql([len(group) for group in token_groups])
        params: dict[str, object] = {"limit": cap, "normalized": normalized}
        if token_groups:
            for position, group in enumerate(token_groups):
                for variant_index, variant in enumerate(group):
                    params[f"tok{position}_{variant_index}"] = f"%{variant}%"
        else:
            params["normalized"] = f"%{normalized}%"
        explain = text(f"EXPLAIN ANALYZE {sql_body}")
        with self.engine.connect() as connection:
            rows = connection.execute(explain, params).fetchall()
        return "\n".join(str(row[0]) for row in rows)

    def check_connection(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def column_names(self) -> set[str]:
        """One-shot schema lookup for load_products / verification scripts, not search."""
        from time import perf_counter

        cached = self._cached_column_names
        if cached is not None:
            return cached
        session = active()
        t0 = perf_counter()
        inspector = inspect(self.engine)
        names = {column["name"] for column in inspector.get_columns(self.table)}
        self._cached_column_names = names
        if session is not None:
            session.add(db_inspect_ms=_ms(perf_counter() - t0), inspect_calls=1)
        return names

    def load_products(self) -> list[ProductRecord]:
        session = active()
        if session is not None:
            session.load_products_calls += 1
            session.notes.append("load_products() fetched full productmaster into Python")
        records: list[ProductRecord] = []
        for row in self._fetch_rows():
            product = product_from_postgres_row(
                productcode=row.get("productcode"),
                name=row.get("name"),
                description=row.get("description"),
                description2=row.get("description2"),
                row_id=row.get("row_id"),
                record_type=row.get("record_type"),
                orderablepartnumber=row.get("orderablepartnumber"),
            )
            if product is not None:
                records.append(product)
        return records

    def fetch_sample_rows(self, limit: int = 5) -> list[dict[str, object]]:
        """Run the verification query: Productcode, name, description, description2 LIMIT n."""
        table_sql = _quote(self.table)
        code_sql = self._productcode_sql()
        name_sql = _quote(self.name_column)
        desc_sql = _quote(self.description_column)
        desc2_sql = _quote(self.description2_column)
        query = text(
            f"""
            SELECT
                {code_sql} AS productcode,
                {name_sql} AS name,
                {desc_sql} AS description,
                {desc2_sql} AS description2
            FROM {table_sql}
            LIMIT :limit
            """
        )
        with self.engine.connect() as connection:
            return [
                {
                    **dict(row),
                    "productcode": productcode_as_text(row.get("productcode")),
                }
                for row in connection.execute(query, {"limit": limit}).mappings()
            ]

    def fetch_by_productcodes(self, codes: list[str]) -> list[dict[str, object]]:
        wanted = [str(code).strip() for code in codes if str(code).strip()]
        if not wanted:
            return []
        table_sql = _quote(self.table)
        code_sql = self._productcode_sql()
        name_sql = _quote(self.name_column)
        desc_sql = _quote(self.description_column)
        desc2_sql = _quote(self.description2_column)
        query = text(
            f"""
            SELECT
                {code_sql} AS productcode,
                {name_sql} AS name,
                {desc_sql} AS description,
                {desc2_sql} AS description2
            FROM {table_sql}
            WHERE {code_sql} IN :codes
               OR {name_sql} IN :names
               OR {desc_sql} IN :descriptions
               OR {desc2_sql} IN :descriptions2
            """
        ).bindparams(
            bindparam("codes", expanding=True),
            bindparam("names", expanding=True),
            bindparam("descriptions", expanding=True),
            bindparam("descriptions2", expanding=True),
        )
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    query,
                    {
                        "codes": wanted,
                        "names": wanted,
                        "descriptions": wanted,
                        "descriptions2": wanted,
                    },
                ).mappings()
            ]

    def fetch_identifier_candidates(self, query: str, limit: int = 50) -> list[ProductRecord]:
        """Retrieve Productcode/name hits by compact token evidence, not exact equality."""
        from matching.productcode import code_tokens, compact_token, is_generic_code_token

        distinctive = [
            compact_token(token)
            for token in code_tokens(query)
            if not is_generic_code_token(token) and len(compact_token(token)) >= 2
        ]
        if not distinctive:
            return []
        sql = text(self.identifier_search_sql(len(distinctive)))
        params: dict[str, object] = {"limit": limit}
        for index, token in enumerate(distinctive):
            needle = token.lower() if self._is_postgres() else token
            params[f"tok{index}"] = f"%{needle}%"
        rows = self._timed_fetch(sql, params, search="fetch_identifier_candidates")
        return self._rows_to_products(rows)

    def _fetch_rows(self) -> list[dict[str, object]]:
        columns = self.column_names()
        table_sql = _quote(self.table)
        code_cast = self._productcode_sql()
        name_sql = _quote(self.name_column)
        desc_sql = _quote(self.description_column)
        desc2_sql = _quote(self.description2_column)
        select_parts = [
            f"{code_cast} AS productcode",
            f"{name_sql} AS name",
            f"{desc_sql} AS description",
            f"{desc2_sql} AS description2",
        ]
        if self.id_column in columns:
            select_parts.append(f"{_quote(self.id_column)} AS row_id")
        has_record_type = self.record_type_column in columns
        if has_record_type:
            select_parts.append(f"{_quote(self.record_type_column)} AS record_type")
        if self.orderablepartnumber_column in columns:
            select_parts.append(f"{_quote(self.orderablepartnumber_column)} AS orderablepartnumber")
        # Gate on name (the real identifier), not Productcode (internal-only) --
        # a row needs a usable name to be matchable at all now.
        where_parts = [
            f"{name_sql} IS NOT NULL",
            f"TRIM(CAST({name_sql} AS TEXT)) <> ''",
            f"TRIM(CAST({name_sql} AS TEXT)) <> '{FAMILY_PRODUCTCODE_PLACEHOLDER}'",
        ]
        if has_record_type:
            where_parts.append(
                f"LOWER(TRIM(CAST({_quote(self.record_type_column)} AS TEXT))) = '{PRODUCT_RECORD_TYPE}'"
            )
        query = text(
            f"""
            SELECT {", ".join(select_parts)}
            FROM {table_sql}
            WHERE {" AND ".join(where_parts)}
            """
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(query).mappings()]
