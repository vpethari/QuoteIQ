from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ai.models import FinalMatchResult
from matching.models import MatchResult
from output.result_view import ResultView, normalize_result
from output.schema import STATUSES_WITH_PART_NUMBER


def format_matching_percentage(value: float | int | None) -> str:
    if value is None:
        return ""
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return text


def format_optional_percentage(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    return format_matching_percentage(value)


def csv_confidence(match_status: str) -> str:
    status = (match_status or "").upper()
    if status in {"CONFIDENT_MATCH", "EXACT_MATCH", "HIGH_CONFIDENCE"}:
        return "HIGH"
    if status == "REVIEW_REQUIRED":
        return "REVIEW"
    if status == "NO_MATCH":
        return "LOW"
    return "MEDIUM"


def format_top_candidates(candidates: Sequence[Mapping[str, Any]], limit: int = 5) -> str:
    parts: list[str] = []
    for item in list(candidates)[:limit]:
        part = str(item.get("official_part_number") or "")
        score = item.get("deterministic_score", item.get("score", ""))
        if not part:
            continue
        score_text = format_matching_percentage(float(score)) if score != "" else ""
        parts.append(f"{part} ({score_text})" if score_text != "" else part)
    return "; ".join(parts)


def csv_row_from_result(item: object) -> dict[str, str]:
    """The CSV_COLUMNS row for any of the three result shapes (MatchResult,
    FinalMatchResult, or an already-serialized JSON payload dict) --
    csv_row_from_match_result/csv_row_from_final_result/csv_row_from_mapping
    below are thin, type-specific wrappers around this single
    implementation, kept for existing call sites that already know which
    shape they have."""
    view: ResultView = normalize_result(item)
    return {
        "Source File": view.source_file or "",
        "Source Sheet": view.source_sheet or "",
        "Source Row": "" if view.source_row is None else str(view.source_row),
        "Requested Description": view.requested_description,
        "Quantity": "" if view.quantity is None else str(view.quantity),
        "Matched Atkore Part Number": view.matched_part_number or "",
        "Matched Salsify ID": view.matched_salsify_id or "",
        "Matched Atkore Description": view.matched_description or "",
        "Matching Percentage": format_matching_percentage(view.matching_percentage),
        "Confidence": csv_confidence(view.match_status),
        "Match Status": view.match_status,
        "Match Reason": view.match_reason,
        "Candidate Count": str(view.candidate_count),
        "Top Candidates": format_top_candidates(view.candidates),
        "Requested Part Number": view.requested_part_number or "",
        "Part Number Match %": format_optional_percentage(view.part_number_match_score),
        "Description Match %": format_optional_percentage(view.description_match_score),
        "Overall Match %": format_matching_percentage(view.overall_match_score),
    }


def csv_row_from_match_result(result: MatchResult) -> dict[str, str]:
    return csv_row_from_result(result)


def csv_row_from_final_result(result: FinalMatchResult) -> dict[str, str]:
    return csv_row_from_result(result)


def csv_row_from_mapping(payload: Mapping[str, Any]) -> dict[str, str]:
    return csv_row_from_result(payload)
