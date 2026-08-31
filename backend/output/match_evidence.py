from __future__ import annotations

from typing import Any, Mapping

from matching.productcode import productcode_as_text
from output.schema import STATUSES_WITH_PART_NUMBER


FIELD_ORDER = (
    ("productcode", "Productcode"),
    ("name", "name"),
    ("description", "description"),
    ("description2", "description2"),
)

MATCH_STATUSES = {
    "CONFIDENT_MATCH",
    "EXACT_MATCH",
    "HIGH_CONFIDENCE",
}


def _status_value(result: Any) -> str:
    status = getattr(result, "match_status", None)
    if status is None and isinstance(result, Mapping):
        status = result.get("match_status")
    return str(getattr(status, "value", status) or "")


def _scores_from_result(result: Any) -> dict[str, float]:
    breakdown = getattr(result, "match_breakdown", None)
    candidates = list(getattr(result, "candidates", None) or [])
    if breakdown is None and isinstance(result, Mapping):
        breakdown = result.get("match_breakdown")
        candidates = list(result.get("candidates") or [])
    if not candidates:
        # FinalMatchResult (the AI-adjudicated result) has no match_breakdown
        # or candidates attribute at all -- only candidate_details, a plain
        # dict per candidate. Without this fallback every field row silently
        # renders "No match" for any row that went through AI, even when the
        # underlying description/name score was strong.
        candidate_details = getattr(result, "candidate_details", None)
        if candidate_details is None and isinstance(result, Mapping):
            candidate_details = result.get("candidate_details")
        candidates = list(candidate_details or [])
    scores = {
        "productcode": float((breakdown or {}).get("productcode_score") or 0.0),
        "name": float((breakdown or {}).get("name_score") or 0.0),
        "description": float((breakdown or {}).get("description_score") or 0.0),
        "description2": float((breakdown or {}).get("description2_score") or 0.0),
    }
    if any(value > 0 for value in scores.values()):
        return scores
    if not candidates:
        return scores
    top = candidates[0]
    field_scores = top.field_scores if hasattr(top, "field_scores") else top.get("field_scores") or {}
    return {
        "productcode": float(field_scores.get("productcode") or 0.0),
        "name": float(field_scores.get("name") or 0.0),
        "description": float(field_scores.get("description") or 0.0),
        "description2": float(field_scores.get("description2") or 0.0),
    }


def field_contribution(score: float, *, match_type: str | None = None, field: str | None = None) -> dict[str, Any]:
    if field == "productcode" and match_type == "partial":
        return {"level": "partial", "label": "Partial match", "score": round(float(score), 2)}
    if field == "productcode" and match_type == "exact" and score >= 99.5:
        return {"level": "exact", "label": "Exact match", "score": round(float(score), 2)}
    if score >= 99.5:
        level, label = "exact", "Exact match"
    elif score >= 70.0:
        level, label = "strong", "Strong match"
    elif score >= 40.0:
        level, label = "partial", "Partial match"
    else:
        level, label = "none", "No match"
    return {"level": level, "label": label, "score": round(float(score), 2)}


def evidence_headline(
    *,
    status: str,
    part_number_match: bool,
    description_match: bool,
    scores: Mapping[str, Any],
) -> str:
    identifier_type = str(scores.get("identifier_match_type") or "")
    identifier_headline = str(scores.get("identifier_headline") or "")
    if str(scores.get("selection_type") or "") == "USER_SELECTED":
        return "User Selected Match"
    productcode = float(scores.get("productcode") or 0.0)
    second = scores.get("second_score")
    gap = scores.get("score_gap")
    competing = (
        status == "REVIEW_REQUIRED"
        and second is not None
        and (gap is None or float(gap) < 8.0)
        and productcode > 0
    )
    if competing or (
        status == "REVIEW_REQUIRED"
        and identifier_type in {"partial", "exact", "normalized_exact"}
        and second is not None
    ):
        return "Multiple possible Productcode matches"
    if identifier_type == "partial" or identifier_headline.startswith("Partial"):
        return "Partial Productcode / Name Match"
    if status == "REVIEW_REQUIRED":
        return "Multiple products have equivalent description matches"
    if status == "NO_MATCH":
        return "No sufficiently similar product found"
    name = float(scores.get("name") or 0.0)
    description = max(float(scores.get("description") or 0.0), float(scores.get("description2") or 0.0))
    exact_code = part_number_match or productcode >= 99.5
    strong_description = description_match or description >= 70.0
    if scores.get("abbrev_reason") and not exact_code and strong_description:
        return str(scores.get("abbrev_reason") or "Normalized Description Match")
    if exact_code and strong_description:
        return "Exact Productcode + Description Match"
    if exact_code or identifier_type in {"exact", "normalized_exact"}:
        return str(identifier_headline or "Exact Productcode Match")
    if strong_description:
        return "Description Match"
    if name >= 99.5:
        return "Exact name Match"
    if name >= 70.0:
        return "name Match"
    parts: list[str] = []
    if productcode >= 40.0:
        parts.append("Productcode")
    if name >= 40.0:
        parts.append("name")
    if description >= 40.0:
        parts.append("Description")
    if parts:
        return " + ".join(parts) + " Match"
    return "Catalog match"


def build_match_evidence(result: Any) -> dict[str, Any]:
    status = _status_value(result)
    if hasattr(result, "matched_part_number") and not isinstance(result, Mapping):
        part_number_match = bool(getattr(result, "part_number_match", False))
        description_match = bool(getattr(result, "description_match", False))
        matched_part = getattr(result, "matched_part_number", None)
        overall = getattr(result, "overall_match_score", None)
        if overall is None:
            if hasattr(result, "final_confidence"):
                # FinalMatchResult (AI path) has no matching_percentage field
                # and leaves overall_match_score unset whenever AI actually
                # ran. Mirror serialize_process_result's exact rule: only
                # "emit" statuses (a real part number was selected) use
                # final_confidence -- REVIEW_REQUIRED/NO_MATCH use the raw
                # deterministic_score, since final_confidence there is AI's
                # own confidence in *rejecting* the match, not a match score.
                emit = str(status).upper() in STATUSES_WITH_PART_NUMBER
                overall = (
                    getattr(result, "final_confidence", None)
                    if emit
                    else getattr(result, "deterministic_score", None)
                )
            if overall is None:
                overall = getattr(result, "matching_percentage", 0)
        reasons = list(getattr(result, "match_reasons", None) or [])
    else:
        part_number_match = bool(result.get("part_number_match"))
        description_match = bool(result.get("description_match"))
        matched_part = result.get("matched_part_number")
        overall = result.get("overall_match_score")
        if overall is None:
            if "final_confidence" in result:
                emit = str(status).upper() in STATUSES_WITH_PART_NUMBER
                overall = result.get("final_confidence") if emit else result.get("deterministic_score")
            if overall is None:
                overall = result.get("matching_percentage") or 0
        reasons = list(result.get("match_reasons") or [])
        if not reasons and result.get("match_reason"):
            reasons = [str(result.get("match_reason"))]

    scores = _scores_from_result(result)
    breakdown = getattr(result, "match_breakdown", None)
    if breakdown is None and isinstance(result, Mapping):
        breakdown = result.get("match_breakdown")
    if isinstance(breakdown, Mapping):
        scores = {
            **scores,
            "identifier_match_type": breakdown.get("identifier_match_type") or "",
            "identifier_headline": breakdown.get("identifier_headline") or "",
            "abbrev_reason": breakdown.get("abbrev_reason") or "",
        }
    scores = {
        **scores,
        "score_gap": getattr(result, "score_gap", None) if not isinstance(result, Mapping) else result.get("score_gap"),
        "second_score": getattr(result, "second_score", None)
        if not isinstance(result, Mapping)
        else result.get("second_score"),
        "selection_type": getattr(result, "selection_type", None)
        if not isinstance(result, Mapping)
        else result.get("selection_type"),
        "match_type_label": getattr(result, "match_type_label", None)
        if not isinstance(result, Mapping)
        else result.get("match_type_label"),
    }
    selected = status in MATCH_STATUSES and bool(matched_part)
    ident_type = str(scores.get("identifier_match_type") or "")
    fields = []
    for key, label in FIELD_ORDER:
        contribution = field_contribution(
            float(scores.get(key, 0.0) or 0.0),
            match_type=ident_type if key == "productcode" else None,
            field=key,
        )
        fields.append(
            {
                "field": label,
                "level": contribution["level"],
                "label": contribution["label"],
                "score": contribution["score"],
            }
        )
    ident_type = str(scores.get("identifier_match_type") or "")
    numeric_conflict = bool(
        isinstance(breakdown, Mapping) and breakdown.get("numeric_conflict")
    )
    numeric_label = "Conflict" if numeric_conflict else (
        "Match"
        if isinstance(breakdown, Mapping) and float(breakdown.get("numeric_unit_score") or 0) >= 100
        else "Not Found"
    )
    separation = "Ambiguous" if status == "REVIEW_REQUIRED" else (
        "Strong" if status in MATCH_STATUSES else "Ambiguous"
    )
    display_status = "MATCH" if status in MATCH_STATUSES else status
    return {
        "status_label": display_status,
        "matched_part_number": (productcode_as_text(matched_part) or None) if selected else None,
        "overall_percent": round(float(overall or 0.0), 2),
        "headline": evidence_headline(
            status=status,
            part_number_match=part_number_match,
            description_match=description_match,
            scores=scores,
        ),
        "fields": fields,
        "detail_reasons": reasons[:6],
        "matching_tokens": list((breakdown or {}).get("matching_tokens") or [])
        if isinstance(breakdown, Mapping)
        else [],
        "normalized_terms": list((breakdown or {}).get("normalized_terms") or [])
        if isinstance(breakdown, Mapping)
        else [],
        "voltage_evidence": list((breakdown or {}).get("voltage_evidence") or [])
        if isinstance(breakdown, Mapping)
        else [],
        "additional_catalog_tokens": list((breakdown or {}).get("additional_catalog_tokens") or [])
        if isinstance(breakdown, Mapping)
        else [],
        "numeric_units": numeric_label,
        "candidate_separation": separation,
        "productcode_match_type": ident_type or "none",
        "overall_decision": display_status if display_status == "MATCH" else status,
        "selection_type": scores.get("selection_type"),
        "match_type_label": scores.get("match_type_label"),
    }
