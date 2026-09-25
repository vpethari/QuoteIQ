"""Add three materialized views summarizing salesorderdetails for the
customer-purchase-history lookup (PostgresCatalogRepository.
customer_purchase_quantities), replacing live aggregation of the raw
detail table.

Why: salesorderdetails is expected to hold ~1 year of data, steady-state
around 2.5 million rows in production (86,982 in this dev database).
Aggregating live from the raw table scales fine for the exact Ship-To/
Bill-To case (an indexed point lookup), but not for the BillToName
substring case ("GRAYBAR" sums every branch sharing that prefix/substring)
-- at 2.5M rows a single branch family's own order history could run to
tens of thousands of rows, re-summed on every quote line that selects a
customer by partial name. This lookup runs once per quote line, so that
cost compounds across a whole quote.

Each view pre-aggregates down to exactly the grain each cascade tier
queries (see customer_purchase_quantities's docstring for the cascade
itself: Ship-To, then Bill-To, then a BillToName substring search) --
confirmed live, even at this dev database's current 86,982 raw rows, each
view already collapses to ~20,000 rows (~4.3x reduction); the collapse
ratio should improve, not worsen, at 2.5M rows, since a full year of
history means more repeat orders per (customer, item) pair, not more
distinct pairs.

Verified live: results identical to the previous raw-table aggregation
for both a Ship-To lookup and a BillToName substring lookup (exact
SUM(OrderQuantity) match), before this migration was written.

Each view has a UNIQUE index on its grouping key -- required for
`REFRESH MATERIALIZED VIEW CONCURRENTLY` (a non-locking refresh), and it
doubles as the query index for the exact-match lookups. The BillToName
view additionally gets a pg_trgm GIN index, same reasoning as the
existing salesorderdetails index (20260925_0007) -- a substring search
can never be accelerated by a plain B-tree.

Refresh is intentionally NOT scheduled by this migration (out of scope --
the user will wire up the refresh cadence against however
salesorderdetails itself gets refreshed/pruned). Whoever owns that job
should run, after each load:
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_purchase_by_shipto;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_purchase_by_billto;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_purchase_by_billtoname;
(CONCURRENTLY requires the unique indexes above, already created here.)

Idempotent (IF NOT EXISTS / IF EXISTS): safe to run against a database
that already has these views (e.g. created ad hoc during investigation)
or one that doesn't. `WITH DATA` (CREATE MATERIALIZED VIEW's default) --
each view is already populated immediately on creation, no separate
initial REFRESH needed.

Revision ID: 20260926_0008
Revises: 20260925_0007
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260926_0008"
down_revision: Union[str, Sequence[str], None] = "20260925_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "salesorderdetails"

_VIEWS = ("mv_purchase_by_shipto", "mv_purchase_by_billto", "mv_purchase_by_billtoname")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    if _TABLE not in inspect(bind).get_table_names():
        return

    op.execute(
        text(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_purchase_by_shipto AS "
            'SELECT "ShipTo" AS ship_to, TRIM("ItemNumber") AS item_number, '
            'SUM("OrderQuantity") AS total_quantity '
            f"FROM {_TABLE} "
            'WHERE "ShipTo" IS NOT NULL '
            'GROUP BY "ShipTo", TRIM("ItemNumber")'
        )
    )
    op.execute(
        text(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_purchase_by_billto AS "
            'SELECT "BillTo" AS bill_to, TRIM("ItemNumber") AS item_number, '
            'SUM("OrderQuantity") AS total_quantity '
            f"FROM {_TABLE} "
            'WHERE "BillTo" IS NOT NULL '
            'GROUP BY "BillTo", TRIM("ItemNumber")'
        )
    )
    op.execute(
        text(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_purchase_by_billtoname AS "
            'SELECT TRIM("BillToName") AS bill_to_name, TRIM("ItemNumber") AS item_number, '
            'SUM("OrderQuantity") AS total_quantity '
            f"FROM {_TABLE} "
            "WHERE TRIM(\"BillToName\") <> '' "
            'GROUP BY TRIM("BillToName"), TRIM("ItemNumber")'
        )
    )

    op.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_purchase_by_shipto "
            "ON mv_purchase_by_shipto (ship_to, item_number)"
        )
    )
    op.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_purchase_by_billto "
            "ON mv_purchase_by_billto (bill_to, item_number)"
        )
    )
    op.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_purchase_by_billtoname "
            "ON mv_purchase_by_billtoname (bill_to_name, item_number)"
        )
    )
    op.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_mv_purchase_by_billtoname_trgm "
            "ON mv_purchase_by_billtoname USING gin (bill_to_name gin_trgm_ops)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    for view in _VIEWS:
        op.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS {view}"))
