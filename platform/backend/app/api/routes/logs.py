from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...db import get_session
from ...models import QAApp, QueryLog, RunStatus
from ...schemas import LogSummaryResponse, QueryLogResponse, TraceStepResponse
from ...security import require_roles
from ...tenancy import current_workspace_id

router = APIRouter(dependencies=[Depends(require_roles("admin", "manager"))])


async def _serialize_log(session: AsyncSession, log: QueryLog) -> QueryLogResponse:
    app_name = None
    if log.app_id:
        app_name = await session.scalar(select(QAApp.name).where(QAApp.id == log.app_id))
    return QueryLogResponse(
        id=log.id,
        trace_id=log.trace_id,
        app_id=log.app_id,
        app_name=app_name,
        conversation_id=log.conversation_id,
        demo_role=log.demo_role,
        query=log.query,
        status=log.status,
        input_tokens=log.input_tokens,
        output_tokens=log.output_tokens,
        total_tokens=log.total_tokens,
        duration_ms=log.duration_ms,
        error_message=log.error_message,
        started_at=log.started_at,
        finished_at=log.finished_at,
        traces=[TraceStepResponse.model_validate(item) for item in log.traces],
    )


@router.get("/summary", response_model=LogSummaryResponse)
async def log_summary(session: AsyncSession = Depends(get_session)) -> LogSummaryResponse:
    row = (
        await session.execute(
            select(
                func.count(QueryLog.id),
                func.count(QueryLog.id).filter(QueryLog.status == RunStatus.SUCCESS),
                func.count(QueryLog.id).filter(QueryLog.status == RunStatus.FAILED),
                func.coalesce(func.sum(QueryLog.input_tokens), 0),
                func.coalesce(func.sum(QueryLog.output_tokens), 0),
                func.coalesce(func.sum(QueryLog.total_tokens), 0),
                func.avg(QueryLog.duration_ms),
            ).where(QueryLog.workspace_id == current_workspace_id())
        )
    ).one()
    query_count, success_count, failed_count, input_tokens, output_tokens, total_tokens, average = row
    completed_count = success_count + failed_count
    success_rate = (success_count / completed_count * 100.0) if completed_count else 0.0
    return LogSummaryResponse(
        query_count=query_count,
        success_count=success_count,
        failed_count=failed_count,
        success_rate=round(success_rate, 2),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        average_duration_ms=round(average) if average is not None else None,
    )


@router.get("", response_model=list[QueryLogResponse])
async def list_logs(
    status: str | None = None,
    search: str | None = None,
    app_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[QueryLogResponse]:
    query = select(QueryLog).where(QueryLog.workspace_id == current_workspace_id()).options(selectinload(QueryLog.traces)).order_by(QueryLog.started_at.desc())
    if status:
        if status not in {RunStatus.RUNNING, RunStatus.SUCCESS, RunStatus.FAILED}:
            raise HTTPException(status_code=422, detail="Invalid log status")
        query = query.where(QueryLog.status == status)
    if app_id:
        query = query.where(QueryLog.app_id == app_id)
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(QueryLog.query.ilike(pattern), QueryLog.trace_id.ilike(pattern)))
    logs = list(await session.scalars(query.offset(offset).limit(limit)))
    return [await _serialize_log(session, log) for log in logs]


@router.get("/{trace_id}", response_model=QueryLogResponse)
async def get_log(trace_id: str, session: AsyncSession = Depends(get_session)) -> QueryLogResponse:
    query = select(QueryLog).where(QueryLog.workspace_id == current_workspace_id()).where(QueryLog.trace_id == trace_id).options(selectinload(QueryLog.traces))
    log = (await session.scalars(query)).one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="Query log not found")
    return await _serialize_log(session, log)
