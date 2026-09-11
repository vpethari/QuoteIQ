from __future__ import annotations

"""Numeric and unit normalization for catalog name/description text.

Voltage and dimension expressions are rewritten into stable tokens so
``120V`` / ``120 volts`` / ``120 V`` compare equal, while ``120`` and ``277``
stay distinct. Productcode identity matching must not use this module.
"""

import re
from dataclasses import dataclass
from fractions import Fraction

from matching.normalizer import fold_whitespace

# Cap applied only when specified numeric units conflict. Global thresholds stay unchanged.
VOLTAGE_CONFLICT_SCORE_CAP = 40.0
DIMENSION_CONFLICT_SCORE_CAP = 40.0
AMPERAGE_CONFLICT_SCORE_CAP = 40.0

_VOLTAGE_EXPR = re.compile(
    r"""
    (?<![A-Z0-9])
    (\d+(?:\.\d+)?)
    (?:
        \s*KVAC(?:\s*AC)?
      | \s*KVDC(?:\s*DC)?
      | \s*KV(?![A-Z])(?:\s*(?:AC|DC))?
      | \s+(?:KILOVOLTS|KILOVOLT)(?:\s*(?:AC|DC))?
      | \s*VAC(?:\s*AC)?
      | \s*VDC(?:\s*DC)?
      | \s*V(?![A-Z])\s*(AC|DC)?
      | \s+(?:VOLTS|VOLT|VOLTAGE)\s*(AC|DC)?
    )
    (?![A-Z0-9])
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NUMERIC_FORM = r"""
    (?:
        (?P<{p}mixed_whole>\d+)(?:\s*-\s*|\s+)(?P<{p}mixed_num>\d+)\s*/\s*(?P<{p}mixed_den>\d+)
      | (?P<{p}frac_num>\d+)\s*/\s*(?P<{p}frac_den>\d+)
      | (?P<{p}decimal>\d*\.\d+)
      | (?P<{p}whole>\d+)
    )
"""

_DIMENSION_EXPR = re.compile(
    r"""
    (?<![A-Z0-9])
    (?:
        # Word-based units ("IN"/"FT"/etc.) keep a trailing boundary check
        # -- needed so e.g. "4 IN" glued directly onto a following word
        # ("4INSTALL") isn't misread as a size.
        """
    + _NUMERIC_FORM.format(p="w_")
    + r"""
        \s*(?:INCHES|INCH|INS|\bIN\b|FEET|FOOT|FT)(?![A-Z0-9])
      |
        # A quote-mark unit can never be part of a longer word, so it must
        # NOT have that same trailing check -- confirmed live, this
        # catalog commonly glues a following letter directly onto the
        # closing quote with no space at all (e.g. "1-1/2\"x 90\u00b0
        # Elbow", ~5,500 description2 rows). Requiring no-letter-follows
        # here made this whole branch fail for every one of them, silently
        # falling through to the bare-fraction branch below and
        # mis-extracting just the trailing "1/2" as the size instead of
        # the true 1-1/2".
        """
    + _NUMERIC_FORM.format(p="q_")
    + r"""
        \s*(?:["\u2033\u201d]|['\u2032])
      |
        # A bare simple fraction with no unit marker at all -- confirmed
        # live, "3/8 SPRING NUT" (no inch mark) left extract_dimensions()
        # completely blind to the query's own stated size, since every
        # branch above requires an explicit unit suffix. Every genuine
        # candidate's own size ("3/8\"-16" etc.) does carry a mark, so the
        # numeric/dimension comparison, rerank, and confidence floor never
        # engaged at all -- letting boilerplate text similarity alone
        # decide, which favored a wrong thread size (3/4"-10) over both the
        # exact literal match and the true 3/8" part. A bare fraction
        # overwhelmingly means a size in inches in this domain, unlike a
        # bare *whole* number (still deliberately excluded here -- see
        # _is_distinctive in catalog/search_query.py for the same judgment
        # call: a bare integer is too often a quantity, hole count, or
        # gauge to assume it's a size).
        #
        # Deliberately NOT extended to the mixed-whole form (e.g. a bare
        # "1 1/2"): confirmed live, that shape's leading whole-number part
        # is genuinely ambiguous with an unrelated adjacent number when
        # there's no unit to anchor it -- "A-100 A-100 3/8 SPRING NUT"
        # (the part code "A-100" concatenated with the genuine, separate
        # "3/8" size) was misread as one mixed number, "100 3/8\"", by an
        # earlier version of this fix that did include that form. A second
        # attempt made the mixed-whole form matched-but-discarded instead
        # (to stop bare_frac_num from independently reading just its
        # trailing fraction) -- but that discarded genuine catalog sizes
        # too, since a product's own name/code commonly ends in a bare
        # number immediately before its real size elsewhere in the same
        # blob, the exact same shape as a genuine mixed number. Between an
        # unmarked mixed-fraction *query* being misread as just its
        # trailing fraction (no confirmed real occurrence so far -- every
        # mixed-fraction query seen this session already carries a quote,
        # e.g. "1 1/2\" GRC COUPLING") and losing bare-fraction extraction
        # for catalog rows whose own code ends in a digit (confirmed,
        # common), the former is accepted as the lesser, narrower risk.
        (?P<bare_frac_num>\d+)\s*/\s*(?P<bare_frac_den>\d+)(?![A-Z0-9])
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_FOOT_UNIT_RE = re.compile(r"FEET|FOOT|FT|['\u2032]", re.IGNORECASE)


def _is_foot_match(match: re.Match[str]) -> bool:
    return bool(_FOOT_UNIT_RE.search(match.group(0)))


_AMPERAGE_EXPR = re.compile(
    r"""
    (?<![A-Z0-9])
    (\d+(?:\.\d+)?)
    (?:
        \s*A(?![A-Z])
      | \s+(?:AMPS|AMPERES|AMPERE|AMP)\b
    )
    (?![A-Z0-9])
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class VoltageSpec:
    volts: int
    polarity: str | None
    raw: str
    unit: str = "V"

    def canonical_tokens(self) -> tuple[str, ...]:
        tokens = (str(self.volts), "V")
        if self.polarity:
            return tokens + (self.polarity,)
        return tokens

    def magnitude_key(self) -> str:
        return f"{self.volts}V"

    def display(self) -> str:
        if self.unit == "KV":
            kv_value = self.volts / 1000
            base = f"{kv_value:g}KV"
        else:
            base = f"{self.volts}V"
        if self.polarity:
            return f"{base} {self.polarity}"
        return base


@dataclass(frozen=True)
class DimensionSpec:
    inches: Fraction
    raw: str
    unit: str = "IN"

    def canonical_tokens(self) -> tuple[str, ...]:
        return (_fraction_token(self.inches), self.unit)

    def magnitude_key(self) -> str:
        return f"{float(self.inches):.6f}{self.unit}"


@dataclass(frozen=True)
class AmpSpec:
    amps: Fraction
    raw: str

    def canonical_tokens(self) -> tuple[str, ...]:
        return (_fraction_token(self.amps), "A")

    def magnitude_key(self) -> str:
        return f"{float(self.amps):.6f}A"

    def display(self) -> str:
        return f"{_fraction_token(self.amps)}A"


@dataclass(frozen=True)
class UnitComparison:
    voltage_status: str
    dimension_status: str
    amperage_status: str
    lines: tuple[str, ...]
    mismatch_reasons: tuple[str, ...]
    score_cap: float | None


def _fraction_token(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    as_float = float(value)
    if as_float == int(as_float):
        return str(int(as_float))
    text = f"{as_float:.4f}".rstrip("0").rstrip(".")
    return text


def _polarity_from_match(match: re.Match[str]) -> str | None:
    body = match.group(0).upper().replace(" ", "")
    explicit = match.group(2)
    if explicit:
        return explicit.upper()
    if "VAC" in body or body.endswith("AC"):
        if "VDC" not in body:
            return "AC"
    if "VDC" in body or (body.endswith("DC") and "VAC" not in body):
        return "DC"
    return None


def _is_kilovolt_match(match: re.Match[str]) -> bool:
    body = match.group(0).upper().replace(" ", "")
    return "KV" in body or "KILOVOLT" in body


def extract_voltages(text: str | None) -> tuple[VoltageSpec, ...]:
    source = fold_whitespace(text)
    if not source:
        return ()
    found: list[VoltageSpec] = []
    seen: set[tuple[int, str | None]] = set()
    for match in _VOLTAGE_EXPR.finditer(source):
        unit = "KV" if _is_kilovolt_match(match) else "V"
        multiplier = 1000 if unit == "KV" else 1
        magnitude = Fraction(match.group(1)) * multiplier
        volts = int(magnitude) if magnitude.denominator == 1 else round(float(magnitude))
        polarity = _polarity_from_match(match)
        key = (volts, polarity)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            VoltageSpec(volts=volts, polarity=polarity, raw=match.group(0).strip(), unit=unit)
        )
    return tuple(found)


def extract_dimensions(text: str | None) -> tuple[DimensionSpec, ...]:
    source = fold_whitespace(text)
    if not source:
        return ()
    found: list[DimensionSpec] = []
    seen: set[tuple[Fraction, str]] = set()
    for match in _DIMENSION_EXPR.finditer(source):
        try:
            if match.group("w_mixed_whole") or match.group("q_mixed_whole"):
                prefix = "w_" if match.group("w_mixed_whole") else "q_"
                inches = Fraction(int(match.group(f"{prefix}mixed_whole"))) + Fraction(
                    int(match.group(f"{prefix}mixed_num")), int(match.group(f"{prefix}mixed_den"))
                )
            elif match.group("w_frac_num") or match.group("q_frac_num"):
                prefix = "w_" if match.group("w_frac_num") else "q_"
                inches = Fraction(int(match.group(f"{prefix}frac_num")), int(match.group(f"{prefix}frac_den")))
            elif match.group("w_decimal") or match.group("q_decimal"):
                inches = Fraction(match.group("w_decimal") or match.group("q_decimal"))
            elif match.group("w_whole") or match.group("q_whole"):
                inches = Fraction(int(match.group("w_whole") or match.group("q_whole")))
            else:
                inches = Fraction(int(match.group("bare_frac_num")), int(match.group("bare_frac_den")))
        except ZeroDivisionError:
            # AWG "aught" sizes like 2/0, 4/0 look like fractions but aren't.
            continue
        unit = "FT" if _is_foot_match(match) else "IN"
        key = (inches, unit)
        if key in seen:
            continue
        seen.add(key)
        found.append(DimensionSpec(inches=inches, raw=match.group(0).strip(), unit=unit))
    return tuple(found)


def extract_amperages(text: str | None) -> tuple[AmpSpec, ...]:
    source = fold_whitespace(text)
    if not source:
        return ()
    found: list[AmpSpec] = []
    seen: set[Fraction] = set()
    for match in _AMPERAGE_EXPR.finditer(source):
        amps = Fraction(match.group(1))
        if amps in seen:
            continue
        seen.add(amps)
        found.append(AmpSpec(amps=amps, raw=match.group(0).strip()))
    return tuple(found)


def apply_unit_normalization(text: str | None) -> str:
    """Rewrite voltage/dimension phrases into canonical tokens. Original text is not mutated."""
    source = fold_whitespace(text)
    if not source:
        return ""

    def _dim_repl(match: re.Match[str]) -> str:
        spec = extract_dimensions(match.group(0))
        if not spec:
            return match.group(0)
        return " " + " ".join(spec[0].canonical_tokens()) + " "

    def _volt_repl(match: re.Match[str]) -> str:
        spec = extract_voltages(match.group(0))
        if not spec:
            return match.group(0)
        return " " + " ".join(spec[0].canonical_tokens()) + " "

    rewritten = _DIMENSION_EXPR.sub(_dim_repl, source)
    rewritten = _VOLTAGE_EXPR.sub(_volt_repl, rewritten)
    return fold_whitespace(rewritten)


def canonical_unit_text(text: str | None) -> str:
    return apply_unit_normalization(text).lower()


def _status(left: set[str], right: set[str]) -> str:
    if not left or not right:
        return "none"
    if left & right:
        return "match"
    return "conflict"


def _dimension_status(q_dims: tuple[DimensionSpec, ...], c_dims: tuple[DimensionSpec, ...]) -> str:
    """Plain set-intersection (see _status) is too lenient for a genuine
    multi-dimension "AxB" product: {2,3} intersecting {3,3} would call that
    a "match" on the strength of the shared "3" alone, and it's also blind
    to order -- {2,3} and {3,2} are the same set, but "2x3 Base Spacer" and
    "3x2 Base Spacer" are different catalog SKUs.

    Only tightens the *multi*-dimension case (both sides have 2+ numbers);
    a single dimension keeps the original intersection-based behavior
    unchanged, since there's no order or multi-value ambiguity to guard
    against there.
    """
    if not q_dims or not c_dims:
        return "none"
    if len(q_dims) >= 2 and len(c_dims) >= 2:
        q_keys = [item.magnitude_key() for item in q_dims]
        c_keys = [item.magnitude_key() for item in c_dims]
        if sorted(q_keys) != sorted(c_keys) or q_keys != c_keys:
            return "conflict"
        return "match"
    return _status({item.magnitude_key() for item in q_dims}, {item.magnitude_key() for item in c_dims})


# "2 x 3" is unambiguous dimension-pair notation on its own -- some catalog
# families never attach a unit to either number (this catalog's Base/
# Intermediate Spacer: "SPACER BASE 2 x 3", no "\"" or "IN" anywhere), so
# _DIMENSION_EXPR's required-unit suffix above can't see a dimension there
# at all, and neither extract_dimensions() nor _dimension_status() above
# ever gets two dimensions to compare -- confirmed live: even a cleanly
# space-separated '2" x 3" SPACER' (no glued-text issue at all) ties
# 80.0/80.0 against both the genuine 2x3 candidate and its transposed 3x2
# sibling SKU, purely from order-blind token-overlap scoring elsewhere,
# since this comparison never has any signal to cap the wrong one with.
#
# Kept as a separate, narrower extractor rather than loosening
# _DIMENSION_EXPR's own unit requirement -- that regex also feeds the
# apply_units auto-detect heuristic and ordinary single-dimension conflict
# checks, neither designed around a bare, unit-less number pair, and
# widening it there risks misreading unrelated digit-x-digit text. This
# also deliberately does NOT touch tokenize_description/PreparedText.tokens
# (the token/fuzzy text-overlap scoring) at all -- only this dedicated
# comparison, so it can only ever narrow an already-tied field_scores
# via score_cap, never change how any other candidate is ranked.
_UNIT_MARK = "[\"″”'′]"
_BARE_NUMBER_PAIR_RE = re.compile(
    rf"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*{_UNIT_MARK}?\s*[xX]\s*(\d+(?:\.\d+)?)\s*{_UNIT_MARK}?(?![A-Za-z0-9])"
)


def extract_bare_number_pairs(text: str | None) -> tuple[tuple[Fraction, Fraction], ...]:
    source = fold_whitespace(text)
    if not source:
        return ()
    pairs: list[tuple[Fraction, Fraction]] = []
    for match in _BARE_NUMBER_PAIR_RE.finditer(source):
        try:
            pairs.append((Fraction(match.group(1)), Fraction(match.group(2))))
        except (ValueError, ZeroDivisionError):
            continue
    return tuple(pairs)


def _bare_pair_status(
    q_pairs: tuple[tuple[Fraction, Fraction], ...], c_pairs: tuple[tuple[Fraction, Fraction], ...]
) -> str:
    """Same order/set discipline as _dimension_status, for a pair neither
    side attached a unit to. Only the query's first pair is compared (the
    size pair is the distinguishing feature; a second incidental "x" match
    elsewhere in a long description is rare and not worth the ambiguity)."""
    if not q_pairs or not c_pairs:
        return "none"
    query = q_pairs[0]
    if query in c_pairs:
        return "match"
    query_sorted = tuple(sorted(query))
    if any(query_sorted == tuple(sorted(candidate)) for candidate in c_pairs):
        return "conflict"  # same two numbers, different order -- a different SKU
    return "conflict"  # a genuinely different size pair


def compare_extracted_units(
    q_volts: tuple[VoltageSpec, ...],
    q_dims: tuple[DimensionSpec, ...],
    c_volts: tuple[VoltageSpec, ...],
    c_dims: tuple[DimensionSpec, ...],
    q_amps: tuple[AmpSpec, ...] = (),
    c_amps: tuple[AmpSpec, ...] = (),
    q_pairs: tuple[tuple[Fraction, Fraction], ...] = (),
    c_pairs: tuple[tuple[Fraction, Fraction], ...] = (),
) -> UnitComparison:
    q_vmag = {item.magnitude_key() for item in q_volts}
    c_vmag = {item.magnitude_key() for item in c_volts}
    q_amag = {item.magnitude_key() for item in q_amps}
    c_amag = {item.magnitude_key() for item in c_amps}

    voltage_status = _status(q_vmag, c_vmag)
    if voltage_status == "match":
        q_pol = {item.polarity for item in q_volts if item.polarity}
        c_pol = {item.polarity for item in c_volts if item.polarity}
        if q_pol and c_pol and q_pol.isdisjoint(c_pol):
            voltage_status = "conflict"

    dimension_status = _dimension_status(q_dims, c_dims)
    if dimension_status == "none":
        dimension_status = _bare_pair_status(q_pairs, c_pairs)
    amperage_status = _status(q_amag, c_amag)

    lines: list[str] = []
    mismatches: list[str] = []
    if voltage_status == "match" and q_volts and c_volts:
        lines.append(f"Voltage: {c_volts[0].display()} ↔ {q_volts[0].raw} — Match")
    elif voltage_status == "conflict" and q_volts and c_volts:
        requested = ", ".join(item.display() for item in q_volts)
        catalog_disp = ", ".join(item.display() for item in c_volts)
        reason = f"Voltage mismatch: requested {requested}, catalog {catalog_disp}"
        lines.append(reason)
        mismatches.append(reason)

    if dimension_status == "match" and q_dims and c_dims:
        lines.append(f"Dimension: {c_dims[0].raw} ↔ {q_dims[0].raw} — Match")
    elif dimension_status == "conflict" and q_dims and c_dims:
        reason = f"Dimension mismatch: requested {q_dims[0].raw}, catalog {c_dims[0].raw}"
        lines.append(reason)
        mismatches.append(reason)

    if amperage_status == "match" and q_amps and c_amps:
        lines.append(f"Amperage: {c_amps[0].display()} ↔ {q_amps[0].raw} — Match")
    elif amperage_status == "conflict" and q_amps and c_amps:
        requested = ", ".join(item.display() for item in q_amps)
        catalog_disp = ", ".join(item.display() for item in c_amps)
        reason = f"Amperage mismatch: requested {requested}, catalog {catalog_disp}"
        lines.append(reason)
        mismatches.append(reason)

    cap = None
    if voltage_status == "conflict":
        cap = VOLTAGE_CONFLICT_SCORE_CAP
    if dimension_status == "conflict":
        cap = DIMENSION_CONFLICT_SCORE_CAP if cap is None else min(cap, DIMENSION_CONFLICT_SCORE_CAP)
    if amperage_status == "conflict":
        cap = AMPERAGE_CONFLICT_SCORE_CAP if cap is None else min(cap, AMPERAGE_CONFLICT_SCORE_CAP)
    return UnitComparison(
        voltage_status=voltage_status,
        dimension_status=dimension_status,
        amperage_status=amperage_status,
        lines=tuple(dict.fromkeys(lines)),
        mismatch_reasons=tuple(mismatches),
        score_cap=cap,
    )


def compare_units(query: str | None, catalog: str | None) -> UnitComparison:
    return compare_extracted_units(
        extract_voltages(query),
        extract_dimensions(query),
        extract_voltages(catalog),
        extract_dimensions(catalog),
        extract_amperages(query),
        extract_amperages(catalog),
        extract_bare_number_pairs(query),
        extract_bare_number_pairs(catalog),
    )


def voltages_conflict(query: str | None, catalog: str | None) -> bool:
    return compare_units(query, catalog).voltage_status == "conflict"
