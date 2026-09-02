from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai.models import AIDecision, AIReasoningResult, CandidateEvaluation
from ai.provider import MockAIReasoningProvider, UnconfiguredAIReasoningProvider, AINotConfiguredError
from ai.service import AIMatchingService, AIPolicyConfig, InMemoryAuditStore
from ai.validator import validate_ai_selection
from catalog.excel_loader import load_catalog_records, load_quote_lines
from matching.matcher import ProductMatcher
from matching.models import MatchCandidate, MatchStatus, ProductRecord, QuoteLine

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "Atkorepartsfile.xlsx"
QUOTE_PATH = ROOT / "data" / "inputfile.xlsx"


@pytest.fixture(scope="module")
def catalog_records() -> list[ProductRecord]:
    return load_catalog_records(CATALOG_PATH)


@pytest.fixture(scope="module")
def matcher(catalog_records: list[ProductRecord]) -> ProductMatcher:
    return ProductMatcher(catalog_records)


def _service(
    matcher: ProductMatcher,
    catalog_records: list[ProductRecord],
    provider: MockAIReasoningProvider,
) -> AIMatchingService:
    return AIMatchingService(
        matcher=matcher,
        catalog=catalog_records,
        provider=provider,
        policy=AIPolicyConfig(),
        audit_store=InMemoryAuditStore(),
    )


def _confident(part: str, confidence: float = 95) -> AIReasoningResult:
    return AIReasoningResult(
        decision=AIDecision.CONFIDENT_MATCH,
        selected_part_number=part,
        confidence_percentage=confidence,
        reasoning_summary="Mock selected a candidate.",
        matched_attributes=["mock"],
        conflicting_attributes=[],
        candidate_evaluations=[
            CandidateEvaluation(official_part_number=part, assessment="selected", score=confidence)
        ],
    )


def test_ai_selects_valid_candidate(matcher: ProductMatcher, catalog_records: list[ProductRecord]) -> None:
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=_confident("2EB40-B-SC")))
    result = service.match_description("10/3 MCT")
    assert result.match_status == "CONFIDENT_MATCH"
    assert result.matched_part_number == "2EB40-B-SC"
    assert result.deterministic_score == 100
    assert result.ai_confidence == 95
    assert result.final_confidence == 95
    assert result.matched_salsify_id == "NA1-2EB40-B-SC"


def test_ai_selects_nonexistent_candidate_rejected(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=_confident("FAKE-999")))
    result = service.match_description("10/3 MCT")
    assert result.match_status == "REVIEW_REQUIRED"
    assert result.matched_part_number is None
    assert result.validation_rejected is True


def test_ai_selects_family_id_rejected(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=_confident("F4_LTG_CBL")))
    result = service.match_description("120V LIGHTING CABLE")
    assert result.match_status == "REVIEW_REQUIRED"
    assert result.matched_part_number is None
    assert result.validation_rejected is True


def test_ai_returns_null_review_required(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    canned = AIReasoningResult(
        decision=AIDecision.REVIEW_REQUIRED,
        selected_part_number=None,
        confidence_percentage=40,
        reasoning_summary="No unique product.",
    )
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=canned))
    result = service.match_description("10/3 MCT")
    assert result.match_status == "REVIEW_REQUIRED"
    assert result.matched_part_number is None


def test_ai_returns_low_confidence_review_required(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=_confident("2EB40-B-SC", 20)))
    result = service.match_description("10/3 MCT")
    assert result.match_status == "REVIEW_REQUIRED"
    assert result.matched_part_number is None


def test_ai_returns_high_confidence_accepted(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=_confident("2EB40-B-SC", 99)))
    result = service.match_description("10/3 MCT")
    assert result.match_status == "CONFIDENT_MATCH"
    assert result.matched_part_number == "2EB40-B-SC"


def test_ai_candidate_list_is_enforced(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    # 1SA is a real catalog product but is not a candidate for "10/3 MCT".
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=_confident("1SA")))
    result = service.match_description("10/3 MCT")
    assert result.matched_part_number is None
    assert result.validation_rejected is True


def test_malformed_part_number_rejected(catalog_records: list[ProductRecord]) -> None:
    candidates = [
        MatchCandidate(
            official_part_number="2EB40-B-SC",
            description="10/3 MCT",
            salsify_id="NA1-2EB40-B-SC",
            score=100,
            score_percentage=100,
        )
    ]
    ai = _confident("2EB40-B-SC\n")
    outcome = validate_ai_selection(ai, candidates, catalog_records)
    assert outcome.accepted is False
    assert "malformed" in outcome.reason.lower()

    candidates = [
        MatchCandidate(
            official_part_number="NOT-IN-CATALOG",
            description="ghost",
            salsify_id="X",
            score=100,
            score_percentage=100,
        )
    ]
    ai = _confident("NOT-IN-CATALOG")
    outcome = validate_ai_selection(ai, candidates, catalog_records)
    assert outcome.accepted is False
    assert outcome.candidate_validated is True
    assert outcome.catalog_validated is False


def test_ambiguous_result_becomes_review_required(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    service = _service(matcher, catalog_records, MockAIReasoningProvider())
    result = service.match_description("120V LIGHTING WHIP W/PAULEX", quantity=5)
    assert result.match_status == "REVIEW_REQUIRED"
    assert result.matched_part_number is None
    assert "distinguish" in result.reasoning_summary.lower() or "equivalent" in result.reasoning_summary.lower()
    parts = {item["official_part_number"] for item in result.candidate_details}
    assert {"1LBP-W", "1LCP-W"} & parts
    assert all("field_scores" in item for item in result.candidate_details)
    assert all("name" in item for item in result.candidate_details)


def test_ai_skipped_for_verified_exact_part_number_match(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    def _fail_if_called(request):
        raise AssertionError("AI provider should not be called for a verified exact part-number match")

    service = _service(matcher, catalog_records, MockAIReasoningProvider(handler=_fail_if_called))
    line = QuoteLine(
        source_file="q.xlsx",
        source_sheet="Sheet1",
        source_row=2,
        requested_description="",
        quantity=5,
        requested_part_number="NA1-2DDDA10-HV",
    )
    result = service.match_line(line)
    assert result.match_status == MatchStatus.EXACT_MATCH.value
    assert result.matched_part_number == "2DDDA10-HV"
    assert result.ai_enabled is False
    assert result.ai_confidence is None


def test_ai_skipped_when_no_candidates(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    def _fail_if_called(request):
        raise AssertionError("AI provider should not be called with zero candidates")

    service = _service(matcher, catalog_records, MockAIReasoningProvider(handler=_fail_if_called))
    result = service.match_description("zzz totally unmatched gibberish zzz not a real product zzz")
    assert result.candidate_count == 0
    assert result.ai_enabled is False


def test_ai_still_runs_for_description_only_exact_match(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    """A description-only match that happens to score as exact/unique still
    goes through AI -- this is the case AI exists to catch (e.g. a family ID
    or unrelated product that shares wording), so it must not be skipped."""
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=_confident("2EB40-B-SC")))
    result = service.match_description("10/3 MCT")
    assert result.deterministic_score == 100
    assert result.ai_enabled is True
    assert result.ai_confidence == 95


def test_ai_disabled_falls_back_to_deterministic_matcher(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=_confident("2EB40-B-SC")))
    result = service.match_description("10/3 MCT", use_ai=False)
    assert result.ai_enabled is False
    assert result.ai_confidence is None
    assert result.match_status == MatchStatus.EXACT_MATCH.value
    assert result.matched_part_number == "2EB40-B-SC"


def test_azure_configuration_missing() -> None:
    provider = UnconfiguredAIReasoningProvider()
    with pytest.raises(AINotConfiguredError):
        provider.reason_about_candidates(
            __import__("ai.models", fromlist=["AIReasoningRequest"]).AIReasoningRequest(
                requested_description="x",
                candidates=[],
            )
        )


def test_malformed_ai_response(matcher: ProductMatcher, catalog_records: list[ProductRecord]) -> None:
    class BadProvider:
        provider_name = "bad"
        model_name = "bad"

        def reason_about_candidates(self, request):
            return {"decision": "YES_PLEASE", "confidence_percentage": "hot"}

    service = AIMatchingService(
        matcher=matcher,
        catalog=catalog_records,
        provider=BadProvider(),  # type: ignore[arg-type]
        audit_store=InMemoryAuditStore(),
    )
    result = service.match_description("10/3 MCT")
    assert result.match_status == "REVIEW_REQUIRED"
    assert result.validation_rejected is True
    assert result.matched_part_number is None


def test_multiple_quote_lines_with_mock_ai(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    lines = load_quote_lines(QUOTE_PATH)
    service = _service(matcher, catalog_records, MockAIReasoningProvider())
    results = service.match_quote(lines)
    assert len(results) == 3
    for result, line in zip(results, lines, strict=True):
        assert result.source_row == line.source_row
        assert result.requested_description == line.requested_description
        assert result.quantity == line.quantity
        assert result.match_status == "REVIEW_REQUIRED"
        assert result.matched_part_number is None
        assert result.deterministic_score == 100
        assert result.ai_confidence is not None


def test_audit_record_creation(matcher: ProductMatcher, catalog_records: list[ProductRecord]) -> None:
    store = InMemoryAuditStore()
    service = AIMatchingService(
        matcher=matcher,
        catalog=catalog_records,
        provider=MockAIReasoningProvider(canned=_confident("2EB40-B-SC")),
        audit_store=store,
    )
    service.match_description("10/3 MCT", source_file="inputfile.xlsx", source_sheet="Sheet1", source_row=2)
    assert len(store.records) == 1
    record = store.records[0]
    assert record.requested_description == "10/3 MCT"
    assert "2EB40-B-SC" in record.candidate_part_numbers
    assert record.ai_decision == "CONFIDENT_MATCH"
    assert record.selected_part_number == "2EB40-B-SC"
    assert record.provider == "mock"
    assert record.prompt_version == "v1"
    assert record.timestamp is not None


def test_pydantic_rejects_invalid_ai_json() -> None:
    with pytest.raises(ValidationError):
        AIReasoningResult.model_validate({"decision": "MAYBE"})


def test_null_confidence_percentage_is_accepted_not_a_schema_error() -> None:
    result = AIReasoningResult.model_validate(
        {
            "decision": "REVIEW_REQUIRED",
            "selected_part_number": None,
            "confidence_percentage": None,
            "reasoning_summary": "Model could not quantify its confidence.",
        }
    )
    assert result.confidence_percentage is None


def test_null_confidence_percentage_routed_to_review_required(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    canned = AIReasoningResult(
        decision=AIDecision.CONFIDENT_MATCH,
        selected_part_number="2EB40-B-SC",
        confidence_percentage=None,
        reasoning_summary="Model omitted a confidence score.",
    )
    service = _service(matcher, catalog_records, MockAIReasoningProvider(canned=canned))
    result = service.match_description("10/3 MCT")
    assert result.match_status == "REVIEW_REQUIRED"
    assert result.matched_part_number is None
    assert result.ai_confidence is None
    assert result.final_confidence == result.deterministic_score


def test_ai_preview_api_and_disabled_quote(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    from app.main import app, get_ai_provider, get_matcher

    app.dependency_overrides[get_matcher] = lambda: matcher
    app.dependency_overrides[get_ai_provider] = lambda: MockAIReasoningProvider()
    client = TestClient(app)
    try:
        preview = client.post(
            "/api/matching/ai-preview",
            json={"description": "120V SWITCH MODULE", "quantity": 10},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["match_status"] == "REVIEW_REQUIRED"
        assert body["matched_part_number"] is None
        assert "deterministic_score" in body
        assert "ai_confidence" in body

        quote = client.post(
            "/api/matching/quote",
            json={
                "use_ai": False,
                "lines": [
                    {
                        "requested_description": "120V SWITCH MODULE",
                        "quantity": 10,
                        "source_file": "inputfile.xlsx",
                        "source_sheet": "Sheet1",
                        "source_row": 4,
                    }
                ],
            },
        )
        assert quote.status_code == 200
        assert quote.json()["results"][0]["match_status"] == "REVIEW_REQUIRED"
    finally:
        app.dependency_overrides.clear()


def test_match_quote_runs_ai_calls_concurrently_and_preserves_order(
    matcher: ProductMatcher, catalog_records: list[ProductRecord]
) -> None:
    import time

    call_order: list[str] = []

    def _slow_handler(request):
        call_order.append(request.requested_description)
        time.sleep(0.2)
        return AIReasoningResult(
            decision=AIDecision.REVIEW_REQUIRED,
            selected_part_number=None,
            confidence_percentage=50,
            reasoning_summary=f"handled {request.requested_description}",
        )

    service = _service(matcher, catalog_records, MockAIReasoningProvider(handler=_slow_handler))
    service.policy.max_concurrent_requests = 6
    lines = [
        QuoteLine(
            source_file="q.xlsx",
            source_sheet="Sheet1",
            source_row=index,
            requested_description=f"120V LIGHTING WHIP W/PAULEX variant {index}",
            quantity=1,
        )
        for index in range(1, 7)
    ]

    started = time.perf_counter()
    results = service.match_quote(lines)
    elapsed = time.perf_counter() - started

    # 6 lines at 0.2s each: ~1.2s sequential vs. well under 1s in parallel.
    assert elapsed < 0.8, f"match_quote took {elapsed:.2f}s -- calls do not appear to run concurrently"
    assert len(call_order) == 6

    # Results must correspond to their input line by position, not completion order.
    for result, line in zip(results, lines, strict=True):
        assert result.source_row == line.source_row
        assert result.requested_description == line.requested_description


def test_ai_preview_unconfigured_returns_503(
    matcher: ProductMatcher,
) -> None:
    from app.main import app, get_ai_provider, get_matcher

    app.dependency_overrides[get_matcher] = lambda: matcher
    app.dependency_overrides[get_ai_provider] = lambda: UnconfiguredAIReasoningProvider()
    client = TestClient(app)
    try:
        response = client.post(
            "/api/matching/ai-preview",
            json={"description": "10/3 MCT", "quantity": 1},
        )
        assert response.status_code == 503
        assert "configured" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
