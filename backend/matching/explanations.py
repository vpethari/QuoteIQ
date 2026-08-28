from __future__ import annotations

from matching.description_normalize import catalog_unit_blob
from matching.models import ProductRecord, ScoreBreakdown
from matching.terminology import NORMALIZED_DESCRIPTION_REASON
from matching.units import compare_extracted_units, extract_amperages, extract_dimensions, extract_voltages
from matching.scoring_prep import PreparedText, prepare_scoring_text


def build_candidate_reasons(
    query: str,
    product: ProductRecord,
    breakdown: ScoreBreakdown,
    *,
    duplicate_description: bool,
    field_scores: dict[str, float] | None = None,
    matched_field: str | None = None,
    identifier_evidence: dict[str, object] | None = None,
    prep_cache: dict[str, PreparedText] | None = None,
    query_prep: PreparedText | None = None,
) -> list[str]:
    reasons: list[str] = []
    description = product.description or ""
    cache = prep_cache if prep_cache is not None else {}
    prepared_query = query_prep or prepare_scoring_text(query, cache)
    prepared_desc = prepare_scoring_text(description, cache)
    query_norm = prepared_query.normalized
    desc_norm = prepared_desc.normalized
    scores = field_scores or {}
    evidence = identifier_evidence or {}

    if evidence.get("headline") and float(scores.get("productcode") or evidence.get("score") or 0) > 0:
        reasons.append(str(evidence["headline"]))
    if evidence.get("matching_tokens") and float(scores.get("productcode") or evidence.get("score") or 0) > 0:
        reasons.append(
            "Matching tokens: " + ", ".join(str(item) for item in evidence["matching_tokens"])
        )
    if evidence.get("normalized_terms") and float(scores.get("productcode") or 0) < 40:
        reasons.append(str(evidence.get("abbrev_reason") or NORMALIZED_DESCRIPTION_REASON))
        reasons.append("Normalized terms: " + "; ".join(str(item) for item in evidence["normalized_terms"]))

    if matched_field:
        label = {
            "productcode": "Productcode",
            "name": "name",
            "description": "description",
            "description2": "description2",
        }.get(matched_field, matched_field)
        reasons.append(f"Strongest text evidence from {label}")

    if scores:
        reasons.append(
            "Productcode match: {productcode:.0f}; Name match: {name:.0f}; "
            "Description match: {description:.0f}; Description2 match: {description2:.0f}".format(
                productcode=scores.get("productcode", 0.0),
                name=scores.get("name", 0.0),
                description=scores.get("description", 0.0),
                description2=scores.get("description2", 0.0),
            )
        )

    if breakdown.exact >= 100.0:
        if query_norm == desc_norm:
            reasons.append("Exact normalized description match")
        else:
            reasons.append("Exact match after synonym/abbreviation normalization")
            reasons.append("Description differs only by abbreviation")

    if duplicate_description:
        reasons.append("Multiple Atkore products have the same description")

    query_attrs = prepared_query.attributes
    product_attrs = prepared_desc.attributes
    shared = query_attrs & product_attrs
    voltages = sorted(
        item.partition(":")[2] for item in shared if item.startswith("voltage:")
    )
    for voltage in voltages:
        reasons.append(f"Voltage matched: {voltage}")
    catalog_blob = catalog_unit_blob(product) or description
    unit_cmp = compare_extracted_units(
        prepared_query.volts,
        prepared_query.dims,
        extract_voltages(catalog_blob),
        extract_dimensions(catalog_blob),
        prepared_query.amps,
        extract_amperages(catalog_blob),
    )
    for line in unit_cmp.lines:
        reasons.append(line)

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
        overlap = sorted(prepared_query.token_set & prepared_desc.token_set)
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
