from __future__ import annotations

"""Central product terminology / synonym map.

Add a new equivalent term by appending it to the appropriate group in
``TERMINOLOGY_GROUPS``. Matching code should call ``canonicalize_token`` rather
than hard-coding replacements.

Canonical forms follow catalog abbreviations (token-based, whole tokens only).
"""

# (canonical_token, equivalent_tokens including the canonical form)
TERMINOLOGY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("V", ("V", "VOLT", "VOLTS", "VOLTAGE")),
    ("EXT", ("EXT", "EXTENSION", "EXTENDED")),
    ("CBL", ("CBL", "CABLE", "CABLES")),
    ("ASSY", ("ASSY", "ASSEMBLY")),
    ("CONN", ("CONN", "CONNECTOR", "CONNECTORS")),
    ("MOD", ("MOD", "MODULE", "MODULES")),
    ("SW", ("SW", "SWITCH", "SWITCHES")),
    ("TERM", ("TERM", "TERMINAL")),
    ("DEG", ("DEG", "DEGREE", "DEGREES")),
    ("EA", ("EA", "EACH", "PIECE", "PIECES", "PCS")),
    ("W", ("WIRE",)),
    ("LIGHTING", ("LIGHTING", "LTG", "LTGS")),
    ("WHIP", ("WHIP", "WHIPS")),
    ("STRUT", ("STRUT", "UNISTRUT")),
    ("TRAY", ("TRAY", "TROF", "TROUGH")),
    ("PVC", ("PVC", "PLASTIC")),
    # This catalog files strut L/T/X joiners under "Fitting"/"Fittings" and
    # never uses the word "joiner" itself. A true synonym (not just a phrase
    # appended for scoring) is required so retrieval's own token matching --
    # which requires the literal word to appear somewhere in the catalog
    # text -- also benefits, not just post-retrieval scoring.
    ("FITTING", ("FITTING", "FITTINGS", "JOINER", "JOINERS")),
    ("FLEX", ("FLEX", "FLEXIBLE")),
)

# Display labels for match evidence (source token -> lowercase expanded word).
EVIDENCE_LABELS: dict[str, str] = {
    "VOLT": "volt",
    "VOLTS": "volts",
    "VOLTAGE": "voltage",
    "EXTENSION": "extension",
    "EXTENDED": "extended",
    "CABLE": "cable",
    "CABLES": "cables",
    "WIRE": "wire",
    "ASSEMBLY": "assembly",
    "CONNECTOR": "connector",
    "MODULE": "module",
    "MODULES": "modules",
    "SWITCH": "switch",
    "SWITCHES": "switches",
    "TERMINAL": "terminal",
    "EACH": "each",
    "PIECE": "piece",
    "PIECES": "pieces",
    "PCS": "pcs",
    "LTG": "ltg",
    "LTGS": "ltgs",
    "WHIPS": "whips",
}

NORMALIZED_DESCRIPTION_REASON = "Normalized Description Match"


def _build_token_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for canonical, variants in TERMINOLOGY_GROUPS:
        for variant in variants:
            mapping[variant.upper()] = canonical.upper()
    return mapping


TOKEN_SYNONYMS: dict[str, str] = _build_token_map()


def _build_variants_map() -> dict[str, tuple[str, ...]]:
    mapping: dict[str, tuple[str, ...]] = {}
    for canonical, variants in TERMINOLOGY_GROUPS:
        variant_set = tuple(sorted({variant.upper() for variant in variants} | {canonical.upper()}))
        for variant in variant_set:
            mapping[variant] = variant_set
    return mapping


TOKEN_VARIANTS: dict[str, tuple[str, ...]] = _build_variants_map()


def canonicalize_token(token: str) -> str:
    """Map one already-tokenized uppercase term to its canonical catalog form."""
    return TOKEN_SYNONYMS.get(token.upper(), token.upper())


def is_synonym_token(token: str) -> bool:
    return token.upper() in TOKEN_SYNONYMS


def token_variants(token: str) -> tuple[str, ...]:
    """All equivalent surface spellings for a token (including itself).

    Catalog ``search_text`` stores raw, uncanonicalized text, so retrieval SQL
    needs every spelling a canonicalized query token could stand for (e.g.
    "cbl" -> ("cable", "cables", "cbl")), not just the canonical form.
    """
    upper = token.upper()
    return TOKEN_VARIANTS.get(upper, (upper,))
