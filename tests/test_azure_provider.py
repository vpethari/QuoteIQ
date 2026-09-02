from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from ai.azure_provider import AzureOpenAIReasoningProvider
from ai.models import AIReasoningRequest


def _request() -> AIReasoningRequest:
    return AIReasoningRequest(requested_description="10/3 MCT", quantity=1, candidates=[])


def _success_body() -> dict:
    content = json.dumps(
        {
            "decision": "REVIEW_REQUIRED",
            "selected_part_number": None,
            "confidence_percentage": 40,
            "reasoning_summary": "ok",
        }
    )
    return {"choices": [{"message": {"content": content}}]}


def _provider(handler) -> AzureOpenAIReasoningProvider:
    return AzureOpenAIReasoningProvider(
        endpoint="https://example.openai.azure.com",
        api_key="key",
        deployment="dep",
        api_version="2024-10-21",
        max_retries=3,
        backoff_base_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )


def test_request_body_includes_fixed_seed_and_zero_temperature() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_success_body())

    provider = _provider(handler)
    provider.reason_about_candidates(_request())
    assert captured["body"]["seed"] == provider.seed
    assert captured["body"]["temperature"] == 0


def test_retries_on_429_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"})
        return httpx.Response(200, json=_success_body())

    provider = _provider(handler)
    result = provider.reason_about_candidates(_request())
    assert calls["count"] == 3
    assert result.reasoning_summary == "ok"


def test_retries_on_503_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 2:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=_success_body())

    provider = _provider(handler)
    result = provider.reason_about_candidates(_request())
    assert calls["count"] == 2
    assert result.reasoning_summary == "ok"


def test_gives_up_after_max_retries() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    provider = _provider(handler)
    with pytest.raises(httpx.HTTPStatusError):
        provider.reason_about_candidates(_request())
    assert calls["count"] == provider.max_retries + 1


def test_does_not_retry_non_retryable_status() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    provider = _provider(handler)
    with pytest.raises(httpx.HTTPStatusError):
        provider.reason_about_candidates(_request())
    assert calls["count"] == 1


def test_retries_on_malformed_json_content_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 2:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return httpx.Response(200, json=_success_body())

    provider = _provider(handler)
    result = provider.reason_about_candidates(_request())
    assert calls["count"] == 2
    assert result.reasoning_summary == "ok"


def test_gives_up_after_max_retries_on_schema_validation_failure() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        content = json.dumps({"decision": "NOT_A_REAL_DECISION"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    provider = _provider(handler)
    with pytest.raises(ValidationError):
        provider.reason_about_candidates(_request())
    assert calls["count"] == provider.max_retries + 1
