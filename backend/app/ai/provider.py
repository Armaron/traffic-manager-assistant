from abc import ABC, abstractmethod

from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult


class AIProvider(ABC):
    """AI backends must implement this contract.

    Message text leaves this app only through analyze_message / generate_reply.
    """

    name: str

    @abstractmethod
    async def analyze_message(self, context: AIAnalysisContext) -> AIAnalysisResult:
        """Return a structured analysis for one inbox item."""

    @abstractmethod
    async def generate_reply(self, context: AIAnalysisContext) -> str | None:
        """Return a draft reply. Never send it automatically."""
