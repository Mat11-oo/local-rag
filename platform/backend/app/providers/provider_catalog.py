from __future__ import annotations

from time import monotonic
from typing import Any

import httpx

from ..models import ProviderName
from .base import ProviderError
from .openrouter_catalog import fetch_openrouter_catalog


PROVIDER_LABELS = {
    ProviderName.OPENROUTER: "OpenRouter",
    ProviderName.AIHUBMIX: "AIHubMix",
    ProviderName.DEEPSEEK: "DeepSeek",
}


def _status_error(provider: ProviderName, response: httpx.Response) -> ProviderError:
    label = PROVIDER_LABELS[provider]
    status_code = response.status_code
    if status_code in {401, 403}:
        return ProviderError(
            f"{label} 认证失败（HTTP {status_code}）：请检查 API Key 是否属于当前服务商，"
            "且只填写密钥本身"
        )
    if status_code == 402:
        return ProviderError(f"{label} 账户余额不足（HTTP 402）：请检查账户额度")
    if status_code == 429:
        return ProviderError(f"{label} 请求过于频繁（HTTP 429）：请稍后重试")
    return ProviderError(f"{label} 服务返回 HTTP {status_code}，请检查 Endpoint 或模型目录权限")


def _supports_image(item: dict[str, Any], model_id: str) -> bool:
    architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    modalities = architecture.get("input_modalities") or item.get("input_modalities") or []
    if isinstance(modalities, list) and "image" in modalities:
        return True
    lowered = model_id.lower()
    return any(marker in lowered for marker in ("vision", "-vl", "vl-", "qwen-vl", "gpt-4o"))


def _generic_types(provider: ProviderName, item: dict[str, Any], model_id: str) -> list[str]:
    if provider == ProviderName.DEEPSEEK:
        return ["llm"]
    lowered = f"{model_id} {item.get('owned_by', '')} {item.get('task', '')}".lower()
    if "rerank" in lowered:
        return ["rerank"]
    if any(marker in lowered for marker in ("embedding", "embed-", "bge-m3", "text-embedding")):
        return ["embedding"]
    types = ["llm"]
    if _supports_image(item, model_id):
        types.append("ocr")
    return types


def _generic_catalog_item(
    provider: ProviderName,
    item: dict[str, Any],
    model_type: str,
) -> dict[str, Any] | None:
    model_id = item.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None
    name = item.get("name") or item.get("display_name") or model_id
    context_length = item.get("context_length")
    return {
        "id": model_id,
        "name": str(name),
        "description": str(item.get("description") or ""),
        "model_type": model_type,
        "context_length": context_length if isinstance(context_length, int) else None,
        "modality": str(item.get("modality") or ""),
        "prompt_price": None,
        "is_free": False,
    }


async def fetch_provider_catalog(
    *,
    provider: ProviderName,
    api_key: str,
    base_url: str,
    timeout: float,
) -> tuple[list[dict[str, Any]], int]:
    if provider == ProviderName.OPENROUTER:
        return await fetch_openrouter_catalog(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
    if provider not in {ProviderName.AIHUBMIX, ProviderName.DEEPSEEK}:
        raise ProviderError(f"{provider} 暂不支持厂商级模型目录接入")

    cleaned_key = api_key.strip()
    label = PROVIDER_LABELS[provider]
    if cleaned_key.lower().startswith("bearer "):
        raise ProviderError("API Key 只需填写密钥本身，不要添加 Bearer 前缀")
    if not cleaned_key:
        raise ProviderError(f"{label} API Key 不能为空")
    started = monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {cleaned_key}", "Accept": "application/json"},
        ) as client:
            response = await client.get(f"{base_url.rstrip('/')}/models")
            if not response.is_success:
                raise _status_error(provider, response)
            body = response.json()
    except ProviderError:
        raise
    except httpx.TimeoutException as exc:
        raise ProviderError(f"连接 {label} 超时，请检查网络、代理或 Endpoint") from exc
    except httpx.ConnectError as exc:
        raise ProviderError(
            f"无法连接 {label}：网络连接失败。请检查 Endpoint、DNS、代理或容器出网设置"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"无法连接 {label}：{type(exc).__name__}") from exc
    except ValueError as exc:
        raise ProviderError(f"{label} 返回了无法解析的模型目录") from exc

    raw_items = body.get("data", []) if isinstance(body, dict) else []
    models: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            continue
        for model_type in _generic_types(provider, raw, raw["id"]):
            item = _generic_catalog_item(provider, raw, model_type)
            if item:
                models.append(item)
    models.sort(key=lambda item: (item["model_type"], item["id"]))
    if not models:
        raise ProviderError(f"{label} 连接成功，但模型目录为空")
    return models, int((monotonic() - started) * 1000)
