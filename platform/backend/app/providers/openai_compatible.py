from __future__ import annotations

from time import monotonic
from typing import Any

import httpx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .base import ModelGateway, ProviderCapabilityError, ProviderError, RerankItem


class OpenAICompatibleGateway(ModelGateway):
    def __init__(
        self,
        *,
        provider: str,
        model_type: str,
        model_name: str,
        base_url: str,
        api_key: str,
        config: dict[str, Any],
        timeout: float,
    ) -> None:
        self.provider = provider
        self.model_type = model_type
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.config = config
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = self.config.get("http_referer", "http://localhost")
            headers["X-Title"] = self.config.get("app_title", "Knowledge Hub")
        return headers

    def _embedding_model(self) -> OpenAIEmbeddings:
        return OpenAIEmbeddings(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model_name,
            timeout=self.timeout,
            max_retries=2,
            # Some OpenAI-compatible providers (including OpenRouter) accept
            # text inputs but reject the token-id arrays produced by
            # LangChain's context-length pre-tokenization path.
            check_embedding_ctx_length=False,
            dimensions=self.config.get("dimensions"),
            default_headers=self._headers,
        )

    def _request_error(self, capability: str, exc: Exception) -> ProviderError:
        status_code = getattr(exc, "status_code", None)
        error_name = type(exc).__name__
        provider_name = {
            "openrouter": "OpenRouter",
            "aihubmix": "AIHubMix",
            "deepseek": "DeepSeek",
            "tongyi": "通义",
        }.get(self.provider, self.provider)
        if status_code in {401, 403} or "Authentication" in error_name:
            return ProviderError(
                f"{provider_name} 认证失败"
                f"{'（HTTP ' + str(status_code) + '）' if status_code else ''}："
                "请检查 API Key 是否属于当前服务商；只填写密钥本身，不要添加 Bearer、引号或空格"
            )
        if status_code == 402:
            return ProviderError(f"{provider_name} 账户余额不足（HTTP 402），请检查额度")
        if status_code == 429 or "RateLimit" in error_name:
            return ProviderError(f"{provider_name} 请求过于频繁或额度受限（HTTP 429），请稍后重试")
        if status_code:
            return ProviderError(
                f"{capability} 请求失败（HTTP {status_code}，{error_name}）："
                "请检查模型标识是否支持该能力"
            )
        return ProviderError(f"{capability} 请求失败：{error_name}")

    def chat_model(self, **overrides: Any) -> ChatOpenAI:
        parameters = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model_name,
            "timeout": self.timeout,
            "max_retries": 2,
            "temperature": self.config.get("temperature", 0.2),
            "stream_usage": True,
            "default_headers": self._headers,
        }
        parameters.update(overrides)
        return ChatOpenAI(**parameters)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.model_type != "embedding":
            raise ProviderCapabilityError("The configured model is not an embedding model")
        try:
            return await self._embedding_model().aembed_documents(texts)
        except Exception as exc:  # provider SDK errors vary
            raise self._request_error("Embedding", exc) from exc

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankItem]:
        if self.model_type != "rerank":
            raise ProviderCapabilityError("The configured model is not a rerank model")

        if self.provider == "tongyi":
            url = self.config.get(
                "rerank_url",
                "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
            )
            payload = {
                "model": self.model_name,
                "input": {"query": query, "documents": documents},
                "parameters": {"top_n": top_n, "return_documents": False},
            }
        else:
            url = self.config.get("rerank_url", f"{self.base_url}/rerank")
            payload = {"model": self.model_name, "query": query, "documents": documents, "top_n": top_n}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Rerank request returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"Rerank request failed: {type(exc).__name__}") from exc

        raw_results = body.get("output", {}).get("results", []) if self.provider == "tongyi" else body.get("results", [])
        try:
            return [
                RerankItem(
                    index=int(item["index"]),
                    score=float(item.get("relevance_score", item.get("score", 0.0))),
                )
                for item in raw_results[:top_n]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("Rerank response did not contain valid ranked results") from exc

    async def test_connection(self) -> str:
        started = monotonic()
        if self.model_type == "embedding":
            vector = await self.embed_query("knowledge hub connection test")
            return f"Embedding endpoint returned {len(vector)} dimensions in {int((monotonic() - started) * 1000)}ms"
        if self.model_type == "rerank":
            result = await self.rerank("test", ["test document"], 1)
            return f"Rerank endpoint returned {len(result)} result in {int((monotonic() - started) * 1000)}ms"
        if self.model_type == "llm":
            try:
                response = await self.chat_model(max_tokens=8).ainvoke("Reply with OK only")
            except Exception as exc:
                raise self._request_error("LLM", exc) from exc
            if not response.content:
                raise ProviderError("LLM endpoint returned an empty response")
            return f"LLM endpoint returned content in {int((monotonic() - started) * 1000)}ms"
        raise ProviderCapabilityError(f"Unsupported model type: {self.model_type}")

