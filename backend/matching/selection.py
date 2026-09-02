from __future__ import annotations

from matching.models import MatchingConfig, MatchResult, MatchStatus
from matching.productcode import EXACT_IDENTITY_TYPES, productcode_as_text


AUTOMATIC = "AUTOMATIC"
USER_SELECTED = "USER_SELECTED"
MATCH_STATUSES = {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}


class SelectionError(ValueError):
    """Raised when a manual candidate selection cannot be applied."""


def make_quote_line_id(result: MatchResult) -> str:
    return "|".join(
        [
            result.source_file or "",
            result.source_sheet or "",
            "" if result.source_row is None else str(result.source_row),
            result.requested_description or "",
        ]
    )


def automatic_match_label(result: MatchResult) -> str:
    breakdown = result.match_breakdown or {}
    ident = str(breakdown.get("identifier_match_type") or "")
    if ident in EXACT_IDENTITY_TYPES or result.part_number_match:
        return "Automatic — Exact Productcode"
    if ident == "partial":
        return "Automatic — Partial Productcode"
    if result.description_match:
        return "Automatic — Description Match"
    return "Automatic"


def prepare_published_result(result: MatchResult, config: MatchingConfig | None = None) -> MatchResult:
    settings = config or MatchingConfig()
    result.quote_line_id = make_quote_line_id(result)
    original = result.overall_match_score
    if original is None:
        original = result.matching_percentage
    result.original_confidence = original
    if result.match_status == MatchStatus.NO_MATCH:
        result.candidates = []
    else:
        result.candidates = list(result.candidates)[: settings.review_candidate_limit]
        for index, candidate in enumerate(result.candidates, start=1):
            candidate.rank = index
    result.candidate_count = len(result.candidates)
    if result.match_status in MATCH_STATUSES:
        result.selection_type = AUTOMATIC
        result.match_type = AUTOMATIC
        result.match_type_label = automatic_match_label(result)
    return result


def _candidate_code(item: object) -> str:
    if hasattr(item, "official_part_number"):
        return productcode_as_text(getattr(item, "official_part_number")) or ""
    payload = item if isinstance(item, dict) else {}
    return productcode_as_text(
        payload.get("productcode") or payload.get("official_part_number")
    ) or ""


def apply_user_selection(result: MatchResult, productcode: str) -> MatchResult:
    if result.match_status != MatchStatus.REVIEW_REQUIRED:
        raise SelectionError("Only REVIEW_REQUIRED lines can be selected.")
    wanted = productcode_as_text(productcode)
    chosen = next((item for item in result.candidates if _candidate_code(item) == wanted), None)
    if chosen is None:
        raise SelectionError("Productcode is not in the candidate list.")
    original = result.original_confidence
    if original is None:
        original = result.overall_match_score if result.overall_match_score is not None else result.matching_percentage
    result.matched_part_number = wanted
    result.matched_description = chosen.description or chosen.name
    result.matched_salsify_id = chosen.salsify_id
    result.matched_orderable_part_number = chosen.orderable_part_number
    result.match_status = MatchStatus.HIGH_CONFIDENCE
    result.confidence_level = MatchStatus.HIGH_CONFIDENCE.value
    result.selection_type = USER_SELECTED
    result.match_type = USER_SELECTED
    result.match_type_label = "User Selected"
    result.original_confidence = original
    result.overall_match_score = original
    result.matching_percentage = float(original or 0.0)
    result.part_number_match = True
    result.match_reasons = list(
        dict.fromkeys([f"User selected Productcode {wanted}", *result.match_reasons])
    )
    return result


def apply_user_selection_payload(payload: dict, productcode: str, quote_line_id: str | None = None) -> dict:
    status = str(payload.get("match_status") or "")
    if status != MatchStatus.REVIEW_REQUIRED.value:
        raise SelectionError("Only REVIEW_REQUIRED lines can be selected.")
    line_id = str(payload.get("quote_line_id") or "")
    if quote_line_id and line_id and quote_line_id != line_id:
        raise SelectionError("quote_line_id does not match the supplied result.")
    wanted = productcode_as_text(productcode)
    chosen = next((item for item in payload.get("candidates") or [] if _candidate_code(item) == wanted), None)
    if chosen is None:
        raise SelectionError("Productcode is not in the candidate list.")
    original = payload.get("original_confidence")
    if original is None:
        original = payload.get("overall_match_score")
    if original is None:
        original = payload.get("matching_percentage")
    updated = dict(payload)
    description = chosen.get("description") or chosen.get("name")
    updated["matched_part_number"] = wanted
    updated["matched_description"] = description
    updated["matched_salsify_id"] = chosen.get("salsify_id")
    updated["matched_orderable_part_number"] = chosen.get("orderable_part_number")
    updated["match_status"] = MatchStatus.HIGH_CONFIDENCE.value
    updated["confidence_level"] = MatchStatus.HIGH_CONFIDENCE.value
    updated["confidence"] = "HIGH"
    updated["selection_type"] = USER_SELECTED
    updated["match_type"] = USER_SELECTED
    updated["match_type_label"] = "User Selected"
    updated["original_confidence"] = original
    updated["overall_match_score"] = original
    updated["matching_percentage"] = original
    updated["part_number_match"] = True
    existing_reason = str(payload.get("match_reason") or "")
    prefix = f"User selected Productcode {wanted}"
    updated["match_reason"] = prefix if not existing_reason else f"{prefix}; {existing_reason}"
    reasons = list(payload.get("match_reasons") or [])
    updated["match_reasons"] = list(dict.fromkeys([prefix, *reasons]))
    from output.match_evidence import build_match_evidence

    updated["match_evidence"] = build_match_evidence(updated)
    return updated
