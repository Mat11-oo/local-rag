from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...models import AuditEvent, ConnectionStatus, ToolConfig
from ...security import AuthContext, encrypt_secret, require_roles
from ...services.tools import execute_http_tool


router = APIRouter()


class ToolPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    kind: Literal["http", "mcp", "workflow"] = "http"
    description: str = Field(default="", max_length=2000)
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = Field(default=None, max_length=4000)
    is_enabled: bool = True

    @model_validator(mode="after")
    def validate_http(self) -> "ToolPayload":
        if self.kind == "http":
            if not self.config.get("url"):
                raise ValueError("HTTP 工具必须配置 URL")
            if self.config.get("method", "GET").upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                raise ValueError("HTTP 方法不受支持")
        return self


class ToolPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    config: dict[str, Any] | None = None
    secret: str | None = Field(default=None, max_length=4000)
    clear_secret: bool = False
    is_enabled: bool | None = None


class ToolTestRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


def serialize(tool: ToolConfig) -> dict[str, Any]:
    return {
        "id": tool.id,
        "name": tool.name,
        "kind": tool.kind,
        "description": tool.description,
        "config": tool.config,
        "has_secret": tool.secret_encrypted is not None,
        "is_enabled": tool.is_enabled,
        "connection_status": tool.connection_status,
        "last_tested_at": tool.last_tested_at,
        "last_error": tool.last_error,
        "created_at": tool.created_at,
        "updated_at": tool.updated_at,
    }


async def owned_tool(session: AsyncSession, tool_id: str, workspace_id: str) -> ToolConfig:
    tool = await session.scalar(select(ToolConfig).where(ToolConfig.id == tool_id, ToolConfig.workspace_id == workspace_id))
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    return tool


@router.get("")
async def list_tools(
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    tools = list(await session.scalars(select(ToolConfig).where(ToolConfig.workspace_id == context.workspace_id).order_by(ToolConfig.updated_at.desc())))
    return [serialize(tool) for tool in tools]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tool(
    payload: ToolPayload,
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tool = ToolConfig(
        workspace_id=context.workspace_id,
        name=payload.name,
        kind=payload.kind,
        description=payload.description,
        config=payload.config,
        secret_encrypted=encrypt_secret(payload.secret),
        is_enabled=payload.is_enabled,
    )
    session.add(tool)
    await session.flush()
    session.add(AuditEvent(workspace_id=context.workspace_id, actor_id=context.user_id, action="tool.created", resource_type="tool", resource_id=tool.id, detail={"kind": tool.kind}))
    await session.commit()
    await session.refresh(tool)
    return serialize(tool)


@router.patch("/{tool_id}")
async def update_tool(
    tool_id: str,
    payload: ToolPatch,
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tool = await owned_tool(session, tool_id, context.workspace_id)
    for key, value in payload.model_dump(exclude_unset=True, exclude={"secret", "clear_secret"}).items():
        setattr(tool, key, value)
    if payload.clear_secret:
        tool.secret_encrypted = None
    elif payload.secret:
        tool.secret_encrypted = encrypt_secret(payload.secret)
    tool.connection_status = ConnectionStatus.UNTESTED
    tool.last_error = None
    session.add(AuditEvent(workspace_id=context.workspace_id, actor_id=context.user_id, action="tool.updated", resource_type="tool", resource_id=tool.id))
    await session.commit()
    await session.refresh(tool)
    return serialize(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    tool_id: str,
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    tool = await owned_tool(session, tool_id, context.workspace_id)
    await session.delete(tool)
    session.add(AuditEvent(workspace_id=context.workspace_id, actor_id=context.user_id, action="tool.deleted", resource_type="tool", resource_id=tool.id))
    await session.commit()
    return Response(status_code=204)


@router.post("/{tool_id}/test")
async def test_tool(
    tool_id: str,
    payload: ToolTestRequest,
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tool = await owned_tool(session, tool_id, context.workspace_id)
    if tool.kind != "http":
        raise HTTPException(status_code=422, detail="该类型工具的连接器尚未启用")
    try:
        result = await execute_http_tool(tool, payload.arguments)
        tool.connection_status = ConnectionStatus.CONNECTED
        tool.last_error = None
    except Exception as exc:
        tool.connection_status = ConnectionStatus.ERROR
        tool.last_error = str(exc)[:2000]
        result = None
    tool.last_tested_at = datetime.now(UTC)
    session.add(AuditEvent(workspace_id=context.workspace_id, actor_id=context.user_id, action="tool.tested", resource_type="tool", resource_id=tool.id, detail={"ok": result is not None}))
    await session.commit()
    if result is None:
        raise HTTPException(status_code=422, detail=tool.last_error or "工具测试失败")
    return {"ok": True, **result}
