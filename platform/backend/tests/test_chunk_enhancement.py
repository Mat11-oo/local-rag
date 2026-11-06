from __future__ import annotations

import json

from httpx import AsyncClient

from app.services.chunk_enhancement import rule_keywords
from tests.test_knowledge_ingestion import ADMIN_HEADERS, MANAGER_HEADERS, _create_mock_embedding

CONTENT = "# 售后政策\n\n七天无理由退货，商品需保持完好。\n\n## 保修\n\n整机保修一年，人为损坏不在保修范围内。"


async def _enhancement_llm(client: AsyncClient) -> str:
    response_text = json.dumps(
        [{"index": 0, "keywords": ["无理由退货", "保修期"], "qa": [{"q": "多久可以退货？", "a": "七天内无理由退货。"}, {"q": "保修多久？", "a": "整机保修一年。"}]}],
        ensure_ascii=False,
    )
    created = await client.post(
        "/api/v1/models", headers=ADMIN_HEADERS,
        json={"display_name": "增强 LLM", "provider": "mock", "model_type": "llm", "model_name": "enhance-double", "config": {"response_text": response_text}},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _knowledge_base(client: AsyncClient, llm_id: str | None) -> str:
    created = await client.post(
        "/api/v1/knowledge-bases", headers=MANAGER_HEADERS,
        json={"name": "售后", "embedding_model_id": await _create_mock_embedding(client), "semantic_llm_model_id": llm_id, "chunk_size": 2000, "chunk_overlap": 0},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _upload(client: AsyncClient, kb_id: str, config: dict) -> dict:
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/files", headers=MANAGER_HEADERS,
        files={"upload": ("policy.md", CONTENT.encode(), "text/markdown")},
        data={"config": json.dumps({"method": "recursive", **config})},
    )
    assert uploaded.status_code == 202, uploaded.text
    return uploaded.json()


async def test_import_generates_qa_pairs_and_keywords_with_llm(client: AsyncClient) -> None:
    kb_id = await _knowledge_base(client, await _enhancement_llm(client))
    body = await _upload(client, kb_id, {"enhance_qa": True, "enhance_keywords": True})
    assert body["file"]["status"] == "completed", body
    assert "chunk_enhancement" in [stage["name"] for stage in body["job"]["stage_details"]]
    chunk = (await client.get(f"/api/v1/knowledge-bases/{kb_id}/chunks", headers=MANAGER_HEADERS)).json()[0]
    assert chunk["metadata_json"]["keywords"] == ["无理由退货", "保修期"]
    assert [item["q"] for item in chunk["metadata_json"]["qa_pairs"]] == ["多久可以退货？", "保修多久？"]

    edited = await client.patch(
        f"/api/v1/knowledge-bases/{kb_id}/chunks/{chunk['id']}", headers=MANAGER_HEADERS,
        json={"qa_pairs": [{"q": "能退货吗？", "a": "七天内可以。"}], "keywords": ["退货"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["metadata_json"]["qa_pairs"] == [{"q": "能退货吗？", "a": "七天内可以。"}]
    assert edited.json()["indexed"] is True  # re-embedded right away


async def test_keywords_fall_back_to_rules_and_qa_requires_llm(client: AsyncClient) -> None:
    kb_id = await _knowledge_base(client, None)
    body = await _upload(client, kb_id, {"enhance_keywords": True})
    assert body["file"]["status"] == "completed", body
    chunk = (await client.get(f"/api/v1/knowledge-bases/{kb_id}/chunks", headers=MANAGER_HEADERS)).json()[0]
    assert "保修" in chunk["metadata_json"]["keywords"]

    rejected = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/files", headers=MANAGER_HEADERS,
        files={"upload": ("other.md", "# 其他\n\n内容".encode(), "text/markdown")},
        data={"config": json.dumps({"method": "recursive", "enhance_qa": True})},
    )
    assert rejected.status_code == 422
    assert "文本理解模型" in rejected.json()["detail"]


def test_rule_keywords_prefers_repeated_terms() -> None:
    words = rule_keywords("保修一年。保修范围不含人为损坏。E07 故障，E07 代码。")
    assert "保修" in words and "E07" in words


async def test_unparseable_model_output_does_not_fail_the_import(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/models", headers=ADMIN_HEADERS,
        json={"display_name": "胡言乱语", "provider": "mock", "model_type": "llm", "model_name": "garbage", "config": {"response_text": "抱歉，我无法输出 JSON"}},
    )
    kb_id = await _knowledge_base(client, created.json()["id"])
    body = await _upload(client, kb_id, {"enhance_qa": True, "enhance_keywords": True})
    assert body["file"]["status"] == "completed", body
    stage = next(item for item in body["job"]["stage_details"] if item["name"] == "chunk_enhancement")
    assert stage["status"] == "warning" and "无法解析" in stage["detail"]
    chunk = (await client.get(f"/api/v1/knowledge-bases/{kb_id}/chunks", headers=MANAGER_HEADERS)).json()[0]
    assert chunk["metadata_json"]["qa_pairs"] == []
    assert chunk["metadata_json"]["keywords"]  # rule fallback
