"""Add productmaster.search_text and a pg_trgm GIN index.

Revision ID: 20260827_0002
Revises: 20260821_0001
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260827_0002"
down_revision: Union[str, Sequence[str], None] = "20260821_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEARCH_TEXT_SQL = """
lower(
    concat_ws(
        ' ',
        CAST("Productcode" AS TEXT),
        name,
        description,
        description2
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
    if "search_text" not in columns:
        op.execute(text("ALTER TABLE productmaster ADD COLUMN search_text TEXT"))
    op.execute(text(f"UPDATE productmaster SET search_text = {SEARCH_TEXT_SQL}"))
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_productmaster_search_text_trgm "
            "ON productmaster USING gin (search_text gin_trgm_ops)"
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
    columns = {column["name"] for column in inspect(bind).get_columns("productmaster")}
    if "search_text" in columns:
        op.execute(text("ALTER TABLE productmaster DROP COLUMN search_text"))
