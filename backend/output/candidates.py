from __future__ import annotations

from typing import Any

from matching.models import MatchCandidate
from matching.productcode import productcode_as_text
from output.match_evidence import field_contribution


def _numeric(value: float) -> float | int:
    if abs(value - round(value)) < 1e-9:
        return int(round(value))
    return round(value, 2)


def candidate_match_reason(item: MatchCandidate | dict[str, Any]) -> str:
    if isinstance(item, MatchCandidate):
        reasons = list(item.match_reasons or [])
        evidence = item.identifier_evidence or {}
        headline = str(evidence.get("headline") or evidence.get("abbrev_reason") or "")
    else:
        reasons = list(item.get("match_reasons") or [])
        headline = str(item.get("match_reason") or "")
        evidence = item.get("identifier_evidence") or item.get("match_evidence") or {}
        if not headline and isinstance(evidence, dict):
            headline = str(evidence.get("headline") or "")
    if headline:
        return headline
    if reasons:
        return str(reasons[0])
    return "Catalog candidate"


def candidate_evidence(item: MatchCandidate | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, MatchCandidate):
        scores = item.field_scores or {}
        ident = str((item.identifier_evidence or {}).get("match_type") or "none")
        reasons = list(item.match_reasons or [])
    else:
        scores = dict(item.get("field_scores") or {})
        ident = str(item.get("productcode_match_type") or "none")
        evidence = item.get("identifier_evidence") or {}
        if isinstance(evidence, dict) and evidence.get("match_type"):
            ident = str(evidence.get("match_type"))
        reasons = list(item.get("match_reasons") or [])
    fields = []
    for key, label in (
        ("name", "Part Number"),
        ("description", "Part Description"),
        ("description2", "Catalog Description"),
    ):
        contribution = field_contribution(
            float(scores.get(key, 0.0) or 0.0),
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
    return {
        "productcode_match_type": ident or "none",
        "fields": fields,
        "detail_reasons": reasons[:4],
        "headline": candidate_match_reason(item),
    }


def candidate_api_dict(item: MatchCandidate | dict[str, Any], *, line_status: str) -> dict[str, Any]:
    if isinstance(item, MatchCandidate):
        code = productcode_as_text(item.official_part_number) or ""
        score = float(item.score)
        payload = {
            "rank": item.rank,
            "productcode": code,
            "official_part_number": code,
            "orderable_part_number": item.orderable_part_number,
            "name": item.name,
            "description": item.description,
            "description2": item.description2,
            "salsify_id": productcode_as_text(item.salsify_id) or "",
            "confidence": _numeric(score),
            "score": _numeric(score),
            "score_percentage": _numeric(float(item.score_percentage)),
            "match_status": line_status,
            "match_reason": candidate_match_reason(item),
            "match_reasons": list(item.match_reasons),
            "field_scores": dict(item.field_scores),
            "identifier_evidence": dict(item.identifier_evidence),
            "match_evidence": candidate_evidence(item),
        }
        return payload
    score = float(item.get("confidence", item.get("deterministic_score", item.get("score", 0))) or 0)
    code = productcode_as_text(item.get("productcode") or item.get("official_part_number")) or ""
    return {
        "rank": item.get("rank"),
        "productcode": code,
        "official_part_number": code,
        "orderable_part_number": item.get("orderable_part_number"),
        "name": item.get("name"),
        "description": item.get("description"),
        "description2": item.get("description2"),
        "salsify_id": productcode_as_text(item.get("salsify_id")) or "",
        "confidence": _numeric(score),
        "score": _numeric(score),
        "score_percentage": _numeric(float(item.get("score_percentage", score) or 0)),
        "match_status": item.get("match_status") or line_status,
        "match_reason": candidate_match_reason(item),
        "match_reasons": list(item.get("match_reasons") or []),
        "field_scores": dict(item.get("field_scores") or {}),
        "identifier_evidence": dict(item.get("identifier_evidence") or {}),
        "match_evidence": item.get("match_evidence") or candidate_evidence(item),
    }
