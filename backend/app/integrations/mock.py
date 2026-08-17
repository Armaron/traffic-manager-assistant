"""In-memory messenger adapters for local development. No network calls."""

from app.enums import Platform
from app.integrations.base import MessengerAdapter
from app.integrations.mock_data import conversations_for_platform, senders_for_platform
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender


class MockMessengerAdapter(MessengerAdapter):
    def __init__(self, platform: Platform) -> None:
        self.platform = platform

    def _conversations(self):
        return conversations_for_platform(self.platform)

    async def health_check(self) -> bool:
        return True

    async def get_chats(self) -> list[UnifiedChat]:
        return [item.chat for item in self._conversations()]

    async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
        for item in self._conversations():
            if item.chat.external_id == chat_id:
                return list(item.messages)
        return []

    async def get_recent_messages(self, limit: int = 50) -> list[UnifiedMessage]:
        messages = [message for item in self._conversations() for message in item.messages]
        messages.sort(key=lambda item: item.timestamp, reverse=True)
        return messages[:limit]

    async def get_sender(self, sender_id: str) -> UnifiedSender | None:
        for sender in senders_for_platform(self.platform):
            if sender.external_id == sender_id:
                return sender
        return None


class MockTypeXAdapter(MockMessengerAdapter):
    def __init__(self) -> None:
        super().__init__(Platform.TYPEX)


class MockSlackAdapter(MockMessengerAdapter):
    def __init__(self) -> None:
        super().__init__(Platform.SLACK)


class MockTelegramAdapter(MockMessengerAdapter):
    def __init__(self) -> None:
        super().__init__(Platform.TELEGRAM)


def mock_adapters() -> list[MockMessengerAdapter]:
    return [MockTypeXAdapter(), MockSlackAdapter(), MockTelegramAdapter()]
