from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from .base import ModelGateway, RerankItem


def _vector(text: str, dimensions: int = 24) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


class MockChatModel(BaseChatModel):
    response_text: str = "这是测试替身生成的回答，不代表真实模型输出。"

    @property
    def _llm_type(self) -> str:
        return "knowledge-hub-test-double"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        message = AIMessage(
            content=self.response_text,
            usage_metadata={"input_tokens": 12, "output_tokens": 16, "total_tokens": 28},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        del messages, stop, run_manager, kwargs
        for index, part in enumerate(re.findall(r".{1,8}", self.response_text, flags=re.DOTALL)):
            usage = {"input_tokens": 12, "output_tokens": 16, "total_tokens": 28} if index == 0 else None
            yield ChatGenerationChunk(message=AIMessageChunk(content=part, usage_metadata=usage))


class MockGateway(ModelGateway):
    provider = "mock"
    is_simulated = True

    def __init__(self, model_type: str, response_text: str | None = None) -> None:
        self.model_type = model_type
        self.response_text = response_text

    async def test_connection(self) -> str:
        return "测试替身可用；未发起任何外部网络请求"

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_vector(text) for text in texts]

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankItem]:
        query_terms = set(re.findall(r"[\w\u4e00-\u9fff]", query.lower()))
        scored: list[RerankItem] = []
        for index, document in enumerate(documents):
            terms = set(re.findall(r"[\w\u4e00-\u9fff]", document.lower()))
            overlap = len(query_terms & terms)
            score = overlap / max(len(query_terms), 1)
            scored.append(RerankItem(index=index, score=score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:top_n]

    def chat_model(self, **overrides: Any) -> BaseChatModel:
        response = overrides.pop("response_text", None) or self.response_text
        return MockChatModel(response_text=response or MockChatModel.model_fields["response_text"].default)

