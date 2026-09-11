"""Add productmaster.preferredflag, used to rank a preferred catalog row
ahead of otherwise-comparable alternatives during matching.

Idempotent (IF NOT EXISTS): this column was already added manually to the
live database before this migration was written, so upgrade()/downgrade()
are safe to run against either a database that already has it or one that
doesn't.

Revision ID: 20260911_0006
Revises: 20260830_0005
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "20260911_0006"
down_revision: Union[str, Sequence[str], None] = "20260830_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    if "productmaster" not in inspect(bind).get_table_names():
        return
    op.execute(
        text(
            "ALTER TABLE productmaster ADD COLUMN IF NOT EXISTS preferredflag TEXT "
            "NOT NULL DEFAULT 'Not Preferred'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in {"postgresql", "postgres"}:
        return
    if "productmaster" not in inspect(bind).get_table_names():
        return
    op.execute(text("ALTER TABLE productmaster DROP COLUMN IF EXISTS preferredflag"))
