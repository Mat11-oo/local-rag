from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

import httpx

from .base import ProviderError


def _status_error(status_code: int) -> ProviderError:
    if status_code in {401, 403}:
        return ProviderError(
            f"OpenRouter 认证失败（HTTP {status_code}）：请重新创建并填写有效 API Key，"
            "不要包含 Bearer、引号或前后空格"
        )
    if status_code == 402:
        return ProviderError("OpenRouter 账户余额不足（HTTP 402）：请充值或检查账户额度")
    if status_code == 429:
        return ProviderError("OpenRouter 请求过于频繁（HTTP 429）：请稍后重试或检查账户限额")
    return ProviderError(f"OpenRouter 服务返回 HTTP {status_code}，请检查 Endpoint 或稍后重试")


def _raise_for_openrouter(response: httpx.Response) -> None:
    if response.is_success:
        return
    raise _status_error(response.status_code)


def _catalog_item(item: dict[str, Any], model_type: str) -> dict[str, Any] | None:
    model_id = item.get("id")
    name = item.get("name") or model_id
    if not isinstance(model_id, str) or not model_id:
        return None
    architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    output_modalities = architecture.get("output_modalities", ["text"])
    if model_type == "llm" and "text" not in output_modalities:
        return None
    if model_type == "rerank" and "rerank" not in output_modalities:
        return None
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    prompt_price = pricing.get("prompt")
    is_free = (
        model_id.endswith(":free") or "(free)" in str(name).lower()
        if model_type == "rerank"
        else str(prompt_price) == "0"
    )
    return {
        "id": model_id,
        "name": str(name),
        "description": str(item.get("description") or ""),
        "model_type": model_type,
        "context_length": item.get("context_length") if isinstance(item.get("context_length"), int) else None,
        "modality": str(architecture.get("modality") or ""),
        "prompt_price": str(prompt_price) if prompt_price is not None else None,
        # OpenRouter currently reports prompt=0 for paid rerank models because
        # their billable unit is exposed separately (tokens/search units).
        "is_free": is_free,
    }


def _supports_image_input(item: dict[str, Any]) -> bool:
    architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    input_modalities = architecture.get("input_modalities", [])
    if isinstance(input_modalities, list) and "image" in input_modalities:
        return True
    modality = str(architecture.get("modality") or "").lower()
    return "image" in modality.partition("->")[0]


async def fetch_openrouter_catalog(
    *,
    api_key: str,
    base_url: str,
    timeout: float,
) -> tuple[list[dict[str, Any]], int]:
    cleaned_key = api_key.strip()
    if cleaned_key.lower().startswith("bearer "):
        raise ProviderError("API Key 只需填写密钥本身，不要添加 Bearer 前缀")
    if not cleaned_key:
        raise ProviderError("OpenRouter API Key 不能为空")

    started = monotonic()
    endpoint = base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {cleaned_key}",
        "Accept": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Knowledge Hub",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            auth_response = await client.get(f"{endpoint}/auth/key")
            _raise_for_openrouter(auth_response)
            llm_response, embedding_response, rerank_response = await asyncio.gather(
                client.get(f"{endpoint}/models"),
                client.get(f"{endpoint}/embeddings/models"),
                client.get(f"{endpoint}/models", params={"output_modalities": "rerank"}),
            )
            _raise_for_openrouter(llm_response)
            _raise_for_openrouter(embedding_response)
            _raise_for_openrouter(rerank_response)
            llm_body = llm_response.json()
            embedding_body = embedding_response.json()
            rerank_body = rerank_response.json()
    except ProviderError:
        raise
    except httpx.TimeoutException as exc:
        raise ProviderError("连接 OpenRouter 超时，请检查网络、代理或 Endpoint") from exc
    except httpx.ConnectError as exc:
        raise ProviderError(
            "无法连接 OpenRouter：网络连接失败。请检查 Endpoint、DNS、代理或容器出网设置"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"无法连接 OpenRouter：{type(exc).__name__}") from exc
    except ValueError as exc:
        raise ProviderError("OpenRouter 返回了无法解析的响应") from exc

    items: list[dict[str, Any]] = []
    for raw in llm_body.get("data", []):
        if isinstance(raw, dict):
            if item := _catalog_item(raw, "llm"):
                items.append(item)
            if _supports_image_input(raw) and (item := _catalog_item(raw, "ocr")):
                items.append(item)
    for raw in embedding_body.get("data", []):
        if isinstance(raw, dict) and (item := _catalog_item(raw, "embedding")):
            items.append(item)
    for raw in rerank_body.get("data", []):
        if isinstance(raw, dict) and (item := _catalog_item(raw, "rerank")):
            items.append(item)
    items.sort(key=lambda item: (item["model_type"], item["id"]))
    return items, int((monotonic() - started) * 1000)
