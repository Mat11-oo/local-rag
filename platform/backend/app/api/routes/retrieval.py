from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...models import KnowledgeBase
from ...providers.base import ProviderError
from ...schemas import RetrievalRequest, RetrievalResponse, RetrievalResultResponse
from ...security import require_roles
from ...services.retrieval import retrieve_knowledge_base
from ...tenancy import current_workspace_id

router = APIRouter(dependencies=[Depends(require_roles("admin", "manager"))])


@router.post("/{knowledge_base_id}/retrieval-test", response_model=RetrievalResponse)
async def test_retrieval(
    knowledge_base_id: str,
    payload: RetrievalRequest,
    session: AsyncSession = Depends(get_session),
) -> RetrievalResponse:
    knowledge_base = await session.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or knowledge_base.workspace_id != current_workspace_id():
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    try:
        run = await retrieve_knowledge_base(
            session,
            knowledge_base,
            payload.query,
            top_k=payload.top_k,
            rerank_top_n=payload.rerank_top_n,
            score_threshold=payload.score_threshold,
            mode=payload.mode,
        )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RetrievalResponse(
        query=payload.query,
        results=[RetrievalResultResponse(**asdict(item)) for item in run.results],
        recalled_count=run.recalled_count,
        returned_count=len(run.results),
        embedding_duration_ms=run.embedding_duration_ms,
        vector_duration_ms=run.vector_duration_ms,
        rerank_duration_ms=run.rerank_duration_ms,
        total_duration_ms=run.total_duration_ms,
        rerank_applied=run.rerank_applied,
        simulated=run.simulated,
    )
