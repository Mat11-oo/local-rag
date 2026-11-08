from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from .models import AppScenario, ChunkMethod, ModelType, ProviderName


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str
    database: Literal["ok", "error"]
    simulated: bool = False


class ModelConfigCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    provider: ProviderName
    model_type: ModelType
    model_name: str = Field(min_length=1, max_length=180)
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, min_length=1)
    is_enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_key_for_real_provider(self) -> "ModelConfigCreate":
        if self.provider != ProviderName.MOCK and not self.api_key:
            raise ValueError("api_key is required for real model providers")
        return self


class ModelConfigUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    model_name: str | None = Field(default=None, min_length=1, max_length=180)
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, min_length=1)
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None


class ModelConfigResponse(ORMModel):
    id: str
    display_name: str
    provider: str
    model_type: str
    model_name: str
    base_url: str
    api_key_masked: str | None = None
    is_enabled: bool
    connection_status: str
    last_tested_at: datetime | None
    last_error: str | None
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    simulated: bool = False


class ConnectionTestResponse(BaseModel):
    ok: bool
    status: str
    latency_ms: int
    provider: str
    model_type: str
    detail: str
    simulated: bool


class OpenRouterCatalogRequest(BaseModel):
    api_key: str | None = Field(default=None, min_length=1)
    source_model_id: str | None = None
    base_url: HttpUrl | None = None

    @model_validator(mode="after")
    def require_credential_source(self) -> "OpenRouterCatalogRequest":
        if not self.api_key and not self.source_model_id:
            raise ValueError("api_key or source_model_id is required")
        return self


class OpenRouterCatalogModel(BaseModel):
    id: str
    name: str
    description: str
    model_type: Literal["llm", "embedding", "rerank", "ocr"]
    context_length: int | None = None
    modality: str
    prompt_price: str | None = None
    is_free: bool = False


class OpenRouterCatalogResponse(BaseModel):
    ok: Literal[True] = True
    detail: str
    latency_ms: int
    models: list[OpenRouterCatalogModel]


class OpenRouterModelSelection(BaseModel):
    model_name: str = Field(min_length=1, max_length=180)
    display_name: str = Field(min_length=1, max_length=120)
    model_type: Literal["llm", "embedding", "rerank", "ocr"]


class OpenRouterBulkImportRequest(OpenRouterCatalogRequest):
    models: list[OpenRouterModelSelection] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def reject_duplicate_models(self) -> "OpenRouterBulkImportRequest":
        identities = [(item.model_type, item.model_name) for item in self.models]
        if len(set(identities)) != len(identities):
            raise ValueError("models cannot contain duplicates")
        return self


class ModelOptionResponse(ORMModel):
    id: str
    display_name: str
    provider: str
    model_type: str
    model_name: str
    is_enabled: bool
    connection_status: str


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    embedding_model_id: str | None = None
    rerank_model_id: str | None = None
    ocr_model_id: str | None = None
    chunk_size: int = Field(default=800, ge=100, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    chunk_method: ChunkMethod = ChunkMethod.RECURSIVE
    parent_chunk_size: int = Field(default=1600, ge=200, le=12000)
    child_chunk_size: int = Field(default=400, ge=80, le=4000)
    semantic_llm_model_id: str | None = None
    metadata_llm_model_id: str | None = None

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "KnowledgeBaseCreate":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.child_chunk_size >= self.parent_chunk_size:
            raise ValueError("child_chunk_size must be smaller than parent_chunk_size")
        if self.chunk_method == ChunkMethod.SEMANTIC and not self.semantic_llm_model_id:
            raise ValueError("semantic_llm_model_id is required for semantic chunking")
        return self


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    embedding_model_id: str | None = None
    rerank_model_id: str | None = None
    ocr_model_id: str | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=1000)
    chunk_method: ChunkMethod | None = None
    parent_chunk_size: int | None = Field(default=None, ge=200, le=12000)
    child_chunk_size: int | None = Field(default=None, ge=80, le=4000)
    semantic_llm_model_id: str | None = None
    metadata_llm_model_id: str | None = None


class KnowledgeBaseResponse(ORMModel):
    id: str
    name: str
    description: str
    embedding_model_id: str | None
    rerank_model_id: str | None
    ocr_model_id: str | None
    embedding_dimension: int | None = None
    chunk_size: int
    chunk_overlap: int
    chunk_method: str
    parent_chunk_size: int
    child_chunk_size: int
    semantic_llm_model_id: str | None
    metadata_llm_model_id: str | None
    file_count: int = 0
    chunk_count: int = 0
    total_chunk_count: int = 0
    semantic_ready: bool = False
    retrieval_status: str = "empty"
    created_at: datetime
    updated_at: datetime


class KnowledgeFileResponse(ORMModel):
    id: str
    knowledge_base_id: str
    filename: str
    content_type: str
    extension: str
    size_bytes: int
    checksum_sha256: str
    status: str
    error_message: str | None
    page_count: int | None
    chunk_count: int
    chunk_config: dict[str, Any]
    document_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WebImportRequest(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=300)
    chunk_config: dict[str, Any] = Field(default_factory=dict)


class DocumentMetadataUpdate(BaseModel):
    document_time: str | None = Field(default=None, max_length=40)
    version: str | None = Field(default=None, max_length=80)
    subjects: list[str] | None = Field(default=None, max_length=10)
    owner: str | None = Field(default=None, max_length=160)
    keywords: list[str] | None = Field(default=None, max_length=20)
    likely_questions: list[str] | None = Field(default=None, max_length=15)


class ImportJobResponse(ORMModel):
    id: str
    file_id: str
    status: str
    progress: int
    current_stage: str
    stage_details: list[dict[str, Any]]
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    simulated: bool = False


class FileUploadResponse(BaseModel):
    file: KnowledgeFileResponse
    job: ImportJobResponse


class ChunkResponse(ORMModel):
    id: str
    knowledge_base_id: str
    file_id: str
    ordinal: int
    title: str
    content: str
    page_number: int | None
    char_count: int
    metadata_json: dict[str, Any]
    indexed: bool
    created_at: datetime
    updated_at: datetime


class ChunkQAPair(BaseModel):
    q: str = Field(min_length=1, max_length=300)
    a: str = Field(min_length=1, max_length=2000)


class ChunkUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, min_length=1)
    keywords: list[str] | None = Field(default=None, max_length=20)
    qa_pairs: list[ChunkQAPair] | None = Field(default=None, max_length=10)


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    mode: Literal["semantic", "fulltext", "hybrid"] = "semantic"
    use_rerank: bool = Field(default=True, description="Use the knowledge base's configured reranker, if any")
    top_k: int = Field(default=8, ge=1, le=50)
    rerank_top_n: int = Field(default=3, ge=1, le=20)
    score_threshold: float = Field(default=0.0, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def validate_retrieval_limits(self) -> "RetrievalRequest":
        if self.use_rerank and self.rerank_top_n > self.top_k:
            raise ValueError("rerank_top_n cannot exceed top_k")
        return self


class RetrievalResultResponse(BaseModel):
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


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievalResultResponse]
    recalled_count: int
    returned_count: int
    embedding_duration_ms: int
    vector_duration_ms: int
    rerank_duration_ms: int | None
    total_duration_ms: int
    rerank_applied: bool
    simulated: bool


class QAAppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    scenario_type: AppScenario = AppScenario.QA
    system_prompt: str = Field(min_length=1, max_length=12000)
    llm_model_id: str
    knowledge_base_ids: list[str] = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)
    rerank_top_n: int = Field(default=3, ge=1, le=20)
    score_threshold: float = Field(default=0.35, ge=-1.0, le=1.0)
    is_enabled: bool = False

    @model_validator(mode="after")
    def validate_limits(self) -> "QAAppCreate":
        if self.rerank_top_n > self.top_k:
            raise ValueError("rerank_top_n cannot exceed top_k")
        if len(set(self.knowledge_base_ids)) != len(self.knowledge_base_ids):
            raise ValueError("knowledge_base_ids cannot contain duplicates")
        return self


class QAAppUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    scenario_type: AppScenario | None = None
    system_prompt: str | None = Field(default=None, min_length=1, max_length=12000)
    llm_model_id: str | None = None
    knowledge_base_ids: list[str] | None = Field(default=None, min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=50)
    rerank_top_n: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    is_enabled: bool | None = None


class AppKnowledgeBaseResponse(ORMModel):
    id: str
    name: str
    description: str


class QAAppResponse(ORMModel):
    id: str
    name: str
    description: str
    scenario_type: str
    system_prompt: str
    llm_model_id: str | None
    knowledge_base_ids: list[str]
    knowledge_bases: list[AppKnowledgeBaseResponse]
    top_k: int
    rerank_top_n: int
    score_threshold: float
    is_enabled: bool
    conversation_count: int = 0
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    conversation_id: str | None = None
    knowledge_base_ids: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_knowledge_bases(self) -> "ChatRequest":
        if self.knowledge_base_ids and len(set(self.knowledge_base_ids)) != len(self.knowledge_base_ids):
            raise ValueError("knowledge_base_ids cannot contain duplicates")
        return self


class ConversationResponse(ORMModel):
    id: str
    app_id: str
    title: str
    demo_role: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(ORMModel):
    id: str
    conversation_id: str
    role: str
    content: str
    citations: list[dict[str, Any]]
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    simulated: bool = False
    input_values: dict[str, Any] = Field(default_factory=dict)
    output_json: dict[str, Any] | list[Any] | None = None
    app_version_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]


class TraceStepResponse(ORMModel):
    id: str
    ordinal: int
    name: str
    status: str
    duration_ms: int
    detail: str
    metadata_json: dict[str, Any]
    created_at: datetime


class QueryLogResponse(ORMModel):
    id: str
    trace_id: str
    app_id: str | None
    app_name: str | None = None
    conversation_id: str | None
    demo_role: str
    query: str
    status: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    duration_ms: int | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    traces: list[TraceStepResponse] = Field(default_factory=list)


class LogSummaryResponse(BaseModel):
    query_count: int
    success_count: int
    failed_count: int
    success_rate: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    average_duration_ms: int | None


