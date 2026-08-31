from __future__ import annotations

import logging
from contextvars import ContextVar

logger = logging.getLogger("quoteiq.quotes")

_warnings: ContextVar[list[str] | None] = ContextVar("_parse_warnings", default=None)


def start_parse_diagnostics() -> None:
    """Reset the parse-warning collector for a new upload."""
    _warnings.set([])


def record_parse_warning(message: str) -> None:
    """Note a heuristic/fallback parsing decision.

    Input files are unpredictable (missing headers, repeated section labels,
    PDFs with no real column structure); rather than silently guessing, every
    fallback decision is logged server-side and surfaced back to the caller
    so it can be shown to the user instead of discovered later as a bad match.
    """
    logger.warning("quote parse fallback: %s", message)
    current = _warnings.get()
    if current is not None:
        current.append(message)


def collect_parse_warnings() -> list[str]:
    return list(_warnings.get() or [])
