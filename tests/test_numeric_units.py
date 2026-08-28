from __future__ import annotations

from catalog.postgres_repository import product_from_postgres_row
from matching.description_normalize import canonical_description, tokenize_description
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
from matching.productcode import productcode_as_text, score_product_code_identifier
from matching.units import (
    apply_unit_normalization,
    compare_units,
    extract_amperages,
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
            "B1EB5-W",
            "BRP 120V WHIP END EXT CBL",
            "BRP 120V WHIP END EXT CBL",
            "BRP 120V WHIP END EXT CBL",
        ),
        _pg_product(333500, "B277-LC", "BRP 277V LIGHTING CBL", "BRP 277V LIGHTING CBL", None),
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
            "B1EB5-W",
            "BRP 120V WHIP END EXT CBL",
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


def test_compound_box_dimensions_split_into_comparable_tokens() -> None:
    assert tokenize_description("QUAZITE 36x24x18 OPEN BOTTOM") == [
        "QUAZITE", "36", "24", "18", "OPEN", "BOTTOM",
    ]
    assert tokenize_description("PVC J-BOX 8x8x4") == ["PVC", "J", "BOX", "8", "8", "4"]
    assert tokenize_description("12x12x10FT N1 PAINTED SC WIREWAY") == [
        "12", "12", "10", "FT", "N1", "PAINTED", "SC", "WIREWAY",
    ]


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
