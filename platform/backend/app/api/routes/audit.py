from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...models import AuditEvent, User
from ...security import AuthContext, require_roles


router = APIRouter(dependencies=[Depends(require_roles("admin"))])


@router.get("")
async def list_audit_events(
    action: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_roles("admin")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    query = select(AuditEvent).where(AuditEvent.workspace_id == context.workspace_id).order_by(AuditEvent.created_at.desc())
    if action:
        query = query.where(AuditEvent.action == action)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(AuditEvent.action.ilike(pattern), AuditEvent.resource_type.ilike(pattern), AuditEvent.resource_id.ilike(pattern)))
    events = list(await session.scalars(query.offset(offset).limit(limit)))
    actor_ids = {item.actor_id for item in events if item.actor_id}
    users = list(await session.scalars(select(User).where(User.id.in_(actor_ids)))) if actor_ids else []
    names = {item.id: item.display_name for item in users}
    return [
        {
            "id": item.id,
            "actor_id": item.actor_id,
            "actor_name": names.get(item.actor_id or "", "Agent / 系统"),
            "action": item.action,
            "resource_type": item.resource_type,
            "resource_id": item.resource_id,
            "detail": item.detail,
            "created_at": item.created_at,
        }
        for item in events
    ]
