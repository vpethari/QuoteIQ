from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic import ValidationError

from ai.models import (
    AIAuditRecord,
    AICandidateInput,
    AIDecision,
    AIReasoningRequest,
    AIReasoningResult,
    FinalMatchResult,
)
from ai.prompt_builder import PROMPT_VERSION
from ai.provider import AINotConfiguredError, AIReasoningProvider
from ai.validator import ValidationOutcome, validate_ai_selection
from matching.category_defaults import normalize_raw_customer_text
from matching.description_normalize import expand_query_for_retrieval, tokenize_description
from matching.matcher import ProductMatcher
from matching.models import MatchCandidate, MatchResult, MatchStatus, ProductRecord, QuoteLine
from matching.noise import strip_quantity_and_noise
from matching.request_cache import end_request_cache, start_request_cache, use_request_cache


def _catalog_terminology_note(raw_description: str) -> str | None:
    """The deterministic matcher's own catalog-terminology expansion for
    this description (see matching.category_defaults), surfaced for the AI
    only when it actually adds something -- most queries don't need it, so
    this keeps the common case's prompt unchanged."""
    if not raw_description:
        return None
    normalized = normalize_raw_customer_text(raw_description)
    expanded = expand_query_for_retrieval(strip_quantity_and_noise(normalized))
    if not expanded:
        return None
    if set(tokenize_description(expanded)) == set(tokenize_description(raw_description)):
        return None
    return expanded


@dataclass
class AIPolicyConfig:
    confident_threshold: float = 90.0
    review_threshold: float = 50.0
    max_candidates: int = 6
    max_concurrent_requests: int = 12


@dataclass
class InMemoryAuditStore:
    records: list[AIAuditRecord] = field(default_factory=list)

    def add(self, record: AIAuditRecord) -> None:
        self.records.append(record)


class AIMatchingService:
    """Runs deterministic matching, then optional AI reasoning and validation."""

    def __init__(
        self,
        matcher: ProductMatcher,
        catalog: Sequence[ProductRecord],
        provider: AIReasoningProvider | None,
        policy: AIPolicyConfig | None = None,
        audit_store: InMemoryAuditStore | None = None,
    ) -> None:
        self.matcher = matcher
        self.catalog = list(catalog)
        self.provider = provider
        self.policy = policy or AIPolicyConfig()
        self.audit_store = audit_store or InMemoryAuditStore()

    def match_description(
        self,
        requested_description: str,
        quantity: int | float | None = None,
        source_file: str | None = None,
        source_sheet: str | None = None,
        source_row: int | None = None,
        use_ai: bool = True,
    ) -> FinalMatchResult:
        line = QuoteLine(
            source_file=source_file or "",
            source_sheet=source_sheet or "",
            source_row=source_row or 0,
            requested_description=requested_description,
            quantity=quantity,
        )
        return self.match_line(line, use_ai=use_ai)

    def match_line(self, line: QuoteLine, use_ai: bool = True) -> FinalMatchResult:
        deterministic = self.matcher.match_line(line)
        if not use_ai or self.provider is None:
            return final_from_deterministic(deterministic, ai_enabled=False)
        if _skip_ai_reasoning(deterministic):
            return final_from_deterministic(deterministic, ai_enabled=False)

        top = deterministic.candidates[: self.policy.max_candidates]
        request = AIReasoningRequest(
            requested_description=line.requested_description,
            quantity=line.quantity,
            catalog_terminology_note=_catalog_terminology_note(line.requested_description),
            candidates=[
                AICandidateInput(
                    official_part_number=item.official_part_number,
                    description=item.description,
                    salsify_id=item.salsify_id,
                    deterministic_score=item.score,
                    match_reasons=list(item.match_reasons),
                )
                for item in top
            ],
        )
        try:
            raw = self.provider.reason_about_candidates(request)
            if isinstance(raw, AIReasoningResult):
                ai_result = AIReasoningResult.model_validate(raw.model_dump())
            else:
                ai_result = AIReasoningResult.model_validate(raw)
        except ValidationError as exc:
            audit = self._audit(line, top, None, validation_rejected=True)
            self.audit_store.add(audit)
            return _rejected(
                deterministic,
                line,
                f"Malformed AI response: {exc.error_count()} validation error(s)",
                provider=self.provider.provider_name,
            )
        except AINotConfiguredError:
            raise
        except Exception as exc:
            audit = self._audit(line, top, None, validation_rejected=True)
            self.audit_store.add(audit)
            return _rejected(
                deterministic,
                line,
                f"AI provider error: {exc}",
                provider=self.provider.provider_name,
            )

        outcome = validate_ai_selection(ai_result, top, self.catalog)
        status, selected, summary = apply_decision_policy(
            ai_result, outcome, self.policy, has_candidates=bool(top)
        )
        if status != AIDecision.CONFIDENT_MATCH:
            selected_pn = None
            selected_desc = None
            selected_salsify = None
            selected_orderable = None
        else:
            selected_pn = outcome.selected_part_number
            selected_desc = outcome.selected_description
            selected_salsify = outcome.selected_salsify_id
            selected_orderable = outcome.selected_orderable_part_number

        rejected = status != AIDecision.CONFIDENT_MATCH and bool(ai_result.selected_part_number) and not outcome.accepted
        if not outcome.accepted and ai_result.selected_part_number:
            rejected = True
            if status == AIDecision.CONFIDENT_MATCH:
                status = AIDecision.REVIEW_REQUIRED
                selected_pn = selected_desc = selected_salsify = selected_orderable = None
                summary = outcome.reason

        det_score = _deterministic_score_for_selection(deterministic, selected_pn)
        ai_conf = ai_result.confidence_percentage
        final_conf = combine_confidence(det_score, ai_conf, status)

        reasoning = summary
        if status == AIDecision.REVIEW_REQUIRED and not ai_result.selected_part_number:
            reasoning = ai_result.reasoning_summary or summary

        audit = self._audit(
            line,
            top,
            ai_result,
            validation_rejected=rejected,
            selected_override=selected_pn,
        )
        self.audit_store.add(audit)

        return FinalMatchResult(
            source_file=line.source_file or None,
            source_sheet=line.source_sheet or None,
            source_row=line.source_row or None,
            requested_description=line.requested_description,
            quantity=line.quantity,
            matched_part_number=selected_pn,
            matched_description=selected_desc,
            matched_salsify_id=selected_salsify,
            matched_orderable_part_number=selected_orderable,
            deterministic_score=det_score,
            ai_confidence=ai_conf,
            final_confidence=final_conf,
            match_status=status.value,
            reasoning_summary=reasoning,
            matched_attributes=list(ai_result.matched_attributes),
            conflicting_attributes=list(ai_result.conflicting_attributes),
            candidate_count=len(top),
            candidate_details=_candidate_details(top),
            validation_rejected=rejected,
            ai_enabled=True,
            prompt_version=PROMPT_VERSION,
            provider=self.provider.provider_name,
            raw_row=dict(deterministic.raw_row),
        )

    def match_quote(self, lines: Sequence[QuoteLine], use_ai: bool = True) -> list[FinalMatchResult]:
        """Match every line, running the (I/O-bound) AI reasoning calls
        concurrently instead of one-at-a-time. Deterministic matching and AI
        validation/audit are unaffected -- only the wall-clock time to
        process a whole quote changes. Results preserve input line order
        regardless of which call finishes first.

        Wraps the whole quote in one request-scoped candidate cache (as
        ProductMatcher.match_quote already does for non-AI quotes) so
        duplicate/near-duplicate lines in the same quote reuse retrieval and
        scoring work instead of repeating it. ContextVars aren't inherited by
        thread pool workers, so each worker rebinds the same cache instance
        explicitly via use_request_cache().
        """
        lines = list(lines)
        cache = start_request_cache()
        try:
            if len(lines) <= 1 or not use_ai or self.provider is None:
                return [self.match_line(line, use_ai=use_ai) for line in lines]

            def _match_with_cache(line: QuoteLine) -> FinalMatchResult:
                use_request_cache(cache)
                return self.match_line(line, use_ai=use_ai)

            workers = max(1, min(self.policy.max_concurrent_requests, len(lines)))
            results: list[FinalMatchResult | None] = [None] * len(lines)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_index = {
                    executor.submit(_match_with_cache, line): index
                    for index, line in enumerate(lines)
                }
                for future in future_to_index:
                    results[future_to_index[future]] = future.result()
            return results  # type: ignore[return-value]
        finally:
            end_request_cache()

    def _audit(
        self,
        line: QuoteLine,
        candidates: Sequence[MatchCandidate],
        ai_result: AIReasoningResult | None,
        validation_rejected: bool,
        selected_override: str | None = None,
    ) -> AIAuditRecord:
        return AIAuditRecord(
            source_file=line.source_file or None,
            source_sheet=line.source_sheet or None,
            source_row=line.source_row or None,
            requested_description=line.requested_description,
            candidate_part_numbers=[item.official_part_number for item in candidates],
            deterministic_scores={item.official_part_number: item.score for item in candidates},
            ai_decision=None if ai_result is None else ai_result.decision.value,
            selected_part_number=(
                selected_override
                if selected_override is not None
                else (None if ai_result is None else ai_result.selected_part_number)
            ),
            ai_confidence=None if ai_result is None else ai_result.confidence_percentage,
            reasoning_summary=None if ai_result is None else ai_result.reasoning_summary,
            provider=self.provider.provider_name if self.provider else "none",
            model=self.provider.model_name if self.provider else None,
            prompt_version=PROMPT_VERSION,
            validation_rejected=validation_rejected,
        )


def apply_decision_policy(
    ai_result: AIReasoningResult,
    outcome: ValidationOutcome,
    policy: AIPolicyConfig,
    has_candidates: bool,
) -> tuple[AIDecision, str | None, str]:
    if not has_candidates:
        return AIDecision.NO_MATCH, None, ai_result.reasoning_summary or "No relevant candidate."
    if ai_result.decision == AIDecision.NO_MATCH and ai_result.selected_part_number is None:
        return AIDecision.NO_MATCH, None, ai_result.reasoning_summary or "No relevant candidate."

    if ai_result.selected_part_number is None:
        return AIDecision.REVIEW_REQUIRED, None, ai_result.reasoning_summary

    if ai_result.selected_part_number and not outcome.accepted:
        return (
            AIDecision.REVIEW_REQUIRED,
            None,
            outcome.reason,
        )

    if ai_result.confidence_percentage is None or ai_result.confidence_percentage < policy.review_threshold:
        return AIDecision.REVIEW_REQUIRED, None, "AI confidence is below the review threshold."

    if (
        ai_result.decision == AIDecision.CONFIDENT_MATCH
        and outcome.accepted
        and ai_result.confidence_percentage >= policy.confident_threshold
    ):
        return AIDecision.CONFIDENT_MATCH, outcome.selected_part_number, ai_result.reasoning_summary

    return AIDecision.REVIEW_REQUIRED, None, ai_result.reasoning_summary


def combine_confidence(
    deterministic_score: float,
    ai_confidence: float | None,
    status: AIDecision,
) -> float:
    if ai_confidence is None:
        return deterministic_score
    if status == AIDecision.CONFIDENT_MATCH:
        return round(min(deterministic_score, ai_confidence), 4)
    return round(ai_confidence, 4)


def _skip_ai_reasoning(result: MatchResult) -> bool:
    """True when there is nothing left for AI reasoning to usefully add.

    Only skips a *verified, conflict-free part-number identity* match: the
    customer specified a real part number, it was found exactly, and the
    description doesn't contradict it. Purely description-driven matches
    still go through AI even when they score as an exact/unique text match,
    since that is exactly the case AI exists to catch (e.g. a family ID or
    an unrelated product that happens to share wording). Also skips when
    there are no candidates at all -- there is nothing to select from.
    """
    if not result.candidates:
        return True
    return bool(result.part_number_match) and result.match_status == MatchStatus.EXACT_MATCH


def final_from_deterministic(result: MatchResult, ai_enabled: bool) -> FinalMatchResult:
    return FinalMatchResult(
        source_file=result.source_file,
        source_sheet=result.source_sheet,
        source_row=result.source_row,
        requested_description=result.requested_description,
        quantity=result.quantity,
        matched_part_number=result.matched_part_number,
        matched_description=result.matched_description,
        matched_salsify_id=result.matched_salsify_id,
        matched_orderable_part_number=result.matched_orderable_part_number,
        deterministic_score=result.top_score,
        ai_confidence=None,
        final_confidence=result.matching_percentage,
        match_status=result.match_status.value,
        reasoning_summary="; ".join(result.match_reasons),
        matched_attributes=[],
        conflicting_attributes=[],
        candidate_count=result.candidate_count,
        candidate_details=_candidate_details(result.candidates),
        validation_rejected=False,
        ai_enabled=ai_enabled,
        prompt_version=None,
        provider=None,
        requested_part_number=result.requested_part_number,
        detected_salsify_id=result.detected_salsify_id,
        detected_part_number=result.detected_part_number,
        customer_raw_text=result.customer_raw_text,
        part_number_match_score=result.part_number_match_score,
        description_match_score=result.description_match_score,
        overall_match_score=result.overall_match_score,
        part_number_match=result.part_number_match,
        description_match=result.description_match,
        raw_row=dict(result.raw_row),
    )


def _deterministic_score_for_selection(result: MatchResult, selected: str | None) -> float:
    if selected:
        for item in result.candidates:
            if item.official_part_number == selected:
                return item.score
    return result.top_score


def _candidate_details(candidates: Sequence[MatchCandidate]) -> list[dict]:
    return [
        {
            "official_part_number": item.official_part_number,
            "orderable_part_number": item.orderable_part_number,
            "description": item.description,
            "salsify_id": item.salsify_id,
            "deterministic_score": item.score,
            "match_reasons": list(item.match_reasons),
            "field_scores": dict(item.field_scores),
            "name": item.name,
        }
        for item in candidates
    ]


def _rejected(
    deterministic: MatchResult,
    line: QuoteLine,
    summary: str,
    provider: str,
) -> FinalMatchResult:
    return FinalMatchResult(
        source_file=line.source_file or None,
        source_sheet=line.source_sheet or None,
        source_row=line.source_row or None,
        requested_description=line.requested_description,
        quantity=line.quantity,
        matched_part_number=None,
        matched_description=None,
        matched_salsify_id=None,
        deterministic_score=deterministic.top_score,
        ai_confidence=None,
        final_confidence=deterministic.top_score,
        match_status=AIDecision.REVIEW_REQUIRED.value,
        reasoning_summary=summary,
        candidate_count=len(deterministic.candidates[:5]),
        candidate_details=_candidate_details(deterministic.candidates[:5]),
        validation_rejected=True,
        ai_enabled=True,
        prompt_version=PROMPT_VERSION,
        provider=provider,
        raw_row=dict(deterministic.raw_row),
    )
