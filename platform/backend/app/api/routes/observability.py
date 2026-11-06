"""可观测：运行、会话、知识构建与用量费用。

所有统计都基于已持久化的 QueryLog / TraceStep / ImportJob，不做估算或补数；
缺失的 Token 或单价保持为空，由前端明确显示「未计价」。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...db import get_session
from ...models import (
    AppVersion,
    Conversation,
    Feedback,
    ImportJob,
    JobStatus,
    KnowledgeBase,
    KnowledgeFile,
    Message,
    QAApp,
    QueryLog,
    RunStatus,
)
from ...security import AuthContext, require_roles

router = APIRouter(dependencies=[Depends(require_roles("admin", "manager"))])

ACTIVE_JOB_STATUSES = {JobStatus.QUEUED, JobStatus.UPLOADING, JobStatus.PARSING, JobStatus.CHUNKING, JobStatus.INDEXING}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _percentile(values: list[int], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(ratio * (len(ordered) - 1))))
    return ordered[index]


async def _app_names(session: AsyncSession, ids: set[str | None]) -> dict[str, str]:
    clean = {item for item in ids if item}
    if not clean:
        return {}
    rows = await session.execute(select(QAApp.id, QAApp.name).where(QAApp.id.in_(clean)))
    return {row.id: row.name for row in rows}


async def _versions(session: AsyncSession, ids: set[str | None]) -> dict[str, int]:
    clean = {item for item in ids if item}
    if not clean:
        return {}
    rows = await session.execute(select(AppVersion.id, AppVersion.version).where(AppVersion.id.in_(clean)))
    return {row.id: row.version for row in rows}


async def _ratings(session: AsyncSession, message_ids: set[str | None]) -> dict[str, int]:
    clean = {item for item in message_ids if item}
    if not clean:
        return {}
    rows = await session.execute(
        select(Feedback.message_id, Feedback.rating).where(Feedback.message_id.in_(clean)).order_by(Feedback.created_at)
    )
    return {row.message_id: row.rating for row in rows}


def _step_summary(log: QueryLog) -> dict[str, int]:
    kinds = [(item.metadata_json or {}).get("kind") for item in log.traces]
    return {
        "step_count": len(log.traces),
        "model_calls": kinds.count("model"),
        "tool_calls": kinds.count("tool"),
        "retrievals": kinds.count("retrieval"),
        "errors": sum(1 for item in log.traces if item.status in {"error", "failed"}),
    }


def _run_item(log: QueryLog, apps: dict[str, str], versions: dict[str, int], ratings: dict[str, int]) -> dict[str, Any]:
    metadata = log.run_metadata or {}
    return {
        "id": log.id,
        "trace_id": log.trace_id,
        "app_id": log.app_id,
        "app_name": apps.get(log.app_id or "", "已删除应用" if log.app_id else None),
        "conversation_id": log.conversation_id,
        "message_id": log.message_id,
        "query": log.query,
        "status": log.status,
        "channel": log.channel,
        "model_name": log.model_name,
        "app_version": versions.get(log.app_version_id or ""),
        "app_version_id": log.app_version_id,
        "duration_ms": log.duration_ms,
        "tokens": {"input": log.input_tokens, "output": log.output_tokens, "total": log.total_tokens},
        "cost": log.cost,
        "currency": (metadata.get("pricing") or {}).get("currency", "USD"),
        "error_message": log.error_message,
        "handoff": bool(metadata.get("handoff")),
        "simulated": bool(metadata.get("simulated")),
        "feedback": ratings.get(log.message_id or ""),
        "started_at": log.started_at,
        "finished_at": log.finished_at,
        **_step_summary(log),
    }


def _log_filters(workspace_id: str, *, days: int | None, app_id: str | None, status: str | None, channel: str | None, search: str | None) -> list[Any]:
    filters: list[Any] = [QueryLog.workspace_id == workspace_id]
    if days:
        filters.append(QueryLog.started_at >= _since(days))
    if app_id:
        filters.append(QueryLog.app_id == app_id)
    if status:
        if status not in {RunStatus.RUNNING, RunStatus.SUCCESS, RunStatus.FAILED}:
            raise HTTPException(status_code=422, detail="Invalid run status")
        filters.append(QueryLog.status == status)
    if channel:
        filters.append(QueryLog.channel == channel)
    if search:
        pattern = f"%{search}%"
        filters.append(or_(QueryLog.query.ilike(pattern), QueryLog.trace_id.ilike(pattern), QueryLog.error_message.ilike(pattern)))
    return filters


# ------------------------------------------------------------------ 总览


@router.get("/overview")
async def overview(
    days: int = Query(default=7, ge=1, le=90),
    app_id: str | None = None,
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    since = _since(days)
    filters = _log_filters(context.workspace_id, days=days, app_id=app_id, status=None, channel=None, search=None)
    rows = (
        await session.execute(
            select(
                QueryLog.trace_id, QueryLog.app_id, QueryLog.status, QueryLog.duration_ms, QueryLog.input_tokens,
                QueryLog.output_tokens, QueryLog.total_tokens, QueryLog.cost, QueryLog.started_at, QueryLog.query,
                QueryLog.error_message, QueryLog.run_metadata, QueryLog.channel,
            ).where(*filters).order_by(QueryLog.started_at.desc()).limit(50000)
        )
    ).all()
    success = [row for row in rows if row.status == RunStatus.SUCCESS]
    failed = [row for row in rows if row.status == RunStatus.FAILED]
    durations = [row.duration_ms for row in rows if row.duration_ms is not None]
    costs = [row.cost for row in rows if row.cost is not None]

    today = datetime.now(UTC).date()
    daily: dict[str, dict[str, Any]] = {
        (today - timedelta(days=offset)).isoformat(): {"runs": 0, "failed": 0, "tokens": 0, "cost": 0.0}
        for offset in range(days - 1, -1, -1)
    }
    per_app: dict[str, dict[str, int]] = defaultdict(lambda: {"runs": 0, "failed": 0})
    for row in rows:
        key = _aware(row.started_at).date().isoformat()  # type: ignore[union-attr]
        if key in daily:
            daily[key]["runs"] += 1
            daily[key]["failed"] += int(row.status == RunStatus.FAILED)
            daily[key]["tokens"] += row.total_tokens or 0
            daily[key]["cost"] += row.cost or 0.0
        if row.app_id:
            per_app[row.app_id]["runs"] += 1
            per_app[row.app_id]["failed"] += int(row.status == RunStatus.FAILED)
    apps = await _app_names(session, {row.app_id for row in rows})

    feedback_rows = (
        await session.execute(
            select(Feedback.rating, func.count(Feedback.id))
            .join(Message, Message.id == Feedback.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.workspace_id == context.workspace_id, Feedback.created_at >= since, *( [Conversation.app_id == app_id] if app_id else []))
            .group_by(Feedback.rating)
        )
    ).all()
    feedback = {"up": 0, "down": 0}
    for rating, count in feedback_rows:
        feedback["up" if rating > 0 else "down"] += count

    job_rows = (
        await session.execute(
            select(ImportJob.status, func.count(ImportJob.id))
            .join(KnowledgeFile, KnowledgeFile.id == ImportJob.file_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeFile.knowledge_base_id)
            .where(KnowledgeBase.workspace_id == context.workspace_id, ImportJob.created_at >= since)
            .group_by(ImportJob.status)
        )
    ).all()
    builds = {"total": 0, "completed": 0, "failed": 0, "running": 0}
    for job_status, count in job_rows:
        builds["total"] += count
        if job_status == JobStatus.COMPLETED:
            builds["completed"] += count
        elif job_status == JobStatus.FAILED:
            builds["failed"] += count
        elif job_status in ACTIVE_JOB_STATUSES:
            builds["running"] += count

    completed = len(success) + len(failed)
    return {
        "days": days,
        "runs": {
            "total": len(rows),
            "success": len(success),
            "failed": len(failed),
            "success_rate": round(len(success) / completed * 100, 2) if completed else None,
            "p50_ms": _percentile(durations, 0.5),
            "p95_ms": _percentile(durations, 0.95),
            "handoff": sum(1 for row in rows if (row.run_metadata or {}).get("handoff")),
        },
        "tokens": {
            "input": sum(row.input_tokens or 0 for row in rows),
            "output": sum(row.output_tokens or 0 for row in rows),
            "total": sum(row.total_tokens or 0 for row in rows),
        },
        "cost": {"total": round(sum(costs), 6) if costs else None, "priced_runs": len(costs), "unpriced_runs": len(success) - len(costs)},
        "feedback": feedback,
        "builds": builds,
        "daily": [{"date": key, **value, "cost": round(value["cost"], 6)} for key, value in daily.items()],
        "top_apps": sorted(
            [{"app_id": key, "app_name": apps.get(key, "已删除应用"), **value} for key, value in per_app.items()],
            key=lambda item: item["runs"],
            reverse=True,
        )[:8],
        "recent_failures": [
            {"trace_id": row.trace_id, "app_id": row.app_id, "app_name": apps.get(row.app_id or "", None), "query": row.query, "error_message": row.error_message, "started_at": row.started_at, "channel": row.channel}
            for row in failed[:6]
        ],
    }


# ------------------------------------------------------------------ 运行


@router.get("/runs")
async def list_runs(
    app_id: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    search: str | None = None,
    days: int | None = Query(default=None, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    filters = _log_filters(context.workspace_id, days=days, app_id=app_id, status=status, channel=channel, search=search)
    total = await session.scalar(select(func.count(QueryLog.id)).where(*filters)) or 0
    logs = list(
        await session.scalars(
            select(QueryLog).where(*filters).options(selectinload(QueryLog.traces)).order_by(QueryLog.started_at.desc()).offset(offset).limit(limit)
        )
    )
    apps = await _app_names(session, {log.app_id for log in logs})
    versions = await _versions(session, {log.app_version_id for log in logs})
    ratings = await _ratings(session, {log.message_id for log in logs})
    return {"total": total, "items": [_run_item(log, apps, versions, ratings) for log in logs]}


@router.get("/runs/{trace_id}")
async def get_run(
    trace_id: str,
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    log = await session.scalar(
        select(QueryLog).where(QueryLog.workspace_id == context.workspace_id, QueryLog.trace_id == trace_id).options(selectinload(QueryLog.traces))
    )
    if not log:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    apps = await _app_names(session, {log.app_id})
    versions = await _versions(session, {log.app_version_id})
    ratings = await _ratings(session, {log.message_id})
    answer = await session.get(Message, log.message_id) if log.message_id else None
    feedback = list(await session.scalars(select(Feedback).where(Feedback.message_id == log.message_id))) if log.message_id else []
    history_count = 0
    if log.conversation_id and answer:
        history_count = await session.scalar(
            select(func.count(Message.id)).where(Message.conversation_id == log.conversation_id, Message.created_at < answer.created_at)
        ) or 0
    return {
        **_run_item(log, apps, versions, ratings),
        "input_values": (log.run_metadata or {}).get("input_values", {}),
        "output": answer.content if answer else None,
        "citations": answer.citations if answer else [],
        "history_messages": max(0, history_count - 1),
        "run_metadata": log.run_metadata or {},
        "feedback_items": [{"rating": item.rating, "comment": item.comment, "created_at": item.created_at} for item in feedback],
        "spans": [
            {
                "id": item.id,
                "ordinal": item.ordinal,
                "kind": (item.metadata_json or {}).get("kind") or "step",
                "name": item.name,
                "status": item.status,
                "duration_ms": item.duration_ms,
                "detail": item.detail,
                "metadata": item.metadata_json or {},
            }
            for item in log.traces
        ],
    }


# ------------------------------------------------------------------ 会话


@router.get("/conversations")
async def list_conversations(
    app_id: str | None = None,
    search: str | None = None,
    days: int | None = Query(default=None, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    filters: list[Any] = [Conversation.workspace_id == context.workspace_id]
    if app_id:
        filters.append(Conversation.app_id == app_id)
    if days:
        filters.append(Conversation.updated_at >= _since(days))
    if search:
        filters.append(Conversation.title.ilike(f"%{search}%"))
    total = await session.scalar(select(func.count(Conversation.id)).where(*filters)) or 0
    conversations = list(await session.scalars(select(Conversation).where(*filters).order_by(Conversation.updated_at.desc()).offset(offset).limit(limit)))
    ids = [item.id for item in conversations]
    turns: dict[str, int] = {}
    stats: dict[str, dict[str, Any]] = {}
    feedback: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
    if ids:
        for conversation_id, count in (
            await session.execute(select(Message.conversation_id, func.count(Message.id)).where(Message.conversation_id.in_(ids), Message.role == "user").group_by(Message.conversation_id))
        ).all():
            turns[conversation_id] = count
        for row in (
            await session.execute(
                select(
                    QueryLog.conversation_id,
                    func.coalesce(func.sum(QueryLog.total_tokens), 0),
                    func.sum(QueryLog.cost),
                    func.count(QueryLog.id).filter(QueryLog.status == RunStatus.FAILED),
                ).where(QueryLog.conversation_id.in_(ids)).group_by(QueryLog.conversation_id)
            )
        ).all():
            stats[row[0]] = {"tokens": int(row[1] or 0), "cost": row[2], "failed_runs": row[3]}
        for conversation_id, rating in (
            await session.execute(select(Message.conversation_id, Feedback.rating).join(Feedback, Feedback.message_id == Message.id).where(Message.conversation_id.in_(ids)))
        ).all():
            feedback[conversation_id]["up" if rating > 0 else "down"] += 1
    apps = await _app_names(session, {item.app_id for item in conversations})
    return {
        "total": total,
        "items": [
            {
                "id": item.id,
                "app_id": item.app_id,
                "app_name": apps.get(item.app_id, "已删除应用"),
                "title": item.title,
                "user_id": item.user_id,
                "demo_role": item.demo_role,
                "turns": turns.get(item.id, 0),
                "tokens": stats.get(item.id, {}).get("tokens", 0),
                "cost": stats.get(item.id, {}).get("cost"),
                "failed_runs": stats.get(item.id, {}).get("failed_runs", 0),
                "feedback": feedback[item.id],
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in conversations
        ],
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    conversation = await session.get(Conversation, conversation_id)
    if not conversation or conversation.workspace_id != context.workspace_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = list(await session.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)))
    logs = list(await session.scalars(select(QueryLog).where(QueryLog.conversation_id == conversation.id).order_by(QueryLog.started_at)))
    trace_by_message = {log.message_id: log for log in logs if log.message_id}
    ratings = await _ratings(session, {item.id for item in messages})
    apps = await _app_names(session, {conversation.app_id})
    return {
        "id": conversation.id,
        "app_id": conversation.app_id,
        "app_name": apps.get(conversation.app_id, "已删除应用"),
        "title": conversation.title,
        "user_id": conversation.user_id,
        "demo_role": conversation.demo_role,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "messages": [
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "citations": item.citations,
                "input_values": item.input_values,
                "tokens": {"input": item.input_tokens, "output": item.output_tokens},
                "duration_ms": item.duration_ms,
                "trace_id": trace_by_message[item.id].trace_id if item.id in trace_by_message else None,
                "cost": trace_by_message[item.id].cost if item.id in trace_by_message else None,
                "feedback": ratings.get(item.id),
                "created_at": item.created_at,
            }
            for item in messages
        ],
        "failed_runs": [
            {"trace_id": log.trace_id, "query": log.query, "error_message": log.error_message, "started_at": log.started_at}
            for log in logs
            if log.status == RunStatus.FAILED
        ],
    }


# ------------------------------------------------------------------ 知识构建


@router.get("/build-jobs")
async def list_build_jobs(
    knowledge_base_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    base = (
        select(ImportJob, KnowledgeFile, KnowledgeBase)
        .join(KnowledgeFile, KnowledgeFile.id == ImportJob.file_id)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeFile.knowledge_base_id)
        .where(KnowledgeBase.workspace_id == context.workspace_id)
    )
    if knowledge_base_id:
        base = base.where(KnowledgeBase.id == knowledge_base_id)
    summary_query = (
        select(ImportJob.status, func.count(ImportJob.id))
        .join(KnowledgeFile, KnowledgeFile.id == ImportJob.file_id)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeFile.knowledge_base_id)
        .where(KnowledgeBase.workspace_id == context.workspace_id, *([KnowledgeBase.id == knowledge_base_id] if knowledge_base_id else []))
        .group_by(ImportJob.status)
    )
    summary_rows = (await session.execute(summary_query)).all()
    summary = {"total": 0, "completed": 0, "failed": 0, "running": 0}
    for job_status, count in summary_rows:
        summary["total"] += count
        if job_status == JobStatus.COMPLETED:
            summary["completed"] += count
        elif job_status == JobStatus.FAILED:
            summary["failed"] += count
        else:
            summary["running"] += count
    if status == "running":
        base = base.where(ImportJob.status.in_(ACTIVE_JOB_STATUSES))
    elif status:
        base = base.where(ImportJob.status == status)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await session.execute(base.order_by(ImportJob.created_at.desc()).offset(offset).limit(limit))).all()
    items = []
    for job, file, knowledge_base in rows:
        started, finished = _aware(job.started_at), _aware(job.finished_at)
        items.append({
            "id": job.id,
            "file_id": file.id,
            "filename": file.filename,
            "extension": file.extension,
            "size_bytes": file.size_bytes,
            "knowledge_base_id": knowledge_base.id,
            "knowledge_base_name": knowledge_base.name,
            "status": job.status,
            "progress": job.progress,
            "current_stage": job.current_stage,
            "stage_details": job.stage_details,
            "error_message": job.error_message or file.error_message,
            "chunk_count": file.chunk_count,
            "chunk_method": (file.chunk_config or {}).get("method") or knowledge_base.chunk_method,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "duration_ms": int((finished - started).total_seconds() * 1000) if started and finished else None,
        })
    return {"total": total, "summary": summary, "items": items}


# ------------------------------------------------------------------ 用量与费用


@router.get("/usage")
async def usage(
    days: int = Query(default=30, ge=1, le=365),
    group_by: str = Query(default="app", pattern="^(app|model|channel)$"),
    app_id: str | None = None,
    context: AuthContext = Depends(require_roles("admin", "manager")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    query = (
        select(QueryLog.app_id, QueryLog.model_name, QueryLog.channel, QueryLog.status, QueryLog.input_tokens, QueryLog.output_tokens, QueryLog.total_tokens, QueryLog.cost, QueryLog.duration_ms, QueryLog.run_metadata)
        .where(QueryLog.workspace_id == context.workspace_id, QueryLog.started_at >= _since(days))
    )
    if app_id:
        query = query.where(QueryLog.app_id == app_id)
    rows = (await session.execute(query.limit(100000))).all()
    apps = await _app_names(session, {row.app_id for row in rows})
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        if group_by == "app":
            key, name = row.app_id or "-", apps.get(row.app_id or "", "已删除应用")
        elif group_by == "model":
            key = name = row.model_name or "未知模型"
        else:
            key = name = row.channel or "web"
        bucket = groups.setdefault(key, {"key": key, "name": name, "runs": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost": 0.0, "priced_runs": 0, "durations": []})
        bucket["runs"] += 1
        bucket["failed"] += int(row.status == RunStatus.FAILED)
        bucket["input_tokens"] += row.input_tokens or 0
        bucket["output_tokens"] += row.output_tokens or 0
        bucket["total_tokens"] += row.total_tokens or 0
        if row.cost is not None:
            bucket["cost"] += row.cost
            bucket["priced_runs"] += 1
        if row.duration_ms is not None:
            bucket["durations"].append(row.duration_ms)
    items = []
    for bucket in groups.values():
        durations = bucket.pop("durations")
        bucket["cost"] = round(bucket["cost"], 6) if bucket["priced_runs"] else None
        bucket["avg_duration_ms"] = round(sum(durations) / len(durations)) if durations else None
        items.append(bucket)
    items.sort(key=lambda item: (item["cost"] or 0, item["total_tokens"]), reverse=True)
    priced = [row.cost for row in rows if row.cost is not None]
    return {
        "days": days,
        "group_by": group_by,
        "currency": "USD",
        "totals": {
            "runs": len(rows),
            "input_tokens": sum(row.input_tokens or 0 for row in rows),
            "output_tokens": sum(row.output_tokens or 0 for row in rows),
            "total_tokens": sum(row.total_tokens or 0 for row in rows),
            "cost": round(sum(priced), 6) if priced else None,
            "priced_runs": len(priced),
        },
        "items": items,
    }
