from app.config import get_settings
from app.integrations.base import MessengerAdapter
from app.integrations.mock import MockMessengerAdapter, MockSlackAdapter, MockTelegramAdapter, MockTypeXAdapter, mock_adapters
from app.integrations.slack_errors import SlackConfigurationError
from app.integrations.telegram_errors import TelegramConfigurationError
from app.integrations.typex_errors import TypeXConfigurationError

__all__ = [
    "MessengerAdapter",
    "MockMessengerAdapter",
    "mock_adapters",
    "get_typex_adapter",
    "get_telegram_adapter",
    "get_slack_adapter",
]


def get_typex_adapter() -> MessengerAdapter:
    from app.integrations.typex import TypeXAdapter

    mode = (get_settings().typex_mode or "").strip().lower()
    if mode == "mock":
        return MockTypeXAdapter()
    if mode == "real":
        return TypeXAdapter.from_settings()
    raise TypeXConfigurationError("Unknown TypeX mode")


def get_telegram_adapter() -> MessengerAdapter:
    from app.integrations.telegram import TelegramAdapter

    mode = (get_settings().telegram_mode or "").strip().lower()
    if mode == "mock":
        return MockTelegramAdapter()
    if mode == "real":
        return TelegramAdapter.from_settings()
    raise TelegramConfigurationError("Unknown Telegram mode")


def get_slack_adapter() -> MessengerAdapter:
    from app.integrations.slack import SlackAdapter

    mode = (get_settings().slack_mode or "").strip().lower()
    if mode == "mock":
        return MockSlackAdapter()
    if mode == "browser":
        raise SlackConfigurationError("Slack browser mode does not use the Slack Web API")
    if mode == "real":
        return SlackAdapter.from_settings()
    raise SlackConfigurationError("Unknown Slack mode")
