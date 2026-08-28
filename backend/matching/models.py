from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


def _api_productcode(value: object | None) -> str | None:
    from matching.productcode import productcode_as_text

    text = productcode_as_text(value)
    return text or None


class MatchStatus(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_MATCH = "NO_MATCH"


@dataclass(frozen=True)
class MatchingConfig:
    weight_exact: float = 0.40
    weight_token: float = 0.25
    weight_fuzzy: float = 0.20
    weight_attribute: float = 0.15
    high_confidence_min: float = 90.0
    min_match_threshold: float = 25.0
    min_score_gap: float = 8.0
    score_tie_epsilon: float = 0.5
    max_candidates: int = 10
    review_candidate_limit: int = 3
    candidate_floor: float = 10.0
    retrieval_candidate_limit: int = 100
    search_text_candidate_limit: int = 30
    part_number_weight: float = 0.70
    description_weight: float = 0.30
    description_compatible_min: float = 50.0
    description_conflict_max: float = 40.0
    confidence_weight_productcode: float = 0.50
    confidence_weight_name: float = 0.15
    confidence_weight_description: float = 0.20
    confidence_weight_description2: float = 0.05
    confidence_weight_numeric: float = 0.10
    ambiguous_confidence_cap: float = 86.0
    numeric_conflict_cap: float = 40.0
    partial_match_max_confidence: float = 78.0

    def __post_init__(self) -> None:
        total = (
            self.weight_exact
            + self.weight_token
            + self.weight_fuzzy
            + self.weight_attribute
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"matching weights must sum to 1.0, got {total}")
        confidence_total = (
            self.confidence_weight_productcode
            + self.confidence_weight_name
            + self.confidence_weight_description
            + self.confidence_weight_description2
            + self.confidence_weight_numeric
        )
        if abs(confidence_total - 1.0) > 1e-6:
            raise ValueError(f"confidence field weights must sum to 1.0, got {confidence_total}")


@dataclass(frozen=True)
class ProductRecord:
    salsify_id: str
    official_part_number: str | None
    description: str | None
    record_type: str
    parent_id: str | None = None
    catalog_number_and_description: str | None = None
    name: str | None = None
    description2: str | None = None
    catalog_row_id: str | None = None

    @property
    def product_code(self) -> str:
        """Authoritative catalog part number (PostgreSQL Productcode)."""
        return (self.official_part_number or "").strip()


@dataclass(frozen=True)
class QuoteLine:
    source_file: str
    source_sheet: str
    source_row: int
    requested_description: str
    quantity: int | float | None = None
    requested_part_number: str | None = None


@dataclass(frozen=True)
class ScoreBreakdown:
    exact: float
    token: float
    fuzzy: float
    attribute: float
    final: float


@dataclass
class MatchCandidate:
    official_part_number: str
    description: str
    salsify_id: str
    score: float
    score_percentage: float
    match_reasons: list[str] = field(default_factory=list)
    breakdown: ScoreBreakdown | None = None
    field_scores: dict[str, float] = field(default_factory=dict)
    matched_field: str | None = None
    identifier_evidence: dict[str, object] = field(default_factory=dict)
    name: str | None = None
    description2: str | None = None
    rank: int | None = None


@dataclass
class MatchResult:
    source_file: str | None
    source_sheet: str | None
    source_row: int | None
    requested_description: str
    quantity: int | float | None
    matched_part_number: str | None
    matched_description: str | None
    matched_salsify_id: str | None
    matching_percentage: float
    confidence_level: str
    match_status: MatchStatus
    candidate_count: int
    candidates: list[MatchCandidate]
    match_reasons: list[str]
    top_score: float
    second_score: float | None
    score_gap: float | None
    requested_part_number: str | None = None
    part_number_match_score: float | None = None
    description_match_score: float | None = None
    overall_match_score: float | None = None
    part_number_match: bool = False
    description_match: bool = False
    customer_raw_text: str | None = None
    detected_salsify_id: str | None = None
    detected_part_number: str | None = None
    match_breakdown: dict[str, Any] | None = None
    quote_line_id: str | None = None
    selection_type: str | None = None
    match_type: str | None = None
    match_type_label: str | None = None
    original_confidence: float | None = None

    def to_api_dict(self) -> dict[str, Any]:
        from output.candidates import candidate_api_dict
        from output.match_evidence import build_match_evidence

        return {
            "source_file": self.source_file,
            "source_sheet": self.source_sheet,
            "source_row": self.source_row,
            "customer_raw_text": self.customer_raw_text or self.requested_description,
            "requested_part_number": _api_productcode(self.requested_part_number),
            "requested_description": self.requested_description,
            "detected_salsify_id": self.detected_salsify_id,
            "detected_part_number": self.detected_part_number,
            "quantity": self.quantity,
            "matched_part_number": _api_productcode(self.matched_part_number),
            "matched_description": self.matched_description,
            "matched_salsify_id": _api_productcode(self.matched_salsify_id),
            "matching_percentage": self.matching_percentage,
            "part_number_match_score": self.part_number_match_score,
            "description_match_score": self.description_match_score,
            "overall_match_score": self.overall_match_score,
            "part_number_match": self.part_number_match,
            "description_match": self.description_match,
            "confidence_level": self.confidence_level,
            "match_status": self.match_status.value,
            "candidate_count": self.candidate_count,
            "top_score": self.top_score,
            "second_score": self.second_score,
            "score_gap": self.score_gap,
            "match_reasons": list(self.match_reasons),
            "match_breakdown": self.match_breakdown,
            "quote_line_id": self.quote_line_id,
            "selection_type": self.selection_type,
            "match_type": self.match_type,
            "match_type_label": self.match_type_label,
            "original_confidence": self.original_confidence,
            "match_evidence": build_match_evidence(self),
            "candidates": [
                candidate_api_dict(item, line_status=self.match_status.value)
                for item in self.candidates
            ],
        }


@dataclass(frozen=True)
class QuoteMatchCsvRow:
    source_file: str
    source_sheet: str
    source_row: str
    requested_description: str
    quantity: str
    matched_atkore_part_number: str
    matched_atkore_description: str
    matching_percentage: str
    confidence: str
    match_status: str

    def as_dict(self) -> dict[str, str]:
        return {
            "Source File": self.source_file,
            "Source Sheet": self.source_sheet,
            "Source Row": self.source_row,
            "Requested Description": self.requested_description,
            "Quantity": self.quantity,
            "Matched Atkore Part Number": self.matched_atkore_part_number,
            "Matched Atkore Description": self.matched_atkore_description,
            "Matching Percentage": self.matching_percentage,
            "Confidence": self.confidence,
            "Match Status": self.match_status,
        }


def match_result_to_csv_row(result: MatchResult) -> QuoteMatchCsvRow:
    return QuoteMatchCsvRow(
        source_file=result.source_file or "",
        source_sheet=result.source_sheet or "",
        source_row="" if result.source_row is None else str(result.source_row),
        requested_description=result.requested_description,
        quantity="" if result.quantity is None else str(result.quantity),
        matched_atkore_part_number=result.matched_part_number or "",
        matched_atkore_description=result.matched_description or "",
        matching_percentage=f"{result.matching_percentage:.2f}",
        confidence=result.confidence_level,
        match_status=result.match_status.value,
    )
