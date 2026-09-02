from __future__ import annotations

"""Confidence vs similarity: match decisions for QuoteIQ quoting.

Similarity (token/field overlap) is computed elsewhere. This module turns
field evidence into a confidence value and a MATCH / REVIEW_REQUIRED / NO_MATCH
decision. Exact Productcode identity is a special high-confidence case and is
not forced through the weighted average.
"""

from dataclasses import dataclass

from matching.models import MatchingConfig, MatchStatus
from matching.productcode import EXACT_IDENTITY_TYPES, IDENTITY_MATCH_TYPES
from matching.units import UnitComparison


def clamp_score(value: float) -> float:
    return round(min(100.0, max(0.0, value)), 4)

MATCH_STATUSES = {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}


@dataclass(frozen=True)
class ConfidenceBreakdown:
    confidence: float
    similarity: float
    productcode_score: float
    name_score: float
    description_score: float
    description2_score: float
    numeric_unit_score: float
    token_coverage_score: float
    productcode_match_type: str
    numeric_conflict: bool
    numeric_label: str
    weights_used: dict[str, float]


def numeric_unit_component(unit_cmp: UnitComparison) -> tuple[float | None, bool, str]:
    if (
        unit_cmp.voltage_status == "conflict"
        or unit_cmp.dimension_status == "conflict"
        or unit_cmp.amperage_status == "conflict"
    ):
        return 0.0, True, "Conflict"
    if (
        unit_cmp.voltage_status == "match"
        or unit_cmp.dimension_status == "match"
        or unit_cmp.amperage_status == "match"
    ):
        return 100.0, False, "Match"
    return None, False, "Not Found"


def _field_weights(config: MatchingConfig) -> dict[str, float]:
    return {
        "productcode": config.confidence_weight_productcode,
        "name": config.confidence_weight_name,
        "description": config.confidence_weight_description,
        "description2": config.confidence_weight_description2,
        "numeric": config.confidence_weight_numeric,
    }


def _renormalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {key: value / total for key, value in weights.items()}


def active_confidence_weights(
    *,
    ident_type: str,
    numeric_score: float | None,
    config: MatchingConfig,
    name_score: float | None = None,
) -> dict[str, float]:
    if ident_type not in IDENTITY_MATCH_TYPES:
        # Description-only search: `name` is tried first as a direct match
        # (it's the real orderable identifier); only when it doesn't score
        # well enough do description/description2 drive confidence instead.
        # Productcode is never part of this weighting -- it's internal-only,
        # and in this schema it's always the same value as `name` anyway
        # (see product_from_postgres_row), so it would just double-count.
        numeric_weight = config.confidence_weight_numeric if numeric_score is not None else 0.0
        remaining = 1.0 - numeric_weight
        direct_match = name_score is not None and name_score >= config.high_confidence_min
        if direct_match:
            weights = {"name": remaining, "numeric": numeric_weight}
        else:
            weights = {
                "description": remaining * 0.80,
                "description2": remaining * 0.20,
                "numeric": numeric_weight,
            }
        return _renormalize(weights)
    weights = _field_weights(config)
    if numeric_score is None:
        extra = weights.pop("numeric", 0.0)
        if "description" in weights:
            weights["description"] += extra * 0.60
        if "name" in weights:
            weights["name"] += extra * 0.40
        elif extra:
            weights["description"] = weights.get("description", 0.0) + extra
    return _renormalize(weights)


def combine_confidence(
    *,
    productcode_score: float,
    name_score: float,
    description_score: float,
    description2_score: float,
    numeric_score: float | None,
    ident_type: str,
    config: MatchingConfig,
) -> tuple[float, dict[str, float]]:
    if ident_type in EXACT_IDENTITY_TYPES:
        return 100.0, _field_weights(config)
    if ident_type not in IDENTITY_MATCH_TYPES and name_score >= config.high_confidence_min:
        # Name is a direct match -- that's the whole answer, no need to also
        # weigh description/description2/numeric in on top of it.
        return 100.0, {"name": 1.0}
    weights = active_confidence_weights(
        ident_type=ident_type,
        numeric_score=numeric_score,
        config=config,
        name_score=name_score,
    )
    numeric_value = 0.0 if numeric_score is None else numeric_score
    values = {
        "productcode": productcode_score,
        "name": name_score,
        "description": description_score,
        "description2": description2_score,
        "numeric": numeric_value,
    }
    total = 0.0
    for key, weight in weights.items():
        total += weight * values.get(key, 0.0)
    confidence = clamp_score(total)
    if ident_type == "partial":
        confidence = min(confidence, config.partial_match_max_confidence)
    return confidence, weights


def build_confidence_breakdown(
    *,
    field_scores: dict[str, float],
    token_coverage: float,
    unit_cmp: UnitComparison,
    ident_type: str,
    similarity: float,
    config: MatchingConfig,
) -> ConfidenceBreakdown:
    numeric_score, conflict, numeric_label = numeric_unit_component(unit_cmp)
    productcode_score = float(field_scores.get("productcode") or 0.0)
    name_score = float(field_scores.get("name") or 0.0)
    description_score = float(field_scores.get("description") or 0.0)
    description2_score = float(field_scores.get("description2") or 0.0)
    confidence, weights = combine_confidence(
        productcode_score=productcode_score,
        name_score=name_score,
        description_score=description_score,
        description2_score=description2_score,
        numeric_score=numeric_score,
        ident_type=ident_type,
        config=config,
    )
    if ident_type not in IDENTITY_MATCH_TYPES and not conflict:
        confidence = max(confidence, token_coverage)
    if conflict:
        cap = unit_cmp.score_cap if unit_cmp.score_cap is not None else config.numeric_conflict_cap
        confidence = min(confidence, cap, config.numeric_conflict_cap)
    return ConfidenceBreakdown(
        confidence=clamp_score(confidence),
        similarity=clamp_score(similarity),
        productcode_score=productcode_score,
        name_score=name_score,
        description_score=description_score,
        description2_score=description2_score,
        numeric_unit_score=0.0 if numeric_score is None else numeric_score,
        token_coverage_score=clamp_score(token_coverage),
        productcode_match_type=ident_type or "none",
        numeric_conflict=conflict,
        numeric_label=numeric_label,
        weights_used=weights,
    )


def competing_productcode_candidates(candidates: list) -> bool:
    """True when two Productcode identities share a prefix but differ in remaining tokens (KL vs KR)."""
    ident = [
        item
        for item in candidates
        if (item.identifier_evidence or {}).get("match_type") in IDENTITY_MATCH_TYPES
    ]
    if len(ident) < 2:
        return False
    first, second = ident[0], ident[1]
    if first.official_part_number == second.official_part_number:
        return False
    query_a = str((first.identifier_evidence or {}).get("query_compact") or "")
    query_b = str((second.identifier_evidence or {}).get("query_compact") or "")
    catalog_a = str((first.identifier_evidence or {}).get("catalog_compact") or "")
    catalog_b = str((second.identifier_evidence or {}).get("catalog_compact") or "")
    if query_a and catalog_a and catalog_b and query_a == query_b and catalog_a != catalog_b:
        if catalog_a.startswith(query_a) and catalog_b.startswith(query_a):
            return True
    extra_a = set((first.identifier_evidence or {}).get("additional_catalog_tokens") or [])
    extra_b = set((second.identifier_evidence or {}).get("additional_catalog_tokens") or [])
    if extra_a and extra_b and extra_a != extra_b:
        return True
    return False


def cap_confidence_for_decision(
    confidence: float,
    *,
    status: MatchStatus,
    competing: bool,
    config: MatchingConfig,
) -> float:
    value = confidence
    if competing or status == MatchStatus.REVIEW_REQUIRED:
        value = min(value, config.ambiguous_confidence_cap)
    return clamp_score(value)


def decide_match_status(
    *,
    top_score: float,
    second_score: float | None,
    score_gap: float | None,
    exact_unique: bool,
    duplicate_top: bool,
    candidate_count: int,
    config: MatchingConfig,
    ident_type: str = "none",
    competing_productcodes: bool = False,
    numeric_conflict: bool = False,
) -> MatchStatus:
    if candidate_count == 0:
        return MatchStatus.NO_MATCH
    if numeric_conflict and top_score < config.min_match_threshold:
        return MatchStatus.NO_MATCH
    if top_score < config.min_match_threshold and ident_type not in IDENTITY_MATCH_TYPES:
        return MatchStatus.NO_MATCH
    if top_score < config.min_match_threshold and ident_type == "partial":
        return MatchStatus.REVIEW_REQUIRED

    if competing_productcodes or duplicate_top:
        return MatchStatus.REVIEW_REQUIRED

    if exact_unique and ident_type in EXACT_IDENTITY_TYPES:
        return MatchStatus.EXACT_MATCH
    if exact_unique and top_score >= 99.0 and ident_type != "partial":
        return MatchStatus.EXACT_MATCH

    if ident_type == "partial":
        return MatchStatus.REVIEW_REQUIRED

    if numeric_conflict:
        return MatchStatus.REVIEW_REQUIRED if top_score >= config.min_match_threshold else MatchStatus.NO_MATCH

    ambiguous_gap = (
        second_score is not None
        and second_score >= config.min_match_threshold
        and (
            score_gap is None
            or score_gap <= config.score_tie_epsilon
            or score_gap < config.min_score_gap
        )
    )
    if ambiguous_gap:
        return MatchStatus.REVIEW_REQUIRED

    if top_score >= config.high_confidence_min:
        return MatchStatus.HIGH_CONFIDENCE
    if top_score >= config.min_match_threshold:
        return MatchStatus.REVIEW_REQUIRED
    return MatchStatus.NO_MATCH
