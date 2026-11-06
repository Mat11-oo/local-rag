from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import get_settings
from .db import SessionLocal
from .models import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID, Membership, User, Workspace
from .security import hash_password


async def bootstrap_defaults(session_factory: async_sessionmaker[AsyncSession] = SessionLocal) -> None:
    settings = get_settings()
    async with session_factory() as session:
        workspace = await session.get(Workspace, DEFAULT_WORKSPACE_ID)
        if not workspace:
            workspace = Workspace(id=DEFAULT_WORKSPACE_ID, name="默认业务空间", slug="default")
            session.add(workspace)
        email = settings.bootstrap_admin_email.strip().lower()
        user = await session.scalar(select(User).where(User.email == email))
        if not user:
            user_values = {
                "email": email,
                "display_name": "平台管理员",
                "password_hash": hash_password(settings.bootstrap_admin_password),
            }
            if not await session.get(User, DEFAULT_USER_ID):
                user_values["id"] = DEFAULT_USER_ID
            user = User(**user_values)
            session.add(user)
            await session.flush()
        membership = await session.scalar(
            select(Membership).where(Membership.workspace_id == workspace.id, Membership.user_id == user.id)
        )
        if not membership:
            session.add(Membership(workspace_id=workspace.id, user_id=user.id, role="admin"))
        await session.commit()
