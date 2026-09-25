"""Add indexes to salesorderdetails, used by the customer-purchase-history
ranking signal (see PostgresCatalogRepository.customer_purchase_quantities).

salesorderdetails is a separate, user-created sales-history table (not
part of the catalog schema the earlier migrations manage) with no indexes
at all -- every lookup was a full sequential scan of its ~87,000 rows.
Every filter in customer_purchase_quantities wraps its column in TRIM()
(the source data is fixed-width, space-padded) or is a leading-wildcard
ILIKE substring search, so plain B-tree indexes on the raw columns would
not have been usable by the query planner -- these are expression indexes
matching the exact predicates the query actually uses, plus a pg_trgm GIN
index for the substring search (a plain B-tree cannot accelerate a
leading-wildcard LIKE/ILIKE at all).

Confirmed live (EXPLAIN ANALYZE, before/after): a BillTo/ShipTo account-
number lookup went from ~11ms to ~0.3ms; a BillToName substring search
went from ~106ms to <1ms; a BillToName prefix search went from ~176ms to
~1ms. This lookup runs once per quote line whenever a customer is
selected, so the pre-index cost scaled directly with quote size (e.g.
~24s of pure lookup time across a 135-line quote at the prefix-search
worst case) -- post-index, that same 135-line cost drops to about 0.15s.
Total added index size: ~6.4MB against a 14MB table.

Idempotent (IF NOT EXISTS / IF EXISTS): safe to run against a database
that already has these indexes (e.g. created ad hoc during investigation)
or one that doesn't.

Revision ID: 20260925_0007
Revises: 20260911_0006
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260925_0007"
down_revision: Union[str, Sequence[str], None] = "20260911_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "salesorderdetails"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    if _TABLE not in inspect(bind).get_table_names():
        return
    op.execute(text(f'CREATE INDEX IF NOT EXISTS ix_salesorderdetails_billto ON {_TABLE} ("BillTo")'))
    op.execute(text(f'CREATE INDEX IF NOT EXISTS ix_salesorderdetails_shipto ON {_TABLE} ("ShipTo")'))
    op.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_salesorderdetails_itemnumber_trim '
            f'ON {_TABLE} (TRIM("ItemNumber"))'
        )
    )
    op.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    op.execute(
        text(
            f'CREATE INDEX IF NOT EXISTS ix_salesorderdetails_billtoname_trgm '
            f'ON {_TABLE} USING gin (TRIM("BillToName") gin_trgm_ops)'
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    if _TABLE not in inspect(bind).get_table_names():
        return
    op.execute(text("DROP INDEX IF EXISTS ix_salesorderdetails_billtoname_trgm"))
    op.execute(text("DROP INDEX IF EXISTS ix_salesorderdetails_itemnumber_trim"))
    op.execute(text("DROP INDEX IF EXISTS ix_salesorderdetails_shipto"))
    op.execute(text("DROP INDEX IF EXISTS ix_salesorderdetails_billto"))
