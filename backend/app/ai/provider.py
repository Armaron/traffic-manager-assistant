from abc import ABC, abstractmethod

from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult


class AIProvider(ABC):
    """AI backends must implement this contract.

    Message text leaves this app only through analyze_message.
    Providers never send replies.
    """

    name: str
    model: str | None = None
    resolved_model: str | None = None

    @abstractmethod
    async def analyze_message(self, context: AIAnalysisContext) -> AIAnalysisResult:
        """Return a structured analysis for one inbox item, including draft_reply."""
