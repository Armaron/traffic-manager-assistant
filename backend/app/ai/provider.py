from abc import ABC, abstractmethod

from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult
from app.schemas.digest import DigestAIOutput, DigestQAModelOutput


class AIProvider(ABC):
    """AI backends must implement this contract.

    Message text leaves this app only through analyze_message / summarize_digest.
    Providers never send replies.
    """

    name: str
    model: str | None = None
    resolved_model: str | None = None

    @abstractmethod
    async def analyze_message(self, context: AIAnalysisContext) -> AIAnalysisResult:
        """Return a structured analysis for one inbox item, including draft_reply."""

    @abstractmethod
    async def summarize_digest(self, payload: dict) -> DigestAIOutput:
        """One structured Russian digest for already-selected chat candidates."""

    @abstractmethod
    async def answer_digest_qa(self, payload: dict) -> DigestQAModelOutput:
        """One structured Russian answer for a Digest Q&A question."""
