from __future__ import annotations

from unittest.mock import MagicMock

from ai.provider import MockAIReasoningProvider
from ai.service import AIMatchingService, AIPolicyConfig, InMemoryAuditStore
from catalog.postgres_repository import product_from_postgres_row
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, QuoteLine
from matching.request_cache import candidate_cache_key, get_request_cache


def _line(text: str, row: int = 2) -> QuoteLine:
    return QuoteLine("quote.xlsx", "Sheet1", row, text, 1)


def _product():
    record = product_from_postgres_row(
        productcode="B1EB5-W",
        name="B1EB5-W",
        description="BRP 120V WHIP END EXT CBL",
        description2="BRP 120V WHIP END EXT CBL",
    )
    assert record is not None
    return record


def _rr(code: str, name: str):
    record = product_from_postgres_row(
        productcode=code,
        name=name,
        description=name,
        description2=None,
    )
    assert record is not None
    return record


def _search(hits: list) -> MagicMock:
    search = MagicMock()
    search.lookup_productcode.return_value = []
    search.fetch_identifier_candidates.return_value = hits
    search.search_text_candidates.return_value = []
    return search


def test_two_identical_b1eb5w_lines_retrieve_once() -> None:
    product = _product()
    search = _search([product])
    matcher = ProductMatcher([], catalog_search=search)
    results = matcher.match_quote([_line("B1EB5-W", 2), _line("B1EB5-W", 3)])
    assert search.fetch_identifier_candidates.call_count == 1
    assert [item.match_status for item in results] == [MatchStatus.EXACT_MATCH, MatchStatus.EXACT_MATCH]
    assert [item.matched_part_number for item in results] == ["B1EB5-W", "B1EB5-W"]


def test_three_identical_rr2ba_lines_retrieve_once() -> None:
    hits = [_rr("333478", "RR 2BA KL"), _rr("333479", "RR 2BA KR")]
    search = _search(hits)
    matcher = ProductMatcher([], catalog_search=search)
    results = matcher.match_quote([_line("RR2BA", row) for row in (2, 3, 4)])
    assert search.fetch_identifier_candidates.call_count == 1
    assert len(results) == 3
    assert all(item.match_status == MatchStatus.REVIEW_REQUIRED for item in results)
    assert all(item.matched_part_number is None for item in results)


def test_different_inputs_retrieve_twice() -> None:
    search = _search([_product()])
    matcher = ProductMatcher([], catalog_search=search)
    matcher.match_quote([_line("B1EB5-W"), _line("RR2BA")])
    assert search.fetch_identifier_candidates.call_count == 2


def test_case_equivalent_codes_share_existing_normalization_key() -> None:
    assert candidate_cache_key("B1EB5-W") == candidate_cache_key("b1eb5-w")
    assert candidate_cache_key("RR2BA") != candidate_cache_key("RR 2BA")
    search = _search([_product()])
    matcher = ProductMatcher([], catalog_search=search)
    matcher.match_quote([_line("B1EB5-W"), _line("b1eb5-w")])
    assert search.fetch_identifier_candidates.call_count == 1


def test_cache_does_not_leak_between_quote_requests() -> None:
    search = _search([_product()])
    matcher = ProductMatcher([], catalog_search=search)
    matcher.match_quote([_line("B1EB5-W")])
    matcher.match_quote([_line("B1EB5-W")])
    assert search.fetch_identifier_candidates.call_count == 2
    assert get_request_cache() is None


def test_ai_enabled_quote_shares_cache_across_concurrent_lines() -> None:
    """AIMatchingService.match_quote runs lines through a ThreadPoolExecutor;
    each worker must rebind the same cache instance (ContextVars are not
    inherited by new threads) for duplicate lines to still retrieve once.
    """
    hits = [_rr("333478", "RR 2BA KL"), _rr("333479", "RR 2BA KR")]
    search = _search(hits)
    matcher = ProductMatcher([], catalog_search=search)
    service = AIMatchingService(
        matcher=matcher,
        catalog=[],
        provider=MockAIReasoningProvider(),
        policy=AIPolicyConfig(max_concurrent_requests=4),
        audit_store=InMemoryAuditStore(),
    )
    lines = [_line("RR2BA", row) for row in (2, 3, 4, 5)]
    results = service.match_quote(lines, use_ai=True)
    assert len(results) == 4
    assert search.fetch_identifier_candidates.call_count == 1
    assert get_request_cache() is None
