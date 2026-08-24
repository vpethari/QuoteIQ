from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ai.models import AIReasoningRequest, AIReasoningResult
from ai.prompt_builder import PROMPT_VERSION, SYSTEM_PROMPT_V1, build_user_prompt
from ai.provider import AINotConfiguredError, AIReasoningProvider

logger = logging.getLogger("quoteiq.ai")


class AzureOpenAIReasoningProvider(AIReasoningProvider):
    provider_name = "azure_openai"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not all([endpoint, api_key, deployment, api_version]):
            raise AINotConfiguredError("Azure OpenAI settings are incomplete.")
        self.endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self.deployment = deployment
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.model_name = deployment

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
            "response_format": {"type": "json_object"},
        }
        headers = {"api-key": self._api_key, "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _parse_json_content(content)
        return AIReasoningResult.model_validate(parsed)


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
