from app.ai.mock_provider import MockAIProvider
from app.ai.provider import AIProvider
from app.config import get_settings


def get_ai_provider() -> AIProvider:
    """Return the configured AI backend. OpenRouter is reserved for a later phase."""
    provider_name = get_settings().ai_provider
    if provider_name == "mock":
        return MockAIProvider()
    if provider_name == "openrouter":
        raise NotImplementedError("OpenRouter provider is not implemented yet")
    raise ValueError(f"Unknown AI provider: {provider_name}")
