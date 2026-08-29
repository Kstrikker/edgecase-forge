import json

import httpx
import pytest

from edgecase_forge.llm.base import Message
from edgecase_forge.llm.capabilities import PORTABLE_OPENAI_COMPATIBLE
from edgecase_forge.llm.errors import AuthenticationError, ResponseValidationError
from edgecase_forge.llm.openai_compatible import OpenAICompatibleProvider
from edgecase_forge.llm.schemas import BaselineAnalysis


def _response(content: str, status: int = 200) -> httpx.Response:
    if status != 200:
        return httpx.Response(status, json={"error": "rejected"})
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
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
        capabilities=PORTABLE_OPENAI_COMPATIBLE,
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

    parsed, _ = _provider(handler).generate_json([Message("user", "scan")], BaselineAnalysis)
    assert parsed.summary == "fixed"
    assert len(requests) == 2


def test_second_invalid_response_fails() -> None:
    provider = _provider(lambda request: _response("{}"))
    with pytest.raises(ResponseValidationError):
        provider.generate_json([Message("user", "scan")], BaselineAnalysis)


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

    parsed, _ = _provider(handler).generate_json([Message("user", "scan")], BaselineAnalysis)
    assert parsed.summary == "ok"
    assert calls == 2


def test_exhausted_rate_limit_raises_after_bounded_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    from edgecase_forge.llm.errors import RateLimitError

    with pytest.raises(RateLimitError):
        _provider(handler, max_transport_retries=2).generate_json(
            [Message("user", "scan")], BaselineAnalysis
        )
    assert calls == 3


def test_accepts_valid_json_followed_by_provider_commentary() -> None:
    content = (
        '{"summary":"ok","findings":[],"generated_test_code":""}'
        "\nI corrected the requested JSON."
    )
    parsed, _ = _provider(lambda request: _response(content)).generate_json(
        [Message("user", "scan")], BaselineAnalysis
    )
    assert parsed.summary == "ok"


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
