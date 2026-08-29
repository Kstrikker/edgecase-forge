from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LLMResult:
    content: str
    provider: str
    model: str
    latency_seconds: float
    usage: Usage = field(default_factory=Usage)
    request_id: str | None = None


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(
        self,
        messages: Sequence[Message],
        response_model: type[BaseModel],
    ) -> tuple[BaseModel, LLMResult]: ...


JsonObject = dict[str, Any]

