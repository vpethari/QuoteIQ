from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from ai.models import (
    AIDecision,
    AIReasoningRequest,
    AIReasoningResult,
    CandidateEvaluation,
)
from matching.normalizer import canonical_text


class AINotConfiguredError(RuntimeError):
    """Raised when an AI provider is requested but credentials are missing."""


class AIReasoningProvider(ABC):
    provider_name: str = "base"
    model_name: str | None = None

    @abstractmethod
    def reason_about_candidates(self, request: AIReasoningRequest) -> AIReasoningResult:
        raise NotImplementedError


class UnconfiguredAIReasoningProvider(AIReasoningProvider):
    provider_name = "unconfigured"

    def reason_about_candidates(self, request: AIReasoningRequest) -> AIReasoningResult:
        raise AINotConfiguredError(
            "AI matching is enabled but no provider is configured. "
            "Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT, "
            "and AZURE_OPENAI_API_VERSION, or use the mock provider in tests."
        )


class MockAIReasoningProvider(AIReasoningProvider):
    """Test double. Never calls a network API."""

    provider_name = "mock"
    model_name = "mock-reasoning"

    def __init__(
        self,
        canned: AIReasoningResult | None = None,
        handler: Callable[[AIReasoningRequest], AIReasoningResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.canned = canned
        self.handler = handler
        self.error = error

    def reason_about_candidates(self, request: AIReasoningRequest) -> AIReasoningResult:
        if self.error is not None:
            raise self.error
        if self.handler is not None:
            return self.handler(request)
        if self.canned is not None:
            return self.canned
        return heuristic_reason(request)


def heuristic_reason(request: AIReasoningRequest) -> AIReasoningResult:
    """Deterministic mock policy used when no canned response is supplied.

    Ambiguous equivalent descriptions become REVIEW_REQUIRED. A single
    standout candidate may become CONFIDENT_MATCH. This does not invent
    part numbers.
    """
    candidates = request.candidates
    if not candidates:
        return AIReasoningResult(
            decision=AIDecision.NO_MATCH,
            selected_part_number=None,
            confidence_percentage=0,
            reasoning_summary="No deterministic candidates were supplied.",
            candidate_evaluations=[],
        )

    top = max(item.deterministic_score for item in candidates)
    leaders = [item for item in candidates if abs(item.deterministic_score - top) <= 0.5]
    query_canon = canonical_text(request.requested_description)
    equivalent = [
        item
        for item in leaders
        if canonical_text(item.description) == query_canon
        or abs(item.deterministic_score - 100.0) <= 0.5
    ]
    if len(equivalent) > 1:
        descriptions = {canonical_text(item.description) for item in equivalent}
        if len(descriptions) == 1 or len(equivalent) > 1:
            return AIReasoningResult(
                decision=AIDecision.REVIEW_REQUIRED,
                selected_part_number=None,
                confidence_percentage=40,
                reasoning_summary=(
                    "Multiple Atkore products have equivalent descriptions and the "
                    "supplied quote does not contain enough information to distinguish them."
                ),
                matched_attributes=[],
                conflicting_attributes=["multiple equivalent catalog descriptions"],
                candidate_evaluations=[
                    CandidateEvaluation(
                        official_part_number=item.official_part_number,
                        assessment="equivalent description; cannot distinguish",
                        score=item.deterministic_score,
                    )
                    for item in equivalent
                ],
            )

    if len(leaders) == 1 and leaders[0].deterministic_score >= 90:
        winner = leaders[0]
        return AIReasoningResult(
            decision=AIDecision.CONFIDENT_MATCH,
            selected_part_number=winner.official_part_number,
            confidence_percentage=95,
            reasoning_summary="A single high-scoring candidate is semantically consistent with the request.",
            matched_attributes=["unique high-scoring candidate"],
            conflicting_attributes=[],
            candidate_evaluations=[
                CandidateEvaluation(
                    official_part_number=winner.official_part_number,
                    assessment="unique confident candidate",
                    score=95,
                )
            ],
        )

    if top < 50:
        return AIReasoningResult(
            decision=AIDecision.NO_MATCH,
            selected_part_number=None,
            confidence_percentage=10,
            reasoning_summary="No candidate is sufficiently relevant.",
            candidate_evaluations=[],
        )

    return AIReasoningResult(
        decision=AIDecision.REVIEW_REQUIRED,
        selected_part_number=None,
        confidence_percentage=55,
        reasoning_summary="Candidates exist but evidence is insufficient for a confident match.",
        candidate_evaluations=[
            CandidateEvaluation(
                official_part_number=item.official_part_number,
                assessment="needs review",
                score=item.deterministic_score,
            )
            for item in candidates[:5]
        ],
    )
