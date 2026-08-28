from __future__ import annotations

import time

from matching.request_text import interpret_customer_text


def _synthetic_keys(count: int, prefix: str) -> tuple[str, ...]:
    return tuple(f"{prefix}{index:06d}-W" for index in range(count))


def test_interpret_customer_text_scales_with_text_not_catalog_size() -> None:
    """Regression test: a large in-memory catalog must not make per-line
    identifier interpretation scale with catalog size. This previously
    compiled/scanned a fresh regex per known key per call, taking minutes
    per quote line once the catalog reached tens of thousands of products.
    """
    salsify_keys = _synthetic_keys(40_000, "SAL")
    official_keys = _synthetic_keys(40_000, "OFF")

    started = time.perf_counter()
    result = interpret_customer_text(
        "BRP 120 volts whip end extension cable",
        salsify_keys=salsify_keys,
        official_keys=official_keys,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, f"interpret_customer_text took {elapsed:.3f}s against an 80k-key catalog"
    assert result.has_description
    assert not result.has_identifier


def test_interpret_customer_text_still_finds_known_keys_at_scale() -> None:
    salsify_keys = _synthetic_keys(20_000, "SAL")
    official_keys = _synthetic_keys(20_000, "OFF") + ("B1EB5-W",)

    started = time.perf_counter()
    result = interpret_customer_text(
        "Need part B1EB5-W for the job",
        salsify_keys=salsify_keys,
        official_keys=official_keys,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    assert "B1EB5-W" in result.lookup_identifiers
    assert result.has_identifier
