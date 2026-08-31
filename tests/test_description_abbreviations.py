from __future__ import annotations

from catalog.postgres_repository import product_from_postgres_row
from matching.description_normalize import (
    abbreviation_evidence,
    canonical_description,
    tokenize_description,
)
from matching.matcher import ProductMatcher
from matching.models import MatchStatus, ProductRecord, QuoteLine
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


def _line(text: str) -> QuoteLine:
    return QuoteLine(
        source_file="quote.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description=text,
        quantity=1,
    )


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
        _pg_product(900003, 900003, "WHIP-A", "120V LIGHTING WHIP W/PAULEX", "WHIP FAMILY"),
        _pg_product(900004, 900004, "WHIP-B", "120V LIGHTING WHIP W/PAULEX", "WHIP FAMILY"),
    ]


def test_token_normalization_volts_extension_cable() -> None:
    expanded = tokenize_description("BRP 120 volts whip end extension cable")
    catalog = tokenize_description("BRP 120V WHIP END EXT CBL")
    assert expanded == ["BRP", "120", "V", "WHIP", "END", "EXT", "CBL"]
    assert catalog == expanded
    assert canonical_description("BRP 120 volt whip end extension cable") == canonical_description(
        "BRP 120V WHIP END EXT CBL"
    )
    assert tokenize_description("scable") == ["SCABLE"]
    assert tokenize_description("cable") == tokenize_description("cbl") == ["CBL"]
    assert tokenize_description("extension") == tokenize_description("ext") == ["EXT"]
    assert tokenize_description("extended") == ["EXT"]
    assert tokenize_description("volts") == tokenize_description("volt") == ["V"]
    assert tokenize_description("voltage") == tokenize_description("V") == ["V"]
    assert tokenize_description("120 volts") == tokenize_description("120V") == ["120", "V"]
    assert tokenize_description("120 V") == ["120", "V"]
    assert tokenize_description("assembly") == tokenize_description("assy") == ["ASSY"]
    assert tokenize_description("connector") == tokenize_description("conn") == ["CONN"]
    assert tokenize_description("switch") == tokenize_description("sw") == ["SW"]
    assert tokenize_description("piece") == tokenize_description("pcs") == ["EA"]
    assert tokenize_description("each") == ["EA"]


def test_brp_120_volts_whip_end_extension_cable_matches() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("BRP 120 volts whip end extension cable"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"
    evidence = build_match_evidence(result)
    assert evidence["matched_part_number"] == "B1EB5-W"
    description_field = next(item for item in evidence["fields"] if item["field"] == "Part Description")
    name_field = next(item for item in evidence["fields"] if item["field"] == "Part Number")
    assert description_field["level"] in {"exact", "strong"} or name_field["level"] in {"exact", "strong"}
    terms = " ".join(evidence.get("normalized_terms") or [])
    reasons = " ".join(result.match_reasons or [])
    assert "volts → V" in terms or "volts → V" in reasons
    assert "120 volts → 120V" in terms or "120 volts → 120V" in reasons
    assert "extension → EXT" in terms or "extension → EXT" in reasons
    assert "cable → CBL" in terms or "cable → CBL" in reasons
    assert "Normalized Description Match" in (
        evidence["headline"],
        *(result.match_reasons or []),
    )
    assert "Exact Productcode Match" not in evidence["headline"]
    assert result.requested_description == "BRP 120 volts whip end extension cable"
    assert result.matched_part_number == "B1EB5-W"


def test_whip_end_extension_cable_120_volts_matches() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("whip end extension cable 120 volts"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"
    assert result.requested_description == "whip end extension cable 120 volts"


def test_brp_catalog_abbreviation_is_exact() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("BRP 120V WHIP END EXT CBL"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"


def test_brp_120_volt_singular() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("BRP 120 volt whip end extension cable"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"


def test_brp_120_v_spaced_abbreviations() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("BRP 120 V whip end ext cbl"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"
    assert result.requested_description == "BRP 120 V whip end ext cbl"


def test_brp_mixed_ext_cable_word() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("BRP 120V WHIP END EXT CABLE"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B1EB5-W"


def test_brp_277_volts_lighting_cable() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("BRP 277 volts lighting cable"))
    assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
    assert result.matched_part_number == "B277-LC"


def test_unrelated_description_no_match() -> None:
    result = ProductMatcher(_catalog()).match_line(_line("PURPLE BANANA ENCLOSURE"))
    assert result.match_status == MatchStatus.NO_MATCH
    assert result.matched_part_number is None


def test_word_order_does_not_reduce_description_score() -> None:
    from matching.scoring import calculate_token_score, score_pair

    catalog = "BRP 120V WHIP END EXT CBL"
    phrases = [
        "BRP 120 volts whip end extension cable",
        "whip end extension cable 120 volts",
        "120V BRP whip end ext cbl",
        "BRP whip end extension cable 120V",
        "BRP 120V WHIP END EXT CBL",
    ]
    matcher = ProductMatcher(_catalog())
    scores = []
    for phrase in phrases:
        result = matcher.match_line(_line(phrase))
        assert result.match_status in {MatchStatus.EXACT_MATCH, MatchStatus.HIGH_CONFIDENCE}
        assert result.matched_part_number == "B1EB5-W"
        token = calculate_token_score(phrase, catalog)
        pair = score_pair(phrase, catalog)
        scores.append((phrase, token, pair.final, result.overall_match_score))
        assert token >= 90
    token_values = [item[1] for item in scores]
    pair_values = [item[2] for item in scores]
    assert max(token_values) - min(token_values) <= 10
    assert max(pair_values) - min(pair_values) <= 15
    shuffled = set(tokenize_description("whip end extension cable 120 volts"))
    catalog_tokens = set(tokenize_description(catalog))
    assert {"WHIP", "END", "EXT", "CBL", "120", "V"} <= shuffled
    assert shuffled <= catalog_tokens
    pairs = abbreviation_evidence(
        "BRP 120 volts whip end extension cable",
        "BRP 120V WHIP END EXT CBL",
    )
    assert "volts → V" in pairs
    assert "120 volts → 120V" in pairs
    assert "extension → EXT" in pairs
    assert "cable → CBL" in pairs
