"""Remove Productcode from the generated search_text / identifier_search columns.

productmaster.Productcode is an internal-only surrogate key; the real,
external orderable identifier is productmaster.name. Customers/external
agents never reference Productcode, so it should never be searchable --
leaving it in these columns meant a query could coincidentally "match" on
an internal number that means nothing to anyone using the tool. Both
columns now derive from name, description, and description2 only.

Revision ID: 20260830_0005
Revises: 20260829_0004
Create Date: 2026-08-30
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260830_0005"
down_revision: Union[str, Sequence[str], None] = "20260829_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Previous (0004) expressions, kept here only so downgrade() can restore them.
OLD_SEARCH_TEXT_SQL = """
lower(
    CAST("Productcode" AS TEXT)
    || CASE WHEN name IS NOT NULL THEN ' ' || name ELSE '' END
    || CASE WHEN description IS NOT NULL THEN ' ' || description ELSE '' END
    || CASE WHEN description2 IS NOT NULL THEN ' ' || description2 ELSE '' END
)
"""

OLD_IDENTIFIER_SEARCH_SQL = """
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

# New expressions: name, description, description2 only -- no Productcode.
SEARCH_TEXT_SQL = """
lower(
    coalesce(name, '')
    || CASE WHEN description IS NOT NULL THEN ' ' || description ELSE '' END
    || CASE WHEN description2 IS NOT NULL THEN ' ' || description2 ELSE '' END
)
"""

IDENTIFIER_SEARCH_SQL = """
lower(
    replace(
        replace(
            replace(
                coalesce(name, '')
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


def _rebuild(search_text_sql: str, identifier_search_sql: str) -> None:
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
        text(f"ALTER TABLE productmaster ADD COLUMN search_text TEXT GENERATED ALWAYS AS ({search_text_sql}) STORED")
    )
    op.execute(
        text(
            "ALTER TABLE productmaster ADD COLUMN identifier_search TEXT "
            f"GENERATED ALWAYS AS ({identifier_search_sql}) STORED"
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


def upgrade() -> None:
    _rebuild(SEARCH_TEXT_SQL, IDENTIFIER_SEARCH_SQL)


def downgrade() -> None:
    _rebuild(OLD_SEARCH_TEXT_SQL, OLD_IDENTIFIER_SEARCH_SQL)
