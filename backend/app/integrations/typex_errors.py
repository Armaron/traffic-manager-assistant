class TypeXError(Exception):
    """Safe TypeX integration failure. Never include message text or raw MCP payloads."""


class TypeXConfigurationError(TypeXError):
    """Missing or invalid TypeX settings."""


class TypeXConnectionError(TypeXError):
    """TypeX Desktop MCP is unreachable."""


class TypeXProtocolError(TypeXError):
    """MCP response was malformed."""


class TypeXToolCallError(TypeXProtocolError):
    """MCP tools/call returned isError=true. Never includes raw MCP content."""


class TypeXToolUnavailableError(TypeXError):
    """Requested TypeX tool is missing, write-only, or not allowed."""


def public_typex_message(exc: TypeXError) -> str:
    if isinstance(exc, TypeXConfigurationError):
        text = str(exc)
        if "Unknown TypeX mode" in text:
            return "Unknown TypeX mode"
        return "TypeX configuration required"
    if isinstance(exc, TypeXConnectionError):
        return "TypeX is not connected"
    if isinstance(exc, TypeXToolUnavailableError):
        return "TypeX read operation failed"
    return "TypeX MCP unavailable"


def public_typex_status(exc: TypeXError) -> int:
    if isinstance(exc, TypeXConfigurationError):
        return 400
    if isinstance(exc, TypeXConnectionError):
        return 503
    return 502
