from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...models import ModelConfig
from ...schemas import ModelOptionResponse
from ...security import require_roles
from ...tenancy import current_workspace_id

router = APIRouter(dependencies=[Depends(require_roles("admin", "manager"))])


@router.get("", response_model=list[ModelOptionResponse])
async def list_model_options(session: AsyncSession = Depends(get_session)) -> list[ModelConfig]:
    result = await session.scalars(select(ModelConfig).where(ModelConfig.workspace_id == current_workspace_id()).order_by(ModelConfig.display_name))
    return list(result)
