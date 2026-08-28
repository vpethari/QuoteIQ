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

_DIMENSION_EXPR = re.compile(
    r"""
    (?<![A-Z0-9])
    (?:
        (?P<mixed_whole>\d+)\s*-\s*(?P<mixed_num>\d+)\s*/\s*(?P<mixed_den>\d+)
      | (?P<frac_num>\d+)\s*/\s*(?P<frac_den>\d+)
      | (?P<decimal>\d+\.\d+)
      | (?P<whole>\d+)
    )
    \s*
    (?:
        INCHES|INCH|INS|\bIN\b
      | ["\u2033\u201d]
      | FEET|FOOT|FT(?![A-Z])
      | ['\u2032]
    )
    (?![A-Z0-9])
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
            if match.group("mixed_whole"):
                inches = Fraction(int(match.group("mixed_whole"))) + Fraction(
                    int(match.group("mixed_num")), int(match.group("mixed_den"))
                )
            elif match.group("frac_num"):
                inches = Fraction(int(match.group("frac_num")), int(match.group("frac_den")))
            elif match.group("decimal"):
                inches = Fraction(match.group("decimal"))
            else:
                inches = Fraction(int(match.group("whole")))
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


def compare_extracted_units(
    q_volts: tuple[VoltageSpec, ...],
    q_dims: tuple[DimensionSpec, ...],
    c_volts: tuple[VoltageSpec, ...],
    c_dims: tuple[DimensionSpec, ...],
    q_amps: tuple[AmpSpec, ...] = (),
    c_amps: tuple[AmpSpec, ...] = (),
) -> UnitComparison:
    q_vmag = {item.magnitude_key() for item in q_volts}
    c_vmag = {item.magnitude_key() for item in c_volts}
    q_dmag = {item.magnitude_key() for item in q_dims}
    c_dmag = {item.magnitude_key() for item in c_dims}
    q_amag = {item.magnitude_key() for item in q_amps}
    c_amag = {item.magnitude_key() for item in c_amps}

    voltage_status = _status(q_vmag, c_vmag)
    if voltage_status == "match":
        q_pol = {item.polarity for item in q_volts if item.polarity}
        c_pol = {item.polarity for item in c_volts if item.polarity}
        if q_pol and c_pol and q_pol.isdisjoint(c_pol):
            voltage_status = "conflict"

    dimension_status = _status(q_dmag, c_dmag)
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
    )


def voltages_conflict(query: str | None, catalog: str | None) -> bool:
    return compare_units(query, catalog).voltage_status == "conflict"
