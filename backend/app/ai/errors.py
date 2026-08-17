class AIProviderError(Exception):
    """Safe, user-facing AI failure. Must never include secrets, prompts, or message text."""


class AIConfigurationError(AIProviderError):
    """Missing or invalid local AI settings."""


class AIAuthenticationError(AIProviderError):
    """OpenRouter rejected the configured API key."""


class AIRateLimitError(AIProviderError):
    """OpenRouter rate-limited the request."""


class AIInsufficientBalanceError(AIProviderError):
    """OpenRouter account has insufficient credits."""


class AIModelUnavailableError(AIProviderError):
    """Configured OpenRouter model was not found."""


class AIUnavailableError(AIProviderError):
    """Network, timeout, or upstream server failure."""


class AIResponseValidationError(AIProviderError):
    """The model response was empty, not JSON, or did not match AIAnalysisResult."""


def public_ai_message(exc: AIProviderError) -> str:
    if isinstance(exc, AIAuthenticationError):
        return "OpenRouter authentication failed"
    if isinstance(exc, AIInsufficientBalanceError):
        return "OpenRouter balance insufficient"
    if isinstance(exc, AIModelUnavailableError):
        return "OpenRouter model unavailable"
    if isinstance(exc, AIRateLimitError):
        return "AI rate limit reached"
    if isinstance(exc, AIConfigurationError):
        return str(exc)
    return "AI provider unavailable"


def public_ai_status(exc: AIProviderError) -> int:
    if isinstance(exc, AIConfigurationError):
        return 500
    if isinstance(exc, AIRateLimitError):
        return 429
    return 502
