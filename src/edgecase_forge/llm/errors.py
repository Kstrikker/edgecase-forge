from __future__ import annotations

import hashlib

from .base import AttemptAccounting


class ProviderError(RuntimeError):
    """Base provider error with a user-safe message."""

    def __init__(
        self, message: str, accounting: AttemptAccounting | None = None
    ) -> None:
        super().__init__(message)
        self.accounting = accounting or AttemptAccounting()
        self.model_response_sha256: tuple[str, ...] = ()
        self.model_response_excerpts: tuple[str, ...] = ()

    def preserve_model_responses(self, *responses: str) -> None:
        self.model_response_sha256 = tuple(
            hashlib.sha256(item.encode("utf-8")).hexdigest() for item in responses
        )
        self.model_response_excerpts = tuple(item[:4000] for item in responses)


class AuthenticationError(ProviderError):
    pass


class RateLimitError(ProviderError):
    def __init__(
        self,
        message: str,
        retry_after: float | None = None,
        accounting: AttemptAccounting | None = None,
    ) -> None:
        super().__init__(message, accounting)
        self.retry_after = retry_after


class ProviderTimeoutError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class UnsupportedCapabilityError(ProviderError):
    pass


class ToolSchemaError(ProviderError):
    pass


class ResponseParseError(ProviderError):
    pass


class ResponseTruncatedError(ResponseParseError):
    pass


class ResponseValidationError(ProviderError):
    pass
