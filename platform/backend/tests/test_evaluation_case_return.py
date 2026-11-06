from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    Message,
    ModelConfig,
    ModelType,
    ProviderName,
    QAApp,
    QueryLog,
    RunStatus,
    TraceStep,
    utc_now,
)
from app.tenancy import DEFAULT_SCOPE


ADMIN = {"X-Demo-Role": "admin"}
MANAGER = {"X-Demo-Role": "manager"}
USER = {"X-Demo-Role": "user"}


async def _seed_online_log(db_session: AsyncSession) -> tuple[QAApp, QueryLog, Message]:
    model = ModelConfig(
        workspace_id=DEFAULT_SCOPE,
        display_name="Mock LLM",
        provider=ProviderName.MOCK,
        model_type=ModelType.LLM,
        model_name="mock-llm",
        base_url="mock://local",
        connection_status="mock",
    )
    db_session.add(model)
    await db_session.flush()
    app = QAApp(
        workspace_id=DEFAULT_SCOPE,
        name="线上员工助手",
        description="用于 Case 回流测试",
        scenario_type="qa",
        system_prompt="回答用户问题。",
        llm_model_id=model.id,
        is_enabled=True,
    )
    db_session.add(app)
    await db_session.flush()
    conversation = Conversation(
        workspace_id=DEFAULT_SCOPE,
        app_id=app.id,
        title="用户咨询",
        demo_role="user",
    )
    db_session.add(conversation)
    await db_session.flush()
    started = utc_now() - timedelta(seconds=2)
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content="年假没有休完可以结转吗？",
        created_at=started,
    )
    assistant = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="这是测试替身生成的回答，不代表真实模型输出。",
        citations=[],
        input_tokens=12,
        output_tokens=16,
        created_at=started + timedelta(seconds=1),
    )
    log = QueryLog(
        workspace_id=DEFAULT_SCOPE,
        app_id=app.id,
        conversation_id=conversation.id,
        demo_role="user",
        query=user_message.content,
        status=RunStatus.SUCCESS,
        input_tokens=12,
        output_tokens=16,
        total_tokens=28,
        duration_ms=320,
        started_at=started,
        finished_at=started + timedelta(seconds=1),
    )
    db_session.add_all([user_message, assistant, log])
    await db_session.flush()
    db_session.add(
        TraceStep(
            query_log_id=log.id,
            ordinal=1,
            name="LLM 生成",
            status=RunStatus.SUCCESS,
            duration_ms=300,
            detail="Mock LLM 流式生成完成",
            metadata_json={"provider": "mock", "model": "mock-llm", "simulated": True},
        )
    )
    await db_session.commit()
    return app, log, assistant


async def _create_set(client: AsyncClient, app_id: str, name: str) -> dict:
    response = await client.post(
        "/api/v1/evaluation-sets",
        headers=MANAGER,
        json={"app_id": app_id, "name": name, "description": "每日线上 Case 回流"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_online_case_return_dedup_readiness_snapshot_and_run(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    app, log, assistant = await _seed_online_log(db_session)

    denied = await client.get("/api/v1/evaluation-sets", headers=USER)
    assert denied.status_code == 403

    good_set = await _create_set(client, app.id, "每日 Good Case")
    good = await client.post(
        f"/api/v1/evaluation-sets/{good_set['id']}/cases/from-logs",
        headers=MANAGER,
        json={"trace_ids": [log.trace_id], "case_type": "good", "tags": ["年假", "回流"]},
    )
    assert good.status_code == 201, good.text
    good_case = good.json()["cases"][0]
    assert good_case["readiness"] == "ready"
    assert good_case["expected_output"] == assistant.content
    assert good_case["source_snapshot"]["model"]["model"] == "mock-llm"
    assert good_case["source_snapshot"]["conversation"][-1]["content"] == assistant.content

    duplicate = await client.post(
        f"/api/v1/evaluation-sets/{good_set['id']}/cases/from-logs",
        headers=ADMIN,
        json={"trace_ids": [log.trace_id], "case_type": "good"},
    )
    assert duplicate.status_code == 409

    good_run = await client.post(f"/api/v1/evaluation-sets/{good_set['id']}/run", headers=MANAGER)
    assert good_run.status_code == 200, good_run.text
    assert good_run.json()["passed_count"] == 1

    bad_set = await _create_set(client, app.id, "每日 Bad Case")
    bad = await client.post(
        f"/api/v1/evaluation-sets/{bad_set['id']}/cases/from-logs",
        headers=MANAGER,
        json={"trace_ids": [log.trace_id], "case_type": "bad"},
    )
    assert bad.status_code == 201, bad.text
    bad_case = bad.json()["cases"][0]
    assert bad_case["readiness"] == "needs_standard"
    assert bad_case["actual_output"] == assistant.content
    assert bad_case["expected_output"] == ""

    blocked = await client.post(f"/api/v1/evaluation-sets/{bad_set['id']}/run", headers=MANAGER)
    assert blocked.status_code == 409
    assert "待补评测标准" in blocked.json()["detail"]

    updated = await client.patch(
        f"/api/v1/evaluation-sets/{bad_set['id']}/cases/{bad_case['id']}",
        headers=MANAGER,
        json={"expected_keywords": ["测试替身"], "tags": ["年假", "需修复"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["readiness"] == "ready"

    run = await client.post(f"/api/v1/evaluation-sets/{bad_set['id']}/run", headers=MANAGER)
    assert run.status_code == 200, run.text
    assert run.json()["passed_count"] == 1, run.text
    assert run.json()["simulated"] is True

    assistant.content = "源日志后来被修改"
    await db_session.commit()
    detail = await client.get(f"/api/v1/evaluation-sets/{good_set['id']}", headers=MANAGER)
    assert detail.status_code == 200
    assert detail.json()["cases"][0]["source_snapshot"]["output"] == "这是测试替身生成的回答，不代表真实模型输出。"


async def test_case_return_rejects_cross_workspace_and_wrong_app(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    app, log, _assistant = await _seed_online_log(db_session)
    suite = await _create_set(client, app.id, "边界验证")

    other_app = QAApp(
        workspace_id=DEFAULT_SCOPE,
        name="另一个应用",
        scenario_type="content",
        system_prompt="测试",
        is_enabled=True,
    )
    db_session.add(other_app)
    await db_session.flush()
    wrong_app_log = QueryLog(
        workspace_id=DEFAULT_SCOPE,
        app_id=other_app.id,
        demo_role="user",
        query="来自其他应用",
        status=RunStatus.FAILED,
        error_message="failed",
    )
    cross_workspace_log = QueryLog(
        workspace_id="00000000-0000-0000-0000-000000000099",
        app_id=app.id,
        demo_role="user",
        query="来自其他空间",
        status=RunStatus.FAILED,
        error_message="failed",
    )
    db_session.add_all([wrong_app_log, cross_workspace_log])
    await db_session.commit()

    wrong_app = await client.post(
        f"/api/v1/evaluation-sets/{suite['id']}/cases/from-logs",
        headers=MANAGER,
        json={"trace_ids": [wrong_app_log.trace_id], "case_type": "bad"},
    )
    assert wrong_app.status_code == 422

    cross_workspace = await client.post(
        f"/api/v1/evaluation-sets/{suite['id']}/cases/from-logs",
        headers=MANAGER,
        json={"trace_ids": [cross_workspace_log.trace_id], "case_type": "bad"},
    )
    assert cross_workspace.status_code == 404

    still_empty = await client.get(f"/api/v1/evaluation-sets/{suite['id']}", headers=MANAGER)
    assert still_empty.json()["case_count"] == 0
    assert log.trace_id != wrong_app_log.trace_id
