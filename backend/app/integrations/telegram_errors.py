class TelegramError(Exception):
    """Safe Telegram integration failure. Never include secrets or message text."""


class TelegramConfigurationError(TelegramError):
    """Missing or invalid Telegram settings."""


class TelegramAuthorizationError(TelegramError):
    """Telegram user session is missing or invalid."""


class TelegramConnectionError(TelegramError):
    """Telegram API is unreachable."""


class TelegramRateLimitError(TelegramError):
    """Telegram FloodWait or rate limit. Never includes wait internals in its message."""

    def __init__(
        self,
        message: str = "Telegram rate limit reached",
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        # Internal only: lets auto sync wait out a flood instead of retrying blindly.
        self.retry_after_seconds = retry_after_seconds


class TelegramReadError(TelegramError):
    """A Telegram read operation failed."""


class TelegramAuthInProgressError(TelegramError):
    """Login currently owns the Telegram session file."""

    def __init__(self, message: str = "Telegram login is in progress") -> None:
        super().__init__(message)


class TelegramAuthFlowError(TelegramError):
    """Safe, structured login failure. Never include codes, passwords, or hashes."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retry_after = retry_after


def public_telegram_message(exc: TelegramError) -> str:
    if isinstance(exc, TelegramConfigurationError):
        text = str(exc)
        if "Unknown Telegram mode" in text:
            return "Unknown Telegram mode"
        return "Telegram configuration required"
    if isinstance(exc, TelegramAuthorizationError):
        return "Telegram authorization required"
    if isinstance(exc, TelegramAuthInProgressError):
        return "Telegram login is in progress"
    if isinstance(exc, TelegramAuthFlowError):
        return str(exc) or "Telegram login failed"
    if isinstance(exc, TelegramConnectionError):
        return "Telegram is not connected"
    if isinstance(exc, TelegramRateLimitError):
        return "Telegram rate limit reached"
    if isinstance(exc, TelegramReadError):
        return "Telegram read failed"
    return "Telegram unavailable"


def public_telegram_status(exc: TelegramError) -> int:
    if isinstance(exc, TelegramConfigurationError):
        return 400
    if isinstance(exc, TelegramAuthorizationError):
        return 401
    if isinstance(exc, TelegramAuthInProgressError):
        return 409
    if isinstance(exc, TelegramAuthFlowError):
        return exc.http_status
    if isinstance(exc, TelegramRateLimitError):
        return 429
    if isinstance(exc, TelegramConnectionError):
        return 503
    return 502
