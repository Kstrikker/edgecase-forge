import json

import httpx
import pytest

from edgecase_forge.llm.base import Message
from edgecase_forge.llm.capabilities import STRICT_OPENAI_COMPATIBLE
from edgecase_forge.llm.errors import (
    AuthenticationError,
    RateLimitError,
    ResponseParseError,
    ResponseTruncatedError,
    ResponseValidationError,
)
from edgecase_forge.llm.openai_compatible import OpenAICompatibleProvider
from edgecase_forge.llm.schemas import BaselineAnalysis


def _response(
    content: str,
    status: int = 200,
    *,
    finish_reason: str | None = "stop",
) -> httpx.Response:
    if status != 200:
        return httpx.Response(status, json={"error": "rejected"})
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": content}, "finish_reason": finish_reason}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
        headers={"x-request-id": "req-1"},
    )


def _provider(handler, **kwargs) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="gemini",
        model="locked-model",
        api_key="test-key",
        base_url="https://example.test/v1",
        capabilities=STRICT_OPENAI_COMPATIBLE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        **kwargs,
    )


def test_normalizes_valid_json_response() -> None:
    payload = {"summary": "ok", "findings": [], "generated_test_code": ""}
    provider = _provider(lambda request: _response(json.dumps(payload)))
    parsed, result = provider.generate_json([Message("user", "scan")], BaselineAnalysis)
    assert parsed.summary == "ok"
    assert result.usage.input_tokens == 10
    assert result.request_id == "req-1"
    assert result.finish_reason == "stop"
    assert result.accounting.finish_reasons == ("stop",)


def test_sends_reasoning_effort_and_larger_completion_budget() -> None:
    request_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_body.update(json.loads(request.content))
        return _response('{"summary":"ok","findings":[],"generated_test_code":""}')

    provider = _provider(handler, reasoning_effort="low")
    provider.generate_json([Message("user", "scan")], BaselineAnalysis)

    assert request_body["reasoning_effort"] == "low"
    assert request_body["max_tokens"] == 8192
    assert provider.experiment_config["reasoning_effort"] == "low"
    assert provider.experiment_config["max_output_tokens"] == 8192


def test_sends_flat_strict_schema_with_descriptions() -> None:
    request_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_body.update(json.loads(request.content))
        return _response('{"summary":"ok","findings":[],"generated_test_code":""}')

    _provider(handler).generate_json([Message("user", "scan")], BaselineAnalysis)
    response_format = request_body["response_format"]
    schema = response_format["json_schema"]["schema"]

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert "reasoning_effort" not in request_body
    assert schema["required"] == ["summary", "findings", "generated_test_code"]
    assert schema["additionalProperties"] is False
    finding = schema["properties"]["findings"]["items"]
    expected_finding_fields = [
        "title",
        "severity",
        "endpoint",
        "claim",
        "evidence",
        "test_file",
        "test_name",
        "reproduced",
    ]
    assert list(finding["properties"]) == expected_finding_fields
    assert finding["required"] == expected_finding_fields
    assert finding["additionalProperties"] is False
    assert all(item.get("description") for item in schema["properties"].values())
    assert all(item.get("description") for item in finding["properties"].values())
    serialized = json.dumps(schema)
    for unsupported in ("$defs", "$ref", "anyOf", "oneOf", "minLength"):
        assert unsupported not in serialized


def test_standard_json_decoder_unescapes_multiline_python_once() -> None:
    code = 'def test_path():\n    value = "C:\\\\tmp"\n    assert value.endswith("tmp")\n'
    payload = {"summary": "ok", "findings": [], "generated_test_code": code}
    parsed, _ = _provider(lambda request: _response(json.dumps(payload))).generate_json(
        [Message("user", "scan")], BaselineAnalysis
    )
    assert parsed.generated_test_code == code


def test_pydantic_rejects_schema_compliant_shape_with_extra_property() -> None:
    payload = {
        "summary": "ok",
        "findings": [],
        "generated_test_code": "",
        "unexpected": True,
    }
    with pytest.raises(ResponseValidationError, match="Extra inputs are not permitted"):
        _provider(lambda request: _response(json.dumps(payload))).generate_json(
            [Message("user", "scan")], BaselineAnalysis
        )


def test_repair_prompt_contains_validation_error_and_runs_once() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _response('{"summary": "missing fields"}')
        body = json.loads(request.content)
        assert "failed validation with this error" in body["messages"][-1]["content"]
        assert "findings" in body["messages"][-1]["content"]
        return _response('{"summary":"fixed","findings":[],"generated_test_code":""}')

    parsed, result = _provider(handler).generate_json(
        [Message("user", "scan")], BaselineAnalysis
    )
    assert parsed.summary == "fixed"
    assert len(requests) == 2
    assert result.usage.input_tokens == 20
    assert result.usage.output_tokens == 40
    assert result.semantic_attempts == 2
    assert result.transport_attempts == 2
    assert result.repair_used is True
    assert result.accounting.finish_reasons == ("stop", "stop")


def test_truncated_response_gets_one_concise_repair() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _response('{"summary":"unfinished","findings":[', finish_reason="length")
        body = json.loads(request.content)
        repair = body["messages"][-1]["content"]
        assert "stopped before completing JSON" in repair
        assert "single highest-confidence defect" in repair
        return _response('{"summary":"fixed","findings":[],"generated_test_code":""}')

    parsed, result = _provider(handler).generate_json(
        [Message("user", "scan")], BaselineAnalysis
    )
    assert parsed.summary == "fixed"
    assert len(requests) == 2
    assert result.repair_used is True
    assert result.accounting.finish_reasons == ("length", "stop")


def test_second_truncated_response_preserves_both_attempts() -> None:
    provider = _provider(
        lambda request: _response('{"summary":"unfinished",', finish_reason="MAX_TOKENS")
    )
    with pytest.raises(ResponseTruncatedError) as captured:
        provider.generate_json([Message("user", "scan")], BaselineAnalysis)
    assert captured.value.accounting.finish_reasons == (
        "MAX_TOKENS",
        "MAX_TOKENS",
    )
    assert len(captured.value.model_response_sha256) == 2


def test_second_invalid_response_fails() -> None:
    provider = _provider(lambda request: _response("{}"))
    with pytest.raises(ResponseValidationError) as captured:
        provider.generate_json([Message("user", "scan")], BaselineAnalysis)
    accounting = captured.value.accounting
    assert accounting.usage.input_tokens == 20
    assert accounting.usage.output_tokens == 40
    assert accounting.semantic_attempts == 2
    assert accounting.transport_attempts == 2
    assert accounting.repair_used is True
    assert len(captured.value.model_response_sha256) == 2
    assert captured.value.model_response_excerpts == ("{}", "{}")


def test_authentication_error_is_not_repaired() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response("", status=401)

    with pytest.raises(AuthenticationError):
        _provider(handler).generate_json([Message("user", "scan")], BaselineAnalysis)
    assert calls == 1


def test_rate_limit_retries_transport_without_semantic_repair() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return _response('{"summary":"ok","findings":[],"generated_test_code":""}')

    parsed, result = _provider(handler).generate_json(
        [Message("user", "scan")], BaselineAnalysis
    )
    assert parsed.summary == "ok"
    assert calls == 2
    assert result.transport_attempts == 2
    assert result.semantic_attempts == 1
    assert result.repair_used is False


def test_rate_limit_without_retry_after_fails_without_blind_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    with pytest.raises(RateLimitError):
        _provider(handler, max_transport_retries=2).generate_json(
            [Message("user", "scan")], BaselineAnalysis
        )
    assert calls == 1


def test_hard_daily_quota_does_not_retry_even_with_retry_after() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            headers={"retry-after": "1"},
            json={"error": {"message": "Requests per day quota exceeded"}},
        )

    with pytest.raises(RateLimitError, match="quota exhausted"):
        _provider(handler).generate_json([Message("user", "scan")], BaselineAnalysis)
    assert calls == 1


def test_strict_schema_rejects_trailing_provider_commentary() -> None:
    content = (
        '{"summary":"ok","findings":[],"generated_test_code":""}'
        "\nI corrected the requested JSON."
    )
    with pytest.raises(ResponseParseError):
        _provider(lambda request: _response(content)).generate_json(
            [Message("user", "scan")], BaselineAnalysis
        )


def test_normalizes_single_evidence_string_to_list() -> None:
    content = json.dumps(
        {
            "summary": "ok",
            "findings": [
                {
                    "title": "Example",
                    "severity": "high",
                    "endpoint": "POST /orders",
                    "claim": "Example claim",
                    "evidence": "one source observation",
                    "test_file": "test_example.py",
                    "test_name": "test_example",
                    "reproduced": False,
                }
            ],
            "generated_test_code": "",
        }
    )
    parsed, _ = _provider(lambda request: _response(content)).generate_json(
        [Message("user", "scan")], BaselineAnalysis
    )
    assert parsed.findings[0].evidence == ["one source observation"]
