from __future__ import annotations

from .base import AttemptAccounting


class ProviderError(RuntimeError):
    """Base provider error with a user-safe message."""

    def __init__(
        self, message: str, accounting: AttemptAccounting | None = None
    ) -> None:
        super().__init__(message)
        self.accounting = accounting or AttemptAccounting()


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


class ResponseValidationError(ProviderError):
    pass
