from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelConfig
from app.security import decrypt_secret


ADMIN = {"X-Demo-Role": "admin"}


def _openrouter_transport(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer sk-or-v1-valid"
    if request.url.path == "/api/v1/auth/key":
        return httpx.Response(200, json={"data": {"label": "knowledge-hub"}})
    if request.url.path == "/api/v1/models" and request.url.params.get("output_modalities") == "rerank":
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "qwen/qwen3-reranker-8b",
                        "name": "Qwen3 Reranker 8B",
                        "description": "Test rerank model",
                        "context_length": 32768,
                        "architecture": {"modality": "text->rerank", "input_modalities": ["text"], "output_modalities": ["rerank"]},
                        "pricing": {"prompt": "0.0000002"},
                    }
                ]
            },
        )
    if request.url.path == "/api/v1/models":
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "qwen/qwen-test",
                        "name": "Qwen Test",
                        "description": "Test chat model",
                        "context_length": 32768,
                        "architecture": {"modality": "text+image->text", "input_modalities": ["text", "image"], "output_modalities": ["text"]},
                        "pricing": {"prompt": "0.000001"},
                    }
                ]
            },
        )
    if request.url.path == "/api/v1/embeddings/models":
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "baai/bge-m3",
                        "name": "BAAI: bge-m3",
                        "description": "Test embedding model",
                        "context_length": 8194,
                        "architecture": {"modality": "text->embeddings", "output_modalities": ["embeddings"]},
                        "pricing": {"prompt": "0"},
                    }
                ]
            },
        )
    return httpx.Response(404)


@pytest.fixture
def mock_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    real_client = httpx.AsyncClient

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(_openrouter_transport), **kwargs)

    monkeypatch.setattr("app.providers.openrouter_catalog.httpx.AsyncClient", client_factory)


async def test_catalog_validates_key_and_bulk_imports_selected_models(
    client: AsyncClient,
    db_session: AsyncSession,
    mock_openrouter: None,
) -> None:
    connection = {"api_key": "  sk-or-v1-valid  ", "base_url": "https://openrouter.ai/api/v1"}
    catalog = await client.post("/api/v1/models/openrouter/catalog", headers=ADMIN, json=connection)

    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["ok"] is True
    rerank_model = next(item for item in catalog.json()["models"] if item["model_type"] == "rerank")
    assert rerank_model["is_free"] is False
    assert [(item["model_type"], item["id"]) for item in catalog.json()["models"]] == [
        ("embedding", "baai/bge-m3"),
        ("llm", "qwen/qwen-test"),
        ("ocr", "qwen/qwen-test"),
        ("rerank", "qwen/qwen3-reranker-8b"),
    ]

    imported = await client.post(
        "/api/v1/models/openrouter/import",
        headers=ADMIN,
        json={
            **connection,
            "models": [
                {"model_name": "baai/bge-m3", "display_name": "BAAI: bge-m3", "model_type": "embedding"},
                {"model_name": "qwen/qwen-test", "display_name": "Qwen Test", "model_type": "llm"},
                {"model_name": "qwen/qwen-test", "display_name": "Qwen Test OCR", "model_type": "ocr"},
                {"model_name": "qwen/qwen3-reranker-8b", "display_name": "Qwen3 Reranker 8B", "model_type": "rerank"},
            ],
        },
    )

    assert imported.status_code == 200, imported.text
    assert len(imported.json()) == 4
    assert {item["connection_status"] for item in imported.json()} == {"untested"}
    stored = list(await db_session.scalars(select(ModelConfig).order_by(ModelConfig.model_type)))
    assert len(stored) == 4
    assert {decrypt_secret(item.api_key_encrypted) for item in stored} == {"sk-or-v1-valid"}


async def test_catalog_returns_actionable_authentication_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_client = httpx.AsyncClient

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    monkeypatch.setattr(
        "app.providers.openrouter_catalog.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    response = await client.post(
        "/api/v1/models/openrouter/catalog",
        headers=ADMIN,
        json={"api_key": "sk-or-v1-invalid"},
    )

    assert response.status_code == 422
    assert "认证失败（HTTP 401）" in response.json()["detail"]
    assert "Bearer" in response.json()["detail"]


async def test_catalog_can_reuse_an_encrypted_saved_connection(
    client: AsyncClient,
    mock_openrouter: None,
) -> None:
    created = await client.post(
        "/api/v1/models",
        headers=ADMIN,
        json={
            "display_name": "Saved OpenRouter",
            "provider": "openrouter",
            "model_type": "llm",
            "model_name": "qwen/qwen-test",
            "api_key": "sk-or-v1-valid",
        },
    )
    response = await client.post(
        "/api/v1/models/openrouter/catalog",
        headers=ADMIN,
        json={"source_model_id": created.json()["id"]},
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["models"]) == 4
