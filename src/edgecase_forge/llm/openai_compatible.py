from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from .base import LLMResult, Message, Usage
from .capabilities import CapabilityProfile
from .errors import (
    AuthenticationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
    ResponseParseError,
    ResponseValidationError,
)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        model: str,
        api_key: str,
        base_url: str,
        capabilities: CapabilityProfile,
        timeout_seconds: float = 60.0,
        temperature: float = 0.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise AuthenticationError(f"Missing API key for {name}")
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._capabilities = capabilities
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def generate_json(
        self,
        messages: Sequence[Message],
        response_model: type[BaseModel],
    ) -> tuple[BaseModel, LLMResult]:
        self._capabilities.require_json()
        first_result = self._request(messages)
        try:
            return self._validate(first_result.content, response_model), first_result
        except (ResponseParseError, ResponseValidationError) as exc:
            repair_error = _sanitized_error(exc)
            repair_messages = [
                *messages,
                Message(role="assistant", content=first_result.content[:12000]),
                Message(
                    role="user",
                    content=(
                        "Your previous output failed validation with this error: "
                        f"{repair_error}. Correct the JSON and return corrected JSON only."
                    ),
                ),
            ]
            repaired = self._request(repair_messages)
            return self._validate(repaired.content, response_model), repaired

    def _request(self, messages: Sequence[Message]) -> LLMResult:
        started = time.monotonic()
        body = {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"{self.name} request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.name} request failed") from exc

        if response.status_code in {401, 403}:
            raise AuthenticationError(f"{self.name} rejected the API key")
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            raise RateLimitError(f"{self.name} rate limit reached", retry_after)
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"{self.name} is temporarily unavailable")
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"{self.name} returned HTTP {response.status_code}"
            )

        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ResponseParseError("Provider response did not contain message content") from exc
        usage_payload = payload.get("usage") or {}
        return LLMResult(
            content=content,
            provider=self.name,
            model=self.model,
            latency_seconds=time.monotonic() - started,
            usage=Usage(
                input_tokens=int(usage_payload.get("prompt_tokens", 0)),
                output_tokens=int(usage_payload.get("completion_tokens", 0)),
            ),
            request_id=response.headers.get("x-request-id"),
        )

    @staticmethod
    def _validate(content: str, response_model: type[BaseModel]) -> BaseModel:
        try:
            payload: Any = json.loads(_strip_json_fence(content))
        except json.JSONDecodeError as exc:
            raise ResponseParseError(f"Invalid JSON at character {exc.pos}") from exc
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in exc.errors()[:8]
            )
            raise ResponseValidationError(details) from exc


def _strip_json_fence(content: str) -> str:
    value = content.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    return value.strip()


def _sanitized_error(error: Exception) -> str:
    return str(error).replace("\n", " ")[:2000]


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None

