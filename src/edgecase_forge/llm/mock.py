from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import BaseModel

from .base import LLMResult, Message, Usage


class MockProvider:
    name = "mock"
    model = "deterministic-baseline-v1.0"

    @property
    def experiment_config(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "implementation": f"{type(self).__module__}.{type(self).__qualname__}",
            "temperature": 0.0,
        }

    def generate_json(
        self,
        messages: Sequence[Message],
        response_model: type[BaseModel],
    ) -> tuple[BaseModel, LLMResult]:
        payload = {
            "summary": "Deterministic no-finding response used for plumbing tests.",
            "findings": [],
            "generated_test_code": "",
        }
        if "invariants" in response_model.model_fields:
            payload["invariants"] = []
        content = json.dumps(payload)
        return response_model.model_validate(payload), LLMResult(
            content=content,
            provider=self.name,
            model=self.model,
            latency_seconds=0.0,
            usage=Usage(input_tokens=0, output_tokens=0),
            request_id="mock-request",
        )
