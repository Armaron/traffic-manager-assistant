from abc import ABC, abstractmethod

from app.enums import Platform
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender


class MessengerAdapter(ABC):
    """Shared contract for TypeX, Slack, and Telegram.

    Inbox code talks only to this interface, never to a specific messenger.
    """

    platform: Platform

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True when the adapter can reach its source."""

    @abstractmethod
    async def get_chats(self) -> list[UnifiedChat]:
        """Return available chats in a unified shape."""

    @abstractmethod
    async def get_messages(self, chat_id: str) -> list[UnifiedMessage]:
        """Return messages for one chat using the messenger's chat id."""

    @abstractmethod
    async def get_recent_messages(self, limit: int = 50) -> list[UnifiedMessage]:
        """Return newest messages across chats."""

    @abstractmethod
    async def get_sender(self, sender_id: str) -> UnifiedSender | None:
        """Return sender details when the adapter can resolve them."""
