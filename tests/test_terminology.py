from __future__ import annotations

from matching.terminology import TOKEN_SYNONYMS, canonicalize_token, token_variants
from matching.description_normalize import tokenize_description


def test_terminology_map_is_token_based_not_substring() -> None:
    assert canonicalize_token("CABLE") == "CBL"
    assert canonicalize_token("SCABLE") == "SCABLE"
    assert tokenize_description("cable tray")[0] == "CBL"
    assert tokenize_description("scable") == ["SCABLE"]


def test_adding_synonym_only_requires_terminology_groups() -> None:
    assert TOKEN_SYNONYMS["VOLTAGE"] == "V"
    assert TOKEN_SYNONYMS["SWITCH"] == "SW"
    assert TOKEN_SYNONYMS["PCS"] == "EA"


def test_grey_is_a_retrieval_synonym_for_the_catalogs_gray() -> None:
    # Confirmed live: a customer's British spelling "Grey" never matched this
    # catalog's own American "Gray" (e.g. "CP20 PVC COUPLING 2 ... PVC
    # Gray"), excluding otherwise-correct candidates from retrieval.
    assert set(token_variants("GREY")) == {"GRAY", "GREY"}
    assert canonicalize_token("GREY") == "GRAY"


def test_fmc_is_a_synonym_for_flex() -> None:
    # Confirmed live: 261 catalog rows abbreviate flexible metal conduit as
    # "FMC".
    assert set(token_variants("FMC")) == {"FLEX", "FLEXIBLE", "FMC"}
    assert canonicalize_token("FMC") == "FLEX"


def test_eg_is_a_synonym_for_electrogalvanized() -> None:
    # Confirmed live: 1,896 rows spell out "Electrogalvanized" in full.
    assert set(token_variants("EG")) == {"EG", "ELECTROGALVANIZED"}
    assert canonicalize_token("ELECTROGALVANIZED") == "EG"


def test_lt_stays_its_own_canonical_form_and_gains_liquidtight_variant() -> None:
    # "LT" must stay self-canonical (not rewritten to "LIQUIDTIGHT") --
    # matching.category_defaults.CATEGORY_DEFAULTS looks up the literal "LT"
    # token for its own bare-category expansion ("LT" -> "LIQUID TIGHT"),
    # and tokenize_description() applies this synonym map before that lookup
    # ever runs. Confirmed live: the catalog spells this two ways -- 316 rows
    # with a space ("Liquid Tight"), 757 rows glued as one word
    # ("Liquidtight") -- so retrieval needs both recognized as "LT".
    assert canonicalize_token("LT") == "LT"
    assert canonicalize_token("LIQUIDTIGHT") == "LT"
    assert set(token_variants("LT")) == {"LT", "LIQUIDTIGHT"}

    from matching.category_defaults import CATEGORY_DEFAULTS

    assert CATEGORY_DEFAULTS["LT"] == "LIQUID TIGHT"


def test_separator_is_a_synonym_for_divider_and_barrier() -> None:
    # Confirmed live: this catalog's cable tray family calls its
    # divider/partition accessory a "Barrier" (e.g. "EGL4-01SB-120 EGL TRAY
    # STR BARRIER") and never "Separator" at all -- a customer's "Separator"
    # found zero candidates without this synonym.
    assert set(token_variants("SEPARATOR")) == {"SEPARATOR", "DIVIDER", "BARRIER"}
    assert canonicalize_token("BARRIER") == "SEPARATOR"
