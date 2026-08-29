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
class AttemptAccounting:
    usage: Usage = field(default_factory=Usage)
    latency_seconds: float = 0.0
    semantic_attempts: int = 0
    transport_attempts: int = 0
    repair_used: bool = False
    request_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LLMResult:
    content: str
    provider: str
    model: str
    latency_seconds: float
    usage: Usage = field(default_factory=Usage)
    request_id: str | None = None
    semantic_attempts: int = 1
    transport_attempts: int = 1
    repair_used: bool = False
    request_ids: tuple[str, ...] = ()

    @property
    def accounting(self) -> AttemptAccounting:
        request_ids = self.request_ids or (
            (self.request_id,) if self.request_id is not None else ()
        )
        return AttemptAccounting(
            usage=self.usage,
            latency_seconds=self.latency_seconds,
            semantic_attempts=self.semantic_attempts,
            transport_attempts=self.transport_attempts,
            repair_used=self.repair_used,
            request_ids=request_ids,
        )


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(
        self,
        messages: Sequence[Message],
        response_model: type[BaseModel],
    ) -> tuple[BaseModel, LLMResult]: ...


JsonObject = dict[str, Any]
