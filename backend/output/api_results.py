from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from output.match_evidence import build_match_evidence
from output.result_view import normalize_result
from output.rows import csv_confidence
from output.schema import STATUSES_WITH_PART_NUMBER
from output.pipeline import QuoteProcessResult


def _numeric_percentage(value: float) -> float | int:
    if abs(value - round(value)) < 1e-9:
        return int(round(value))
    return round(value, 2)


def _candidate_dict(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "score": _numeric_percentage(float(item.get("score") or 0))}


def serialize_process_result(result: QuoteProcessResult) -> dict[str, Any]:
    view = normalize_result(result)
    candidates = [_candidate_dict(item) for item in view.candidates]

    return {
        "source_row": view.source_row,
        "requested_part_number": view.requested_part_number,
        "requested_description": view.requested_description,
        "customer_raw_text": view.customer_raw_text,
        "detected_salsify_id": view.detected_salsify_id,
        "detected_part_number": view.detected_part_number,
        "quantity": view.quantity,
        "matched_part_number": view.matched_part_number,
        "matched_description": view.matched_description,
        "matched_salsify_id": view.matched_salsify_id,
        "matched_orderable_part_number": view.matched_orderable_part_number,
        "matching_percentage": _numeric_percentage(view.matching_percentage),
        "part_number_match_score": (
            None if view.part_number_match_score is None else _numeric_percentage(view.part_number_match_score)
        ),
        "description_match_score": (
            None if view.description_match_score is None else _numeric_percentage(view.description_match_score)
        ),
        "overall_match_score": _numeric_percentage(float(view.overall_match_score or 0)),
        "part_number_match": view.part_number_match,
        "description_match": view.description_match,
        "confidence": csv_confidence(view.match_status),
        "match_status": view.match_status,
        "match_reason": view.match_reason,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "match_evidence": build_match_evidence(result),
        "raw_row": dict(view.raw_row),
        "quote_line_id": view.quote_line_id,
        "original_confidence": view.original_confidence,
        "selection_type": view.selection_type,
        "match_type": view.match_type,
        "match_type_label": view.match_type_label,
    }


def summarize_results(payloads: Sequence[dict[str, Any]]) -> dict[str, int]:
    matched = 0
    review = 0
    no_match = 0
    for item in payloads:
        status = str(item.get("match_status") or "").upper()
        if status in STATUSES_WITH_PART_NUMBER:
            matched += 1
        elif status == "REVIEW_REQUIRED":
            review += 1
        elif status == "NO_MATCH":
            no_match += 1
    return {
        "total": len(payloads),
        "matched": matched,
        "review_required": review,
        "no_match": no_match,
    }
