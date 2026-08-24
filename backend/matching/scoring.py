from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

from matching.attributes import extract_attributes
from matching.attributes import extract_attributes
from matching.models import MatchingConfig, ScoreBreakdown
from matching.normalizer import canonical_text, normalize_text
from matching.tokenizer import tokenize_description


def clamp_score(value: float) -> float:
    return round(min(100.0, max(0.0, value)), 4)


def calculate_exact_score(query: str, candidate_description: str) -> float:
    query_canonical = canonical_text(query)
    candidate_canonical = canonical_text(candidate_description)
    if query_canonical and query_canonical == candidate_canonical:
        return 100.0
    if normalize_text(query) and normalize_text(query) == normalize_text(candidate_description):
        return 100.0
    return 0.0


def calculate_token_score(query: str, candidate_description: str) -> float:
    query_tokens = set(tokenize_description(query))
    candidate_tokens = set(tokenize_description(candidate_description))
    if not query_tokens or not candidate_tokens:
        return 0.0
    overlap = len(query_tokens & candidate_tokens)
    dice = (2.0 * overlap) / (len(query_tokens) + len(candidate_tokens))
    return clamp_score(dice * 100.0)


def calculate_fuzzy_score(query: str, candidate_description: str) -> float:
    left = canonical_text(query) or normalize_text(query)
    right = canonical_text(candidate_description) or normalize_text(candidate_description)
    if not left or not right:
        return 0.0
    ratio = SequenceMatcher(None, left, right).ratio()
    return clamp_score(ratio * 100.0)


def calculate_attribute_score(query: str, candidate_description: str) -> float:
    query_attrs = extract_attributes(query)
    candidate_attrs = extract_attributes(candidate_description)
    if not query_attrs or not candidate_attrs:
        return 0.0
    overlap = len(query_attrs & candidate_attrs)
    union = len(query_attrs | candidate_attrs)
    if union == 0:
        return 0.0
    return clamp_score((overlap / union) * 100.0)


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
    return clamp_score(combined)


def score_pair(
    query: str,
    candidate_description: str,
    config: MatchingConfig | None = None,
) -> ScoreBreakdown:
    exact = calculate_exact_score(query, candidate_description)
    token = calculate_token_score(query, candidate_description)
    fuzzy = calculate_fuzzy_score(query, candidate_description)
    attribute = calculate_attribute_score(query, candidate_description)
    final = calculate_final_score(exact, token, fuzzy, attribute, config)
    return ScoreBreakdown(
        exact=exact,
        token=token,
        fuzzy=fuzzy,
        attribute=attribute,
        final=final,
    )


def calculate_score_gap(scores: Sequence[float]) -> tuple[float, float | None, float | None]:
    ordered = sorted((float(item) for item in scores), reverse=True)
    if not ordered:
        return 0.0, None, None
    top = ordered[0]
    second = ordered[1] if len(ordered) > 1 else None
    gap = None if second is None else round(top - second, 4)
    return top, second, gap


def descriptions_conflict(
    query: str,
    catalog_description: str,
    breakdown: ScoreBreakdown,
    config: MatchingConfig | None = None,
) -> bool:
    settings = config or MatchingConfig()
    query_attrs = extract_attributes(query)
    catalog_attrs = extract_attributes(catalog_description)
    for kind in ("voltage", "size", "phrase"):
        left = {item.partition(":")[2] for item in query_attrs if item.startswith(f"{kind}:")}
        right = {item.partition(":")[2] for item in catalog_attrs if item.startswith(f"{kind}:")}
        if left and right and left.isdisjoint(right):
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
