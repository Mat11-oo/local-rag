from __future__ import annotations

import pytest

from app.providers.mock import MockGateway
from app.services.chunking import split_document
from app.services.parsers import ParsedDocument, ParsedUnit


async def test_parent_child_chunking_embeds_children_and_keeps_parent_context() -> None:
    parsed = ParsedDocument(
        units=[
            ParsedUnit(
                title="差旅制度",
                content=("员工出差前需要审批。报销必须提交发票。" * 35),
                metadata={"source_type": "markdown"},
            )
        ]
    )

    chunks = await split_document(
        parsed,
        chunk_method="parent_child",
        chunk_size=800,
        chunk_overlap=80,
        parent_chunk_size=420,
        child_chunk_size=120,
    )

    assert len(chunks) > 2
    assert all(chunk.metadata["chunk_method"] == "parent_child" for chunk in chunks)
    assert all(len(chunk.page_content) <= 120 for chunk in chunks)
    assert all(chunk.page_content in chunk.metadata["parent_content"] for chunk in chunks)
    assert len({chunk.metadata["parent_id"] for chunk in chunks}) >= 2


async def test_semantic_chunking_uses_llm_json_without_rewriting_source() -> None:
    source = "第一部分介绍背景。\n\n第二部分给出结论。"
    gateway = MockGateway(
        "llm",
        response_text='{"chunks":["第一部分介绍背景。","第二部分给出结论。"]}',
    )
    chunks = await split_document(
        ParsedDocument(units=[ParsedUnit(content=source, title="报告")]),
        chunk_method="semantic",
        chunk_size=800,
        chunk_overlap=100,
        semantic_gateway=gateway,
    )

    assert [chunk.page_content for chunk in chunks] == ["第一部分介绍背景。", "第二部分给出结论。"]
    assert all(chunk.metadata["chunk_method"] == "semantic" for chunk in chunks)


async def test_semantic_chunking_rejects_llm_rewrite() -> None:
    gateway = MockGateway("llm", response_text='{"chunks":["这是模型改写后的摘要"]}')

    with pytest.raises(ValueError, match="改写了原文"):
        await split_document(
            ParsedDocument(units=[ParsedUnit(content="这是未经改写的原文")]),
            chunk_method="semantic",
            chunk_size=800,
            chunk_overlap=100,
            semantic_gateway=gateway,
        )


async def test_semantic_chunking_rejects_omitted_source_text() -> None:
    gateway = MockGateway("llm", response_text='{"chunks":["第一部分。"]}')

    with pytest.raises(ValueError, match="遗漏了原文"):
        await split_document(
            ParsedDocument(units=[ParsedUnit(content="第一部分。第二部分。")]),
            chunk_method="semantic",
            chunk_size=800,
            chunk_overlap=100,
            semantic_gateway=gateway,
        )


async def test_separator_supports_regex_clause_boundaries() -> None:
    from app.services.chunking import split_document
    from app.services.parsers import ParsedDocument, ParsedUnit

    text = "第一条 总则内容。第二条 退货规则。第三条 保修规则。"
    parsed = ParsedDocument(units=[ParsedUnit(content=text, title="政策")], page_count=None, used_ocr=False)
    chunks = await split_document(parsed, chunk_method="separator", chunk_size=12, chunk_overlap=0, separators=["re:(?=第[一二三四五六七八九十]+条)"])
    assert [chunk.page_content for chunk in chunks] == ["第一条 总则内容。", "第二条 退货规则。", "第三条 保修规则。"]


async def test_heading_only_sections_merge_into_next_section() -> None:
    from app.services.chunking import split_document
    from app.services.parsers import ParsedDocument, ParsedUnit

    text = "# 差旅办法\n\n## 第一章 总则\n\n第一条 内容。\n\n## 第二章 住宿\n\n第三条 标准。"
    parsed = ParsedDocument(units=[ParsedUnit(content=text, title="差旅办法")])
    chunks = await split_document(parsed, chunk_method="heading", chunk_size=800, chunk_overlap=0, heading_level=3)
    assert len(chunks) == 2
    assert chunks[0].page_content.startswith("# 差旅办法")
    assert "第一条" in chunks[0].page_content
