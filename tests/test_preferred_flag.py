from __future__ import annotations

import dataclasses

from catalog.postgres_repository import _parse_preferredflag, product_from_postgres_row
from matching.matcher import ProductMatcher
from matching.models import MatchingConfig, ProductRecord, QuoteLine


def _line(text: str) -> QuoteLine:
    return QuoteLine(source_file="quote.xlsx", source_sheet="Sheet1", source_row=2, requested_description=text)


def _product(name: str, description: str, *, preferred: bool = False) -> ProductRecord:
    record = product_from_postgres_row(
        productcode=name,
        name=name,
        description=description,
        preferredflag="Preferred" if preferred else "Not Preferred",
    )
    assert record is not None
    return record


def test_parse_preferredflag_recognizes_preferred_text() -> None:
    assert _parse_preferredflag("Preferred") is True
    assert _parse_preferredflag("preferred") is True
    assert _parse_preferredflag(" Preferred ") is True


def test_parse_preferredflag_defaults_false_for_anything_else() -> None:
    assert _parse_preferredflag("Not Preferred") is False
    assert _parse_preferredflag(None) is False
    assert _parse_preferredflag("") is False
    assert _parse_preferredflag("Yes") is False


def test_product_from_postgres_row_sets_preferred_flag() -> None:
    preferred = product_from_postgres_row(productcode="1", name="A1", description="A1", preferredflag="Preferred")
    not_preferred = product_from_postgres_row(
        productcode="2", name="A2", description="A2", preferredflag="Not Preferred"
    )
    missing = product_from_postgres_row(productcode="3", name="A3", description="A3")
    assert preferred is not None and preferred.preferred is True
    assert not_preferred is not None and not_preferred.preferred is False
    assert missing is not None and missing.preferred is False


def test_preferred_candidate_outranks_equal_scoring_non_preferred() -> None:
    # Two rows with identical description text score identically on text
    # alone -- confirmed live this catalog has many such ties (e.g. several
    # otherwise-comparable locknut/coupling variants). preferredflag is the
    # tie-break Atkore actually wants: among equally-good text matches, the
    # one they've marked Preferred should surface first.
    # Query intentionally doesn't say "STEEL" so neither candidate's score
    # maxes out at 100 -- leaves room for the bonus to actually separate two
    # otherwise-identical scores rather than both clamping to the same 100.
    preferred = _product("PREF1", "1/2 WIDGET CONNECTOR STEEL", preferred=True)
    plain = _product("PLAIN1", "1/2 WIDGET CONNECTOR STEEL", preferred=False)
    matcher = ProductMatcher([preferred, plain])
    result = matcher.match_line(_line("1/2 WIDGET CONNECTOR"))
    assert result.candidates[0].official_part_number == "PREF1"
    assert result.candidates[0].preferred is True
    assert result.candidates[0].score > result.candidates[1].score


def test_preferred_bonus_cannot_overcome_a_clearly_better_match() -> None:
    # The bonus (MatchingConfig.preferred_score_bonus, default 5.0) is
    # deliberately modest -- confirmed live this catalog's real score gaps
    # between a genuinely correct and a genuinely wrong candidate are much
    # larger than that (e.g. an 8-15+ point gap between differently-sized
    # parts). A preferred flag on the wrong part must not be able to
    # promote it over a clearly better-matching non-preferred one.
    exact_text = "3/4 STEEL EMT SET SCREW COUPLING WITH INSULATED THROAT"
    good_match = _product("GOOD1", exact_text, preferred=False)
    weak_match = _product("WEAK1", "3/4 PLASTIC BUSHING", preferred=True)
    matcher = ProductMatcher([good_match, weak_match])
    result = matcher.match_line(_line(exact_text))
    assert result.candidates[0].official_part_number == "GOOD1"


def test_preferred_bonus_applied_after_variant_conflict_cap() -> None:
    # A candidate variant_conflict already flagged as the wrong specialty
    # (see matching.category_defaults._SPECIALTY_VARIANT_MARKERS) must stay
    # capped near description_conflict_max even if it's preferred -- the
    # bonus nudges ranking among legitimate candidates, it doesn't rescue a
    # confirmed wrong-family match.
    config = MatchingConfig()
    conn_marker_text = "1/2 EMT STAINLESS STEEL ONE HOLE STRAP"
    plain_query = "1/2 EMT ONE HOLE STRAP"
    conflicted_preferred = _product("CONFLICT1", conn_marker_text, preferred=True)
    matcher = ProductMatcher([conflicted_preferred], config=config)
    result = matcher.match_line(_line(plain_query))
    candidate = result.candidates[0]
    assert candidate.official_part_number == "CONFLICT1"
    assert candidate.score <= config.description_conflict_max + config.preferred_score_bonus
