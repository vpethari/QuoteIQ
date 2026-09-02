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
