"""Initial catalog_versions and products tables.

Revision ID: 20260821_0001
Revises:
Create Date: 2026-08-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260821_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("product_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("family_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("source_file_hash", name="uq_catalog_versions_source_file_hash"),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("salsify_id", sa.Text(), nullable=False),
        sa.Column("official_part_number", sa.Text(), nullable=True),
        sa.Column("catalog_number_and_description", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("record_type", sa.Text(), nullable=False),
        sa.Column("catalog_version_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["catalog_version_id"],
            ["catalog_versions.id"],
            name="fk_products_catalog_version_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "record_type IN ('product', 'family')",
            name="ck_products_record_type",
        ),
    )

    op.create_index("ix_products_official_part_number", "products", ["official_part_number"])
    op.create_index("ix_products_salsify_id", "products", ["salsify_id"])
    op.create_index("ix_products_description", "products", ["description"])
    op.create_index("ix_products_parent_id", "products", ["parent_id"])
    op.create_index("ix_products_record_type", "products", ["record_type"])
    op.create_index("ix_products_catalog_version_id", "products", ["catalog_version_id"])

    op.create_index(
        "uq_products_version_salsify_id",
        "products",
        ["catalog_version_id", "salsify_id"],
        unique=True,
    )
    op.create_index(
        "uq_products_version_official_part_number",
        "products",
        ["catalog_version_id", "official_part_number"],
        unique=True,
        postgresql_where=sa.text(
            "record_type = 'product' AND official_part_number IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_products_version_official_part_number", table_name="products")
    op.drop_index("uq_products_version_salsify_id", table_name="products")
    op.drop_index("ix_products_catalog_version_id", table_name="products")
    op.drop_index("ix_products_record_type", table_name="products")
    op.drop_index("ix_products_parent_id", table_name="products")
    op.drop_index("ix_products_description", table_name="products")
    op.drop_index("ix_products_salsify_id", table_name="products")
    op.drop_index("ix_products_official_part_number", table_name="products")
    op.drop_table("products")
    op.drop_table("catalog_versions")
