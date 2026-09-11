from __future__ import annotations

from fractions import Fraction

from catalog.postgres_repository import product_from_postgres_row
from matching.description_normalize import canonical_description, tokenize_description
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.productcode import productcode_as_text, score_product_code_identifier
from matching.units import (
    DimensionSpec,
    apply_unit_normalization,
    compare_units,
    extract_amperages,
    extract_bare_number_pairs,
    extract_dimensions,
    extract_voltages,
)
from output.match_evidence import build_match_evidence


def _pg_product(
    row_id: int,
    productcode: object,
    name: str | None,
    description: str | None,
    description2: str | None = None,
) -> ProductRecord:
    record = product_from_postgres_row(
        productcode=productcode,
        name=name,
        description=description,
        description2=description2,
        row_id=row_id,
    )
    assert record is not None
    return record


def _catalog() -> list[ProductRecord]:
    return [
        _pg_product(
            333427,
            333427,
            "B1EB5-W",
            "BRP 120V WHIP END EXT CBL",
            "BRP 120V WHIP END EXT CBL",
        ),
        _pg_product(333500, 333500, "B277-LC", "BRP 277V LIGHTING CBL", None),
        _pg_product(
            800001,
            "1MD12BZUZ115EB1",
            "1MD12BZUZ115EB1",
            "SPECIAL HV KIT",
            None,
        ),
    ]


def _line(text: str) -> QuoteLine:
    return QuoteLine(
        source_file="quote.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description=text,
        quantity=1,
    )


def test_voltage_spellings_normalize_to_120_v() -> None:
    expected = ["120", "V"]
    assert tokenize_description("120V") == expected
    assert tokenize_description("120 V") == expected
    assert tokenize_description("120 volt") == expected
    assert tokenize_description("120 volts") == expected
    assert canonical_description("120V") == "120 v"
    assert canonical_description("120 volts") == "120 v"
    assert apply_unit_normalization("120V").lower() == "120 v"
    assert apply_unit_normalization("277V").lower() == "277 v"
    assert tokenize_description("277V") == ["277", "V"]
    assert canonical_description("120V") != canonical_description("277V")


def test_vac_forms_are_equivalent() -> None:
    expected = ["120", "V", "AC"]
    assert tokenize_description("120 VAC") == expected
    assert tokenize_description("120V AC") == expected
    assert tokenize_description("120 volt AC") == expected
    assert tokenize_description("120 volts AC") == expected
    assert canonical_description("120 VAC") == "120 v ac"


def test_voltage_match_and_conflict_comparison() -> None:
    match = compare_units("120 volts", "120V")
    assert match.voltage_status == "match"
    assert any("Match" in line for line in match.lines)
    conflict = compare_units("277 volts", "120V")
    assert conflict.voltage_status == "conflict"
    assert any("Voltage mismatch: requested 277V, catalog 120V" in line for line in conflict.lines)
    assert conflict.score_cap is not None


def test_brp_120_volts_is_strong_match() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("BRP 120 volts whip end extension cable"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"
    assert result.requested_description == "BRP 120 volts whip end extension cable"
    evidence = build_match_evidence(result)
    blob = " ".join(evidence.get("voltage_evidence") or []) + " ".join(result.match_reasons or [])
    assert "120V" in blob and "Match" in blob
    assert "Voltage mismatch" not in blob


def test_brp_277_volts_is_not_equivalent_to_b1eb5w() -> None:
    query = "BRP 277 volts whip end extension cable"
    result = ProductMatcher(_catalog()).match_line(_line(query))
    assert result.matched_part_number != "B1EB5-W"
    conflicting = [item for item in result.candidates if item.official_part_number == "B1EB5-W"]
    if conflicting:
        evidence = conflicting[0].identifier_evidence or {}
        assert (evidence.get("unit_evidence") or {}).get("voltage_status") == "conflict"
        assert any("Voltage mismatch" in reason for reason in conflicting[0].match_reasons)
    else:
        from matching.description_normalize import description_retrieval_hit

        product = next(item for item in _catalog() if item.product_code == "B1EB5-W")
        assert description_retrieval_hit(query, product) is False


def test_brp_277_against_only_120v_catalog_is_not_a_match() -> None:
    catalog = [
        _pg_product(
            333427,
            333427,
            "B1EB5-W",
            "BRP 120V WHIP END EXT CBL",
            "BRP 120V WHIP END EXT CBL",
        )
    ]
    result = ProductMatcher(catalog).match_line(_line("BRP 277 volts whip end extension cable"))
    assert result.matched_part_number is None
    assert result.match_status in {MatchStatus.NO_MATCH, MatchStatus.REVIEW_REQUIRED}
    if result.candidates:
        assert result.candidates[0].score <= 40.0
        reasons = " ".join(result.candidates[0].match_reasons)
        assert "Voltage mismatch: requested 277V, catalog 120V" in reasons
    half = tokenize_description('1/2"')
    assert half == tokenize_description("1/2 in")
    assert half == tokenize_description("1/2 inch")
    assert "0.5" in half or "1/2" in half
    assert tokenize_description("1 inch") == tokenize_description("1 in") == tokenize_description('1"')
    mixed = tokenize_description('2-1/2"')
    assert mixed == tokenize_description("2.5 inch")
    assert mixed == tokenize_description("2.5 in")


def test_kilovolt_spellings_normalize_and_match() -> None:
    spec = extract_voltages("15KV HV TERMINATION")
    assert len(spec) == 1
    assert spec[0].volts == 15000
    assert spec[0].display() == "15KV"

    match = compare_units("15KV", "15000V")
    assert match.voltage_status == "match"

    match = compare_units("15 KILOVOLT", "15KV")
    assert match.voltage_status == "match"


def test_kilovolt_conflict_is_capped() -> None:
    conflict = compare_units("5KV HV TERMINATION", "35KV HV TERMINATION")
    assert conflict.voltage_status == "conflict"
    assert conflict.score_cap is not None
    assert any("Voltage mismatch" in line for line in conflict.lines)


def test_kva_power_rating_is_not_parsed_as_kilovolts() -> None:
    assert extract_voltages("15KVA TRANSFORMER") == ()


def test_awg_aught_sizes_do_not_crash_dimension_extraction() -> None:
    assert extract_dimensions('2/0"') == ()
    assert extract_dimensions("4/0 IN CONDUIT") == ()
    assert extract_dimensions("#2/0 MECH LUG") == ()


def test_awg_aught_sizes_still_ignored_with_no_unit_at_all() -> None:
    # Confirmed live: a bare bare AWG size ("2/0"/"4/0", no unit marker)
    # must not be misread as a "2/0 inch" or "4/0 inch" dimension by the
    # bare-fraction recognition below -- the zero-denominator guard these
    # already relied on with an explicit unit must still catch them here.
    assert extract_dimensions("2/0") == ()
    assert extract_dimensions("4/0 CONDUIT") == ()
    assert extract_dimensions("#2/0 MECH LUG") == ()


def test_bare_fraction_with_no_unit_marker_is_recognized_as_inches() -> None:
    # Confirmed live: "3/8 SPRING NUT" (no inch mark at all) left
    # extract_dimensions() completely blind to the query's own stated
    # size -- every branch used to require an explicit unit suffix, so the
    # numeric/dimension comparison, rerank, and confidence floor never
    # engaged, letting boilerplate text similarity alone decide (which
    # favored a wrong thread size, 3/4"-10, over the correct 3/8" part).
    spec = extract_dimensions("3/8 SPRING NUT")
    assert len(spec) == 1
    assert spec[0].inches == Fraction(3, 8)
    assert spec[0].unit == "IN"


def test_bare_fraction_does_not_absorb_an_unrelated_adjacent_number() -> None:
    # Confirmed live: "A-100 A-100 3/8 SPRING NUT" (a catalog row's own
    # name, "A-100", concatenated with its genuine "3/8" size elsewhere in
    # the same blob) must extract just the real size, 3/8" -- an earlier
    # version of this fix also recognized a *bare mixed fraction* (a bare
    # whole number followed by a fraction, e.g. an unmarked "1 1/2"), which
    # misread "100" (part of the unrelated code) plus the following "3/8"
    # as one fake mixed number, "100 3/8\"" (Fraction(803, 8)).
    spec = extract_dimensions("A-100 A-100 3/8 SPRING NUT")
    assert spec == (DimensionSpec(inches=Fraction(3, 8), raw="3/8", unit="IN"),)


def test_bare_fraction_rejects_implausible_denominators() -> None:
    # Confirmed live: "PVC - Sch 40/80 Conduit" (a Schedule 40/80 rating,
    # in ~2,900 catalog rows) was misread as a bare "40/80" = 1/2" size,
    # spuriously conflicting with every PVC candidate's own dimension
    # against any query size that wasn't exactly 1/2" -- e.g. capping
    # BV2030 ("SPACER BASE 2 x 3", Preferred) to the same 45% as a
    # completely wrong-sized sibling for "2\"x3\" BASE SPACER", instead of
    # its genuine, correct 97%. Of ~24,400 genuine quote-marked fraction
    # sizes in this catalog, 99.99% use a denominator of 2, 4, 8, 16, 32,
    # or 64 -- a schedule number/ratio/rating essentially never does.
    assert extract_dimensions("PVC - Sch 40/80 Conduit") == ()
    assert extract_dimensions("9/10 RATIO") == ()
    # A plausible denominator must still work.
    assert extract_dimensions("7/16 BOLT") == (DimensionSpec(inches=Fraction(7, 16), raw="7/16", unit="IN"),)


def test_bare_fraction_still_requires_unit_for_whole_numbers() -> None:
    # A bare whole number (e.g. a leftover mixed-fraction fragment, a hole
    # count, a wire gauge) is still too ambiguous to assume it's a size --
    # only extended to simple fractions, which overwhelmingly mean a size
    # in this domain. See catalog/search_query.py's _is_distinctive for
    # the same judgment call made for retrieval.
    assert extract_dimensions("4 GRC STRUT CLAMP") == ()
    assert extract_dimensions('4" GRC STRUT CLAMP') != ()


def test_quote_marked_size_recognized_even_with_no_space_before_next_word() -> None:
    # Confirmed live: ~5,500 description2 rows glue a following word
    # directly onto the closing inch mark with no space at all (e.g.
    # "1-1/2\"x 90° Elbow, Galvanized Rigid Conduit" -- 876773). The
    # word-unit branch's own trailing boundary check (needed so "4 IN"
    # glued onto "4INSTALL" isn't misread) was, before this fix, shared
    # with the quote-mark branch too, rejecting the whole match for every
    # one of these rows and silently falling through to the bare-fraction
    # branch, which mis-extracted just the trailing "1/2" (0.5") instead
    # of the true 1-1/2" (1.5") -- capping 876773's own description2
    # similarity score and letting differently-sized sibling parts
    # outrank the correct one for "1 1/2\" GRC 90 DEG ELBOW".
    spec = extract_dimensions('1-1/2"x 90° Elbow, Galvanized Rigid Conduit')
    assert spec == (DimensionSpec(inches=Fraction(3, 2), raw='1-1/2"', unit="IN"),)

    # Same fix for a plain (non-mixed) quoted size and for feet.
    assert extract_dimensions('3/4"L NIPPLE') == (DimensionSpec(inches=Fraction(3, 4), raw='3/4"', unit="IN"),)
    assert extract_dimensions("4'x REEL") == (DimensionSpec(inches=Fraction(4, 1), raw="4'", unit="FT"),)

    # The word-unit branch's own trailing check must still apply --
    # "4INSTALL" must not be misread as a 4" size.
    assert extract_dimensions("4INSTALL") == ()


def test_decimal_kilovolt_values_parse_at_full_magnitude() -> None:
    spec = extract_voltages("34.5kV SEL 3-Phase")
    assert len(spec) == 1
    assert spec[0].volts == 34500

    spec = extract_voltages("24.4kV MCOV")
    assert len(spec) == 1
    assert spec[0].volts == 24400

    match = compare_units("34.5kV MV Cable", "34500V MV Cable")
    assert match.voltage_status == "match"
    conflict = compare_units("34.5kV MV Cable", "15kV MV Cable")
    assert conflict.voltage_status == "conflict"


def test_amperage_is_extracted_and_capped_on_conflict() -> None:
    spec = extract_amperages("30A 3R NF DISCONNECT")
    assert len(spec) == 1
    assert spec[0].amps == 30

    assert extract_amperages("15KVA TRANSFORMER") == ()
    assert extract_amperages("10 AWG AL") == ()

    match = compare_units("30A 3R NF DISCONNECT", "30A 3R NF DISCONNECT")
    assert match.amperage_status == "match"
    conflict = compare_units("30A 3R NF DISCONNECT", "100A 3R NF DISCONNECT")
    assert conflict.amperage_status == "conflict"
    assert conflict.score_cap is not None


def test_amp_token_survives_instead_of_being_dropped_as_stopword() -> None:
    assert "AMP" in tokenize_description("30A 3R NF DISCONNECT")
    assert "AMP" in tokenize_description("100A 3R NF DISCONNECT")
    # Part numbers with a bare trailing A no longer silently lose that suffix.
    assert "AMP" in tokenize_description("3M COLD-SHRINK 5536A #750 SPLICE KIT")


def test_foot_symbol_and_word_are_recognized_as_a_distinct_unit() -> None:
    spec = extract_dimensions("6' FIXTURE WHIP")
    assert len(spec) == 1 and spec[0].unit == "FT" and spec[0].inches == 6

    assert tokenize_description("6' FIXTURE WHIP") == ["6", "FT", "FIXTURE", "WHIP"]
    assert tokenize_description("25' Pole") == ["25", "FT", "POLE"]
    assert tokenize_description("10ft") == ["10", "FT"]
    assert tokenize_description("POWER TRAC - 6FT") == ["POWER", "TRAC", "6", "FT"]

    # 6 feet and 6 inches must never be treated as the same magnitude -- a
    # 6-foot whip should not cheaply match a 6-inch fitting just because both
    # descriptions contain the digit 6.
    six_feet = compare_units("6' WHIP", "6\" WHIP")
    assert six_feet.dimension_status == "conflict"

    # But a real match on the foot value still overlaps normally alongside
    # unrelated inch-based attributes elsewhere in the same description.
    still_matches = compare_units("6' FIXTURE WHIP", "6' WHIP, 1/2\" FITTING")
    assert still_matches.dimension_status == "match"


def test_leading_decimal_point_keeps_its_magnitude() -> None:
    # Confirmed live: '.75" EMT' extracted no dimension at all -- the
    # leading "." isn't part of [A-Za-z0-9], so noise.py's retrieval-side
    # token-span regex silently dropped it and started the token at "75",
    # and units.py's own decimal group required a digit before the dot too
    # (\d+\.\d+), so even a correctly preserved ".75" still wouldn't parse.
    # Both silently turned a customer's 0.75" (3/4") into 75" -- a 100x
    # size error.
    spec = extract_dimensions('.75" EMT')
    assert len(spec) == 1
    assert spec[0].inches == extract_dimensions('0.75" EMT')[0].inches


def test_glued_x_between_size_and_length_is_retrievable() -> None:
    # Confirmed live: '3/4"x10\' EMT' (no spaces around "x", a common way
    # customers write a size-by-length) matched EMT straps instead of the
    # genuine 10'-long conduit stick, because "x10'" glues into one opaque
    # token and the 10' length is lost before retrieval ever sees it.
    # Scoped to retrieval only (matching/noise.py) -- NOT applied inside
    # tokenize_description, which also drives scoring for every match in
    # the system (see the multi-dimension tests below for why that
    # distinction matters).
    from matching.noise import strip_quantity_and_noise

    assert strip_quantity_and_noise('3/4"x10\' EMT') == strip_quantity_and_noise('3/4" x 10\' EMT')
    assert strip_quantity_and_noise("2\"x3\" BASE SPACER") == strip_quantity_and_noise('2" x 3" BASE SPACER')


def test_multi_dimension_comparison_requires_exact_order_and_full_set() -> None:
    # Plain set-intersection is too lenient for a genuine multi-dimension
    # "AxB" product: {2,3} intersecting {3,3} would call that a "match" on
    # the strength of the shared "3" alone, and it's also blind to order --
    # {2,3} and {3,2} are the same set, but "2x3 Base Spacer" and "3x2 Base
    # Spacer" are different catalog SKUs. Confirmed live: this tie is
    # *pre-existing* and independent of any glued-text issue -- even a
    # cleanly spaced '2" x 3" SPACER' query ties 80.0/80.0 against both the
    # genuine 2x3 candidate and its transposed 3x2 sibling once retrieval
    # finds both, since nothing previously compared the pair's order.
    same_order = compare_units('2" x 3" SPACER', '2" x 3" Base Spacer')
    assert same_order.dimension_status == "match"

    reordered = compare_units('2" x 3" SPACER', '3" x 2" Base Spacer')
    assert reordered.dimension_status == "conflict"

    different_numbers = compare_units('2" x 4" SPACER', '2" x 3" Base Spacer')
    assert different_numbers.dimension_status == "conflict"

    # A single dimension keeps the original, more lenient intersection
    # behavior -- there's no order or multi-value ambiguity to guard there.
    single = compare_units('3/4" EMT', '3/4" Electrical Metallic Tubing')
    assert single.dimension_status == "match"


def test_bare_number_pair_extracted_without_any_unit() -> None:
    # "2 x 3" is unambiguous dimension-pair notation on its own -- some
    # catalog families never attach a unit to either number (this
    # catalog's Base/Intermediate Spacer: "SPACER BASE 2 x 3", no "\"" or
    # "IN" anywhere), so extract_dimensions() (which requires a unit
    # suffix) can never see a dimension there, and the order/set check
    # above never has anything to compare. extract_bare_number_pairs()
    # fills that gap without touching extract_dimensions()'s own unit
    # requirement (which also feeds the apply_units auto-detect
    # heuristic and would risk misreading unrelated text if loosened).
    assert extract_bare_number_pairs("SPACER BASE 2 x 3 BV2030") == ((2, 3),)
    assert extract_bare_number_pairs('2"x3" SPACER') == ((2, 3),)
    assert extract_bare_number_pairs("no numbers here") == ()

    same_order = compare_units("2x3 SPACER", "SPACER BASE 2 x 3 BV2030")
    assert same_order.dimension_status == "match"
    reordered = compare_units("2x3 SPACER", "SPACER BASE 3 x 2 BV3020")
    assert reordered.dimension_status == "conflict"


def test_compound_box_dimensions_split_into_comparable_tokens() -> None:
    assert tokenize_description("QUAZITE 36x24x18 OPEN BOTTOM") == [
        "QUAZITE", "36", "24", "18", "OPEN", "BOTTOM",
    ]
    assert tokenize_description("PVC J-BOX 8x8x4") == ["PVC", "J", "BOX", "8", "8", "4"]
    assert tokenize_description("12x12x10FT N1 PAINTED SC WIREWAY") == [
        "12", "12", "10", "FT", "N1", "PAINTED", "SC", "WIREWAY",
    ]


def test_glued_x_retrieval_fix_does_not_touch_bare_digit_box_dimensions() -> None:
    # The retrieval-side glued-x fix only fires when a genuine unit mark
    # ("\"", "'") sits directly before the "x" -- NOT for a bare digit
    # ("12x12x10FT"), which is a *different*, already-handled shorthand
    # (WxHxD box/wireway dimensions) that depends on staying glued as one
    # token. An earlier, unscoped version of this regex (firing on any
    # digit before "x") broke this case, caught by this exact test.
    from matching.noise import strip_quantity_and_noise

    cleaned = strip_quantity_and_noise("QUAZITE 36x24x18 OPEN BOTTOM")
    assert "36X24X18" in cleaned.upper().replace(" ", "")


def test_space_separated_mixed_number_matches_dash_separated() -> None:
    # Customers commonly write a mixed-number size with a space ("1 1/2\"")
    # rather than this catalog's own dash form ("1-1/2\""). The dimension
    # regex previously required a literal dash, so "1 1/2\"" fell through
    # to matching only the bare fraction "1/2" -> "0.5 IN", leaving the
    # leading "1" as an unrelated whole-number token -- "1 1/2\"" and
    # "1-1/2\"" never token-matched on size at all. Confirmed live: this
    # silently ranked the wrong-size 1/2" squeeze connector above the
    # correct 1-1/2" one for a "1 1/2\" ... FLEX CONN" query.
    assert apply_unit_normalization('1 1/2" FLEX CONN') == apply_unit_normalization('1-1/2" FLEX CONN')
    assert tokenize_description('1 1/2" FLEX CONN') == tokenize_description('1-1/2" FLEX CONN')
    space_dims = extract_dimensions('1 1/2" FLEX CONN')
    dash_dims = extract_dimensions('1-1/2" FLEX CONN')
    assert [(d.inches, d.unit) for d in space_dims] == [(d.inches, d.unit) for d in dash_dims]


def test_productcode_is_not_parsed_as_measurement() -> None:
    code = "1MD12BZUZ115EB1"
    assert productcode_as_text(code) == code
    assert tokenize_description(code) == [code]
    assert extract_voltages(code) == ()
    score, evidence = score_product_code_identifier(code, code)
    assert score == 100.0
    assert evidence.get("match_type") == "exact"
    result = ProductMatcher(_catalog()).match_line(_line(code))
    assert result.matched_part_number == code
    assert result.match_status == MatchStatus.EXACT_MATCH
    assert result.requested_description == code
