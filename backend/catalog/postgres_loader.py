from __future__ import annotations

from sqlalchemy.engine import Engine

from catalog.postgres_repository import (
    PostgresCatalogRepository,
    product_from_postgres_row,
)

__all__ = ["PostgresCatalogRepository", "load_catalog_from_postgres", "product_from_postgres_row"]


def load_catalog_from_postgres(
    engine: Engine,
    *,
    table: str = "productmaster",
    id_column: str = "id",
    productcode_column: str = "Productcode",
    name_column: str = "name",
    description_column: str = "description",
    description2_column: str = "description2",
) -> list:
    return PostgresCatalogRepository(
        engine,
        table=table,
        id_column=id_column,
        productcode_column=productcode_column,
        name_column=name_column,
        description_column=description_column,
        description2_column=description2_column,
    ).load_products()
