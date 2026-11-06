from __future__ import annotations

import httpx
import pytest

from app.models import ProviderName
from app.providers.provider_catalog import fetch_provider_catalog


async def test_aihubmix_catalog_classifies_supported_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://aihubmix.com/v1/models"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o", "name": "GPT-4o"},
                    {"id": "text-embedding-3-large"},
                    {"id": "qwen3-reranker-4b"},
                ]
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.providers.provider_catalog.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    models, _ = await fetch_provider_catalog(
        provider=ProviderName.AIHUBMIX,
        api_key="test-key",
        base_url="https://aihubmix.com/v1",
        timeout=5,
    )

    identities = {(item["model_type"], item["id"]) for item in models}
    assert ("llm", "gpt-4o") in identities
    assert ("ocr", "gpt-4o") in identities
    assert ("embedding", "text-embedding-3-large") in identities
    assert ("rerank", "qwen3-reranker-4b") in identities


async def test_deepseek_catalog_exposes_llm_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.providers.provider_catalog.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    models, _ = await fetch_provider_catalog(
        provider=ProviderName.DEEPSEEK,
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        timeout=5,
    )

    assert {(item["model_type"], item["id"]) for item in models} == {
        ("llm", "deepseek-chat"),
        ("llm", "deepseek-reasoner"),
    }
