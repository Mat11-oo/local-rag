from __future__ import annotations

import json

import httpx
import pytest

from app.providers.openai_compatible import OpenAICompatibleGateway
from app.services.ocr import _provider_error_message


def test_ocr_provider_error_prefers_nested_region_detail() -> None:
    assert _provider_error_message(
        {
            "message": "Provider returned error",
            "metadata": {"raw": "This model is not available in your region."},
        }
    ) == "This model is not available in your region."


async def test_embedding_sends_text_instead_of_token_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["input"] = body["input"]
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2], "index": 0}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "openai._base_client.AsyncHttpxClientWrapper",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler),
            base_url=kwargs.get("base_url"),
            headers=kwargs.get("headers"),
            timeout=kwargs.get("timeout"),
        ),
    )
    gateway = OpenAICompatibleGateway(
        provider="openrouter",
        model_type="embedding",
        model_name="baai/bge-m3",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        config={},
        timeout=5,
    )

    vectors = await gateway.embed_documents(["企业知识库测试文本"])

    assert vectors == [[0.1, 0.2]]
    assert captured["input"] == ["企业知识库测试文本"]


async def test_tongyi_rerank_uses_dashscope_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"output": {"results": [{"index": 1, "relevance_score": 0.92}]}},
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.providers.openai_compatible.httpx.AsyncClient",
        lambda **_: real_client(transport=httpx.MockTransport(handler)),
    )
    gateway = OpenAICompatibleGateway(
        provider="tongyi",
        model_type="rerank",
        model_name="gte-rerank-v2",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="test-key",
        config={},
        timeout=5,
    )

    result = await gateway.rerank("年假", ["无关", "年假结转"], 1)

    assert result[0].index == 1
    assert result[0].score == 0.92
    assert captured["url"] == "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    assert captured["body"] == {
        "model": "gte-rerank-v2",
        "input": {"query": "年假", "documents": ["无关", "年假结转"]},
        "parameters": {"top_n": 1, "return_documents": False},
    }


async def test_aihubmix_rerank_uses_openai_compatible_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"index": 0, "score": 0.8}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.providers.openai_compatible.httpx.AsyncClient",
        lambda **_: real_client(transport=httpx.MockTransport(handler)),
    )
    gateway = OpenAICompatibleGateway(
        provider="aihubmix",
        model_type="rerank",
        model_name="bge-reranker-v2-m3",
        base_url="https://aihubmix.com/v1",
        api_key="test-key",
        config={},
        timeout=5,
    )

    result = await gateway.rerank("query", ["document"], 1)

    assert result[0].score == 0.8
    assert captured["url"] == "https://aihubmix.com/v1/rerank"
    assert captured["body"] == {
        "model": "bge-reranker-v2-m3",
        "query": "query",
        "documents": ["document"],
        "top_n": 1,
    }


async def test_openrouter_rerank_uses_native_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.91}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.providers.openai_compatible.httpx.AsyncClient",
        lambda **_: real_client(transport=httpx.MockTransport(handler)),
    )
    gateway = OpenAICompatibleGateway(
        provider="openrouter",
        model_type="rerank",
        model_name="qwen/qwen3-reranker-8b",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        config={},
        timeout=5,
    )

    result = await gateway.rerank("query", ["document"], 1)

    assert result[0].score == 0.91
    assert captured["url"] == "https://openrouter.ai/api/v1/rerank"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["body"] == {
        "model": "qwen/qwen3-reranker-8b",
        "query": "query",
        "documents": ["document"],
        "top_n": 1,
    }
