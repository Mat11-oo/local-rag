from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient, Response


ADMIN = {"X-Demo-Role": "admin"}
MANAGER = {"X-Demo-Role": "manager"}
USER = {"X-Demo-Role": "user"}


def _events(response: Response) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((event, json.loads(data)))
    return events


async def _model(client: AsyncClient, model_type: str) -> str:
    response = await client.post(
        "/api/v1/models",
        headers=ADMIN,
        json={
            "display_name": f"Mock {model_type}",
            "provider": "mock",
            "model_type": model_type,
            "model_name": f"mock-{model_type}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _ready_app(client: AsyncClient) -> tuple[str, str]:
    embedding_id = await _model(client, "embedding")
    rerank_id = await _model(client, "rerank")
    llm_id = await _model(client, "llm")
    knowledge = await client.post(
        "/api/v1/knowledge-bases",
        headers=MANAGER,
        json={
            "name": "员工制度",
            "embedding_model_id": embedding_id,
            "rerank_model_id": rerank_id,
            "chunk_size": 100,
            "chunk_overlap": 20,
        },
    )
    assert knowledge.status_code == 201, knowledge.text
    knowledge_base_id = knowledge.json()["id"]
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/files",
        headers=MANAGER,
        files={
            "upload": (
                "leave.md",
                "# 年假结转\n\n因业务安排未休完的年假，经负责人确认后可结转至次年第一季度。".encode(),
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 202, uploaded.text
    app = await client.post(
        "/api/v1/apps",
        headers=MANAGER,
        json={
            "name": "员工助手",
            "system_prompt": "你是企业员工知识助手，只依据资料回答。",
            "llm_model_id": llm_id,
            "knowledge_base_ids": [knowledge_base_id],
            "top_k": 8,
            "rerank_top_n": 3,
            "score_threshold": 0,
            "is_enabled": True,
        },
    )
    assert app.status_code == 201, app.text
    return app.json()["id"], llm_id


async def test_sse_chat_persists_messages_tokens_citations_and_trace(client: AsyncClient) -> None:
    app_id, _ = await _ready_app(client)

    response = await client.post(
        f"/api/v1/apps/{app_id}/chat",
        headers=USER,
        json={"message": "年假没有休完可以结转吗？"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert "citations" in names
    assert "token" in names
    assert names[-1] == "done"
    meta = events[0][1]
    done = events[-1][1]
    assert done["total_tokens"] == 28
    assert done["simulated"] is True
    assert done["simulation"] == {"llm": True, "retrieval": True}

    conversation = await client.get(
        f"/api/v1/conversations/{meta['conversation_id']}",
        headers=USER,
    )
    assert conversation.status_code == 200, conversation.text
    messages = conversation.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["citations"][0]["filename"] == "leave.md"
    assert messages[1]["input_tokens"] == 12
    assert messages[1]["output_tokens"] == 16

    logs = await client.get("/api/v1/logs", headers=MANAGER)
    assert logs.status_code == 200, logs.text
    assert len(logs.json()) == 1
    log = logs.json()[0]
    assert log["trace_id"] == meta["trace_id"]
    assert log["status"] == "success"
    assert log["total_tokens"] == 28
    assert [trace["name"] for trace in log["traces"]] == [
        "查询预处理",
        "向量检索",
        "Rerank",
        "LLM 生成",
    ]

    detail = await client.get(f"/api/v1/logs/{meta['trace_id']}", headers=MANAGER)
    assert detail.status_code == 200
    assert detail.json()["app_name"] == "员工助手"

    summary = await client.get("/api/v1/logs/summary", headers=MANAGER)
    assert summary.status_code == 200
    assert summary.json()["query_count"] == 1
    assert summary.json()["success_rate"] == 100.0
    assert summary.json()["total_tokens"] == 28


async def test_chat_failure_is_an_sse_error_and_is_logged(client: AsyncClient) -> None:
    app_id, llm_id = await _ready_app(client)
    disabled = await client.patch(
        f"/api/v1/models/{llm_id}",
        headers=ADMIN,
        json={"is_enabled": False},
    )
    assert disabled.status_code == 200

    response = await client.post(
        f"/api/v1/apps/{app_id}/chat",
        headers=USER,
        json={"message": "请回答这个问题"},
    )

    assert response.status_code == 200
    events = _events(response)
    assert events[-1][0] == "error"
    assert "missing or disabled" in events[-1][1]["detail"]
    logs = await client.get("/api/v1/logs?status=failed", headers=MANAGER)
    assert logs.status_code == 200
    assert len(logs.json()) == 1
    assert logs.json()[0]["total_tokens"] is None


async def test_chat_can_select_a_subset_of_app_knowledge_bases(client: AsyncClient) -> None:
    app_id, _ = await _ready_app(client)
    app_detail = await client.get(f"/api/v1/apps/{app_id}", headers=MANAGER)
    first_kb_id = app_detail.json()["knowledge_base_ids"][0]
    embedding_id = await _model(client, "embedding")
    second = await client.post(
        "/api/v1/knowledge-bases",
        headers=MANAGER,
        json={
            "name": "产品手册",
            "embedding_model_id": embedding_id,
            "chunk_size": 100,
            "chunk_overlap": 20,
        },
    )
    second_kb_id = second.json()["id"]
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{second_kb_id}/files",
        headers=MANAGER,
        files={"upload": ("product.md", "# 产品\n\n支持组合检索。".encode(), "text/markdown")},
    )
    assert uploaded.status_code == 202
    updated = await client.patch(
        f"/api/v1/apps/{app_id}",
        headers=MANAGER,
        json={"knowledge_base_ids": [first_kb_id, second_kb_id]},
    )
    assert updated.status_code == 200
    assert [item["name"] for item in updated.json()["knowledge_bases"]] == ["员工制度", "产品手册"]

    response = await client.post(
        f"/api/v1/apps/{app_id}/chat",
        headers=USER,
        json={"message": "产品支持什么？", "knowledge_base_ids": [second_kb_id]},
    )
    events = _events(response)
    assert events[0][1]["knowledge_base_ids"] == [second_kb_id]
    assert events[-1][0] == "done"

    logs = await client.get("/api/v1/logs", headers=MANAGER)
    retrieval_trace = next(item for item in logs.json()[0]["traces"] if item["name"] == "向量检索")
    assert retrieval_trace["metadata_json"]["knowledge_base_ids"] == [second_kb_id]

    rejected = await client.post(
        f"/api/v1/apps/{app_id}/chat",
        headers=USER,
        json={"message": "越权查询", "knowledge_base_ids": ["not-allowed"]},
    )
    assert rejected.status_code == 422
