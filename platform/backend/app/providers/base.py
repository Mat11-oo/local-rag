from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel


class ProviderError(RuntimeError):
    """A sanitized model-provider failure safe to show in the API."""


class ProviderCapabilityError(ProviderError):
    """The selected provider does not expose the requested capability."""


@dataclass(slots=True)
class RerankItem:
    index: int
    score: float


class ModelGateway(ABC):
    provider: str
    model_type: str
    is_simulated: bool = False

    @abstractmethod
    async def test_connection(self) -> str:
        raise NotImplementedError

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ProviderCapabilityError(f"{self.provider} gateway is not configured for embeddings")

    async def embed_query(self, text: str) -> list[float]:
        results = await self.embed_documents([text])
        return results[0]

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankItem]:
        raise ProviderCapabilityError(f"{self.provider} gateway is not configured for reranking")

    def chat_model(self, **overrides: Any) -> BaseChatModel:
        raise ProviderCapabilityError(f"{self.provider} gateway is not configured for chat")

