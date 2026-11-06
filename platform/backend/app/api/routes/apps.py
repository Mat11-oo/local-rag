from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...db import get_session
from ...models import Conversation, KnowledgeBase, ModelConfig, ModelType, QAApp
from ...schemas import QAAppCreate, QAAppResponse, QAAppUpdate
from ...security import DemoRole, get_demo_role, require_roles
from ...tenancy import current_workspace_id

router = APIRouter()


async def _load_app(session: AsyncSession, app_id: str) -> QAApp | None:
    query = select(QAApp).where(QAApp.id == app_id, QAApp.workspace_id == current_workspace_id()).options(selectinload(QAApp.knowledge_bases))
    return (await session.scalars(query)).one_or_none()


async def _app_or_404(session: AsyncSession, app_id: str, role: DemoRole) -> QAApp:
    app = await _load_app(session, app_id)
    if app is None or (role == "user" and not app.is_enabled):
        raise HTTPException(status_code=404, detail="QA app not found")
    return app


async def _validate_llm(session: AsyncSession, model_id: str) -> None:
    model = await session.get(ModelConfig, model_id)
    if model is None or model.workspace_id != current_workspace_id() or model.model_type != ModelType.LLM:
        raise HTTPException(status_code=422, detail="LLM model configuration not found")


async def _resolve_knowledge_bases(session: AsyncSession, ids: list[str]) -> list[KnowledgeBase]:
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="knowledge_base_ids cannot contain duplicates")
    result = list(await session.scalars(select(KnowledgeBase).where(KnowledgeBase.id.in_(ids), KnowledgeBase.workspace_id == current_workspace_id())))
    found = {item.id for item in result}
    missing = [item for item in ids if item not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Knowledge bases not found: {', '.join(missing)}")
    by_id = {item.id: item for item in result}
    return [by_id[item] for item in ids]


async def _serialize_app(session: AsyncSession, app: QAApp) -> QAAppResponse:
    conversation_count = await session.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.app_id == app.id)
    )
    return QAAppResponse(
        id=app.id,
        name=app.name,
        description=app.description,
        scenario_type=app.scenario_type,
        system_prompt=app.system_prompt,
        llm_model_id=app.llm_model_id,
        knowledge_base_ids=[item.id for item in app.knowledge_bases],
        knowledge_bases=app.knowledge_bases,
        top_k=app.top_k,
        rerank_top_n=app.rerank_top_n,
        score_threshold=app.score_threshold,
        is_enabled=app.is_enabled,
        conversation_count=conversation_count or 0,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.get("", response_model=list[QAAppResponse])
async def list_apps(
    role: DemoRole = Depends(get_demo_role),
    session: AsyncSession = Depends(get_session),
) -> list[QAAppResponse]:
    query = select(QAApp).where(QAApp.workspace_id == current_workspace_id()).options(selectinload(QAApp.knowledge_bases)).order_by(QAApp.updated_at.desc())
    if role == "user":
        query = query.where(QAApp.is_enabled.is_(True))
    apps = list(await session.scalars(query))
    return [await _serialize_app(session, app) for app in apps]


@router.post(
    "",
    response_model=QAAppResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("admin", "manager"))],
)
async def create_app(payload: QAAppCreate, session: AsyncSession = Depends(get_session)) -> QAAppResponse:
    await _validate_llm(session, payload.llm_model_id)
    knowledge_bases = await _resolve_knowledge_bases(session, payload.knowledge_base_ids)
    app = QAApp(
        name=payload.name,
        description=payload.description,
        scenario_type=payload.scenario_type,
        system_prompt=payload.system_prompt,
        llm_model_id=payload.llm_model_id,
        top_k=payload.top_k,
        rerank_top_n=payload.rerank_top_n,
        score_threshold=payload.score_threshold,
        is_enabled=payload.is_enabled,
        knowledge_bases=knowledge_bases,
    )
    session.add(app)
    await session.commit()
    return await _serialize_app(session, (await _load_app(session, app.id)) or app)


@router.get("/{app_id}", response_model=QAAppResponse)
async def get_app(
    app_id: str,
    role: DemoRole = Depends(get_demo_role),
    session: AsyncSession = Depends(get_session),
) -> QAAppResponse:
    return await _serialize_app(session, await _app_or_404(session, app_id, role))


@router.patch(
    "/{app_id}",
    response_model=QAAppResponse,
    dependencies=[Depends(require_roles("admin", "manager"))],
)
async def update_app(
    app_id: str,
    payload: QAAppUpdate,
    session: AsyncSession = Depends(get_session),
) -> QAAppResponse:
    app = await _load_app(session, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="QA app not found")
    values = payload.model_dump(exclude_unset=True)
    knowledge_base_ids = values.pop("knowledge_base_ids", None)
    if "llm_model_id" in values:
        if values["llm_model_id"] is None:
            raise HTTPException(status_code=422, detail="llm_model_id cannot be null")
        await _validate_llm(session, values["llm_model_id"])
    next_top_k = values.get("top_k", app.top_k)
    next_rerank_top_n = values.get("rerank_top_n", app.rerank_top_n)
    if next_rerank_top_n > next_top_k:
        raise HTTPException(status_code=422, detail="rerank_top_n cannot exceed top_k")
    if knowledge_base_ids is not None:
        app.knowledge_bases = await _resolve_knowledge_bases(session, knowledge_base_ids)
    for key, value in values.items():
        setattr(app, key, value)
    await session.commit()
    return await _serialize_app(session, (await _load_app(session, app.id)) or app)


@router.delete(
    "/{app_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles("admin", "manager"))],
)
async def delete_app(app_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    app = await session.get(QAApp, app_id)
    if app is None or app.workspace_id != current_workspace_id():
        raise HTTPException(status_code=404, detail="QA app not found")
    await session.delete(app)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
