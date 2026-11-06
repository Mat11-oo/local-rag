from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...db import get_session
from ...models import (
    Conversation,
    Message,
    ModelConfig,
    QAApp,
    QueryLog,
    RunStatus,
    TraceStep,
)
from ...providers import build_gateway
from ...providers.base import ProviderError
from ...schemas import (
    ChatRequest,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
)
from ...security import DemoRole, get_demo_role
from ...services.retrieval import RetrievedChunk, RetrievalRun, retrieve_knowledge_base
from ...tenancy import current_workspace_id

app_router = APIRouter()
conversation_router = APIRouter()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for item in content:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                pieces.append(str(item.get("text", "")))
        return "".join(pieces)
    return str(content) if content is not None else ""


async def _load_app(session: AsyncSession, app_id: str) -> QAApp | None:
    query = select(QAApp).where(QAApp.id == app_id, QAApp.workspace_id == current_workspace_id()).options(selectinload(QAApp.knowledge_bases))
    return (await session.scalars(query)).one_or_none()


async def _conversation_or_404(
    session: AsyncSession,
    conversation_id: str,
    role: DemoRole,
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.workspace_id != current_workspace_id() or (role == "user" and conversation.demo_role != role):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _message_response(message: Message) -> MessageResponse:
    return MessageResponse.model_validate(message)


def _citation(item: RetrievedChunk) -> dict[str, Any]:
    return {
        "chunk_id": item.chunk_id,
        "knowledge_base_id": item.knowledge_base_id,
        "file_id": item.file_id,
        "filename": item.filename,
        "title": item.title,
        "page_number": item.page_number,
        "content": item.content,
        "vector_score": round(item.vector_score, 6),
        "rerank_score": round(item.rerank_score, 6) if item.rerank_score is not None else None,
        "score": round(item.final_score, 6),
        "metadata": item.metadata,
    }


def _history_messages(messages: list[Message]) -> list[BaseMessage]:
    history: list[BaseMessage] = []
    for message in messages[-12:]:
        if message.role == "user":
            history.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            history.append(AIMessage(content=message.content))
    return history


async def _retrieve_for_app(
    session: AsyncSession,
    app: QAApp,
    query: str,
    knowledge_bases: list[Any],
) -> tuple[list[RetrievedChunk], list[RetrievalRun]]:
    runs: list[RetrievalRun] = []
    fusion_scores: dict[str, float] = {}
    chunks_by_id: dict[str, RetrievedChunk] = {}
    for knowledge_base in knowledge_bases:
        run = await retrieve_knowledge_base(
            session,
            knowledge_base,
            query,
            top_k=app.top_k,
            rerank_top_n=app.rerank_top_n,
            score_threshold=app.score_threshold,
        )
        runs.append(run)
        for rank, item in enumerate(run.results, start=1):
            fusion_scores[item.chunk_id] = fusion_scores.get(item.chunk_id, 0.0) + 1.0 / (10 + rank)
            chunks_by_id[item.chunk_id] = item
    combined = sorted(chunks_by_id.values(), key=lambda item: fusion_scores[item.chunk_id], reverse=True)
    return combined[: app.rerank_top_n], runs


def _trace(
    log: QueryLog,
    ordinal: int,
    name: str,
    duration_ms: int,
    detail: str,
    metadata: dict[str, Any] | None = None,
) -> TraceStep:
    return TraceStep(
        query_log=log,
        ordinal=ordinal,
        name=name,
        status=RunStatus.SUCCESS,
        duration_ms=duration_ms,
        detail=detail,
        metadata_json=metadata or {},
    )


async def _stream_answer(
    *,
    session: AsyncSession,
    app: QAApp,
    conversation: Conversation,
    query_log: QueryLog,
    question: str,
    history: list[Message],
    knowledge_bases: list[Any],
) -> AsyncIterator[str]:
    started = monotonic()
    answer_parts: list[str] = []
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    citations: list[dict[str, Any]] = []
    yield _sse(
        "meta",
        {
            "conversation_id": conversation.id,
            "trace_id": query_log.trace_id,
            "app_id": app.id,
            "knowledge_base_ids": [item.id for item in knowledge_bases],
        },
    )
    try:
        preprocessing_started = monotonic()
        normalized_question = " ".join(question.split())
        preprocessing_duration = int((monotonic() - preprocessing_started) * 1000)
        session.add(
            _trace(
                query_log,
                1,
                "查询预处理",
                preprocessing_duration,
                "去除多余空白并保留原始语义",
            )
        )

        retrieval_started = monotonic()
        retrieved, runs = await _retrieve_for_app(
            session, app, normalized_question, knowledge_bases
        )
        retrieval_duration = int((monotonic() - retrieval_started) * 1000)
        citations = [_citation(item) for item in retrieved]
        recalled_count = sum(run.recalled_count for run in runs)
        session.add(
            _trace(
                query_log,
                2,
                "向量检索",
                sum(run.embedding_duration_ms + run.vector_duration_ms for run in runs),
                f"从 {len(runs)} 个知识库召回 {recalled_count} 个候选分块",
                {
                    "knowledge_base_ids": [item.id for item in knowledge_bases],
                    "recalled_count": recalled_count,
                    "returned_count": len(retrieved),
                    "simulated": any(run.simulated for run in runs),
                },
            )
        )
        rerank_applied = any(run.rerank_applied for run in runs)
        rerank_duration = sum(run.rerank_duration_ms or 0 for run in runs)
        session.add(
            _trace(
                query_log,
                3,
                "Rerank",
                rerank_duration,
                (
                    f"重排后保留 {len(retrieved)} 个分块"
                    if rerank_applied
                    else "未配置 Rerank，按向量相似度排序"
                ),
                {"applied": rerank_applied},
            )
        )
        if citations:
            yield _sse("citations", {"items": citations})

        llm_model = await session.get(ModelConfig, app.llm_model_id)
        if llm_model is None or llm_model.workspace_id != current_workspace_id() or not llm_model.is_enabled:
            raise ValueError("Configured LLM model is missing or disabled")
        gateway = build_gateway(llm_model)
        context_parts: list[str] = []
        remaining_context = 12000
        for index, item in enumerate(retrieved, start=1):
            heading = f"[资料 {index}] {item.filename}{' 第 ' + str(item.page_number) + ' 页' if item.page_number else ''}"
            available = remaining_context - len(heading) - 2
            if available <= 0:
                break
            content = item.content[:available]
            context_parts.append(f"{heading}\n{content}")
            remaining_context -= len(heading) + len(content) + 2
        context = "\n\n".join(context_parts)
        if not context:
            context = "未检索到达到阈值的知识库内容。"
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "{system_prompt}\n\n"
                    "必须优先依据下方知识库资料回答，不得编造资料中不存在的制度、数字或结论。"
                    "资料不足时直接说明不知道，并建议用户向对应负责人确认。"
                    "回答中需要引用时使用 [资料 1] 这样的编号。\n\n"
                    "知识库资料：\n{context}",
                ),
                MessagesPlaceholder("history"),
                ("human", "{question}"),
            ]
        )
        chain = prompt | gateway.chat_model()
        llm_started = monotonic()
        async for chunk in chain.astream(
            {
                "system_prompt": app.system_prompt,
                "context": context,
                "history": _history_messages(history),
                "question": normalized_question,
            }
        ):
            text = _content_text(getattr(chunk, "content", chunk))
            if text:
                answer_parts.append(text)
                yield _sse("token", {"text": text})
            usage = getattr(chunk, "usage_metadata", None)
            if usage:
                current_input = usage.get("input_tokens")
                current_output = usage.get("output_tokens")
                current_total = usage.get("total_tokens")
                input_tokens = max(input_tokens or 0, current_input or 0) or input_tokens
                output_tokens = max(output_tokens or 0, current_output or 0) or output_tokens
                total_tokens = max(total_tokens or 0, current_total or 0) or total_tokens
        llm_duration = int((monotonic() - llm_started) * 1000)
        answer = "".join(answer_parts).strip()
        if not answer:
            raise ValueError("LLM returned an empty answer")

        duration_ms = int((monotonic() - started) * 1000)
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            citations=citations,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            simulated=gateway.is_simulated or any(run.simulated for run in runs),
        )
        session.add(assistant_message)
        session.add(
            _trace(
                query_log,
                4,
                "LLM 生成",
                llm_duration,
                f"{llm_model.display_name} 流式生成完成",
                {
                    "provider": llm_model.provider,
                    "model": llm_model.model_name,
                    "simulated": gateway.is_simulated,
                },
            )
        )
        query_log.status = RunStatus.SUCCESS
        query_log.input_tokens = input_tokens
        query_log.output_tokens = output_tokens
        query_log.total_tokens = total_tokens
        query_log.duration_ms = duration_ms
        query_log.finished_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(assistant_message)
        yield _sse(
            "done",
            {
                "message_id": assistant_message.id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "duration_ms": duration_ms,
                "retrieval_duration_ms": retrieval_duration,
                "simulated": gateway.is_simulated or any(run.simulated for run in runs),
                "simulation": {
                    "llm": gateway.is_simulated,
                    "retrieval": any(run.simulated for run in runs),
                },
            },
        )
    except asyncio.CancelledError:
        query_log.status = RunStatus.FAILED
        query_log.error_message = "Client disconnected before the stream completed"
        query_log.duration_ms = int((monotonic() - started) * 1000)
        query_log.finished_at = datetime.now(UTC)
        await session.commit()
        raise
    except Exception as exc:
        safe_error = str(exc) if isinstance(exc, (ProviderError, ValueError)) else f"{type(exc).__name__}"
        query_log.status = RunStatus.FAILED
        query_log.error_message = safe_error
        query_log.duration_ms = int((monotonic() - started) * 1000)
        query_log.finished_at = datetime.now(UTC)
        session.add(
            TraceStep(
                query_log=query_log,
                ordinal=99,
                name="执行失败",
                status=RunStatus.FAILED,
                duration_ms=query_log.duration_ms,
                detail=safe_error,
                metadata_json={},
            )
        )
        await session.commit()
        yield _sse("error", {"detail": safe_error, "trace_id": query_log.trace_id})


@app_router.get("/{app_id}/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    app_id: str,
    role: DemoRole = Depends(get_demo_role),
    session: AsyncSession = Depends(get_session),
) -> list[Conversation]:
    app = await _load_app(session, app_id)
    if app is None or (role == "user" and not app.is_enabled):
        raise HTTPException(status_code=404, detail="QA app not found")
    query = select(Conversation).where(Conversation.app_id == app_id, Conversation.workspace_id == current_workspace_id()).order_by(Conversation.updated_at.desc())
    if role == "user":
        query = query.where(Conversation.demo_role == role)
    return list(await session.scalars(query))


@conversation_router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    role: DemoRole = Depends(get_demo_role),
    session: AsyncSession = Depends(get_session),
) -> ConversationDetailResponse:
    conversation = await _conversation_or_404(session, conversation_id, role)
    messages = list(
        await session.scalars(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
        )
    )
    return ConversationDetailResponse(
        id=conversation.id,
        app_id=conversation.app_id,
        title=conversation.title,
        demo_role=conversation.demo_role,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_message_response(item) for item in messages],
    )


@app_router.post("/{app_id}/chat")
async def chat(
    app_id: str,
    payload: ChatRequest,
    role: DemoRole = Depends(get_demo_role),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="message cannot be blank")
    app = await _load_app(session, app_id)
    if app is None or (role == "user" and not app.is_enabled):
        raise HTTPException(status_code=404, detail="QA app not found")
    if not app.llm_model_id:
        raise HTTPException(status_code=422, detail="QA app has no LLM model configured")
    if not app.knowledge_bases:
        raise HTTPException(status_code=422, detail="QA app has no knowledge base configured")
    knowledge_bases = list(app.knowledge_bases)
    if payload.knowledge_base_ids is not None:
        allowed = {item.id: item for item in app.knowledge_bases}
        invalid = [item for item in payload.knowledge_base_ids if item not in allowed]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail="Selected knowledge bases must belong to this app",
            )
        knowledge_bases = [allowed[item] for item in payload.knowledge_base_ids]

    history: list[Message] = []
    if payload.conversation_id:
        conversation = await _conversation_or_404(session, payload.conversation_id, role)
        if conversation.app_id != app.id:
            raise HTTPException(status_code=422, detail="Conversation does not belong to this QA app")
        history = list(
            await session.scalars(
                select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
            )
        )
    else:
        conversation = Conversation(
            app_id=app.id,
            title=question[:60],
            demo_role=role,
        )
        session.add(conversation)
        await session.flush()

    conversation.updated_at = datetime.now(UTC)
    session.add(Message(conversation_id=conversation.id, role="user", content=question, citations=[]))
    query_log = QueryLog(
        app_id=app.id,
        conversation_id=conversation.id,
        demo_role=role,
        query=question,
        status=RunStatus.RUNNING,
    )
    session.add(query_log)
    await session.commit()

    return StreamingResponse(
        _stream_answer(
            session=session,
            app=app,
            conversation=conversation,
            query_log=query_log,
            question=question,
            history=history,
            knowledge_bases=knowledge_bases,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
