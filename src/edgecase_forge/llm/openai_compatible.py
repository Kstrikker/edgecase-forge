from __future__ import annotations

import json
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx
from pydantic import BaseModel, ValidationError

from .base import AttemptAccounting, LLMResult, Message, Usage
from .capabilities import CapabilityProfile
from .errors import (
    AuthenticationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ProviderError,
    RateLimitError,
    ResponseParseError,
    ResponseTruncatedError,
    ResponseValidationError,
)
from .response_schema import flat_strict_schema


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
        max_output_tokens: int = 8192,
        reasoning_effort: str | None = None,
        max_transport_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise AuthenticationError(f"Missing API key for {name}")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")
        if max_transport_retries < 0:
            raise ValueError("max_transport_retries cannot be negative")
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._capabilities = capabilities
        self._temperature = temperature
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort
        self._max_transport_retries = max_transport_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep
        self._client = client or httpx.Client(timeout=timeout_seconds)

    @property
    def experiment_config(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "implementation": f"{type(self).__module__}.{type(self).__qualname__}",
            "base_url": self._base_url,
            "temperature": self._temperature,
            "max_output_tokens": self._max_output_tokens,
            "reasoning_effort": self._reasoning_effort,
            "timeout_seconds": self._timeout_seconds,
            "max_transport_retries": self._max_transport_retries,
            "retry_backoff_seconds": self._retry_backoff_seconds,
            "response_format": self._capabilities.structured_output,
            "strict_json_schema": self._capabilities.strict_json_schema,
        }

    def generate_json(
        self,
        messages: Sequence[Message],
        response_model: type[BaseModel],
    ) -> tuple[BaseModel, LLMResult]:
        self._capabilities.require_json()
        response_format = self._response_format(response_model)
        first_result = self._request(messages, response_format)
        try:
            return self._validate_result(first_result, response_model), first_result
        except (ResponseParseError, ResponseValidationError) as exc:
            repair_error = _sanitized_error(exc)
            if isinstance(exc, ResponseTruncatedError):
                repair_instruction = (
                    "Regenerate the complete object from the beginning. Keep summary under "
                    "80 words, report only the single highest-confidence defect, and return "
                    "one compact executable pytest module."
                )
            else:
                repair_instruction = "Correct the response without changing its meaning."
            repair_messages = [
                *messages,
                Message(role="assistant", content=first_result.content[:12000]),
                Message(
                    role="user",
                    content=(
                        "Your previous output failed validation with this error: "
                        f"{repair_error}. {repair_instruction} Return exactly one corrected "
                        "JSON object matching "
                        "the required schema. Put executable Python directly in the "
                        "generated_test_code string using standard JSON escaping. Do not "
                        "use Markdown fences or commentary."
                    ),
                ),
            ]
            try:
                repaired = self._request(repair_messages, response_format)
            except ProviderError as repair_failure:
                repair_failure.accounting = _combine_accounting(
                    first_result.accounting,
                    repair_failure.accounting,
                    semantic_attempts=2,
                    repair_used=True,
                )
                repair_failure.preserve_model_responses(first_result.content)
                raise
            combined = _combine_results(first_result, repaired)
            try:
                parsed = self._validate_result(repaired, response_model)
            except (ResponseParseError, ResponseValidationError) as final_error:
                final_error.accounting = combined.accounting
                final_error.preserve_model_responses(
                    first_result.content,
                    repaired.content,
                )
                raise
            return parsed, combined

    def _response_format(self, response_model: type[BaseModel]) -> dict[str, Any]:
        if self._capabilities.structured_output == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__.lower(),
                    "strict": self._capabilities.strict_json_schema,
                    "schema": flat_strict_schema(response_model),
                },
            }
        return {"type": "json_object"}

    def _request(
        self,
        messages: Sequence[Message],
        response_format: dict[str, Any],
    ) -> LLMResult:
        started = time.monotonic()
        body = {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "response_format": response_format,
        }
        if self._reasoning_effort is not None:
            body["reasoning_effort"] = self._reasoning_effort
        response: httpx.Response | None = None
        for attempt in range(self._max_transport_retries + 1):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
            except httpx.TimeoutException as exc:
                if attempt == self._max_transport_retries:
                    raise ProviderTimeoutError(
                        f"{self.name} request timed out",
                        _request_accounting(started, attempt + 1, response),
                    ) from exc
                self._sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            except httpx.HTTPError as exc:
                raise ProviderUnavailableError(
                    f"{self.name} request failed",
                    _request_accounting(started, attempt + 1, response),
                ) from exc

            if response.status_code in {401, 403}:
                raise AuthenticationError(
                    f"{self.name} rejected the API key",
                    _request_accounting(started, attempt + 1, response),
                )
            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers.get("retry-after"))
                hard_quota = _is_hard_quota(response)
                can_retry = (
                    not hard_quota
                    and retry_after is not None
                    and 0 <= retry_after <= 60
                    and attempt < self._max_transport_retries
                )
                if can_retry:
                    self._sleep(retry_after)
                    continue
                message = (
                    f"{self.name} quota exhausted"
                    if hard_quota
                    else f"{self.name} rate limit reached"
                )
                raise RateLimitError(
                    message,
                    retry_after,
                    _request_accounting(started, attempt + 1, response),
                )
            if response.status_code >= 500:
                retry_after = _parse_retry_after(response.headers.get("retry-after"))
                if attempt < self._max_transport_retries:
                    delay = (
                        retry_after
                        if retry_after is not None and 0 <= retry_after <= 60
                        else self._retry_backoff_seconds * (2**attempt)
                    )
                    self._sleep(min(delay, 60.0))
                    continue
                raise ProviderUnavailableError(
                    f"{self.name} is temporarily unavailable",
                    _request_accounting(started, attempt + 1, response),
                )
            if response.status_code >= 400:
                raise ProviderUnavailableError(
                    f"{self.name} returned HTTP {response.status_code}",
                    _request_accounting(started, attempt + 1, response),
                )
            break

        if response is None:
            raise ProviderUnavailableError(
                f"{self.name} returned no response",
                _request_accounting(started, self._max_transport_retries + 1, None),
            )

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ResponseParseError(
                "Provider response was not valid JSON",
                _request_accounting(started, attempt + 1, response),
            ) from exc
        try:
            choice = payload["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ResponseParseError(
                "Provider response did not contain message content",
                _request_accounting(started, attempt + 1, response),
            ) from exc
        usage_payload = payload.get("usage") or {}
        finish_reason_value = choice.get("finish_reason")
        finish_reason = (
            str(finish_reason_value) if finish_reason_value is not None else None
        )
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
            transport_attempts=attempt + 1,
            request_ids=tuple(
                value for value in (response.headers.get("x-request-id"),) if value
            ),
            finish_reason=finish_reason,
        )

    def _validate_result(
        self,
        result: LLMResult,
        response_model: type[BaseModel],
    ) -> BaseModel:
        if _is_truncated_finish_reason(result.finish_reason):
            raise ResponseTruncatedError(
                f"Provider stopped before completing JSON ({result.finish_reason})",
                result.accounting,
            )
        try:
            return self._validate(result.content, response_model)
        except ResponseParseError as exc:
            if _looks_like_truncated_json(result.content):
                raise ResponseTruncatedError(
                    "Provider stopped before completing JSON",
                    result.accounting,
                ) from exc
            raise

    def _validate(self, content: str, response_model: type[BaseModel]) -> BaseModel:
        try:
            if self._capabilities.structured_output == "json_schema":
                payload: Any = json.loads(content)
            else:
                payload = _extract_first_json_value(content)
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


def _extract_first_json_value(content: str) -> Any:
    value = _strip_json_fence(content)
    first_object = value.find("{")
    if first_object < 0:
        raise json.JSONDecodeError("No JSON object found", value, 0)
    payload, _ = json.JSONDecoder().raw_decode(value, first_object)
    return payload


def _sanitized_error(error: Exception) -> str:
    return str(error).replace("\n", " ")[:2000]


def _combine_results(first: LLMResult, repaired: LLMResult) -> LLMResult:
    accounting = _combine_accounting(
        first.accounting,
        repaired.accounting,
        semantic_attempts=2,
        repair_used=True,
    )
    return LLMResult(
        content=repaired.content,
        provider=repaired.provider,
        model=repaired.model,
        latency_seconds=accounting.latency_seconds,
        usage=accounting.usage,
        request_id=repaired.request_id,
        semantic_attempts=accounting.semantic_attempts,
        transport_attempts=accounting.transport_attempts,
        repair_used=accounting.repair_used,
        request_ids=accounting.request_ids,
        finish_reason=repaired.finish_reason,
        finish_reasons=accounting.finish_reasons,
    )


def _combine_accounting(
    first: AttemptAccounting,
    second: AttemptAccounting,
    *,
    semantic_attempts: int,
    repair_used: bool,
) -> AttemptAccounting:
    return AttemptAccounting(
        usage=Usage(
            input_tokens=first.usage.input_tokens + second.usage.input_tokens,
            output_tokens=first.usage.output_tokens + second.usage.output_tokens,
        ),
        latency_seconds=first.latency_seconds + second.latency_seconds,
        semantic_attempts=semantic_attempts,
        transport_attempts=first.transport_attempts + second.transport_attempts,
        repair_used=repair_used,
        request_ids=first.request_ids + second.request_ids,
        finish_reasons=first.finish_reasons + second.finish_reasons,
    )


def _request_accounting(
    started: float, attempts: int, response: httpx.Response | None
) -> AttemptAccounting:
    request_id = response.headers.get("x-request-id") if response is not None else None
    return AttemptAccounting(
        latency_seconds=time.monotonic() - started,
        semantic_attempts=1,
        transport_attempts=attempts,
        request_ids=(request_id,) if request_id else (),
    )


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


def _is_hard_quota(response: httpx.Response) -> bool:
    message = response.text.lower()
    markers = (
        "per day",
        "per_day",
        "perday",
        "daily quota",
        "requests per day",
    )
    return any(marker in message for marker in markers)


def _is_truncated_finish_reason(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower().replace("-", "_")
    return normalized in {"length", "max_tokens", "max_token"}


def _looks_like_truncated_json(content: str) -> bool:
    value = content.rstrip()
    if not value.startswith("{"):
        return False
    return value.endswith(("[", "{", ",", ":"))
