from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ModelConfig, ModelType, ProviderName
from ..providers import build_gateway
from .manifest import Manifest
from .templates import create_manifest


class DesignError(ValueError):
    pass


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return str(content) if content is not None else ""


def parse_manifest_json(content: Any) -> Manifest:
    text = _content_text(content).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
        ends = [index for index in (text.rfind("}"), text.rfind("]")) if index >= 0]
        if not starts or not ends:
            raise DesignError("模型未返回可解析的 JSON Manifest，请调整需求描述后重试")
        try:
            payload = json.loads(text[min(starts) : max(ends) + 1])
        except json.JSONDecodeError as exc:
            raise DesignError("模型返回的 Manifest 不是有效 JSON，请重试") from exc
    try:
        return Manifest.model_validate(payload)
    except ValidationError as exc:
        raise DesignError(f"模型返回的 Manifest 不符合协议：{exc.errors()}") from exc


def mock_design(
    brief: str,
    *,
    template_key: str = "content",
    llm_model_id: str | None = None,
    base_manifest: dict[str, Any] | Manifest | None = None,
) -> Manifest:
    del brief
    values = base_manifest.model_dump(mode="json") if isinstance(base_manifest, Manifest) else dict(base_manifest or {})
    values.pop("schema_version", None)
    values["llm_model_id"] = llm_model_id if llm_model_id is not None else values.get("llm_model_id")
    return create_manifest(template_key, **values)


async def design_manifest(
    session: AsyncSession,
    *,
    brief: str,
    workspace_id: str,
    template_key: str = "content",
    llm_model_id: str | None = None,
    base_manifest: dict[str, Any] | Manifest | None = None,
) -> tuple[Manifest, bool]:
    model: ModelConfig | None = None
    if llm_model_id:
        model = await session.get(ModelConfig, llm_model_id)
        if (
            model is None
            or model.workspace_id != workspace_id
            or model.model_type != ModelType.LLM
            or not model.is_enabled
        ):
            raise DesignError("所选 LLM 模型不存在、已禁用或不属于当前业务空间")
    if model is None or model.provider == ProviderName.MOCK:
        return (
            mock_design(
                brief,
                template_key=template_key,
                llm_model_id=llm_model_id,
                base_manifest=base_manifest,
            ),
            True,
        )

    base = mock_design(
        brief,
        template_key=template_key,
        llm_model_id=llm_model_id,
        base_manifest=base_manifest,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是 FDE 应用设计器。只输出一个 JSON 对象，不要 Markdown 代码块或解释。"
                "对象必须符合 fde.app/v2 Manifest。保留模板协议、字段类型和约束，"
                "根据需求改进名称、描述、system_prompt、输入字段、输出与 guardrails。"
                "template_key 必须保持为 {template_key}，llm_model_id 必须保持为 {llm_model_id}。"
                "不要虚构模型或知识库 ID。\n基础 Manifest：\n{base_manifest}",
            ),
            ("human", "应用需求：\n{brief}"),
        ]
    )
    chain = prompt | build_gateway(model).chat_model()
    try:
        response = await chain.ainvoke(
            {
                "brief": brief,
                "template_key": template_key,
                "llm_model_id": llm_model_id,
                "base_manifest": base.model_dump_json(),
            }
        )
        manifest = parse_manifest_json(getattr(response, "content", response))
    except DesignError:
        raise
    except Exception as exc:
        raise DesignError(f"真实模型设计失败：{exc}") from exc
    if manifest.template_key != template_key or manifest.llm_model_id != llm_model_id:
        raise DesignError("模型擅自更改了 template_key 或 llm_model_id，请重试")
    return manifest, False
