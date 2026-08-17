from app.config import get_settings
from app.integrations.base import MessengerAdapter
from app.integrations.mock import MockMessengerAdapter, MockTypeXAdapter, mock_adapters
from app.integrations.typex_errors import TypeXConfigurationError

__all__ = ["MessengerAdapter", "MockMessengerAdapter", "mock_adapters", "get_typex_adapter"]


def get_typex_adapter() -> MessengerAdapter:
    from app.integrations.typex import TypeXAdapter

    mode = (get_settings().typex_mode or "").strip().lower()
    if mode == "mock":
        return MockTypeXAdapter()
    if mode == "real":
        return TypeXAdapter.from_settings()
    raise TypeXConfigurationError("Unknown TypeX mode")
