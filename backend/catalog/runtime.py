from __future__ import annotations

from pathlib import Path

from app.config import PROJECT_ROOT, Settings, get_settings
from catalog.excel_loader import load_catalog_records
from catalog.postgres_repository import PostgresCatalogRepository
from matching.models import ProductRecord

POSTGRES_CATALOG_SOURCES = frozenset({"postgresql", "postgres"})


def normalized_catalog_source(value: str | None) -> str:
    source = (value or "postgresql").strip().lower()
    if source in POSTGRES_CATALOG_SOURCES:
        return "postgresql"
    return source


def postgres_catalog_repository(settings: Settings | None = None) -> PostgresCatalogRepository:
    from app.db import get_engine

    config = settings or get_settings()
    return PostgresCatalogRepository(
        get_engine(),
        table=config.catalog_table,
        id_column=config.catalog_id_column,
        productcode_column=config.catalog_productcode_column,
        name_column=config.catalog_name_column,
        description_column=config.catalog_description_column,
        description2_column=config.catalog_description2_column,
        retrieval_limit=config.catalog_retrieval_limit,
    )


def load_runtime_catalog(settings: Settings | None = None) -> list[ProductRecord]:
    """Load catalog products for matching.

    PostgreSQL is the runtime source. Excel is only used when
    ``CATALOG_SOURCE=excel`` (tests / import compatibility).
    """
    config = settings or get_settings()
    source = normalized_catalog_source(config.catalog_source)
    if source == "excel":
        catalog_path = Path(config.catalog_excel_path)
        if not catalog_path.is_file():
            catalog_path = PROJECT_ROOT / "data" / "Atkorepartsfile.xlsx"
        return load_catalog_records(catalog_path)

    return postgres_catalog_repository(config).load_products()
