from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from time import monotonic
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from ..config import Settings, get_settings
from ..models import ModelConfig, ModelType, ProviderName
from ..security import decrypt_secret


class OcrError(RuntimeError):
    pass


def _provider_error_message(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    metadata = body.get("metadata")
    if isinstance(metadata, dict) and metadata.get("raw"):
        return str(metadata["raw"])
    error = body.get("error")
    if isinstance(error, dict):
        nested = _provider_error_message(error)
        if nested:
            return nested
    return str(body.get("message") or "")


class CloudOcr(ABC):
    is_available: bool = False
    is_simulated: bool = False

    @abstractmethod
    async def extract_markdown(self, image: bytes, mime_type: str) -> str:
        raise NotImplementedError


class DisabledOcr(CloudOcr):
    async def extract_markdown(self, image: bytes, mime_type: str) -> str:
        del image, mime_type
        raise OcrError(
            "该文件需要 OCR 才能识别文字：请在知识库「配置」中选择「图片理解 / OCR」模型后重试"
        )


class VisionCloudOcr(CloudOcr):
    is_available = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        provider: str,
        timeout: float,
    ) -> None:
        headers: dict[str, str] = {}
        if provider == ProviderName.OPENROUTER:
            headers = {"HTTP-Referer": "http://localhost", "X-Title": "Knowledge Hub"}
        self.model = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            temperature=0,
            max_retries=2,
            timeout=timeout,
            default_headers=headers or None,
        )
        self.provider = provider
        self.model_name = model_name

    async def extract_markdown(self, image: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(image).decode("ascii")
        prompt = (
            "Extract all visible text and tables from this enterprise document image. "
            "Return faithful Markdown only. Preserve table rows and columns; do not summarize, infer, or add facts. "
            "If a region is unreadable, write [无法识别]."
        )
        try:
            response = await self.model.ainvoke(
                [
                    HumanMessage(
                        content=[
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                        ]
                    )
                ]
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            body = getattr(exc, "body", None)
            provider_message = _provider_error_message(body)
            lowered = provider_message.lower()
            if status_code == 403 and any(
                marker in lowered for marker in ("region", "country", "location", "geographic")
            ):
                raise OcrError(
                    f"OCR 模型因地区限制不可用（HTTP 403）：{provider_message}。请更换当前地区可用的视觉模型"
                ) from exc
            if status_code in {401, 403} or "Authentication" in type(exc).__name__:
                raise OcrError(f"OCR 认证失败{'（HTTP ' + str(status_code) + '）' if status_code else ''}：请检查 API Key") from exc
            raise OcrError(f"Cloud OCR request failed: {type(exc).__name__}") from exc
        content = _content_text(response.content)
        if not content.strip():
            raise OcrError("Cloud OCR returned empty content")
        return content.strip()

    async def test_connection(self) -> str:
        # A valid 1x1 PNG verifies that the endpoint accepts multimodal input.
        sample = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n3cAAAAASUVORK5CYII="
        )
        started = monotonic()
        await self.extract_markdown(sample, "image/png")
        return f"OCR endpoint accepted image input in {int((monotonic() - started) * 1000)}ms"


class MockCloudOcr(CloudOcr):
    is_available = True
    is_simulated = True

    async def extract_markdown(self, image: bytes, mime_type: str) -> str:
        del image, mime_type
        return "这是 OCR 测试替身提取的文本，未发起外部网络请求。"

    async def test_connection(self) -> str:
        return "OCR 测试替身可用；未发起任何外部网络请求"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return str(content) if content is not None else ""


def build_ocr(model: ModelConfig, settings: Settings | None = None) -> CloudOcr:
    if model.model_type != ModelType.OCR:
        raise OcrError("The configured model is not an OCR model")
    if model.provider == ProviderName.MOCK:
        return MockCloudOcr()
    api_key = decrypt_secret(model.api_key_encrypted)
    if not api_key:
        raise OcrError("The OCR model configuration has no API key")
    active = settings or get_settings()
    return VisionCloudOcr(
        api_key=api_key,
        base_url=model.base_url,
        model_name=model.model_name,
        provider=model.provider,
        timeout=active.request_timeout_seconds,
    )


def get_ocr(settings: Settings | None = None) -> CloudOcr:
    active = settings or get_settings()
    if active.ocr_provider == "vision":
        if not active.ocr_api_key:
            raise OcrError("APP_OCR_API_KEY is required for legacy cloud OCR configuration")
        return VisionCloudOcr(
            api_key=active.ocr_api_key,
            base_url=active.ocr_base_url,
            model_name=active.ocr_model_name,
            provider=ProviderName.TONGYI,
            timeout=active.request_timeout_seconds,
        )
    return DisabledOcr()

