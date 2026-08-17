from app.ai.errors import AIConfigurationError
from app.ai.mock_provider import MockAIProvider
from app.ai.openrouter_provider import OpenRouterProvider
from app.ai.provider import AIProvider
from app.config import get_settings


def get_ai_provider() -> AIProvider:
    """Return the configured AI backend. Unknown names fail closed."""
    settings = get_settings()
    provider_name = (settings.ai_provider or "").strip().lower()
    if provider_name == "mock":
        return MockAIProvider()
    if provider_name == "openrouter":
        return OpenRouterProvider.from_settings(settings)
    raise AIConfigurationError("Unknown AI provider")
