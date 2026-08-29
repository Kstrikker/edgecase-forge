class ProviderError(RuntimeError):
    """Base provider error with a user-safe message."""


class AuthenticationError(ProviderError):
    pass


class RateLimitError(ProviderError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
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

