from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class CatalogVersion(Base):
    __tablename__ = "catalog_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_file_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    product_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    family_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    products: Mapped[list[Product]] = relationship(back_populates="catalog_version")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("record_type IN ('product', 'family')", name="ck_products_record_type"),
        UniqueConstraint(
            "catalog_version_id",
            "salsify_id",
            name="uq_products_version_salsify_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    salsify_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    official_part_number: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    catalog_number_and_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    record_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    catalog_version_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    catalog_version: Mapped[CatalogVersion] = relationship(back_populates="products")
