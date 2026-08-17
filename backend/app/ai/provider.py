from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    """AI backends must implement this contract.

    Message text leaves this app only through analyze_message / generate_reply.
    """

    name: str

    @abstractmethod
    async def analyze_message(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return a structured analysis for one inbox item."""

    @abstractmethod
    async def generate_reply(self, context: dict[str, Any]) -> str:
        """Return a draft reply. Never send it automatically."""
