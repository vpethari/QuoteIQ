from __future__ import annotations

from matching.attributes import extract_attributes
from matching.models import MatchCandidate, ProductRecord, ScoreBreakdown
from matching.normalizer import canonical_text, normalize_text
from matching.tokenizer import tokenize_description


def build_candidate_reasons(
    query: str,
    product: ProductRecord,
    breakdown: ScoreBreakdown,
    *,
    duplicate_description: bool,
) -> list[str]:
    reasons: list[str] = []
    description = product.description or ""
    query_norm = normalize_text(query)
    desc_norm = normalize_text(description)
    query_canon = canonical_text(query)
    desc_canon = canonical_text(description)

    if breakdown.exact >= 100.0:
        if query_norm == desc_norm:
            reasons.append("Exact normalized description match")
        else:
            reasons.append("Exact match after synonym/abbreviation normalization")
            reasons.append("Description differs only by abbreviation")

    if duplicate_description:
        reasons.append("Multiple Atkore products have the same description")

    query_attrs = extract_attributes(query)
    product_attrs = extract_attributes(description)
    shared = query_attrs & product_attrs
    voltages = sorted(
        item.partition(":")[2] for item in shared if item.startswith("voltage:")
    )
    for voltage in voltages:
        reasons.append(f"Voltage matched: {voltage}")

    phrases = sorted(
        item.partition(":")[2] for item in shared if item.startswith("phrase:")
    )
    for phrase in phrases:
        reasons.append(f"Product type matched: {phrase}")

    notable_tokens = sorted(
        item.partition(":")[2]
        for item in shared
        if item.startswith("token:")
        and item.partition(":")[2] in {"MOLEX", "PAULEX", "DBL", "EXT", "DIST", "HEAD", "END", "WHIP", "CABLE", "SWITCH", "MODULE", "LIGHTING"}
    )
    for token in notable_tokens:
        reasons.append(f"{token} attribute matched")

    sizes = sorted(item.partition(":")[2] for item in shared if item.startswith("size:"))
    for size in sizes:
        reasons.append(f"Size matched: {size}")

    if breakdown.token > 0:
        overlap = sorted(set(tokenize_description(query)) & set(tokenize_description(description)))
        if overlap and breakdown.exact < 100.0:
            preview = ", ".join(overlap[:6])
            reasons.append(f"Shared tokens: {preview}")

    if breakdown.fuzzy > 0 and breakdown.exact < 100.0:
        reasons.append(f"Character similarity {breakdown.fuzzy:.1f}%")

    if not reasons:
        reasons.append("Partial description similarity")
    return _dedupe(reasons)


def build_result_reasons(
    *,
    match_status: str,
    exact_unique: bool,
    duplicate_top: bool,
    top_score: float,
    score_gap: float | None,
    min_score_gap: float,
    min_match_threshold: float,
    candidate_count: int,
) -> list[str]:
    reasons: list[str] = []
    if match_status == "EXACT_MATCH":
        reasons.append("Unique exact normalized description match")
    elif match_status == "HIGH_CONFIDENCE":
        reasons.append("Top candidate is above the high-confidence threshold")
        if score_gap is not None:
            reasons.append(f"Score gap {score_gap:.2f} is large enough to select a winner")
    elif match_status == "REVIEW_REQUIRED":
        if duplicate_top:
            reasons.append("Multiple Atkore products have the same description")
            reasons.append("Insufficient information to choose a single part number")
        elif score_gap is not None and score_gap < min_score_gap:
            reasons.append(
                f"Score gap {score_gap:.2f} is below the configured separation {min_score_gap:.2f}"
            )
        else:
            reasons.append("Good candidates exist but a unique winner was not established")
    elif match_status == "NO_MATCH":
        if candidate_count == 0:
            reasons.append("No catalog product reached the candidate floor")
        else:
            reasons.append(
                f"Top score {top_score:.2f} is below the minimum match threshold {min_match_threshold:.2f}"
            )
    if exact_unique:
        reasons.append("Exactly one product shares this normalized description")
    return _dedupe(reasons)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
