class SlackError(Exception):
    """Safe Slack integration failure. Never include secrets, tokens, or message text."""


class SlackConfigurationError(SlackError):
    """Missing or invalid Slack settings."""


class SlackAuthenticationError(SlackError):
    """Slack user token is missing, invalid, or revoked."""


class SlackPermissionError(SlackError):
    """Slack scopes or workspace policy do not allow the read."""


class SlackAppApprovalError(SlackConfigurationError):
    """Workspace requires app installation or admin approval."""


class SlackConnectionError(SlackError):
    """Slack API or Socket Mode is unreachable."""


class SlackRateLimitError(SlackError):
    """Slack HTTP 429 / rate_limited. Message never includes response bodies."""

    def __init__(
        self,
        message: str = "Slack rate limit reached",
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class SlackReadError(SlackError):
    """A Slack read operation failed."""


class SlackSocketError(SlackError):
    """Socket Mode protocol failure. Never includes envelope payloads."""


def public_slack_message(exc: SlackError) -> str:
    if isinstance(exc, SlackAppApprovalError):
        return "Slack app approval required"
    if isinstance(exc, SlackConfigurationError):
        text = str(exc)
        if "Unknown Slack mode" in text:
            return "Unknown Slack mode"
        return "Slack configuration required"
    if isinstance(exc, SlackAuthenticationError):
        return "Slack authentication failed"
    if isinstance(exc, SlackPermissionError):
        return "Slack permission denied"
    if isinstance(exc, SlackRateLimitError):
        return "Slack rate limit reached"
    if isinstance(exc, SlackConnectionError):
        return "Slack is not connected"
    if isinstance(exc, SlackSocketError):
        return "Slack socket unavailable"
    if isinstance(exc, SlackReadError):
        return "Slack read failed"
    return "Slack unavailable"


def public_slack_status(exc: SlackError) -> int:
    if isinstance(exc, SlackConfigurationError):
        return 400
    if isinstance(exc, SlackAuthenticationError):
        return 401
    if isinstance(exc, SlackPermissionError):
        return 403
    if isinstance(exc, SlackRateLimitError):
        return 429
    if isinstance(exc, SlackConnectionError):
        return 503
    return 502


def public_slack_code(exc: SlackError) -> str:
    if isinstance(exc, SlackAppApprovalError):
        return "slack_configuration"
    if isinstance(exc, SlackConfigurationError):
        return "slack_configuration"
    if isinstance(exc, SlackAuthenticationError):
        return "slack_authentication"
    if isinstance(exc, SlackPermissionError):
        return "slack_permission"
    if isinstance(exc, SlackRateLimitError):
        return "slack_rate_limit"
    if isinstance(exc, SlackConnectionError):
        return "slack_connection"
    if isinstance(exc, SlackSocketError):
        return "slack_socket"
    return "slack_api"
