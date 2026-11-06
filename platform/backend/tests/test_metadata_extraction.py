from __future__ import annotations

import json

import pytest

from app.providers.mock import MockGateway
from app.services.metadata_extraction import (
    build_embedding_text,
    build_source_sample,
    extract_document_metadata,
)
from app.services.parsers import ParsedDocument, ParsedUnit


async def test_rule_extraction_builds_searchable_metadata() -> None:
    parsed = ParsedDocument(
        units=[
            ParsedUnit(
                title="差旅报销制度",
                content=(
                    "# 差旅报销制度\n"
                    "版本号：V2.1\n"
                    "生效日期：2026年10月26日\n"
                    "负责人：财务共享中心\n\n"
                    "## 报销时限\n员工应在出差结束后 30 天内提交发票。"
                ),
            )
        ]
    )

    metadata = await extract_document_metadata(parsed, "集团差旅制度.md")

    assert metadata["document_time"] == "2026-10-26"
    assert metadata["version"] == "V2.1"
    assert metadata["owner"] == "财务共享中心"
    assert "集团差旅制度" in metadata["subjects"]
    assert metadata["keywords"]
    assert any("版本" in question for question in metadata["likely_questions"])
    assert metadata["extraction_method"] == "rules"

    embedding_text = build_embedding_text("员工应在 30 天内提交发票。", metadata)
    assert "版本：V2.1" in embedding_text
    assert "负责人或部门：财务共享中心" in embedding_text
    assert "[正文]\n员工应在 30 天内提交发票。" in embedding_text


async def test_llm_extraction_normalizes_and_limits_fields() -> None:
    response = {
        "document_time": "2025/3/8",
        "version": "V3",
        "subjects": ["会员中心", "会员中心", "积分产品"],
        "owner": "增长产品部",
        "keywords": [f"关键词{i}" for i in range(30)],
        "likely_questions": ["积分何时过期？", "如何查询积分？"],
    }
    gateway = MockGateway("llm", response_text=json.dumps(response, ensure_ascii=False))
    parsed = ParsedDocument(units=[ParsedUnit(title="会员规则", content="积分有效期为一年。")])

    metadata = await extract_document_metadata(parsed, "会员规则.md", gateway=gateway, model_id="model-1")

    assert metadata["document_time"] == "2025-03-08"
    assert metadata["subjects"] == ["会员中心", "积分产品"]
    assert len(metadata["keywords"]) == 20
    assert metadata["likely_questions"] == ["积分何时过期？", "如何查询积分？"]
    assert metadata["extraction_method"] == "llm"
    assert metadata["model_id"] == "model-1"


async def test_llm_extraction_rejects_invalid_json() -> None:
    gateway = MockGateway("llm", response_text="不是 JSON")
    parsed = ParsedDocument(units=[ParsedUnit(content="有效内容")])

    with pytest.raises(ValueError, match="未返回 JSON"):
        await extract_document_metadata(parsed, "invalid.md", gateway=gateway, model_id="model-1")


def test_source_sample_is_bounded_for_long_documents() -> None:
    parsed = ParsedDocument(
        units=[ParsedUnit(title=f"章节 {index}", content="企业制度内容" * 3000) for index in range(12)]
    )

    sample = build_source_sample(parsed, max_chars=5000)

    assert len(sample) <= 5000
    assert "章节 0" in sample
    assert "中间内容已截断" in sample
