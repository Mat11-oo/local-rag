from __future__ import annotations

import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.db import build_engine, init_db
from app.models import DocumentChunk, JobStatus, KnowledgeBase, KnowledgeFile, ModelConfig
from app.services.retrieval import retrieve_knowledge_base
from app.services.storage import S3ObjectStorage


pytestmark = pytest.mark.skipif(
    os.getenv("APP_RUN_INTEGRATION") != "1",
    reason="set APP_RUN_INTEGRATION=1 when the Docker infrastructure is running",
)


async def test_postgres_pgvector_redis_and_s3_roundtrip() -> None:
    database_url = "postgresql+asyncpg://rag:rag@127.0.0.1:56432/rag_hub"
    engine = build_engine(database_url)
    await init_db(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    unique = uuid4().hex

    async with session_factory() as session:
        extension = await session.scalar(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
        assert extension == "vector"

        embedding_model = ModelConfig(
            display_name=f"integration-embedding-{unique}",
            provider="mock",
            model_type="embedding",
            model_name="deterministic-test-vector",
            base_url="mock://local",
            config={},
        )
        session.add(embedding_model)
        await session.flush()
        knowledge_base = KnowledgeBase(
            name=f"integration-kb-{unique}",
            embedding_model_id=embedding_model.id,
            chunk_size=800,
            chunk_overlap=120,
        )
        session.add(knowledge_base)
        await session.flush()
        file = KnowledgeFile(
            knowledge_base_id=knowledge_base.id,
            filename="integration.md",
            content_type="text/markdown",
            extension=".md",
            size_bytes=20,
            storage_key=f"integration/{unique}.md",
            checksum_sha256="a" * 64,
            status=JobStatus.COMPLETED,
            chunk_count=1,
        )
        session.add(file)
        await session.flush()
        from app.providers.mock import _vector

        content = "企业知识库集成测试内容"
        session.add(
            DocumentChunk(
                knowledge_base_id=knowledge_base.id,
                file_id=file.id,
                ordinal=1,
                title="集成测试",
                content=content,
                char_count=len(content),
                metadata_json={"source_type": "integration"},
                embedding=_vector(content),
            )
        )
        await session.commit()

        run = await retrieve_knowledge_base(
            session,
            knowledge_base,
            content,
            top_k=3,
            rerank_top_n=1,
            score_threshold=0,
        )
        assert run.results[0].content == content
        assert run.results[0].vector_score > 0.99

        await session.execute(delete(KnowledgeBase).where(KnowledgeBase.id == knowledge_base.id))
        await session.execute(delete(ModelConfig).where(ModelConfig.id == embedding_model.id))
        await session.commit()
    await engine.dispose()

    redis = Redis.from_url("redis://127.0.0.1:57379/0")
    try:
        assert await redis.ping() is True
    finally:
        await redis.aclose()

    settings = Settings(
        storage_backend="s3",
        s3_endpoint_url="http://127.0.0.1:59000",
        s3_access_key="rag-minio",
        s3_secret_key="change-this-minio-secret",
        s3_bucket="rag-documents",
    )
    storage = S3ObjectStorage(settings)
    key = f"integration/{unique}.txt"
    await storage.put_bytes(key, b"s3-roundtrip", "text/plain")
    assert await storage.get_bytes(key) == b"s3-roundtrip"
    await storage.delete(key)
