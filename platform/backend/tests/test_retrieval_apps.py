from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiClient, DEFAULT_WORKSPACE_ID, Workspace
from app.security import hash_token


ADMIN = {"X-Demo-Role": "admin"}
MANAGER = {"X-Demo-Role": "manager"}
USER = {"X-Demo-Role": "user"}


async def _model(client: AsyncClient, model_type: str) -> str:
    response = await client.post(
        "/api/v1/models",
        headers=ADMIN,
        json={
            "display_name": f"测试 {model_type}",
            "provider": "mock",
            "model_type": model_type,
            "model_name": f"test-{model_type}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _knowledge_base(client: AsyncClient, embedding_id: str, rerank_id: str) -> str:
    response = await client.post(
        "/api/v1/knowledge-bases",
        headers=MANAGER,
        json={
            "name": "员工知识库",
            "embedding_model_id": embedding_id,
            "rerank_model_id": rerank_id,
            "chunk_size": 100,
            "chunk_overlap": 20,
        },
    )
    assert response.status_code == 201, response.text
    knowledge_base_id = response.json()["id"]
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/files",
        headers=MANAGER,
        files={
            "upload": (
                "travel.md",
                "# 差旅制度\n\n员工出差前需要提交审批。\n\n# 费用\n\n报销需提供发票和行程单。".encode(),
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 202, uploaded.text
    assert uploaded.json()["job"]["status"] == "completed"
    return knowledge_base_id


async def test_retrieval_applies_mock_embedding_and_rerank(client: AsyncClient) -> None:
    embedding_id = await _model(client, "embedding")
    rerank_id = await _model(client, "rerank")
    knowledge_base_id = await _knowledge_base(client, embedding_id, rerank_id)

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/retrieval-test",
        headers=MANAGER,
        json={
            "query": "员工出差前需要提交审批",
            "top_k": 8,
            "rerank_top_n": 3,
            "score_threshold": 0,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recalled_count"] >= 1
    assert body["returned_count"] >= 1
    assert body["rerank_applied"] is True
    assert body["simulated"] is True
    assert body["results"][0]["rerank_score"] is not None
    assert body["results"][0]["filename"] == "travel.md"

    fulltext = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/retrieval-test",
        headers=MANAGER,
        json={"query": "行程单", "mode": "fulltext", "top_k": 8, "rerank_top_n": 3, "score_threshold": 0},
    )
    assert fulltext.status_code == 200, fulltext.text
    assert fulltext.json()["results"][0]["keyword_score"] > 0

    hybrid = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/retrieval-test",
        headers=MANAGER,
        json={"query": "差旅审批", "mode": "hybrid", "top_k": 8, "rerank_top_n": 3, "score_threshold": 0},
    )
    assert hybrid.status_code == 200, hybrid.text
    assert hybrid.json()["returned_count"] >= 1


async def test_shared_retrieval_enforces_read_scope_and_workspace(
    client: AsyncClient, db_session: AsyncSession,
) -> None:
    knowledge_base_id = await _knowledge_base(
        client, await _model(client, "embedding"), await _model(client, "rerank")
    )
    other_workspace = Workspace(name="Other", slug="other")
    db_session.add(other_workspace)
    await db_session.flush()
    db_session.add_all([
        ApiClient(name="reader", workspace_id=DEFAULT_WORKSPACE_ID,
                  token_hash=hash_token("reader"), scopes=["knowledge:read"]),
        ApiClient(name="writer", workspace_id=DEFAULT_WORKSPACE_ID,
                  token_hash=hash_token("writer"), scopes=["knowledge:write"]),
        ApiClient(name="other", workspace_id=other_workspace.id,
                  token_hash=hash_token("other"), scopes=["knowledge:read"]),
    ])
    await db_session.commit()

    base_url = f"/api/v1/knowledge-bases/{knowledge_base_id}"
    payload = {"query": "行程单", "mode": "fulltext"}
    reader = {"Authorization": "Bearer reader"}
    result = await client.post(f"{base_url}/retrieve", headers=reader, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["results"][0]["filename"] == "travel.md"
    assert result.json()["rerank_applied"] is True

    local = await client.post(
        f"{base_url}/retrieve", headers=reader,
        json={**payload, "use_rerank": False, "top_k": 1},
    )
    assert local.status_code == 200, local.text
    assert local.json()["returned_count"] == 1
    assert local.json()["rerank_applied"] is False
    assert local.json()["simulated"] is False
    for token, expected in [("writer", 403), ("other", 404)]:
        denied = await client.post(
            f"{base_url}/retrieve", headers={"Authorization": f"Bearer {token}"}, json=payload
        )
        assert denied.status_code == expected, denied.text
    assert (await client.post(
        f"{base_url}/retrieval-test", headers=reader, json=payload
    )).status_code == 403


async def test_shared_fulltext_retrieval_business_questions(client: AsyncClient) -> None:
    fixtures = {
        "充值规则.md": (
            "## 充值渠道\n游戏内商城和官网充值中心是官方充值渠道。\n\n"
            "## 到账时间\n充值最迟30分钟到账。超过30分钟没到账，请提交订单号。\n\n"
            "## 退款规则\n一笔充值的钻石只要用了一部分，这笔充值就不能退款。\n\n"
            "## 未成年人充值退款\n监护人申请未成年人充值退款，需要提交身份证、监护关系证明和充值订单记录。"
        ),
        "账号安全.md": (
            "## 换绑手机号\n原手机号已经停用，请通过账号申诉换绑手机号。\n\n"
            "## 找回密码\n忘记密码时可以通过验证码重设密码。"
        ),
    }
    embedding_id = await _model(client, "embedding")
    knowledge_bases = {}
    for filename, content in fixtures.items():
        created = await client.post(
            "/api/v1/knowledge-bases", headers=MANAGER,
            json={"name": filename, "embedding_model_id": embedding_id},
        )
        assert created.status_code == 201, created.text
        knowledge_base_id = created.json()["id"]
        knowledge_bases[filename] = knowledge_base_id
        uploaded = await client.post(
            f"/api/v1/knowledge-bases/{knowledge_base_id}/files",
            headers=MANAGER,
            files={"upload": (filename, content.encode(), "text/markdown")},
            data={"config": '{"method":"heading","heading_level":2}'},
        )
        assert uploaded.status_code == 202, uploaded.text
        assert uploaded.json()["job"]["status"] == "completed", uploaded.text

    cases = [
        ("充值规则.md", "充值超过30分钟没到账怎么办？", "到账时间"),
        ("充值规则.md", "游戏的官方充值渠道有哪些？", "充值渠道"),
        ("充值规则.md", "一笔充值的钻石只用了一部分，能退款吗？", "退款规则"),
        ("充值规则.md", "监护人申请未成年人充值退款需要提交哪些材料？", "未成年人充值退款"),
        ("充值规则.md", "公司年假怎么计算？", None),
        ("充值规则.md", "原手机号已经停用，怎么换绑手机号？", None),
        ("账号安全.md", "原手机号已经停用，怎么换绑手机号？", "换绑手机号"),
    ]
    for filename, query, expected_title in cases:
        result = await client.post(
            f"/api/v1/knowledge-bases/{knowledge_bases[filename]}/retrieve",
            headers=MANAGER,
            json={
                "query": query, "mode": "fulltext", "use_rerank": False,
                "top_k": 3, "score_threshold": 0.25,
            },
        )
        assert result.status_code == 200, result.text
        hits = result.json()["results"]
        if expected_title is None:
            assert hits == [], query
        else:
            assert hits, query
            assert hits[0]["title"] == expected_title, query
            assert hits[0]["filename"] == filename, query


async def test_qa_app_crud_and_user_visibility(client: AsyncClient) -> None:
    embedding_id = await _model(client, "embedding")
    rerank_id = await _model(client, "rerank")
    llm_id = await _model(client, "llm")
    knowledge_base_id = await _knowledge_base(client, embedding_id, rerank_id)

    model_options = await client.get("/api/v1/model-options", headers=MANAGER)
    assert model_options.status_code == 200
    assert {item["id"] for item in model_options.json()} == {embedding_id, rerank_id, llm_id}
    assert all("api_key_masked" not in item for item in model_options.json())

    created = await client.post(
        "/api/v1/apps",
        headers=MANAGER,
        json={
            "name": "员工助手",
            "description": "回答内部制度问题",
            "system_prompt": "只依据知识库回答，并标注来源。",
            "llm_model_id": llm_id,
            "knowledge_base_ids": [knowledge_base_id],
            "top_k": 8,
            "rerank_top_n": 3,
            "score_threshold": 0,
            "is_enabled": False,
        },
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]
    assert created.json()["scenario_type"] == "qa"
    assert created.json()["knowledge_bases"][0]["name"] == "员工知识库"
    assert created.json()["conversation_count"] == 0

    hidden = await client.get("/api/v1/apps", headers=USER)
    assert hidden.status_code == 200
    assert hidden.json() == []

    enabled = await client.patch(
        f"/api/v1/apps/{app_id}",
        headers=MANAGER,
        json={"is_enabled": True, "scenario_type": "review", "top_k": 5, "rerank_top_n": 2},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["is_enabled"] is True
    assert enabled.json()["scenario_type"] == "review"
    assert enabled.json()["top_k"] == 5

    visible = await client.get("/api/v1/apps", headers=USER)
    assert visible.status_code == 200
    assert [item["id"] for item in visible.json()] == [app_id]

    forbidden = await client.post(
        "/api/v1/apps",
        headers=USER,
        json={
            "name": "不允许创建",
            "system_prompt": "test",
            "llm_model_id": llm_id,
            "knowledge_base_ids": [knowledge_base_id],
        },
    )
    assert forbidden.status_code == 403
