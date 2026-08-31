"""EXPLAIN ANALYZE candidate retrieval against productmaster.search_text.

Usage from repo root:
  py backend/scripts/verify_search_text.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import reset_engine  # noqa: E402
from catalog.runtime import postgres_catalog_repository  # noqa: E402
from catalog.search_query import retrieval_search_string, retrieval_search_token_groups  # noqa: E402

SAMPLE_QUERY = "BRP 120 volts whip end extension cable"


def main() -> int:
    settings = get_settings()
    reset_engine()
    repository = postgres_catalog_repository(settings)
    if not repository.check_connection():
        print("PostgreSQL is not connected. Set DATABASE_URL.")
        return 1
    columns = repository.column_names()
    print(f"table={repository.table}")
    print(f"search_text_column={'search_text' in columns}")
    print(f"query={SAMPLE_QUERY!r}")
    token_groups = retrieval_search_token_groups(SAMPLE_QUERY)
    print(f"retrieval_token_groups={token_groups}")
    print(f"retrieval_string={retrieval_search_string(SAMPLE_QUERY)!r}")
    sql = repository.search_text_sql([len(group) for group in token_groups])
    print("candidate_retrieval_query=")
    print(sql)
    try:
        plan = repository.explain_search_text_candidates(SAMPLE_QUERY)
    except Exception as exc:
        print(f"EXPLAIN ANALYZE failed: {exc}")
        return 1
    print("explain_analyze=")
    print(plan)
    hits = repository.search_text_candidates(SAMPLE_QUERY)
    print(f"candidates_returned={len(hits)}")
    for item in hits[:10]:
        print(f"  Productcode={item.product_code!r} name={item.name!r} description={item.description!r}")
    index_used = "idx_productmaster_search_text_trgm" in plan.lower() or "search_text" in plan.lower()
    gin_or_bitmap = "idx_productmaster_search_text_trgm" in plan or "Bitmap Index Scan" in plan or "Index Scan" in plan
    print(f"index_mentioned={index_used}")
    print(f"index_or_bitmap_scan={gin_or_bitmap}")
    if "idx_productmaster_search_text_trgm" in plan:
        print("OK: EXPLAIN ANALYZE references idx_productmaster_search_text_trgm")
        return 0
    print("WARN: index name was not found in EXPLAIN ANALYZE output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
