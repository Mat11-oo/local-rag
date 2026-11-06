from __future__ import annotations

from .base import ModelGateway, ProviderError
from .mock import MockGateway
from .openai_compatible import OpenAICompatibleGateway
from ..config import get_settings
from ..models import ModelConfig, ProviderName
from ..security import decrypt_secret


DEFAULT_BASE_URLS = {
    ProviderName.OPENROUTER: "https://openrouter.ai/api/v1",
    ProviderName.AIHUBMIX: "https://aihubmix.com/v1",
    ProviderName.DEEPSEEK: "https://api.deepseek.com/v1",
    ProviderName.TONGYI: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ProviderName.MOCK: "mock://local",
}


def default_base_url(provider: str) -> str:
    try:
        return DEFAULT_BASE_URLS[ProviderName(provider)]
    except (ValueError, KeyError) as exc:
        raise ProviderError(f"Unsupported provider: {provider}") from exc


def build_gateway(model: ModelConfig) -> ModelGateway:
    if model.provider == ProviderName.MOCK:
        return MockGateway(model.model_type, response_text=model.config.get("response_text"))

    if not get_settings().allow_external_processing:
        raise ProviderError("云端处理尚未授权。请前往“设置 → 本地环境”开启云端资料处理后重试。")

    api_key = decrypt_secret(model.api_key_encrypted)
    if not api_key:
        raise ProviderError("The model configuration has no API key")
    return OpenAICompatibleGateway(
        provider=model.provider,
        model_type=model.model_type,
        model_name=model.model_name,
        base_url=model.base_url,
        api_key=api_key,
        config=model.config,
        timeout=get_settings().request_timeout_seconds,
    )

