from __future__ import annotations

import os

from .base import LLMProvider
from .capabilities import STRICT_OPENAI_COMPATIBLE
from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
        "reasoning_effort": "low",
    },
    "grok": {
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "default_model": "grok-4-fast-non-reasoning",
        "reasoning_effort": None,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-5-mini",
        "reasoning_effort": None,
    },
}


def build_provider(name: str, model: str | None = None) -> LLMProvider:
    normalized = name.lower()
    if normalized == "mock":
        return MockProvider()
    if normalized not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}")
    profile = PROVIDERS[normalized]
    return OpenAICompatibleProvider(
        name=normalized,
        model=model or profile["default_model"],
        api_key=os.getenv(profile["api_key_env"], ""),
        base_url=profile["base_url"],
        capabilities=STRICT_OPENAI_COMPATIBLE,
        reasoning_effort=profile["reasoning_effort"],
    )
