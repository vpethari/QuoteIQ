from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher
from time import perf_counter

from matching.attributes import extract_attributes
from matching.category_defaults import (
    candidate_color_conflicts,
    default_color_for_query,
    mentions_no_spring,
    mentions_stainless,
    unrequested_specialty_marker,
    wants_spring_nut,
)
from matching.models import MatchingConfig, ProductRecord, ScoreBreakdown
from matching.productcode import (
    EXACT_IDENTITY_TYPES,
    IDENTITY_MATCH_TYPES,
    field_is_code_like,
    score_product_code_identifier,
)
from matching.description_normalize import catalog_unit_blob, tokenize_description
from matching.units import compare_extracted_units, extract_amperages, extract_dimensions, extract_voltages
from matching.confidence import build_confidence_breakdown
from matching.request_cache import get_request_cache
from matching.scoring_prep import PreparedText, prepare_scoring_text
from matching.timing_diag import _ms, active


def clamp_score(value: float) -> float:
    return round(min(100.0, max(0.0, value)), 4)


def _prep_cache(explicit: dict[str, PreparedText] | None) -> dict[str, PreparedText]:
    if explicit is not None:
        return explicit
    request = get_request_cache()
    if request is not None:
        return request.prepared_text
    return {}


def _acc(session, field: str, started: float | None) -> None:
    if session is None or started is None:
        return
    session.add(**{field: _ms(perf_counter() - started)})


def _exact_prepared(query: PreparedText, candidate: PreparedText) -> float:
    if query.token_set and query.token_set == candidate.token_set:
        return 100.0
    if query.canonical and query.canonical == candidate.canonical:
        return 100.0
    if query.normalized and query.normalized == candidate.normalized:
        return 100.0
    return 0.0


def _token_prepared(query: PreparedText, candidate: PreparedText) -> float:
    """Order-independent token overlap. Query coverage is weighted higher than extra catalog tokens."""
    if not query.token_set or not candidate.token_set:
        return 0.0
    overlap = len(query.token_set & candidate.token_set)
    query_coverage = overlap / len(query.token_set)
    catalog_coverage = overlap / len(candidate.token_set)
    return clamp_score((0.75 * query_coverage + 0.25 * catalog_coverage) * 100.0)


def _fuzzy_prepared(query: PreparedText, candidate: PreparedText) -> float:
    session = active()
    if session is not None:
        session.add(fuzzy_calls=1)
    left = query.canonical or query.normalized
    right = candidate.canonical or candidate.normalized
    if not left or not right:
        return 0.0
    started = perf_counter() if session is not None else None
    ratio = SequenceMatcher(None, left, right).ratio()
    _acc(session, "score_fuzzy_ms", started)
    return clamp_score(ratio * 100.0)


def _attribute_prepared(query: PreparedText, candidate: PreparedText) -> float:
    query_attrs = query.attributes
    candidate_attrs = candidate.attributes
    if not query_attrs or not candidate_attrs:
        return 0.0
    overlap = len(query_attrs & candidate_attrs)
    union = len(query_attrs | candidate_attrs)
    if union == 0:
        return 0.0
    return clamp_score((overlap / union) * 100.0)


def calculate_exact_score(query: str, candidate_description: str) -> float:
    cache = _prep_cache(None)
    return _exact_prepared(
        prepare_scoring_text(query, cache),
        prepare_scoring_text(candidate_description, cache),
    )


def calculate_token_score(query: str, candidate_description: str) -> float:
    """Order-independent token overlap. Query coverage is weighted higher than extra catalog tokens."""
    cache = _prep_cache(None)
    return _token_prepared(
        prepare_scoring_text(query, cache),
        prepare_scoring_text(candidate_description, cache),
    )


def calculate_fuzzy_score(query: str, candidate_description: str) -> float:
    cache = _prep_cache(None)
    return _fuzzy_prepared(
        prepare_scoring_text(query, cache),
        prepare_scoring_text(candidate_description, cache),
    )


def calculate_final_score(
    exact: float,
    token: float,
    fuzzy: float,
    attribute: float,
    config: MatchingConfig | None = None,
) -> float:
    settings = config or MatchingConfig()
    combined = (
        settings.weight_exact * exact
        + settings.weight_token * token
        + settings.weight_fuzzy * fuzzy
        + settings.weight_attribute * attribute
    )
    token_primary = 0.70 * token + 0.15 * attribute + 0.10 * fuzzy + 0.05 * exact
    return clamp_score(max(combined, token_primary))


def calculate_attribute_score(query: str, candidate_description: str) -> float:
    cache = _prep_cache(None)
    return _attribute_prepared(
        prepare_scoring_text(query, cache),
        prepare_scoring_text(candidate_description, cache),
    )


def score_pair_prepared(
    query: PreparedText,
    candidate: PreparedText,
    config: MatchingConfig | None = None,
) -> ScoreBreakdown:
    session = active()
    if session is not None:
        session.add(score_pair_calls=1)
    started = perf_counter() if session is not None else None
    exact = _exact_prepared(query, candidate)
    _acc(session, "score_exact_ms", started)
    started = perf_counter() if session is not None else None
    token = _token_prepared(query, candidate)
    _acc(session, "score_token_ms", started)
    fuzzy = _fuzzy_prepared(query, candidate)
    started = perf_counter() if session is not None else None
    attribute = _attribute_prepared(query, candidate)
    _acc(session, "score_attr_ms", started)
    started = perf_counter() if session is not None else None
    final = calculate_final_score(exact, token, fuzzy, attribute, config)
    _acc(session, "score_agg_ms", started)
    return ScoreBreakdown(
        exact=exact,
        token=token,
        fuzzy=fuzzy,
        attribute=attribute,
        final=final,
    )


def score_pair(
    query: str,
    candidate_description: str,
    config: MatchingConfig | None = None,
    *,
    prep_cache: dict[str, PreparedText] | None = None,
    query_prep: PreparedText | None = None,
) -> ScoreBreakdown:
    cache = _prep_cache(prep_cache)
    prepared_query = query_prep or prepare_scoring_text(query, cache)
    prepared_candidate = prepare_scoring_text(candidate_description, cache)
    return score_pair_prepared(prepared_query, prepared_candidate, config)


TEXT_FIELD_WEIGHTS = {
    "productcode": 0.40,
    "name": 0.20,
    "description": 0.25,
    "description2": 0.15,
}

IDENTITY_WEIGHT = 0.70
NAME_SUPPORT_WEIGHT = 0.15
DESCRIPTION_SUPPORT_WEIGHT = 0.10
DESCRIPTION2_SUPPORT_WEIGHT = 0.05


def catalog_text_fields(product: ProductRecord) -> dict[str, str]:
    return {
        "productcode": product.product_code,
        "name": (product.name or "").strip(),
        "description": (product.description or "").strip(),
        "description2": (product.description2 or "").strip(),
    }


def combine_identification_confidence(
    identifier_score: float,
    text_scores: dict[str, float],
) -> float:
    """Productcode identity dominates; name/description only support."""
    return clamp_score(
        IDENTITY_WEIGHT * identifier_score
        + NAME_SUPPORT_WEIGHT * text_scores.get("name", 0.0)
        + DESCRIPTION_SUPPORT_WEIGHT * text_scores.get("description", 0.0)
        + DESCRIPTION2_SUPPORT_WEIGHT * text_scores.get("description2", 0.0)
    )


def score_product_fields(
    query: str,
    product: ProductRecord,
    config: MatchingConfig | None = None,
    *,
    prep_cache: dict[str, PreparedText] | None = None,
    query_prep: PreparedText | None = None,
) -> tuple[ScoreBreakdown, dict[str, float], str | None, dict[str, object]]:
    """Score identity separately from supporting name/description text."""
    settings = config or MatchingConfig()
    cache = _prep_cache(prep_cache)
    prepared_query = query_prep or prepare_scoring_text(query, cache)
    fields = catalog_text_fields(product)
    text_scores: dict[str, float] = {}
    breakdowns: dict[str, ScoreBreakdown] = {}
    identifier_evidence: dict[str, object] = {}
    best_ident = 0.0
    best_ident_field: str | None = None
    name_is_code = field_is_code_like(fields.get("name"))
    for name, value in fields.items():
        pair = (
            score_pair(query, value, settings, prep_cache=cache, query_prep=prepared_query)
            if value
            else ScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0)
        )
        text_scores[name] = pair.final
        breakdowns[name] = pair
        ident_score, evidence = 0.0, {}
        use_identifier = False
        if value and name == "productcode":
            use_identifier = True
        elif value and name == "name" and field_is_code_like(value):
            use_identifier = True
        elif value and name in {"description", "description2"} and field_is_code_like(value) and not name_is_code:
            use_identifier = True
        if use_identifier:
            session = active()
            started = perf_counter() if session is not None else None
            ident_score, evidence = score_product_code_identifier(query, value)
            _acc(session, "score_ident_ms", started)
        if evidence.get("match_type") in IDENTITY_MATCH_TYPES and ident_score >= best_ident:
            best_ident = ident_score
            best_ident_field = name
            identifier_evidence = {**evidence, "source_field": name}

    ident_type = str(identifier_evidence.get("match_type") or "none")
    field_scores = dict(text_scores)
    blob = " ".join(value for key, value in fields.items() if key != "productcode" and value)
    combined = (
        score_pair(query, blob, settings, prep_cache=cache, query_prep=prepared_query)
        if blob
        else ScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0)
    )
    session = active()
    started = perf_counter() if session is not None else None
    catalog_blob = catalog_unit_blob(product)
    unit_cmp = compare_extracted_units(
        prepared_query.volts,
        prepared_query.dims,
        extract_voltages(catalog_blob),
        extract_dimensions(catalog_blob),
        prepared_query.amps,
        extract_amperages(catalog_blob),
    )
    _acc(session, "score_units_ms", started)
    token_coverage = combined.token
    similarity = max(field_scores.values(), default=0.0)

    if ident_type in IDENTITY_MATCH_TYPES:
        field_scores["productcode"] = max(field_scores.get("productcode", 0.0), best_ident)
        if best_ident_field and best_ident_field != "productcode":
            field_scores[best_ident_field] = max(field_scores.get(best_ident_field, 0.0), best_ident)
        if ident_type in EXACT_IDENTITY_TYPES:
            overall = 100.0
            merged = ScoreBreakdown(100.0, 100.0, 100.0, 0.0, overall)
        else:
            winner = breakdowns.get(best_ident_field or "productcode", ScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0))
            confidence = build_confidence_breakdown(
                field_scores=field_scores,
                token_coverage=max(winner.token, combined.token),
                unit_cmp=unit_cmp,
                ident_type=ident_type,
                similarity=max(similarity, best_ident),
                config=settings,
            )
            overall = confidence.confidence
            merged = ScoreBreakdown(
                exact=winner.exact,
                token=max(winner.token, best_ident),
                fuzzy=max(winner.fuzzy, best_ident * 0.9),
                attribute=winner.attribute,
                final=overall,
            )
        matched_field = "productcode" if field_scores.get("productcode", 0.0) > 0 else best_ident_field
        identifier_evidence = {
            **identifier_evidence,
            "unit_evidence": {
                "voltage_status": unit_cmp.voltage_status,
                "dimension_status": unit_cmp.dimension_status,
                "amperage_status": unit_cmp.amperage_status,
                "lines": list(unit_cmp.lines),
                "mismatch_reasons": list(unit_cmp.mismatch_reasons),
            },
            "token_coverage_score": token_coverage,
            "numeric_unit_score": 0.0
            if unit_cmp.voltage_status == "none"
            and unit_cmp.dimension_status == "none"
            and unit_cmp.amperage_status == "none"
            else (0.0 if unit_cmp.score_cap else 100.0),
            "numeric_conflict": bool(unit_cmp.score_cap),
            "similarity_score": similarity,
        }
        return merged, field_scores, matched_field, identifier_evidence

    weighted = sum(TEXT_FIELD_WEIGHTS[name] * field_scores[name] for name in TEXT_FIELD_WEIGHTS)
    best_name = max(field_scores, key=lambda item: field_scores[item])
    best_final = max(field_scores.values(), default=0.0)
    winner = breakdowns.get(best_name, ScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0))
    similarity = clamp_score(max(best_final, combined.final, weighted))
    confidence = build_confidence_breakdown(
        field_scores=field_scores,
        token_coverage=max(winner.token, combined.token),
        unit_cmp=unit_cmp,
        ident_type="none",
        similarity=similarity,
        config=settings,
    )
    overall = confidence.confidence
    merged = ScoreBreakdown(
        exact=winner.exact,
        token=max(winner.token, combined.token),
        fuzzy=max(winner.fuzzy, combined.fuzzy),
        attribute=max(winner.attribute, combined.attribute),
        final=overall,
    )
    matched_field = best_name if best_final > 0 else None
    identifier_evidence = {
        **identifier_evidence,
        "unit_evidence": {
            "voltage_status": unit_cmp.voltage_status,
            "dimension_status": unit_cmp.dimension_status,
            "amperage_status": unit_cmp.amperage_status,
            "lines": list(unit_cmp.lines),
            "mismatch_reasons": list(unit_cmp.mismatch_reasons),
        },
        "token_coverage_score": confidence.token_coverage_score,
        "numeric_unit_score": confidence.numeric_unit_score,
        "numeric_conflict": confidence.numeric_conflict,
        "similarity_score": confidence.similarity,
        "productcode_match_type": "none",
    }
    return merged, field_scores, matched_field, identifier_evidence


def calculate_score_gap(scores: Sequence[float]) -> tuple[float, float | None, float | None]:
    ordered = sorted((float(item) for item in scores), reverse=True)
    if not ordered:
        return 0.0, None, None
    top = ordered[0]
    second = ordered[1] if len(ordered) > 1 else None
    gap = None if second is None else round(top - second, 4)
    return top, second, gap


def variant_conflict(query: str, catalog_text: str) -> bool:
    """True when `catalog_text` names a specialty variant, material, or color
    the customer's `query` didn't ask for. Plain word-overlap scoring can't
    tell these cases apart on its own, since the conflicting candidate often
    shares nearly all its vocabulary with the query -- see
    matching.category_defaults for the confirmed cases behind each check.
    """
    if mentions_stainless(query) != mentions_stainless(catalog_text):
        return True
    query_tokens = tokenize_description(query)
    if wants_spring_nut(query_tokens) and mentions_no_spring(catalog_text):
        return True
    if unrequested_specialty_marker(query, catalog_text) is not None:
        return True
    default_color = default_color_for_query(query_tokens)
    if default_color and candidate_color_conflicts(tokenize_description(catalog_text), default_color):
        return True
    return False


def descriptions_conflict(
    query: str,
    catalog_description: str,
    breakdown: ScoreBreakdown,
    config: MatchingConfig | None = None,
) -> bool:
    settings = config or MatchingConfig()
    query_attrs = extract_attributes(query)
    catalog_attrs = extract_attributes(catalog_description)
    for kind in ("voltage", "amperage", "size", "phrase"):
        left = {item.partition(":")[2] for item in query_attrs if item.startswith(f"{kind}:")}
        right = {item.partition(":")[2] for item in catalog_attrs if item.startswith(f"{kind}:")}
        if left and right and left.isdisjoint(right):
            return True
    if variant_conflict(query, catalog_description):
        return True
    return breakdown.exact < 100.0 and breakdown.final < settings.description_conflict_max


def descriptions_compatible(
    query: str,
    catalog_description: str,
    breakdown: ScoreBreakdown,
    config: MatchingConfig | None = None,
) -> bool:
    settings = config or MatchingConfig()
    if breakdown.exact >= 100.0:
        return True
    if descriptions_conflict(query, catalog_description, breakdown, settings):
        return False
    return breakdown.final >= settings.description_compatible_min
