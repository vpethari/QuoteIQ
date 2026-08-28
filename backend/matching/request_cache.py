"""Request-scoped candidate retrieval cache. Does not change matching rules."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from matching.noise import strip_quantity_and_noise
from matching.productcode import is_product_code_query, normalize_code_text
from matching.scoring_prep import PreparedText


@dataclass
class RequestCandidateCache:
    candidates: dict[str, tuple] = field(default_factory=dict)
    lookups: dict[str, tuple] = field(default_factory=dict)
    scored: dict[str, tuple] = field(default_factory=dict)
    prepared_text: dict[str, PreparedText] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    database_candidate_queries: int = 0


_CACHE: ContextVar[RequestCandidateCache | None] = ContextVar(
    "quoteiq_request_candidate_cache", default=None
)


def candidate_cache_key(query: str) -> str:
    """Key from existing retrieval normalization only."""
    from catalog.search_query import retrieval_search_string

    cleaned = strip_quantity_and_noise(query)
    if is_product_code_query(cleaned):
        return "code:" + normalize_code_text(cleaned)
    return "text:" + retrieval_search_string(cleaned)


def start_request_cache() -> RequestCandidateCache:
    cache = RequestCandidateCache()
    _CACHE.set(cache)
    return cache


def get_request_cache() -> RequestCandidateCache | None:
    return _CACHE.get()


def end_request_cache() -> RequestCandidateCache | None:
    cache = _CACHE.get()
    _CACHE.set(None)
    return cache
