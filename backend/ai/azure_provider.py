from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Callable, TypeVar

import httpx
from pydantic import ValidationError

from ai.models import AIReasoningRequest, AIReasoningResult
from ai.prompt_builder import PROMPT_VERSION, SYSTEM_PROMPT_V1, build_user_prompt
from ai.provider import AINotConfiguredError, AIReasoningProvider

logger = logging.getLogger("quoteiq.ai")

T = TypeVar("T")


class AzureOpenAIReasoningProvider(AIReasoningProvider):
    provider_name = "azure_openai"

    # 429 (rate limit) and 5xx (transient server-side) are worth retrying;
    # everything else (4xx auth/validation) will fail the same way again.
    _RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str,
        timeout_seconds: float = 30.0,
        seed: int = 42,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not all([endpoint, api_key, deployment, api_version]):
            raise AINotConfiguredError("Azure OpenAI settings are incomplete.")
        self.endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self.deployment = deployment
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.model_name = deployment
        self.seed = seed
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        # One shared, thread-safe client for the provider's lifetime instead
        # of opening a new connection (TLS handshake included) per call --
        # concurrent match_quote workers reuse the same pooled connections.
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def close(self) -> None:
        self._client.close()

    def reason_about_candidates(self, request: AIReasoningRequest) -> AIReasoningResult:
        payload = [item.model_dump() for item in request.candidates]
        user_prompt = build_user_prompt(
            request.requested_description,
            request.quantity,
            json.dumps(payload, indent=2),
        )
        logger.debug(
            "Azure reasoning request prompt_version=%s candidate_count=%s",
            PROMPT_VERSION,
            len(request.candidates),
        )
        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version={self.api_version}"
        )
        body = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_V1},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            # Fixed seed for run-to-run reproducibility. Azure/OpenAI don't
            # guarantee bit-for-bit determinism even at temperature=0, but a
            # stable seed measurably reduces how often borderline candidates
            # flip between CONFIDENT_MATCH and REVIEW_REQUIRED across runs.
            "seed": self.seed,
            "response_format": {"type": "json_object"},
        }
        headers = {"api-key": self._api_key, "Content-Type": "application/json"}

        def _parse(raw_body: dict[str, Any]) -> AIReasoningResult:
            content = raw_body["choices"][0]["message"]["content"]
            parsed = _parse_json_content(content)
            return AIReasoningResult.model_validate(parsed)

        return self._request_with_retry(url, headers, body, _parse)

    def _request_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        parse: Callable[[dict[str, Any]], T],
    ) -> T:
        attempt = 0
        while True:
            try:
                response = self._client.post(url, headers=headers, json=body)
                response.raise_for_status()
                return parse(response.json())
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in self._RETRYABLE_STATUS_CODES or attempt >= self.max_retries:
                    raise
                delay = self._retry_delay(exc.response, attempt)
                logger.warning(
                    "Azure OpenAI request failed with %s (attempt %s/%s); retrying in %.1fs",
                    status,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise
                delay = self._retry_delay(None, attempt)
                logger.warning(
                    "Azure OpenAI request error (%s) (attempt %s/%s); retrying in %.1fs",
                    exc,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                # The model occasionally returns truncated/non-JSON content or a
                # payload that fails schema validation on an otherwise-200 response.
                # That's a transient generation glitch, not a permanent failure --
                # worth a retry same as a 5xx, up to the same attempt budget.
                if attempt >= self.max_retries:
                    raise
                delay = self._retry_delay(None, attempt)
                logger.warning(
                    "Azure OpenAI response failed to parse/validate (%s) (attempt %s/%s); retrying in %.1fs",
                    exc,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
            time.sleep(delay)
            attempt += 1

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    pass
        base = self.backoff_base_seconds * (2**attempt)
        return base + random.uniform(0, base * 0.25)


def _parse_json_content(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)
