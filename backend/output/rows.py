from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ai.models import FinalMatchResult
from matching.models import MatchCandidate, MatchResult
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


def format_top_candidates(
    candidates: Sequence[Mapping[str, Any]] | Sequence[MatchCandidate],
    limit: int = 5,
) -> str:
    parts: list[str] = []
    for item in list(candidates)[:limit]:
        if isinstance(item, MatchCandidate):
            part = item.official_part_number
            score = item.score
        else:
            part = str(item.get("official_part_number") or "")
            score = item.get("deterministic_score", item.get("score", ""))
        if not part:
            continue
        score_text = format_matching_percentage(float(score)) if score != "" else ""
        parts.append(f"{part} ({score_text})" if score_text != "" else part)
    return "; ".join(parts)


def _part_number_for_csv(status: str, part_number: str | None) -> str:
    if (status or "").upper() not in STATUSES_WITH_PART_NUMBER:
        return ""
    return part_number or ""


def csv_row_from_match_result(result: MatchResult) -> dict[str, str]:
    status = result.match_status.value
    reason = "; ".join(result.match_reasons)
    return {
        "Source File": result.source_file or "",
        "Source Sheet": result.source_sheet or "",
        "Source Row": "" if result.source_row is None else str(result.source_row),
        "Requested Description": result.requested_description,
        "Quantity": "" if result.quantity is None else str(result.quantity),
        "Matched Atkore Part Number": _part_number_for_csv(status, result.matched_part_number),
        "Matched Salsify ID": _part_number_for_csv(status, result.matched_salsify_id),
        "Matched Atkore Description": (
            (result.matched_description or "")
            if (status or "").upper() in STATUSES_WITH_PART_NUMBER
            else ""
        ),
        "Matching Percentage": format_matching_percentage(result.matching_percentage),
        "Confidence": csv_confidence(status),
        "Match Status": status,
        "Match Reason": reason,
        "Candidate Count": str(result.candidate_count),
        "Top Candidates": format_top_candidates(result.candidates),
        "Requested Part Number": result.requested_part_number or "",
        "Part Number Match %": format_optional_percentage(result.part_number_match_score),
        "Description Match %": format_optional_percentage(result.description_match_score),
        "Overall Match %": format_matching_percentage(
            result.overall_match_score if result.overall_match_score is not None else result.matching_percentage
        ),
    }


def csv_row_from_final_result(result: FinalMatchResult) -> dict[str, str]:
    status = result.match_status
    emit = status.upper() in STATUSES_WITH_PART_NUMBER
    percentage = (
        result.final_confidence
        if emit
        else result.deterministic_score
    )
    return {
        "Source File": result.source_file or "",
        "Source Sheet": result.source_sheet or "",
        "Source Row": "" if result.source_row is None else str(result.source_row),
        "Requested Description": result.requested_description,
        "Quantity": "" if result.quantity is None else str(result.quantity),
        "Matched Atkore Part Number": _part_number_for_csv(status, result.matched_part_number),
        "Matched Salsify ID": _part_number_for_csv(status, result.matched_salsify_id),
        "Matched Atkore Description": (result.matched_description or "") if emit else "",
        "Matching Percentage": format_matching_percentage(percentage),
        "Confidence": csv_confidence(status),
        "Match Status": status,
        "Match Reason": result.reasoning_summary or "",
        "Candidate Count": str(result.candidate_count),
        "Top Candidates": format_top_candidates(result.candidate_details),
        "Requested Part Number": result.requested_part_number or "",
        "Part Number Match %": format_optional_percentage(result.part_number_match_score),
        "Description Match %": format_optional_percentage(result.description_match_score),
        "Overall Match %": format_matching_percentage(
            result.overall_match_score if result.overall_match_score is not None else percentage
        ),
    }


def csv_row_from_mapping(payload: Mapping[str, Any]) -> dict[str, str]:
    status = str(payload.get("match_status") or "")
    emit = status.upper() in STATUSES_WITH_PART_NUMBER
    part = payload.get("matched_part_number") or payload.get("matched_atkore_part_number")
    description = payload.get("matched_description") or payload.get("matched_atkore_description")
    percentage = payload.get("matching_percentage")
    if percentage is None:
        percentage = payload.get("final_confidence", payload.get("deterministic_score", 0))
    candidates = payload.get("candidates") or payload.get("candidate_details") or []
    reasons = payload.get("match_reasons")
    if isinstance(reasons, list):
        reason_text = "; ".join(str(item) for item in reasons)
    else:
        reason_text = str(payload.get("reasoning_summary") or payload.get("match_reason") or "")
    count = payload.get("candidate_count", len(candidates) if isinstance(candidates, list) else 0)
    if "part_number_match_score" in payload:
        pn_score = payload.get("part_number_match_score")
        pn_text = format_optional_percentage(None if pn_score is None else float(pn_score))
    else:
        pn_text = "N/A"
    if "description_match_score" in payload:
        desc_score = payload.get("description_match_score")
        desc_text = format_optional_percentage(None if desc_score is None else float(desc_score))
    else:
        desc_text = format_matching_percentage(float(percentage or 0))
    if payload.get("overall_match_score") is None:
        overall_text = format_matching_percentage(float(percentage or 0))
    else:
        overall_text = format_matching_percentage(float(payload["overall_match_score"]))
    return {
        "Source File": str(payload.get("source_file") or ""),
        "Source Sheet": str(payload.get("source_sheet") or ""),
        "Source Row": "" if payload.get("source_row") is None else str(payload["source_row"]),
        "Requested Description": str(payload.get("requested_description") or ""),
        "Quantity": "" if payload.get("quantity") is None else str(payload.get("quantity")),
        "Matched Atkore Part Number": _part_number_for_csv(status, None if part is None else str(part)),
        "Matched Salsify ID": _part_number_for_csv(
            status,
            None if payload.get("matched_salsify_id") is None else str(payload.get("matched_salsify_id")),
        ),
        "Matched Atkore Description": (str(description) if emit and description else ""),
        "Matching Percentage": format_matching_percentage(float(percentage or 0)),
        "Confidence": csv_confidence(status),
        "Match Status": status,
        "Match Reason": reason_text,
        "Candidate Count": str(count),
        "Top Candidates": format_top_candidates(candidates if isinstance(candidates, list) else []),
        "Requested Part Number": str(payload.get("requested_part_number") or ""),
        "Part Number Match %": pn_text,
        "Description Match %": desc_text,
        "Overall Match %": overall_text,
    }
