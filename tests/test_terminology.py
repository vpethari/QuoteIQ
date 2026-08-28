from __future__ import annotations

from matching.terminology import TOKEN_SYNONYMS, canonicalize_token
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
