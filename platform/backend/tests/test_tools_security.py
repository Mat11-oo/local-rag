from __future__ import annotations

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from app.models import DEFAULT_WORKSPACE_ID, ApiClient, ToolConfig
from app.fde.manifest import Manifest, Tool
from app.fde.runtime import _agent_answer
from app.security import encrypt_secret, hash_token
from app.services.tools import execute_http_tool


ADMIN = {"X-Demo-Role": "admin"}


async def test_tool_crud_never_returns_secret(client) -> None:
    created = await client.post(
        "/api/v1/tools",
        headers=ADMIN,
        json={
            "name": "查询库存",
            "kind": "http",
            "description": "按 SKU 查询库存",
            "secret": "private-token",
            "config": {
                "method": "GET",
                "url": "https://inventory.example.com/items/{{sku}}",
                "parameters": {"type": "object", "required": ["sku"], "properties": {"sku": {"type": "string"}}},
                "auth_type": "bearer",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["has_secret"] is True
    assert "secret" not in body
    listed = await client.get("/api/v1/tools", headers=ADMIN)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["id"]
    deleted = await client.delete(f"/api/v1/tools/{body['id']}", headers=ADMIN)
    assert deleted.status_code == 204


async def test_http_tool_renders_arguments_and_secret() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/items/ES-200"
        assert request.headers["authorization"] == "Bearer private-token"
        return httpx.Response(200, json={"stock": 12}, headers={"content-type": "application/json"})

    tool = ToolConfig(
        workspace_id=DEFAULT_WORKSPACE_ID,
        name="查询库存",
        kind="http",
        secret_encrypted=encrypt_secret("private-token"),
        config={
            "method": "GET",
            "url": "https://127.0.0.1/items/{{sku}}",
            "allow_private_network": True,
            "parameters": {"type": "object", "required": ["sku"], "properties": {"sku": {"type": "string"}}},
            "auth_type": "bearer",
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mocked:
        result = await execute_http_tool(tool, {"sku": "ES-200"}, client=mocked)
    assert result["data"] == {"stock": 12}


async def test_api_client_scope_is_enforced(client, db_session) -> None:
    raw = "fde_scope_test"
    db_session.add(ApiClient(
        workspace_id=DEFAULT_WORKSPACE_ID,
        name="read-only",
        token_hash=hash_token(raw),
        role="manager",
        scopes=["apps:read"],
    ))
    await db_session.commit()
    headers = {"Authorization": f"Bearer {raw}"}
    assert (await client.get("/api/v1/fde/capabilities", headers=headers)).status_code == 200
    denied = await client.post("/api/v1/fde/design", headers=headers, json={"brief": "test", "template_key": "content"})
    assert denied.status_code == 403
    assert denied.json()["detail"] == "API Token 缺少权限：apps:write"


class ToolCallingModel(BaseChatModel):
    _calls: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "tool-calling-test"

    def bind_tools(self, tools, **kwargs):
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop=None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        self._calls += 1
        message = AIMessage(
            content="" if self._calls == 1 else "当前库存 12 件。",
            tool_calls=[{"name": "query_stock", "args": {"sku": "ES-200"}, "id": "call-1"}] if self._calls == 1 else [],
            usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class ToolCallingGateway:
    is_simulated = False

    def __init__(self) -> None:
        self.model = ToolCallingModel()

    def chat_model(self, **kwargs):
        del kwargs
        return self.model


async def test_agent_executes_authorized_tool(db_session, monkeypatch) -> None:
    tool = ToolConfig(
        workspace_id=DEFAULT_WORKSPACE_ID,
        name="查询库存",
        kind="http",
        description="按 SKU 查询库存",
        config={"url": "https://example.com", "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}}},
    )
    db_session.add(tool)
    await db_session.commit()
    await db_session.refresh(tool)

    async def fake_execute(config, arguments):
        assert config.id == tool.id
        assert arguments == {"sku": "ES-200"}
        return {"content": '{"stock":12}'}

    monkeypatch.setattr("app.fde.runtime.execute_http_tool", fake_execute)
    manifest = Manifest(
        type="agent",
        name="库存 Agent",
        template_key="content",
        system_prompt="需要时查询库存",
        llm_model_id="model",
        tools=[Tool(name="query_stock", tool_id=tool.id)],
    )
    answer, usage, steps = await _agent_answer(
        db_session,
        manifest,
        gateway=ToolCallingGateway(),
        query="ES-200 还有货吗？",
        input_text="",
        context="",
        history=[],
        workspace_id=DEFAULT_WORKSPACE_ID,
    )
    assert answer == "当前库存 12 件。"
    assert usage["total"] == 16
    assert steps[0]["status"] == "success"
