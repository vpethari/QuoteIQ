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
