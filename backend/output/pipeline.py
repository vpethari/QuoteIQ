from __future__ import annotations

from pathlib import Path

from ai.models import FinalMatchResult
from ai.service import AIMatchingService
from matching.matcher import ProductMatcher
from matching.models import MatchResult
from output.csv_writer import render_csv_bytes, rows_from_results
from quotes.models import LineItem
from quotes.parse_diagnostics import start_parse_diagnostics
from quotes.parser import line_items_to_quote_lines, parse_quote_file
from quotes.pdf_parser import parse_pdf_quote_file

QuoteProcessResult = MatchResult | FinalMatchResult


def _parse_line_items(path: str | Path, source_name: str | None) -> list[LineItem]:
    start_parse_diagnostics()
    if Path(path).suffix.lower() == ".pdf":
        return parse_pdf_quote_file(path, source_name=source_name)
    return parse_quote_file(path, source_name=source_name)


def process_quote_results(
    path: str | Path,
    matcher: ProductMatcher,
    *,
    use_ai: bool = False,
    ai_service: AIMatchingService | None = None,
    source_name: str | None = None,
) -> list[QuoteProcessResult]:
    items = _parse_line_items(path, source_name)
    lines = line_items_to_quote_lines(items)
    if use_ai:
        if ai_service is None:
            raise ValueError("AI matching was requested but no AI service was provided.")
        return list(ai_service.match_quote(lines, use_ai=True))
    return list(matcher.match_quote(lines))


def process_quote_to_csv(
    path: str | Path,
    matcher: ProductMatcher,
    *,
    use_ai: bool = False,
    ai_service: AIMatchingService | None = None,
    source_name: str | None = None,
) -> bytes:
    results = process_quote_results(
        path,
        matcher,
        use_ai=use_ai,
        ai_service=ai_service,
        source_name=source_name,
    )
    return render_csv_bytes(rows_from_results(results))
