from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from output.schema import STATUSES_WITH_PART_NUMBER


@dataclass
class ResultView:
    """Canonical, serialization-ready view of one matched quote line.

    MatchResult (deterministic) and FinalMatchResult (AI-reasoned) are two
    separate, hand-maintained shapes, and a raw JSON dict (a result the
    frontend already holds, round-tripped back for a CSV re-download) is a
    third. Every consumer that turns a result into API JSON or a CSV row
    used to re-implement its own isinstance branch to read the "same"
    handful of fields from whichever of the three it got -- which is
    exactly how fields like match_type_label went missing on one path
    while working fine on another. normalize_result() below is the only
    place that still needs to know about that three-way split; everything
    else should read a ResultView instead.

    matched_part_number/description/salsify_id/orderable_part_number are
    already gated by match status here (None unless the status is one of
    STATUSES_WITH_PART_NUMBER) -- consumers don't need to re-check status
    themselves before displaying them.
    """

    source_file: str | None
    source_sheet: str | None
    source_row: int | None
    requested_description: str
    requested_part_number: str | None
    quantity: int | float | None
    match_status: str
    matched_part_number: str | None
    matched_description: str | None
    matched_salsify_id: str | None
    matched_orderable_part_number: str | None
    matching_percentage: float
    part_number_match_score: float | None
    description_match_score: float | None
    overall_match_score: float | None
    part_number_match: bool
    description_match: bool
    match_reason: str
    candidate_count: int
    candidates: list[dict[str, Any]]
    raw_row: dict[str, str]
    selection_type: str | None
    match_type: str | None
    match_type_label: str | None
    customer_raw_text: str | None
    detected_salsify_id: str | None
    detected_part_number: str | None
    quote_line_id: str | None
    original_confidence: float | None


def _shape_candidate(item: object) -> dict[str, Any]:
    """One candidate -> the plain-dict shape every consumer actually reads
    (official_part_number, orderable_part_number, description, salsify_id,
    score, match_reasons, name), regardless of whether it started life as a
    MatchCandidate or an already-serialized dict."""
    from matching.models import MatchCandidate

    if isinstance(item, MatchCandidate):
        return {
            "official_part_number": item.official_part_number,
            "orderable_part_number": item.orderable_part_number,
            "description": item.description,
            "salsify_id": item.salsify_id,
            "score": item.score,
            "match_reasons": list(item.match_reasons),
            "name": item.name,
        }
    if isinstance(item, Mapping):
        score = item.get("deterministic_score", item.get("score", 0))
        return {
            "official_part_number": item.get("official_part_number"),
            "orderable_part_number": item.get("orderable_part_number"),
            "description": item.get("description"),
            "salsify_id": item.get("salsify_id"),
            "score": score,
            "match_reasons": list(item.get("match_reasons") or []),
            "name": item.get("name"),
        }
    raise TypeError(f"Unsupported candidate type: {type(item)!r}")


def normalize_result(item: object) -> ResultView:
    from ai.models import FinalMatchResult
    from matching.models import MatchResult

    if isinstance(item, FinalMatchResult):
        status = item.match_status
        emit = status.upper() in STATUSES_WITH_PART_NUMBER
        percentage = item.final_confidence if emit else item.deterministic_score
        overall = item.overall_match_score if item.overall_match_score is not None else percentage
        return ResultView(
            source_file=item.source_file,
            source_sheet=item.source_sheet,
            source_row=item.source_row,
            requested_description=item.requested_description,
            requested_part_number=item.requested_part_number,
            quantity=item.quantity,
            match_status=status,
            matched_part_number=item.matched_part_number if emit else None,
            matched_description=item.matched_description if emit else None,
            matched_salsify_id=item.matched_salsify_id if emit else None,
            matched_orderable_part_number=item.matched_orderable_part_number if emit else None,
            matching_percentage=float(overall or 0),
            part_number_match_score=item.part_number_match_score,
            description_match_score=item.description_match_score,
            overall_match_score=overall,
            part_number_match=item.part_number_match,
            description_match=item.description_match,
            match_reason=item.reasoning_summary,
            candidate_count=len(item.candidate_details),
            candidates=[_shape_candidate(candidate) for candidate in item.candidate_details],
            raw_row=dict(item.raw_row or {}),
            selection_type=item.selection_type,
            match_type=item.match_type,
            match_type_label=item.match_type_label,
            customer_raw_text=item.customer_raw_text or item.requested_description,
            detected_salsify_id=item.detected_salsify_id,
            detected_part_number=item.detected_part_number,
            quote_line_id=item.quote_line_id,
            original_confidence=item.original_confidence,
        )
    if isinstance(item, MatchResult):
        status = item.match_status.value
        emit = status.upper() in STATUSES_WITH_PART_NUMBER
        overall = item.overall_match_score if item.overall_match_score is not None else item.matching_percentage
        return ResultView(
            source_file=item.source_file,
            source_sheet=item.source_sheet,
            source_row=item.source_row,
            requested_description=item.requested_description,
            requested_part_number=item.requested_part_number,
            quantity=item.quantity,
            match_status=status,
            matched_part_number=item.matched_part_number if emit else None,
            matched_description=item.matched_description if emit else None,
            matched_salsify_id=item.matched_salsify_id if emit else None,
            matched_orderable_part_number=item.matched_orderable_part_number if emit else None,
            matching_percentage=float(overall or 0),
            part_number_match_score=item.part_number_match_score,
            description_match_score=item.description_match_score,
            overall_match_score=overall,
            part_number_match=item.part_number_match,
            description_match=item.description_match,
            match_reason="; ".join(item.match_reasons),
            candidate_count=len(item.candidates),
            candidates=[_shape_candidate(candidate) for candidate in item.candidates],
            raw_row=dict(item.raw_row or {}),
            selection_type=item.selection_type,
            match_type=item.match_type,
            match_type_label=item.match_type_label,
            customer_raw_text=item.customer_raw_text or item.requested_description,
            detected_salsify_id=item.detected_salsify_id,
            detected_part_number=item.detected_part_number,
            quote_line_id=item.quote_line_id,
            original_confidence=item.original_confidence,
        )
    if isinstance(item, Mapping):
        status = str(item.get("match_status") or "")
        emit = status.upper() in STATUSES_WITH_PART_NUMBER
        percentage = item.get("matching_percentage")
        if percentage is None:
            percentage = item.get("final_confidence", item.get("deterministic_score", 0))
        overall = item.get("overall_match_score")
        overall = float(overall) if overall is not None else float(percentage or 0)
        candidates = item.get("candidates") or item.get("candidate_details") or []
        reasons = item.get("match_reasons")
        if isinstance(reasons, list):
            reason_text = "; ".join(str(entry) for entry in reasons)
        else:
            reason_text = str(item.get("reasoning_summary") or item.get("match_reason") or "")
        raw_row = item.get("raw_row") or {}
        requested = str(item.get("requested_description") or "")
        matched_part = item.get("matched_part_number")
        matched_description = item.get("matched_description") or item.get("matched_atkore_description")
        matched_salsify = item.get("matched_salsify_id")
        matched_orderable = item.get("matched_orderable_part_number")
        pn_score = item.get("part_number_match_score")
        desc_score = item.get("description_match_score")
        return ResultView(
            source_file=item.get("source_file"),
            source_sheet=item.get("source_sheet"),
            source_row=item.get("source_row"),
            requested_description=requested,
            requested_part_number=item.get("requested_part_number"),
            quantity=item.get("quantity"),
            match_status=status,
            matched_part_number=(str(matched_part) if matched_part else None) if emit else None,
            matched_description=(str(matched_description) if matched_description else None) if emit else None,
            matched_salsify_id=(str(matched_salsify) if matched_salsify else None) if emit else None,
            matched_orderable_part_number=(str(matched_orderable) if matched_orderable else None) if emit else None,
            matching_percentage=overall,
            part_number_match_score=None if pn_score is None else float(pn_score),
            description_match_score=None if desc_score is None else float(desc_score),
            overall_match_score=overall,
            part_number_match=bool(item.get("part_number_match")),
            description_match=bool(item.get("description_match")),
            match_reason=reason_text,
            candidate_count=int(item.get("candidate_count", len(candidates))),
            candidates=[_shape_candidate(candidate) for candidate in candidates],
            raw_row={str(key): value for key, value in raw_row.items()},
            selection_type=item.get("selection_type"),
            match_type=item.get("match_type"),
            match_type_label=item.get("match_type_label"),
            customer_raw_text=item.get("customer_raw_text") or requested,
            detected_salsify_id=item.get("detected_salsify_id"),
            detected_part_number=item.get("detected_part_number"),
            quote_line_id=item.get("quote_line_id"),
            original_confidence=item.get("original_confidence"),
        )
    raise TypeError(f"Unsupported result type: {type(item)!r}")
