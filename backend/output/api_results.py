from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ai.models import FinalMatchResult
from matching.models import MatchCandidate, MatchResult
from output.match_evidence import build_match_evidence
from output.rows import csv_confidence
from output.schema import STATUSES_WITH_PART_NUMBER
from output.pipeline import QuoteProcessResult


def _numeric_percentage(value: float) -> float | int:
    if abs(value - round(value)) < 1e-9:
        return int(round(value))
    return round(value, 2)


def _candidate_dict(item: MatchCandidate | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, MatchCandidate):
        return {
            "official_part_number": item.official_part_number,
            "description": item.description,
            "salsify_id": item.salsify_id,
            "score": _numeric_percentage(item.score),
            "match_reasons": list(item.match_reasons),
        }
    score = item.get("deterministic_score", item.get("score", 0))
    return {
        "official_part_number": item.get("official_part_number"),
        "description": item.get("description"),
        "salsify_id": item.get("salsify_id"),
        "score": _numeric_percentage(float(score or 0)),
        "match_reasons": list(item.get("match_reasons") or []),
    }


def serialize_process_result(result: QuoteProcessResult) -> dict[str, Any]:
    if isinstance(result, FinalMatchResult):
        status = result.match_status
        emit = status.upper() in STATUSES_WITH_PART_NUMBER
        percentage = result.final_confidence if emit else result.deterministic_score
        reason = result.reasoning_summary
        candidates = [_candidate_dict(item) for item in result.candidate_details]
        matched_part = result.matched_part_number if emit else None
        matched_description = result.matched_description if emit else None
        matched_salsify = result.matched_salsify_id if emit else None
        source_row = result.source_row
        requested = result.requested_description
        quantity = result.quantity
        requested_part_number = result.requested_part_number
        pn_score = result.part_number_match_score
        desc_score = result.description_match_score
        overall = result.overall_match_score if result.overall_match_score is not None else percentage
        pn_match = result.part_number_match
        desc_match = result.description_match
    else:
        status = result.match_status.value
        emit = status.upper() in STATUSES_WITH_PART_NUMBER
        percentage = result.matching_percentage
        reason = "; ".join(result.match_reasons)
        candidates = [_candidate_dict(item) for item in result.candidates]
        matched_part = result.matched_part_number if emit else None
        matched_description = result.matched_description if emit else None
        matched_salsify = result.matched_salsify_id if emit else None
        source_row = result.source_row
        requested = result.requested_description
        quantity = result.quantity
        requested_part_number = result.requested_part_number
        pn_score = result.part_number_match_score
        desc_score = result.description_match_score
        overall = result.overall_match_score if result.overall_match_score is not None else percentage
        pn_match = result.part_number_match
        desc_match = result.description_match

    return {
        "source_row": source_row,
        "requested_part_number": requested_part_number,
        "requested_description": requested,
        "customer_raw_text": getattr(result, "customer_raw_text", None) or requested,
        "detected_salsify_id": getattr(result, "detected_salsify_id", None),
        "detected_part_number": getattr(result, "detected_part_number", None),
        "quantity": quantity,
        "matched_part_number": matched_part,
        "matched_description": matched_description,
        "matched_salsify_id": matched_salsify,
        "matching_percentage": _numeric_percentage(float(overall or 0)),
        "part_number_match_score": None if pn_score is None else _numeric_percentage(float(pn_score)),
        "description_match_score": None if desc_score is None else _numeric_percentage(float(desc_score)),
        "overall_match_score": _numeric_percentage(float(overall or 0)),
        "part_number_match": pn_match,
        "description_match": desc_match,
        "confidence": csv_confidence(status),
        "match_status": status,
        "match_reason": reason,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "match_evidence": build_match_evidence(result),
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
