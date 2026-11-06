from __future__ import annotations

from httpx import AsyncClient
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from tests.test_fde_api import ADMIN, content_inputs, design_content

USER = {"X-Demo-Role": "user"}


async def priced_mock_llm(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/models",
        headers=ADMIN,
        json={
            "display_name": "计价测试模型",
            "provider": "mock",
            "model_type": "llm",
            "model_name": "priced-test",
            "config": {"input_price_per_million": 2.0, "output_price_per_million": 8.0, "currency": "USD"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def content_app(client: AsyncClient, model_id: str) -> str:
    manifest = await design_content(client, model_id)
    created = await client.post("/api/v1/fde/apps", headers=ADMIN, json={"manifest": manifest})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_preview_run_is_fully_observable(client: AsyncClient) -> None:
    model_id = await priced_mock_llm(client)
    app_id = await content_app(client, model_id)

    ran = await client.post(f"/api/v1/fde/apps/{app_id}/preview", headers=ADMIN, json={"input_values": content_inputs()})
    assert ran.status_code == 200, ran.text
    trace_id = ran.json()["trace_id"]

    runs = await client.get("/api/v1/observability/runs", headers=ADMIN, params={"app_id": app_id})
    assert runs.status_code == 200
    item = runs.json()["items"][0]
    assert item["trace_id"] == trace_id
    assert item["channel"] == "debug"
    assert item["model_name"] == "priced-test"
    # mock usage: 12 input + 16 output tokens at $2 / $8 per million
    assert item["cost"] == round(12 * 2 / 1e6 + 16 * 8 / 1e6, 8)
    assert item["model_calls"] == 1

    detail = await client.get(f"/api/v1/observability/runs/{trace_id}", headers=ADMIN)
    assert detail.status_code == 200
    body = detail.json()
    assert [span["kind"] for span in body["spans"]] == ["context", "model"]
    assert body["output"]
    assert body["input_values"]["dish_name"] == "云南汽锅鸡"
    assert body["run_metadata"]["pricing"]["input_per_million"] == 2.0

    conversations = await client.get("/api/v1/observability/conversations", headers=ADMIN, params={"app_id": app_id})
    conversation = conversations.json()["items"][0]
    assert conversation["turns"] == 1
    assert conversation["tokens"] == 28
    detail = await client.get(f"/api/v1/observability/conversations/{conversation['id']}", headers=ADMIN)
    assistant = [message for message in detail.json()["messages"] if message["role"] == "assistant"][0]
    assert assistant["trace_id"] == trace_id

    overview = await client.get("/api/v1/observability/overview", headers=ADMIN)
    assert overview.status_code == 200
    stats = overview.json()
    assert stats["runs"]["total"] == 1
    assert stats["runs"]["success_rate"] == 100.0
    assert stats["cost"]["priced_runs"] == 1
    assert stats["daily"][-1]["runs"] == 1

    usage = await client.get("/api/v1/observability/usage", headers=ADMIN, params={"group_by": "model"})
    assert usage.json()["items"][0]["name"] == "priced-test"
    assert usage.json()["totals"]["total_tokens"] == 28


async def test_failed_run_is_logged_with_error_span(client: AsyncClient) -> None:
    model_id = await priced_mock_llm(client)
    app_id = await content_app(client, model_id)

    failed = await client.post(f"/api/v1/fde/apps/{app_id}/preview", headers=ADMIN, json={"input_values": {"channel": "不存在的渠道"}})
    assert failed.status_code == 422
    trace_id = failed.json()["detail"]["trace_id"]

    runs = await client.get("/api/v1/observability/runs", headers=ADMIN, params={"status": "failed"})
    item = runs.json()["items"][0]
    assert item["trace_id"] == trace_id
    assert item["error_message"]
    detail = await client.get(f"/api/v1/observability/runs/{trace_id}", headers=ADMIN)
    assert detail.json()["spans"][-1]["kind"] == "error"
    overview = await client.get("/api/v1/observability/overview", headers=ADMIN)
    assert overview.json()["recent_failures"][0]["trace_id"] == trace_id


async def test_observability_requires_manager_role(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/observability/overview", headers=USER)).status_code == 403
    assert (await client.get("/api/v1/observability/runs", headers=USER)).status_code == 403


async def _knowledge_base(client: AsyncClient) -> str:
    embedding = await client.post(
        "/api/v1/models",
        headers=ADMIN,
        json={"display_name": "Embedding", "provider": "mock", "model_type": "embedding", "model_name": "deterministic-test-vector"},
    )
    created = await client.post(
        "/api/v1/knowledge-bases",
        headers=ADMIN,
        json={"name": "差旅制度", "embedding_model_id": embedding.json()["id"], "chunk_size": 200, "chunk_overlap": 20},
    )
    assert created.status_code == 201, created.text
    kb_id = created.json()["id"]
    content = "# 差旅制度\n\n员工出差前需要提交审批，经部门负责人同意后方可出行。\n\n## 住宿\n\n一线城市住宿标准为每晚 500 元。"
    uploaded = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/files",
        headers=ADMIN,
        files={"upload": ("travel.md", content.encode(), "text/markdown")},
    )
    assert uploaded.status_code == 202, uploaded.text
    return kb_id


async def test_build_jobs_are_listed(client: AsyncClient) -> None:
    kb_id = await _knowledge_base(client)
    jobs = await client.get("/api/v1/observability/build-jobs", headers=ADMIN)
    assert jobs.status_code == 200
    body = jobs.json()
    assert body["summary"]["completed"] == 1
    item = body["items"][0]
    assert item["knowledge_base_id"] == kb_id
    assert item["filename"] == "travel.md"
    assert item["chunk_count"] >= 1
    assert item["stage_details"]


class KnowledgeAgentModel(BaseChatModel):
    _calls: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "knowledge-agent-test"

    def bind_tools(self, tools, **kwargs):
        del kwargs
        self._tool_names = [tool.name for tool in tools]
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs) -> ChatResult:
        del stop, run_manager, kwargs
        self._calls += 1
        if self._calls == 1:
            message = AIMessage(content="", tool_calls=[{"name": "knowledge_search", "args": {"query": "住宿标准"}, "id": "call-1"}], usage_metadata={"input_tokens": 40, "output_tokens": 6, "total_tokens": 46})
        else:
            observation = next(item for item in messages if isinstance(item, ToolMessage))
            assert "500 元" in str(observation.content)
            message = AIMessage(content="一线城市住宿标准为每晚 500 元。[资料 1]", usage_metadata={"input_tokens": 120, "output_tokens": 20, "total_tokens": 140})
        return ChatResult(generations=[ChatGeneration(message=message)])


class KnowledgeAgentGateway:
    is_simulated = False

    def __init__(self) -> None:
        self.model = KnowledgeAgentModel()

    def chat_model(self, **kwargs):
        del kwargs
        return self.model


async def test_agent_uses_knowledge_as_tool_and_records_spans(client: AsyncClient, monkeypatch) -> None:
    kb_id = await _knowledge_base(client)
    model_id = await priced_mock_llm(client)
    gateway = KnowledgeAgentGateway()
    monkeypatch.setattr("app.fde.runtime.build_gateway", lambda model: gateway)
    manifest = {
        "schema_version": "fde.app/v2",
        "type": "agent",
        "name": "差旅 Agent",
        "template_key": "qa",
        "system_prompt": "回答差旅制度问题，先检索知识库。",
        "llm_model_id": model_id,
        "knowledge_base_ids": [kb_id],
        "input_fields": [],
        "tools": [{"name": "knowledge_retrieval", "config": {"mode": "fulltext", "score_threshold": 0}}],
        "guardrails": {"human_handoff": True},
    }
    created = await client.post("/api/v1/fde/apps", headers=ADMIN, json={"manifest": manifest})
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]

    ran = await client.post(f"/api/v1/fde/apps/{app_id}/preview", headers=ADMIN, json={"message": "深圳出差住宿标准是多少？"})
    assert ran.status_code == 200, ran.text
    result = ran.json()
    assert "500 元" in result["content"]
    assert result["citations"], "knowledge tool results must become citations"
    assert result["agent_steps"][0]["kind"] == "retrieval"
    assert "transfer_to_human" in gateway.model._tool_names

    detail = await client.get(f"/api/v1/observability/runs/{result['trace_id']}", headers=ADMIN)
    kinds = [span["kind"] for span in detail.json()["spans"]]
    assert kinds == ["context", "model", "retrieval", "model"]
    first_model = detail.json()["spans"][1]
    assert first_model["metadata"]["tool_calls"][0]["name"] == "knowledge_search"
    assert detail.json()["tokens"]["total"] == 186


async def test_trace_to_evaluation_set_to_release_gate_loop(client: AsyncClient) -> None:
    model_id = await priced_mock_llm(client)
    app_id = await content_app(client, model_id)
    ran = await client.post(f"/api/v1/fde/apps/{app_id}/preview", headers=ADMIN, json={"input_values": content_inputs()})
    trace_id = ran.json()["trace_id"]

    created = await client.post("/api/v1/evaluation-sets", headers=ADMIN, json={"app_id": app_id, "name": "文案回归集"})
    suite_id = created.json()["id"]
    returned = await client.post(f"/api/v1/evaluation-sets/{suite_id}/cases/from-logs", headers=ADMIN, json={"trace_ids": [trace_id], "case_type": "bad"})
    assert returned.status_code == 201, returned.text
    case = returned.json()["cases"][0]
    assert case["readiness"] == "needs_standard"
    assert case["input_values"]["dish_name"] == "云南汽锅鸡"
    assert case["source_snapshot"]["channel"] == "debug"
    assert case["source_snapshot"]["model"]["model"] == "priced-test"
    assert (await client.post(f"/api/v1/evaluation-sets/{suite_id}/run", headers=ADMIN)).status_code == 409

    patched = await client.patch(f"/api/v1/evaluation-sets/{suite_id}/cases/{case['id']}", headers=ADMIN, json={"expected_keywords": ["云南汽锅鸡"]})
    assert patched.json()["readiness"] == "ready"
    manual = await client.post(
        f"/api/v1/evaluation-sets/{suite_id}/cases",
        headers=ADMIN,
        json={"name": "手工用例", "message": "写一段文案", "input_values": content_inputs(), "expected_keywords": ["汽锅鸡"]},
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["readiness"] == "ready"

    passed = await client.post(f"/api/v1/evaluation-sets/{suite_id}/run", headers=ADMIN)
    assert passed.json()["passed_count"] == 2, passed.text

    gate = await client.patch(f"/api/v1/evaluation-sets/{suite_id}", headers=ADMIN, json={"is_release_gate": True})
    assert gate.json()["is_release_gate"] is True
    assert (await client.post(f"/api/v1/fde/apps/{app_id}/versions", headers=ADMIN, json={"release_notes": "v1"})).status_code == 201
    assert (await client.post(f"/api/v1/fde/apps/{app_id}/publish", headers=ADMIN, json={})).status_code == 200

    failing = await client.post(
        f"/api/v1/evaluation-sets/{suite_id}/cases",
        headers=ADMIN,
        json={"name": "必然失败", "message": "写一段文案", "input_values": content_inputs(), "expected_keywords": ["不存在的词"]},
    )
    assert (await client.post(f"/api/v1/evaluation-sets/{suite_id}/run", headers=ADMIN)).json()["failed_count"] == 1
    assert (await client.post(f"/api/v1/fde/apps/{app_id}/publish", headers=ADMIN, json={})).status_code == 409
    assert (await client.delete(f"/api/v1/evaluation-sets/{suite_id}/cases/{failing.json()['id']}", headers=ADMIN)).status_code == 204


async def test_single_file_can_be_rechunked_with_new_method(client: AsyncClient) -> None:
    kb_id = await _knowledge_base(client)
    files = (await client.get(f"/api/v1/knowledge-bases/{kb_id}/files", headers=ADMIN)).json()
    file_id = files[0]["id"]
    retried = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/files/{file_id}/retry",
        headers=ADMIN,
        json={"chunk_config": {"method": "heading", "heading_level": 2, "chunk_size": 300, "chunk_overlap": 0}},
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["status"] == "completed"
    files = (await client.get(f"/api/v1/knowledge-bases/{kb_id}/files", headers=ADMIN)).json()
    assert files[0]["chunk_config"]["method"] == "heading"
    chunks = (await client.get(f"/api/v1/knowledge-bases/{kb_id}/chunks", headers=ADMIN, params={"file_id": file_id})).json()
    assert {chunk["metadata_json"].get("chunk_method") for chunk in chunks} == {"heading"}
    # Retry without a body keeps the stored per-file configuration.
    assert (await client.post(f"/api/v1/knowledge-bases/{kb_id}/files/{file_id}/retry", headers=ADMIN)).status_code == 202


async def test_business_user_sees_only_published_app_and_own_conversations(client: AsyncClient, db_session) -> None:
    from app.models import DEFAULT_WORKSPACE_ID, Membership, User
    from app.security import hash_password

    model_id = await priced_mock_llm(client)
    app_id = await content_app(client, model_id)
    assert (await client.get(f"/api/v1/fde/apps/{app_id}", headers=USER)).status_code == 404

    await client.post(f"/api/v1/fde/apps/{app_id}/versions", headers=ADMIN, json={"release_notes": "v1"})
    assert (await client.post(f"/api/v1/fde/apps/{app_id}/publish", headers=ADMIN, json={})).status_code == 200
    draft = (await client.get(f"/api/v1/fde/apps/{app_id}", headers=ADMIN)).json()["manifest"]
    draft["system_prompt"] = "未发布的草稿提示词"
    await client.put(f"/api/v1/fde/apps/{app_id}/manifest", headers=ADMIN, json={"manifest": draft})

    user = User(email="biz@example.com", display_name="业务", password_hash=hash_password("biz-password-1"))
    db_session.add(user)
    await db_session.flush()
    db_session.add(Membership(workspace_id=DEFAULT_WORKSPACE_ID, user_id=user.id, role="user"))
    await db_session.commit()
    token = (await client.post("/api/v1/auth/login", json={"email": "biz@example.com", "password": "biz-password-1"})).json()["token"]
    biz = {"Authorization": f"Bearer {token}"}

    visible = await client.get(f"/api/v1/fde/apps/{app_id}", headers=biz)
    assert visible.status_code == 200
    assert visible.json()["manifest"]["system_prompt"] != "未发布的草稿提示词"
    assert len(visible.json()["versions"]) == 1

    ran = await client.post(f"/api/v1/fde/apps/{app_id}/run", headers=biz, json={"input_values": content_inputs()})
    assert ran.status_code == 200, ran.text
    assert (await client.post(f"/api/v1/fde/apps/{app_id}/preview", headers=ADMIN, json={"input_values": content_inputs()})).status_code == 200

    mine = (await client.get(f"/api/v1/fde/apps/{app_id}/my-conversations", headers=biz)).json()
    assert [item["id"] for item in mine] == [ran.json()["conversation_id"]]
    detail = await client.get(f"/api/v1/fde/conversations/{ran.json()['conversation_id']}", headers=biz)
    assert [item["role"] for item in detail.json()["messages"]] == ["user", "assistant"]
    runs = (await client.get("/api/v1/observability/runs", headers=ADMIN, params={"channel": "web"})).json()["items"]
    assert runs[0]["app_version"] == 1


async def test_public_share_does_not_leak_private_configuration(client: AsyncClient) -> None:
    model_id = await priced_mock_llm(client)
    app_id = await content_app(client, model_id)
    await client.post(f"/api/v1/fde/apps/{app_id}/versions", headers=ADMIN, json={"release_notes": "v1"})
    await client.post(f"/api/v1/fde/apps/{app_id}/publish", headers=ADMIN, json={})
    share = await client.post(f"/api/v1/fde/apps/{app_id}/shares", headers=ADMIN, json={"name": "外部", "expires_in_days": 7, "max_uses": None})
    token = share.json()["token"]
    public = (await client.get(f"/api/v1/fde/share/{token}")).json()
    for manifest in (public["manifest"], public["published_version"]["manifest"]):
        assert manifest["system_prompt"] == ""
        assert manifest["llm_model_id"] is None
        assert manifest["tools"] == []
        assert manifest["input_fields"], "form fields are still needed to render the page"
    ran = await client.post(f"/api/v1/fde/share/{token}/run", json={"input_values": content_inputs()})
    assert ran.status_code == 200, ran.text
    runs = (await client.get("/api/v1/observability/runs", headers=ADMIN, params={"channel": "share"})).json()["items"]
    assert runs[0]["trace_id"] == ran.json()["trace_id"]
