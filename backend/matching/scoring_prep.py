"""Prepared scoring text. Same normalization/tokenization as the existing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from matching.normalizer import normalize_text
from matching.tokenizer import tokenize_description
from matching.units import extract_amperages, extract_dimensions, extract_voltages


@dataclass(frozen=True)
class PreparedText:
    original: str
    tokens: tuple[str, ...]
    token_set: frozenset[str]
    canonical: str
    normalized: str
    attributes: frozenset[str]
    volts: tuple
    dims: tuple
    amps: tuple


_EMPTY = PreparedText(
    original="",
    tokens=(),
    token_set=frozenset(),
    canonical="",
    normalized="",
    attributes=frozenset(),
    volts=(),
    dims=(),
    amps=(),
)


def prepare_scoring_text(value: str | None, cache: dict[str, PreparedText] | None = None) -> PreparedText:
    """Tokenize/normalize once. Results match tokenize_description + canonical_text + normalize_text."""
    text = "" if value is None else str(value)
    if not text:
        return _EMPTY
    if cache is not None:
        hit = cache.get(text)
        if hit is not None:
            return hit
    from matching.attributes import attributes_from_parts
    from matching.timing_diag import _ms, active

    session = active()
    started = perf_counter() if session is not None else None
    tokens = tuple(tokenize_description(text))
    normalized = normalize_text(text)
    prepared = PreparedText(
        original=text,
        tokens=tokens,
        token_set=frozenset(tokens),
        canonical=" ".join(tokens),
        normalized=normalized,
        attributes=attributes_from_parts(text, normalized, list(tokens)),
        volts=extract_voltages(text),
        dims=extract_dimensions(text),
        amps=extract_amperages(text),
    )
    if cache is not None:
        cache[text] = prepared
    if started is not None and session is not None:
        session.add(score_prep_ms=_ms(perf_counter() - started))
    return prepared
