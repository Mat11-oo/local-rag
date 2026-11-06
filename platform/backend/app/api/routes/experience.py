"""Small UX event vocabulary. No prompts, filenames, queries, keys or answer text."""
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ...db import get_session
from ...models import AuditEvent, QueryLog, RunStatus, Conversation
from ...security import AuthContext, require_roles

router = APIRouter()


class ExperienceEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: UUID
    session_id: UUID
    event: Literal['task_started','trusted_answer_confirmed','onboarding_opened','import_started','import_completed','import_failed','preview_failed','save_failed','save_recovered','search_started','search_selected','chat_started','chat_completed','chat_failed','chat_wait_cancelled']
    occurred_at: datetime | None = None
    task_id: UUID | None = None
    operation_id: UUID | None = None
    trace_id: UUID | None = None
    failure_kind: Literal['network','auth','permission','missing','validation','provider','unknown'] | None = None
    recovery_ms: int | None = Field(default=None,ge=0,le=86400000)
    duration_ms: int | None = Field(default=None, ge=0, le=86400000)


@router.post('/events', status_code=202)
async def capture(body: ExperienceEvent, context: AuthContext = Depends(require_roles('admin','manager','user')), session: AsyncSession = Depends(get_session)):
    if await session.get(AuditEvent, str(body.id)):
        return {'accepted': True}
    if body.event == 'trusted_answer_confirmed':
        log = await session.scalar(select(QueryLog).where(QueryLog.trace_id==str(body.trace_id),QueryLog.workspace_id==context.workspace_id,QueryLog.status==RunStatus.SUCCESS))
        meta = (log.run_metadata or {}) if log else {}
        conversation = await session.get(Conversation,log.conversation_id) if log and log.conversation_id else None
        if not log or meta.get('simulated',True) or not meta.get('citation_count') or meta.get('handoff') or (conversation and conversation.user_id and conversation.user_id!=context.user_id):
            raise HTTPException(status_code=409,detail='请先核对当前操作者已完成、带引用且非测试替身的回答。')
    occurred=body.occurred_at or datetime.now(UTC)
    if occurred.tzinfo is None or not datetime.now(UTC)-timedelta(days=30)<=occurred<=datetime.now(UTC)+timedelta(minutes=5):
        raise HTTPException(status_code=422,detail='事件时间不在最近30天至未来5分钟的允许范围内。')
    detail={'event':body.event,'duration_ms':body.duration_ms}
    for field in ('task_id','operation_id','failure_kind','recovery_ms'):
        value=getattr(body,field)
        if value is not None:detail[field]=str(value) if isinstance(value,UUID) else value
    session.add(AuditEvent(id=str(body.id),workspace_id=context.workspace_id,actor_id=context.user_id,
        created_at=occurred,action='ux.event',resource_type='ux_session',resource_id=str(body.session_id),
        detail=detail))
    await session.commit()
    return {'accepted':True}


@router.get('/summary')
async def summary(days: int = Query(default=7,ge=1,le=30), context: AuthContext = Depends(require_roles('admin','manager')), session: AsyncSession = Depends(get_session)):
    rows = list(await session.scalars(select(AuditEvent).where(AuditEvent.workspace_id==context.workspace_id,AuditEvent.action=='ux.event',AuditEvent.created_at>=datetime.now(UTC)-timedelta(days=days)).order_by(AuditEvent.created_at.desc()).limit(5001)))
    selected=rows[:5000]
    counts = Counter(row.detail['event'] for row in selected)
    failures=Counter(row.detail.get('failure_kind','unknown') for row in selected if row.detail.get('event','').endswith('_failed'))
    recoveries=[row.detail['recovery_ms'] for row in selected if row.detail.get('recovery_ms') is not None]
    tasks={}
    for row in sorted(selected,key=lambda row:(row.created_at,0 if row.detail.get('event')=='task_started' else 1)):
        task_id=row.detail.get('task_id')
        if not task_id:continue
        task=tasks.setdefault(task_id,{'first':row.created_at,'last':row.created_at,'phase':'started','complete':False,'trusted_at':None,'started':False})
        task['last']=row.created_at
        task['phase']=row.detail['event']
        if row.detail['event']=='task_started':task['first']=row.created_at;task['started']=True
        if row.detail['event']=='trusted_answer_confirmed' and not task['complete']:task['complete']=True;task['trusted_at']=row.created_at
    complete=[task for task in tasks.values() if task['complete'] and task['started']]
    interrupted=Counter(task['phase'] for task in tasks.values() if task['started'] and not task['complete'])
    trusted_durations=[int((task['trusted_at']-task['first']).total_seconds()*1000) for task in complete]
    task_summary={'started':sum(task['started'] for task in tasks.values()),'completed':len(complete),'unfinished_by_last_event':dict(interrupted),'mean_first_trusted_ms':round(sum(trusted_durations)/len(trusted_durations)) if trusted_durations else None,'recovered_operations':len(recoveries),'mean_recovery_ms':round(sum(recoveries)/len(recoveries)) if recoveries else None,'failure_categories':dict(failures)}
    durations = [row.detail['duration_ms'] for row in rows[:5000] if row.detail.get('event')=='chat_completed' and row.detail.get('duration_ms') is not None]
    return {'tasks':task_summary,'days':days,'events':dict(counts),'sessions':len({row.resource_id for row in rows[:5000]}),
            'sample_count':min(len(rows),5000),'truncated':len(rows)>5000,
            'mean_completed_chat_ms':round(sum(durations)/len(durations)) if durations else None,
            'scope':'当前工作空间的已记录交互；测试替身、重复尝试及本地多人操作均可能计入，未完成只表示窗口内尚未记录可信回答确认，不等于永久流失。可信回答由用户核对引用后确认，不代表自动判断业务正确率。'}
