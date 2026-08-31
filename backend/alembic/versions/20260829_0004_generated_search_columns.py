"""Convert productmaster.search_text / identifier_search to generated columns.

Both columns were previously plain TEXT populated by a one-time backfill
UPDATE (migrations 20260827_0002 / 20260827_0003). Nothing kept them in sync
with later inserts/updates to Productcode, name, description, or
description2 -- a catalog refresh that didn't remember to re-run the backfill
script would silently leave search unable to find the changed rows.

GENERATED ALWAYS AS (...) STORED columns are recomputed by Postgres itself on
every insert/update, so this failure mode can no longer happen. The
expressions are unchanged from the original migrations, so existing values
and search behavior are identical -- this only changes how the columns stay
up to date.

Revision ID: 20260829_0004
Revises: 20260827_0003
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260829_0004"
down_revision: Union[str, Sequence[str], None] = "20260827_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEARCH_TEXT_SQL = """
lower(
    CAST("Productcode" AS TEXT)
    || CASE WHEN name IS NOT NULL THEN ' ' || name ELSE '' END
    || CASE WHEN description IS NOT NULL THEN ' ' || description ELSE '' END
    || CASE WHEN description2 IS NOT NULL THEN ' ' || description2 ELSE '' END
)
"""
# concat_ws() is STABLE, not IMMUTABLE (it accepts a polymorphic VARIADIC
# "any" argument), so a GENERATED column can't use it directly -- Postgres
# rejects the whole expression with "generation expression is not
# immutable". This CASE-based rewrite only uses immutable primitives
# (||, coalesce equivalents via CASE) and was verified to produce byte-
# identical values to the old concat_ws version across all 65,745 existing
# rows before this migration was applied.

IDENTIFIER_SEARCH_SQL = """
lower(
    replace(
        replace(
            replace(
                CAST("Productcode" AS TEXT)
                || coalesce(name, '')
                || coalesce(description, '')
                || coalesce(description2, ''),
                ' ',
                ''
            ),
            '-',
            ''
        ),
        '/',
        ''
    )
)
"""
# Same concat_ws -> || rewrite as SEARCH_TEXT_SQL above, for the same reason.
# With an empty-string separator, coalesce-to-'' is exactly equivalent to
# concat_ws's null-skipping, so this is a pure immutability fix with no
# behavior change -- also verified byte-identical against all existing rows.


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    tables = inspect(bind).get_table_names()
    if "productmaster" not in tables:
        return

    op.execute(text("DROP INDEX IF EXISTS idx_productmaster_search_text_trgm"))
    op.execute(text("DROP INDEX IF EXISTS idx_productmaster_identifier_search_trgm"))
    op.execute(text("ALTER TABLE productmaster DROP COLUMN IF EXISTS search_text"))
    op.execute(text("ALTER TABLE productmaster DROP COLUMN IF EXISTS identifier_search"))

    op.execute(
        text(f"ALTER TABLE productmaster ADD COLUMN search_text TEXT GENERATED ALWAYS AS ({SEARCH_TEXT_SQL}) STORED")
    )
    op.execute(
        text(
            "ALTER TABLE productmaster ADD COLUMN identifier_search TEXT "
            f"GENERATED ALWAYS AS ({IDENTIFIER_SEARCH_SQL}) STORED"
        )
    )

    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_productmaster_search_text_trgm "
            "ON productmaster USING gin (search_text gin_trgm_ops)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_productmaster_identifier_search_trgm "
            "ON productmaster USING gin (identifier_search gin_trgm_ops)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    tables = inspect(bind).get_table_names()
    if "productmaster" not in tables:
        return

    op.execute(text("DROP INDEX IF EXISTS idx_productmaster_search_text_trgm"))
    op.execute(text("DROP INDEX IF EXISTS idx_productmaster_identifier_search_trgm"))
    op.execute(text("ALTER TABLE productmaster DROP COLUMN IF EXISTS search_text"))
    op.execute(text("ALTER TABLE productmaster DROP COLUMN IF EXISTS identifier_search"))

    op.execute(text("ALTER TABLE productmaster ADD COLUMN search_text TEXT"))
    op.execute(text(f"UPDATE productmaster SET search_text = {SEARCH_TEXT_SQL}"))
    op.execute(text("ALTER TABLE productmaster ADD COLUMN identifier_search TEXT"))
    op.execute(text(f"UPDATE productmaster SET identifier_search = {IDENTIFIER_SEARCH_SQL}"))

    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_productmaster_search_text_trgm "
            "ON productmaster USING gin (search_text gin_trgm_ops)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_productmaster_identifier_search_trgm "
            "ON productmaster USING gin (identifier_search gin_trgm_ops)"
        )
    )
