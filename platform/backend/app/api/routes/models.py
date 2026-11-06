from __future__ import annotations

from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...db import get_session
from ...models import ConnectionStatus, ModelConfig, ModelType, ProviderName, utc_now
from ...providers import build_gateway, default_base_url
from ...providers.base import ProviderError
from ...providers.openrouter_catalog import fetch_openrouter_catalog
from ...providers.provider_catalog import PROVIDER_LABELS, fetch_provider_catalog
from ...services.ocr import OcrError, build_ocr
from ...schemas import (
    ConnectionTestResponse,
    ModelConfigCreate,
    ModelConfigResponse,
    ModelConfigUpdate,
    OpenRouterBulkImportRequest,
    OpenRouterCatalogRequest,
    OpenRouterCatalogResponse,
)
from ...security import decrypt_secret, encrypt_secret, mask_secret, require_roles
from ...tenancy import current_workspace_id

router = APIRouter(dependencies=[Depends(require_roles("admin"))])


def serialize_model(model: ModelConfig) -> ModelConfigResponse:
    secret = decrypt_secret(model.api_key_encrypted)
    return ModelConfigResponse(
        id=model.id,
        display_name=model.display_name,
        provider=model.provider,
        model_type=model.model_type,
        model_name=model.model_name,
        base_url=model.base_url,
        api_key_masked=mask_secret(secret),
        is_enabled=model.is_enabled,
        connection_status=model.connection_status,
        last_tested_at=model.last_tested_at,
        last_error=model.last_error,
        config=model.config,
        created_at=model.created_at,
        updated_at=model.updated_at,
        simulated=model.provider == ProviderName.MOCK,
    )


async def get_model_or_404(session: AsyncSession, model_id: str) -> ModelConfig:
    model = await session.get(ModelConfig, model_id)
    if model is None or model.workspace_id != current_workspace_id():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model configuration not found")
    return model


async def _openrouter_credentials(
    payload: OpenRouterCatalogRequest,
    session: AsyncSession,
) -> tuple[str, str]:
    if payload.api_key:
        api_key = payload.api_key.strip()
        base_url = str(payload.base_url).rstrip("/") if payload.base_url else default_base_url(ProviderName.OPENROUTER)
        return api_key, base_url

    source = await get_model_or_404(session, payload.source_model_id or "")
    if source.provider != ProviderName.OPENROUTER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="source_model_id must reference an OpenRouter model",
        )
    api_key = decrypt_secret(source.api_key_encrypted)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The saved OpenRouter connection has no API key",
        )
    base_url = str(payload.base_url).rstrip("/") if payload.base_url else source.base_url
    return api_key, base_url


async def _provider_credentials(
    provider: ProviderName,
    payload: OpenRouterCatalogRequest,
    session: AsyncSession,
) -> tuple[str, str]:
    if provider not in PROVIDER_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{provider} 暂不支持厂商级模型目录接入",
        )
    if payload.api_key:
        return (
            payload.api_key.strip(),
            str(payload.base_url).rstrip("/") if payload.base_url else default_base_url(provider),
        )
    source = await get_model_or_404(session, payload.source_model_id or "")
    if source.provider != provider:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"source_model_id must reference a {PROVIDER_LABELS[provider]} model",
        )
    api_key = decrypt_secret(source.api_key_encrypted)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The saved {PROVIDER_LABELS[provider]} connection has no API key",
        )
    return api_key, str(payload.base_url).rstrip("/") if payload.base_url else source.base_url


@router.get("", response_model=list[ModelConfigResponse])
async def list_models(session: AsyncSession = Depends(get_session)) -> list[ModelConfigResponse]:
    result = await session.scalars(select(ModelConfig).where(ModelConfig.workspace_id == current_workspace_id()).order_by(ModelConfig.created_at.desc()))
    return [serialize_model(model) for model in result]


@router.post("", response_model=ModelConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_model(payload: ModelConfigCreate, session: AsyncSession = Depends(get_session)) -> ModelConfigResponse:
    if payload.provider == ProviderName.MOCK and get_settings().env == "production":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Mock providers are disabled in production")
    model = ModelConfig(
        display_name=payload.display_name,
        provider=payload.provider,
        model_type=payload.model_type,
        model_name=payload.model_name,
        base_url=str(payload.base_url).rstrip("/") if payload.base_url else default_base_url(payload.provider),
        api_key_encrypted=encrypt_secret(payload.api_key.strip() if payload.api_key else None),
        is_enabled=payload.is_enabled,
        connection_status=ConnectionStatus.MOCK if payload.provider == ProviderName.MOCK else ConnectionStatus.UNTESTED,
        config=payload.config,
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return serialize_model(model)


@router.post("/openrouter/catalog", response_model=OpenRouterCatalogResponse)
async def openrouter_catalog(
    payload: OpenRouterCatalogRequest,
    session: AsyncSession = Depends(get_session),
) -> OpenRouterCatalogResponse:
    api_key, base_url = await _openrouter_credentials(payload, session)
    try:
        models, latency_ms = await fetch_openrouter_catalog(
            api_key=api_key,
            base_url=base_url,
            timeout=get_settings().request_timeout_seconds,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return OpenRouterCatalogResponse(
        detail=f"OpenRouter 连接成功，已加载 {len(models)} 个可选模型",
        latency_ms=latency_ms,
        models=models,
    )


@router.post("/openrouter/import", response_model=list[ModelConfigResponse])
async def import_openrouter_models(
    payload: OpenRouterBulkImportRequest,
    session: AsyncSession = Depends(get_session),
) -> list[ModelConfigResponse]:
    api_key, base_url = await _openrouter_credentials(payload, session)
    try:
        catalog, _ = await fetch_openrouter_catalog(
            api_key=api_key,
            base_url=base_url,
            timeout=get_settings().request_timeout_seconds,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    available = {(item["model_type"], item["id"]): item for item in catalog}
    requested = {(item.model_type, item.model_name) for item in payload.models}
    missing = sorted(f"{model_type}:{model_name}" for model_type, model_name in requested if (model_type, model_name) not in available)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"OpenRouter 当前目录中不存在这些模型：{', '.join(missing)}",
        )

    existing_models = list(
        await session.scalars(select(ModelConfig).where(ModelConfig.workspace_id == current_workspace_id()).where(ModelConfig.provider == ProviderName.OPENROUTER))
    )
    existing = {(item.model_type, item.model_name): item for item in existing_models}
    encrypted_key = encrypt_secret(api_key.strip())
    saved: list[ModelConfig] = []
    for selection in payload.models:
        identity = (selection.model_type, selection.model_name)
        model = existing.get(identity)
        if model is None:
            model = ModelConfig(
                display_name=selection.display_name,
                provider=ProviderName.OPENROUTER,
                model_type=ModelType(selection.model_type),
                model_name=selection.model_name,
                base_url=base_url,
                api_key_encrypted=encrypted_key,
                is_enabled=True,
                connection_status=ConnectionStatus.UNTESTED,
                config={"temperature": 0.2} if selection.model_type == ModelType.LLM else {},
            )
            session.add(model)
        else:
            model.display_name = selection.display_name
            model.base_url = base_url
            model.api_key_encrypted = encrypted_key
            model.is_enabled = True
            model.connection_status = ConnectionStatus.UNTESTED
            model.last_error = None
        saved.append(model)

    await session.commit()
    for model in saved:
        await session.refresh(model)
    return [serialize_model(model) for model in saved]


@router.post("/providers/{provider}/catalog", response_model=OpenRouterCatalogResponse)
async def provider_catalog(
    provider: ProviderName,
    payload: OpenRouterCatalogRequest,
    session: AsyncSession = Depends(get_session),
) -> OpenRouterCatalogResponse:
    api_key, base_url = await _provider_credentials(provider, payload, session)
    try:
        models, latency_ms = await fetch_provider_catalog(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            timeout=get_settings().request_timeout_seconds,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    label = PROVIDER_LABELS[provider]
    return OpenRouterCatalogResponse(
        detail=f"{label} 连接成功，已加载 {len(models)} 个可选模型",
        latency_ms=latency_ms,
        models=models,
    )


@router.post("/providers/{provider}/import", response_model=list[ModelConfigResponse])
async def import_provider_models(
    provider: ProviderName,
    payload: OpenRouterBulkImportRequest,
    session: AsyncSession = Depends(get_session),
) -> list[ModelConfigResponse]:
    api_key, base_url = await _provider_credentials(provider, payload, session)
    try:
        catalog, _ = await fetch_provider_catalog(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            timeout=get_settings().request_timeout_seconds,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    available = {(item["model_type"], item["id"]): item for item in catalog}
    requested = {(item.model_type, item.model_name) for item in payload.models}
    missing = sorted(
        f"{model_type}:{model_name}"
        for model_type, model_name in requested
        if (model_type, model_name) not in available
    )
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{PROVIDER_LABELS[provider]} 当前目录中不存在这些模型：{', '.join(missing)}",
        )
    existing_models = list(
        await session.scalars(select(ModelConfig).where(ModelConfig.workspace_id == current_workspace_id()).where(ModelConfig.provider == provider))
    )
    existing = {(item.model_type, item.model_name): item for item in existing_models}
    encrypted_key = encrypt_secret(api_key)
    saved: list[ModelConfig] = []
    for selection in payload.models:
        identity = (selection.model_type, selection.model_name)
        model = existing.get(identity)
        if model is None:
            model = ModelConfig(
                display_name=selection.display_name,
                provider=provider,
                model_type=ModelType(selection.model_type),
                model_name=selection.model_name,
                base_url=base_url,
                api_key_encrypted=encrypted_key,
                is_enabled=True,
                connection_status=ConnectionStatus.UNTESTED,
                config={"temperature": 0.2} if selection.model_type == ModelType.LLM else {},
            )
            session.add(model)
        else:
            model.display_name = selection.display_name
            model.base_url = base_url
            model.api_key_encrypted = encrypted_key
            model.is_enabled = True
            model.connection_status = ConnectionStatus.UNTESTED
            model.last_error = None
        saved.append(model)
    await session.commit()
    for model in saved:
        await session.refresh(model)
    return [serialize_model(model) for model in saved]


@router.get("/{model_id}", response_model=ModelConfigResponse)
async def get_model(model_id: str, session: AsyncSession = Depends(get_session)) -> ModelConfigResponse:
    return serialize_model(await get_model_or_404(session, model_id))


@router.patch("/{model_id}", response_model=ModelConfigResponse)
async def update_model(
    model_id: str,
    payload: ModelConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> ModelConfigResponse:
    model = await get_model_or_404(session, model_id)
    values = payload.model_dump(exclude_unset=True)
    new_key = values.pop("api_key", None)
    if new_key:
        model.api_key_encrypted = encrypt_secret(new_key.strip())
    if "base_url" in values and values["base_url"] is not None:
        values["base_url"] = str(values["base_url"]).rstrip("/")
    for key, value in values.items():
        setattr(model, key, value)
    model.connection_status = ConnectionStatus.MOCK if model.provider == ProviderName.MOCK else ConnectionStatus.UNTESTED
    model.last_error = None
    await session.commit()
    await session.refresh(model)
    return serialize_model(model)


@router.post("/{model_id}/test", response_model=ConnectionTestResponse)
async def test_model(model_id: str, session: AsyncSession = Depends(get_session)) -> ConnectionTestResponse:
    model = await get_model_or_404(session, model_id)
    started = monotonic()
    try:
        if model.model_type == ModelType.OCR:
            ocr = build_ocr(model)
            detail = await ocr.test_connection()
            simulated = ocr.is_simulated
        else:
            gateway = build_gateway(model)
            detail = await gateway.test_connection()
            simulated = gateway.is_simulated
    except (ProviderError, OcrError) as exc:
        latency = int((monotonic() - started) * 1000)
        model.connection_status = ConnectionStatus.ERROR
        model.last_tested_at = utc_now()
        model.last_error = str(exc)
        await session.commit()
        return ConnectionTestResponse(
            ok=False,
            status=ConnectionStatus.ERROR,
            latency_ms=latency,
            provider=model.provider,
            model_type=model.model_type,
            detail=str(exc),
            simulated=False,
        )

    latency = int((monotonic() - started) * 1000)
    model.connection_status = ConnectionStatus.MOCK if simulated else ConnectionStatus.CONNECTED
    model.last_tested_at = utc_now()
    model.last_error = None
    await session.commit()
    return ConnectionTestResponse(
        ok=True,
        status=model.connection_status,
        latency_ms=latency,
        provider=model.provider,
        model_type=model.model_type,
        detail=detail,
        simulated=simulated,
    )


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    model = await get_model_or_404(session, model_id)
    await session.delete(model)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

