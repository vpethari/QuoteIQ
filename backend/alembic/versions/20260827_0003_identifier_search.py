"""Add productmaster.identifier_search compact GIN index.

Revision ID: 20260827_0003
Revises: 20260827_0002
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260827_0003"
down_revision: Union[str, Sequence[str], None] = "20260827_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IDENTIFIER_SEARCH_SQL = """
lower(
    replace(
        replace(
            replace(
                concat_ws(
                    '',
                    CAST("Productcode" AS TEXT),
                    coalesce(name, ''),
                    coalesce(description, ''),
                    coalesce(description2, '')
                ),
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


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    tables = inspect(bind).get_table_names()
    if "productmaster" not in tables:
        return
    op.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    columns = {column["name"] for column in inspect(bind).get_columns("productmaster")}
    if "identifier_search" not in columns:
        op.execute(text("ALTER TABLE productmaster ADD COLUMN identifier_search TEXT"))
    op.execute(text(f"UPDATE productmaster SET identifier_search = {IDENTIFIER_SEARCH_SQL}"))
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
    op.execute(text("DROP INDEX IF EXISTS idx_productmaster_identifier_search_trgm"))
    columns = {column["name"] for column in inspect(bind).get_columns("productmaster")}
    if "identifier_search" in columns:
        op.execute(text("ALTER TABLE productmaster DROP COLUMN identifier_search"))
