from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AIDecision(StrEnum):
    CONFIDENT_MATCH = "CONFIDENT_MATCH"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_MATCH = "NO_MATCH"


class CandidateEvaluation(BaseModel):
    official_part_number: str
    assessment: str
    score: float = Field(ge=0, le=100)


def _stringify_attribute_item(key: str | None, item: Any) -> str:
    """Render one matched/conflicting-attribute entry as a plain string,
    whatever shape the model actually returned it in (see
    AIReasoningResult.coerce_attribute_list)."""
    if isinstance(item, dict):
        text = "; ".join(
            f"{sub_key}: {', '.join(str(v) for v in sub_value) if isinstance(sub_value, list) else sub_value}"
            for sub_key, sub_value in item.items()
        )
    elif isinstance(item, list):
        text = ", ".join(str(entry) for entry in item)
    else:
        text = item if isinstance(item, str) else str(item)
    return f"{key}: {text}" if key is not None else text


class AIReasoningResult(BaseModel):
    decision: AIDecision
    selected_part_number: str | None = None
    # The model sometimes reports null instead of a number when it genuinely
    # can't quantify its confidence -- treat that as "not confident enough"
    # rather than a schema violation that discards an otherwise-valid response.
    confidence_percentage: float | None = Field(default=None, ge=0, le=100)
    reasoning_summary: str
    matched_attributes: list[str] = Field(default_factory=list)
    conflicting_attributes: list[str] = Field(default_factory=list)
    candidate_evaluations: list[CandidateEvaluation] = Field(default_factory=list)

    @field_validator("selected_part_number", mode="before")
    @classmethod
    def empty_part_to_none(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("matched_attributes", "conflicting_attributes", mode="before")
    @classmethod
    def coerce_attribute_list(cls, value: Any) -> Any:
        # The model sometimes returns these as a dict (attribute -> note)
        # instead of a flat list of strings, or as a list whose individual
        # items are themselves dicts/objects (e.g. a candidate-evaluation-
        # shaped entry) instead of plain strings. Flatten either shape rather
        # than reject an otherwise-valid response over a shape mismatch.
        if isinstance(value, dict):
            return [_stringify_attribute_item(key, item) for key, item in value.items()]
        if isinstance(value, list):
            return [_stringify_attribute_item(None, item) for item in value]
        return value


class AICandidateInput(BaseModel):
    official_part_number: str
    description: str
    salsify_id: str
    deterministic_score: float
    match_reasons: list[str] = Field(default_factory=list)


class AIReasoningRequest(BaseModel):
    requested_description: str
    quantity: int | float | None = None
    candidates: list[AICandidateInput]
    # The deterministic matcher's own catalog-terminology expansion (e.g.
    # "SS CONN" -> "SET SCREW CONNECTOR", "FLEX CONN" -> "SQUEEZE
    # CONNECTOR") applied for retrieval/scoring, only set when it actually
    # changes the wording -- see matching.category_defaults. Without this,
    # the AI reasons from the customer's raw abbreviation alone and can
    # reject a candidate the deterministic matcher already knows is correct
    # (confirmed live: "SS" read as "Stainless Steel" instead of "Set
    # Screw", rejecting a genuine plain-steel set-screw connector).
    catalog_terminology_note: str | None = None


class AIAuditRecord(BaseModel):
    source_file: str | None = None
    source_sheet: str | None = None
    source_row: int | None = None
    requested_description: str
    candidate_part_numbers: list[str]
    deterministic_scores: dict[str, float]
    ai_decision: str | None = None
    selected_part_number: str | None = None
    ai_confidence: float | None = None
    reasoning_summary: str | None = None
    provider: str
    model: str | None = None
    prompt_version: str
    validation_rejected: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FinalMatchResult(BaseModel):
    source_file: str | None = None
    source_sheet: str | None = None
    source_row: int | None = None
    requested_description: str
    quantity: int | float | None = None
    matched_part_number: str | None = None
    matched_description: str | None = None
    matched_salsify_id: str | None = None
    matched_orderable_part_number: str | None = None
    deterministic_score: float
    ai_confidence: float | None = None
    final_confidence: float
    match_status: str
    reasoning_summary: str
    matched_attributes: list[str] = Field(default_factory=list)
    conflicting_attributes: list[str] = Field(default_factory=list)
    candidate_count: int
    candidate_details: list[dict[str, Any]] = Field(default_factory=list)
    validation_rejected: bool = False
    ai_enabled: bool = True
    prompt_version: str | None = None
    provider: str | None = None
    requested_part_number: str | None = None
    detected_salsify_id: str | None = None
    detected_part_number: str | None = None
    customer_raw_text: str | None = None
    part_number_match_score: float | None = None
    description_match_score: float | None = None
    overall_match_score: float | None = None
    part_number_match: bool = False
    description_match: bool = False
