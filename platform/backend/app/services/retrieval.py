from __future__ import annotations

import math
import re
from dataclasses import dataclass
from time import monotonic
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import DocumentChunk, KnowledgeBase, ModelConfig
from ..providers import build_gateway


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: str
    knowledge_base_id: str
    file_id: str
    filename: str
    title: str
    content: str
    page_number: int | None
    vector_score: float
    keyword_score: float | None
    rerank_score: float | None
    final_score: float
    metadata: dict[str, Any]


@dataclass(slots=True)
class RetrievalRun:
    results: list[RetrievedChunk]
    recalled_count: int
    embedding_duration_ms: int
    vector_duration_ms: int
    rerank_duration_ms: int | None
    total_duration_ms: int
    rerank_applied: bool
    simulated: bool


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return -1.0
    return dot / (left_norm * right_norm)


def _to_result(chunk: DocumentChunk, vector_score: float, keyword_score: float | None = None) -> RetrievedChunk:
    parent_content = chunk.metadata_json.get("parent_content")
    content = parent_content if isinstance(parent_content, str) and parent_content.strip() else chunk.content
    parent_title = chunk.metadata_json.get("parent_title")
    return RetrievedChunk(
        chunk_id=chunk.id,
        knowledge_base_id=chunk.knowledge_base_id,
        file_id=chunk.file_id,
        filename=chunk.file.filename,
        title=str(parent_title) if parent_title else chunk.title,
        content=content,
        page_number=chunk.page_number,
        vector_score=vector_score,
        keyword_score=keyword_score,
        rerank_score=None,
        final_score=keyword_score if keyword_score is not None else vector_score,
        metadata=chunk.metadata_json,
    )


async def _vector_search(
    session: AsyncSession,
    knowledge_base_id: str,
    query_vector: list[float],
    top_k: int,
) -> list[RetrievedChunk]:
    if session.bind and session.bind.dialect.name == "postgresql":
        distance = cast(DocumentChunk.embedding, Vector()).cosine_distance(query_vector)
        query = (
            select(DocumentChunk, (1.0 - distance).label("vector_score"))
            .where(
                DocumentChunk.knowledge_base_id == knowledge_base_id,
                DocumentChunk.embedding.is_not(None),
            )
            .options(selectinload(DocumentChunk.file))
            .order_by(distance)
            .limit(top_k)
        )
        rows = (await session.execute(query)).all()
        return [_to_result(chunk, float(score)) for chunk, score in rows]

    query = (
        select(DocumentChunk)
        .where(
            DocumentChunk.knowledge_base_id == knowledge_base_id,
            DocumentChunk.embedding.is_not(None),
        )
        .options(selectinload(DocumentChunk.file))
    )
    chunks = list(await session.scalars(query))
    scored = [
        _to_result(chunk, _cosine_similarity(query_vector, chunk.embedding or []))
        for chunk in chunks
    ]
    return sorted(scored, key=lambda item: item.vector_score, reverse=True)[:top_k]


def _lexical_terms(text: str) -> set[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9][a-z0-9_.-]*", lowered)
    chinese = re.findall(r"[\u4e00-\u9fff]", lowered)
    bigrams = ["".join(chinese[index:index + 2]) for index in range(max(0, len(chinese) - 1))]
    return set([*words, *chinese, *bigrams])


async def _fulltext_search(session: AsyncSession, knowledge_base_id: str, query_text: str, top_k: int) -> list[RetrievedChunk]:
    chunks = list(await session.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.knowledge_base_id == knowledge_base_id)
        .options(selectinload(DocumentChunk.file))
        .limit(5000)
    ))
    query_terms = _lexical_terms(query_text)
    if not query_terms:
        return []
    scored: list[RetrievedChunk] = []
    lowered_query = query_text.lower().strip()
    for chunk in chunks:
        source = f"{chunk.title}\n{chunk.content}".lower()
        source_terms = _lexical_terms(source)
        overlap = len(query_terms & source_terms) / max(len(query_terms), 1)
        exact_bonus = 0.25 if lowered_query and lowered_query in source else 0.0
        score = min(1.0, overlap + exact_bonus)
        if score > 0:
            scored.append(_to_result(chunk, 0.0, score))
    return sorted(scored, key=lambda item: item.keyword_score or 0.0, reverse=True)[:top_k]


def _rrf(vector: list[RetrievedChunk], keyword: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    by_id: dict[str, RetrievedChunk] = {}
    for results in (vector, keyword):
        for rank, item in enumerate(results, start=1):
            scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (60 + rank)
            current = by_id.get(item.chunk_id)
            if current is None:
                by_id[item.chunk_id] = item
            else:
                current.vector_score = max(current.vector_score, item.vector_score)
                current.keyword_score = max(current.keyword_score or 0.0, item.keyword_score or 0.0) or None
    maximum = max(scores.values(), default=1.0)
    for chunk_id, item in by_id.items():
        item.final_score = scores[chunk_id] / maximum
    return sorted(by_id.values(), key=lambda item: item.final_score, reverse=True)[:top_k]


async def retrieve_knowledge_base(
    session: AsyncSession,
    knowledge_base: KnowledgeBase,
    query: str,
    *,
    top_k: int,
    rerank_top_n: int,
    score_threshold: float,
    mode: str = "semantic",
) -> RetrievalRun:
    started = monotonic()
    if mode not in {"semantic", "fulltext", "hybrid"}:
        raise ValueError("Unsupported retrieval mode")
    embedding_gateway = None
    vector_candidates: list[RetrievedChunk] = []
    embedding_duration_ms = 0
    if mode in {"semantic", "hybrid"}:
        indexed_count = await session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.knowledge_base_id == knowledge_base.id, DocumentChunk.embedding.is_not(None)))
        if not indexed_count:
            raise ValueError("尚未构建可用向量索引，请先使用全文检索，或在知识库配置中构建索引。此次未调用向量模型。")
        if not knowledge_base.embedding_model_id:
            raise ValueError("Knowledge base has no embedding model configured")
        embedding_model = await session.get(ModelConfig, knowledge_base.embedding_model_id)
        if embedding_model is None or not embedding_model.is_enabled:
            raise ValueError("Configured embedding model is missing or disabled")
        embedding_gateway = build_gateway(embedding_model)
        embedding_started = monotonic()
        query_vector = await embedding_gateway.embed_query(query)
        if knowledge_base.embedding_dimension is not None and len(query_vector) != knowledge_base.embedding_dimension:
            raise ValueError("Embedding model dimension does not match the knowledge base index; rebuild with a compatible model")
        embedding_duration_ms = int((monotonic() - embedding_started) * 1000)
        vector_candidates = await _vector_search(session, knowledge_base.id, query_vector, top_k)

    vector_started = monotonic()
    keyword_candidates = await _fulltext_search(session, knowledge_base.id, query, top_k) if mode in {"fulltext", "hybrid"} else []
    candidates = vector_candidates if mode == "semantic" else keyword_candidates if mode == "fulltext" else _rrf(vector_candidates, keyword_candidates, top_k)
    # Parent-child retrieval embeds small child chunks but returns the parent
    # context. Multiple matching children of one parent should not crowd out
    # results from other parents.
    deduplicated: dict[str, RetrievedChunk] = {}
    for candidate in candidates:
        parent_id = candidate.metadata.get("parent_id")
        key = f"{candidate.file_id}:{parent_id}" if parent_id else candidate.chunk_id
        current = deduplicated.get(key)
        if current is None or candidate.final_score > current.final_score:
            deduplicated[key] = candidate
    candidates = list(deduplicated.values())
    candidates.sort(key=lambda item: item.final_score, reverse=True)
    vector_duration_ms = int((monotonic() - vector_started) * 1000)
    recalled_count = len(candidates)
    rerank_duration_ms: int | None = None
    rerank_applied = False
    simulated = bool(embedding_gateway and embedding_gateway.is_simulated)

    if candidates and knowledge_base.rerank_model_id:
        rerank_model = await session.get(ModelConfig, knowledge_base.rerank_model_id)
        if rerank_model is None or not rerank_model.is_enabled:
            raise ValueError("Configured rerank model is missing or disabled")
        rerank_gateway = build_gateway(rerank_model)
        rerank_started = monotonic()
        ranked = await rerank_gateway.rerank(
            query,
            [candidate.content for candidate in candidates],
            min(rerank_top_n, len(candidates)),
        )
        rerank_duration_ms = int((monotonic() - rerank_started) * 1000)
        reranked: list[RetrievedChunk] = []
        for item in ranked:
            if item.index < 0 or item.index >= len(candidates):
                continue
            candidate = candidates[item.index]
            candidate.rerank_score = item.score
            candidate.final_score = item.score
            reranked.append(candidate)
        candidates = reranked
        rerank_applied = True
        simulated = simulated or rerank_gateway.is_simulated

    results = [candidate for candidate in candidates if candidate.final_score >= score_threshold]
    return RetrievalRun(
        results=results,
        recalled_count=recalled_count,
        embedding_duration_ms=embedding_duration_ms,
        vector_duration_ms=vector_duration_ms,
        rerank_duration_ms=rerank_duration_ms,
        total_duration_ms=int((monotonic() - started) * 1000),
        rerank_applied=rerank_applied,
        simulated=simulated,
    )
