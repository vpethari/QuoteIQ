"""Prepared scoring text must match the existing tokenize/normalize helpers."""

from matching.attributes import extract_attributes
from matching.normalizer import canonical_text, normalize_text
from matching.scoring import score_pair
from matching.scoring_prep import prepare_scoring_text
from matching.tokenizer import tokenize_description
from matching.units import extract_dimensions, extract_voltages


SAMPLES = [
    "extension cable 120 volts",
    "BRP 120 volts whip end extension cable",
    "steel conduit 1/2 inch",
    "B1EB5-W",
    "RR 2BA KR",
]


def test_prepare_scoring_text_matches_existing_helpers() -> None:
    cache: dict = {}
    for sample in SAMPLES:
        prepared = prepare_scoring_text(sample, cache)
        assert prepared.tokens == tuple(tokenize_description(sample))
        assert prepared.canonical == canonical_text(sample)
        assert prepared.normalized == normalize_text(sample)
        assert prepared.attributes == extract_attributes(sample)
        assert prepared.volts == extract_voltages(sample)
        assert prepared.dims == extract_dimensions(sample)
        assert prepare_scoring_text(sample, cache) is prepared


def test_score_pair_is_deterministic_with_cache() -> None:
    query = "whip end extension cable 120 volts"
    candidate = "120V WHIP END EXT CABLE"
    first = score_pair(query, candidate)
    cached = score_pair(query, candidate, prep_cache={})
    assert first == cached
