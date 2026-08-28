"""Verify the existing Azure table ``productmaster``.

  SELECT "Productcode", name, description, description2
  FROM productmaster
  LIMIT 10;

Also confirms Productcode values B1EB5-W, 1MD12BZUZ115EB1, and 1MD06AZJZ040V1S.

Usage from repo root:

  py backend/scripts/verify_postgres_catalog.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import reset_engine  # noqa: E402
from catalog.postgres_repository import (  # noqa: E402
    product_from_postgres_row,
)
from catalog.runtime import normalized_catalog_source, postgres_catalog_repository  # noqa: E402

EXPECTED_CODES = ("B1EB5-W", "1MD12BZUZ115EB1", "1MD06AZJZ040V1S")


def main() -> int:
    settings = get_settings()
    reset_engine()
    source = normalized_catalog_source(settings.catalog_source)
    repository = postgres_catalog_repository(settings)
    connected = repository.check_connection()
    print(f"catalog_source={source}")
    print(f"database={'connected' if connected else 'disconnected'}")
    print(f"table={settings.catalog_table}")
    if not connected:
        print("PostgreSQL is not connected. Set DATABASE_URL.")
        return 1
    if settings.catalog_table != "productmaster":
        print("ERROR: CATALOG_TABLE must be productmaster.")
        return 1

    print(
        'SELECT "Productcode", name, description, description2 '
        "FROM productmaster LIMIT 10;"
    )
    sample = repository.fetch_sample_rows(limit=10)
    if not sample:
        print("No rows returned from productmaster.")
        return 1
    for row in sample:
        print(
            f"  Productcode={row.get('productcode')!r} "
            f"name={row.get('name')!r} description={row.get('description')!r} "
            f"description2={row.get('description2')!r}"
        )

    found = repository.fetch_by_productcodes(list(EXPECTED_CODES))
    found_codes = set()
    for row in found:
        for key in ("productcode", "name", "description", "description2"):
            value = row.get(key)
            if value is not None and str(value).strip():
                found_codes.add(str(value).strip())
        mapped = product_from_postgres_row(
            productcode=row.get("productcode"),
            name=row.get("name"),
            description=row.get("description"),
            description2=row.get("description2"),
        )
        if mapped is not None:
            found_codes.add(mapped.product_code)
            print(
                f"  lookup Productcode={row.get('productcode')!r} "
                f"name={row.get('name')!r} matched_part_number={mapped.product_code!r}"
            )
    print(f"lookup={sorted(found_codes)}")
    missing = [code for code in EXPECTED_CODES if code not in found_codes]
    if missing:
        print(f"ERROR: missing Productcode values: {missing}")
        return 1
    print("OK: productmaster sample and expected Productcode values were retrieved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
