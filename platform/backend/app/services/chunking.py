from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..models import ChunkMethod
from ..providers.base import ModelGateway
from .parsers import ParsedDocument


SEPARATORS = ["\n## ", "\n### ", "\n\n", "\n", "。", "；", ";", " "]


def normalize_chunk_config(
    values: dict[str, Any] | None,
    *,
    default_method: str,
    default_chunk_size: int,
    default_chunk_overlap: int,
    default_parent_chunk_size: int,
    default_child_chunk_size: int,
) -> dict[str, Any]:
    raw = values or {}
    method = str(raw.get("method", default_method))
    allowed = {item.value for item in ChunkMethod}
    if method not in allowed:
        raise ValueError("不支持的切块方式")
    try:
        chunk_size = max(50, min(int(raw.get("chunk_size", default_chunk_size)), 12000))
        chunk_overlap = max(0, min(int(raw.get("chunk_overlap", default_chunk_overlap)), 1000))
        parent_chunk_size = max(200, min(int(raw.get("parent_chunk_size", default_parent_chunk_size)), 12000))
        child_chunk_size = max(80, min(int(raw.get("child_chunk_size", default_child_chunk_size)), 4000))
        heading_level = max(1, min(int(raw.get("heading_level", 3)), 6))
        rows_per_chunk = max(1, min(int(raw.get("rows_per_chunk", 1)), 20))
    except (TypeError, ValueError) as exc:
        raise ValueError("切块配置包含无效数字") from exc
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    if method == ChunkMethod.PARENT_CHILD and child_chunk_size >= parent_chunk_size:
        raise ValueError("child_chunk_size must be smaller than parent_chunk_size")
    separators = [str(item) for item in raw.get("separators", []) if str(item)][:20]
    try:
        qa_per_chunk = max(1, min(int(raw.get("qa_per_chunk", 3)), 5))
    except (TypeError, ValueError) as exc:
        raise ValueError("切块配置包含无效数字") from exc
    return {
        "method": method,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "parent_chunk_size": parent_chunk_size,
        "child_chunk_size": child_chunk_size,
        "separators": separators,
        "heading_level": heading_level,
        "rows_per_chunk": rows_per_chunk,
        # 分块增强：关键词抽取 / 生成问答对
        "enhance_keywords": bool(raw.get("enhance_keywords", False)),
        "enhance_qa": bool(raw.get("enhance_qa", False)),
        "qa_per_chunk": qa_per_chunk,
    }


def _derive_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        candidate = re.sub(r"^[#\-*\d.\s]+", "", line).strip()
        if 2 <= len(candidate) <= 80 and not candidate.startswith("|"):
            return candidate
    return fallback


def _splitter(chunk_size: int, chunk_overlap: int, separators: list[str] | None = None) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=separators or SEPARATORS,
    )


def _base_metadata(parsed: ParsedDocument, unit_index: int, unit: Any) -> dict[str, Any]:
    return {
        **unit.metadata,
        "title": unit.title,
        "page_number": unit.page_number,
        "unit_index": unit_index,
        "used_ocr": parsed.used_ocr,
    }


def _recursive_chunks(parsed: ParsedDocument, chunk_size: int, chunk_overlap: int) -> list[Document]:
    splitter = _splitter(chunk_size, chunk_overlap)
    chunks: list[Document] = []
    for unit_index, unit in enumerate(parsed.units):
        base = _base_metadata(parsed, unit_index, unit)
        for split_index, content in enumerate(splitter.split_text(unit.content)):
            normalized = content.strip()
            if not normalized:
                continue
            chunks.append(
                Document(
                    page_content=normalized,
                    metadata={
                        **base,
                        "chunk_method": ChunkMethod.RECURSIVE,
                        "split_index": split_index,
                        "title": _derive_title(normalized, unit.title or f"分块 {len(chunks) + 1}"),
                    },
                )
            )
    return chunks


def _direct_chunks(parsed: ParsedDocument, method: str) -> list[Document]:
    chunks: list[Document] = []
    for unit_index, unit in enumerate(parsed.units):
        content = unit.content.strip()
        if not content:
            continue
        chunks.append(Document(page_content=content, metadata={**_base_metadata(parsed, unit_index, unit), "chunk_method": method, "title": unit.title or _derive_title(content, f"分块 {unit_index + 1}")}))
    return chunks


def _heading_chunks(parsed: ParsedDocument, chunk_size: int, heading_level: int) -> list[Document]:
    chunks: list[Document] = []
    pattern = re.compile(rf"(?m)^(?=#{{1,{max(1, min(heading_level, 6))}}}\s+)")
    for unit_index, unit in enumerate(parsed.units):
        raw_sections = [item.strip() for item in pattern.split(unit.content) if item.strip()]
        # 只有标题、没有正文的段落（如文档总标题）并入下一段，避免产生无检索价值的空标题块。
        sections: list[str] = []
        carry = ""
        for item in raw_sections:
            if all(line.lstrip().startswith("#") for line in item.splitlines() if line.strip()):
                carry = f"{carry}\n\n{item}".strip()
                continue
            sections.append(f"{carry}\n\n{item}".strip() if carry else item)
            carry = ""
        if carry:
            sections.append(carry)
        if len(sections) <= 1:
            sections = [unit.content]
        for section_index, section in enumerate(sections):
            for split_index, content in enumerate(_splitter(chunk_size, 0).split_text(section)):
                chunks.append(Document(page_content=content.strip(), metadata={**_base_metadata(parsed, unit_index, unit), "chunk_method": ChunkMethod.HEADING, "section_index": section_index, "split_index": split_index, "title": _derive_title(section, unit.title or f"章节 {section_index + 1}")}))
    return chunks


def _table_row_chunks(parsed: ParsedDocument, rows_per_chunk: int) -> list[Document]:
    chunks: list[Document] = []
    batch_size = max(1, min(rows_per_chunk, 20))
    for unit_index, unit in enumerate(parsed.units):
        lines = [line.strip() for line in unit.content.splitlines() if line.strip()]
        table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
        if len(table_lines) < 3:
            content = unit.content.strip()
            if content:
                chunks.append(
                    Document(
                        page_content=content,
                        metadata={
                            **_base_metadata(parsed, unit_index, unit),
                            "chunk_method": ChunkMethod.TABLE_ROW,
                            "title": unit.title or _derive_title(content, f"分块 {unit_index + 1}"),
                        },
                    )
                )
            continue
        header = table_lines[0]
        rows = table_lines[2:]
        for start in range(0, len(rows), batch_size):
            content = "\n".join([header, table_lines[1], *rows[start:start + batch_size]])
            chunks.append(Document(page_content=content, metadata={**_base_metadata(parsed, unit_index, unit), "chunk_method": ChunkMethod.TABLE_ROW, "row_start": start + 1, "title": f"{unit.title or '表格'} · 第 {start + 1} 行"}))
    return chunks


def _qa_chunks(parsed: ParsedDocument) -> list[Document]:
    chunks: list[Document] = []
    for unit_index, unit in enumerate(parsed.units):
        lines = [line.strip().strip("|") for line in unit.content.splitlines() if line.strip().startswith("|")]
        rows = [[cell.strip() for cell in line.split("|")] for line in lines]
        for row_index, row in enumerate(rows[2:] if len(rows) >= 3 else []):
            if len(row) < 2 or not row[0] or not row[1]:
                continue
            content = f"问题：{row[0]}\n答案：{row[1]}"
            metadata = {**_base_metadata(parsed, unit_index, unit), "chunk_method": ChunkMethod.QA, "question": row[0], "title": row[0]}
            if len(row) > 2 and row[2]:
                metadata["alternative_questions"] = [item.strip() for item in re.split(r"[|；;]", row[2]) if item.strip()]
            chunks.append(Document(page_content=content, metadata=metadata))
    return chunks or _direct_chunks(parsed, ChunkMethod.QA)


def _parent_child_chunks(
    parsed: ParsedDocument,
    *,
    parent_chunk_size: int,
    child_chunk_size: int,
    chunk_overlap: int,
) -> list[Document]:
    parent_splitter = _splitter(parent_chunk_size, min(chunk_overlap, parent_chunk_size - 1))
    child_overlap = min(max(20, chunk_overlap // 2), child_chunk_size - 1)
    child_splitter = _splitter(child_chunk_size, child_overlap)
    chunks: list[Document] = []
    for unit_index, unit in enumerate(parsed.units):
        base = _base_metadata(parsed, unit_index, unit)
        for parent_index, parent in enumerate(parent_splitter.split_text(unit.content)):
            parent = parent.strip()
            if not parent:
                continue
            parent_id = f"u{unit_index}-p{parent_index}"
            parent_title = _derive_title(parent, unit.title or f"父块 {parent_index + 1}")
            for child_index, child in enumerate(child_splitter.split_text(parent)):
                child = child.strip()
                if not child:
                    continue
                chunks.append(
                    Document(
                        page_content=child,
                        metadata={
                            **base,
                            "chunk_method": ChunkMethod.PARENT_CHILD,
                            "parent_id": parent_id,
                            "parent_index": parent_index,
                            "child_index": child_index,
                            "parent_content": parent,
                            "parent_title": parent_title,
                            "title": _derive_title(child, parent_title),
                        },
                    )
                )
    return chunks


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def _parse_semantic_chunks(raw: str, source: str) -> list[str]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        body = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("语义切分模型未返回有效 JSON") from exc
    values = body.get("chunks") if isinstance(body, dict) else body
    if not isinstance(values, list) or not values:
        raise ValueError("语义切分模型未返回任何分块")
    chunks = [str(value).strip() for value in values if str(value).strip()]
    cursor = 0
    for chunk in chunks:
        position = source.find(chunk, cursor)
        if position < 0:
            raise ValueError("语义切分结果改写了原文，已拒绝写入索引")
        cursor = position + len(chunk)
    normalized_source = re.sub(r"\s+", "", source)
    normalized_chunks = re.sub(r"\s+", "", "".join(chunks))
    if normalized_chunks != normalized_source:
        raise ValueError("语义切分结果遗漏了原文内容，已拒绝写入索引")
    return chunks


async def _semantic_chunks(
    parsed: ParsedDocument,
    *,
    gateway: ModelGateway,
    safe_input_size: int,
) -> list[Document]:
    pre_splitter = _splitter(safe_input_size, 0)
    chunks: list[Document] = []
    for unit_index, unit in enumerate(parsed.units):
        base = _base_metadata(parsed, unit_index, unit)
        for window_index, source in enumerate(pre_splitter.split_text(unit.content)):
            source = source.strip()
            if not source:
                continue
            prompt = (
                "你是企业文档语义切分器。按主题完整性把原文切成若干段。"
                "必须逐字保留原文，不得总结、改写、增删或调整顺序。"
                "仅返回 JSON：{\"chunks\":[\"原文段1\",\"原文段2\"]}。\n\n原文：\n"
                f"{source}"
            )
            try:
                response = await gateway.chat_model(temperature=0, max_tokens=4096).ainvoke(
                    [HumanMessage(content=prompt)]
                )
            except Exception as exc:
                raise ValueError(f"语义切分模型调用失败：{type(exc).__name__}") from exc
            for semantic_index, content in enumerate(
                _parse_semantic_chunks(_message_text(response.content), source)
            ):
                chunks.append(
                    Document(
                        page_content=content,
                        metadata={
                            **base,
                            "chunk_method": ChunkMethod.SEMANTIC,
                            "semantic_window_index": window_index,
                            "semantic_index": semantic_index,
                            "title": _derive_title(content, unit.title or f"语义分块 {len(chunks) + 1}"),
                        },
                    )
                )
    return chunks


async def split_document(
    parsed: ParsedDocument,
    *,
    chunk_method: str = ChunkMethod.RECURSIVE,
    chunk_size: int,
    chunk_overlap: int,
    parent_chunk_size: int = 1600,
    child_chunk_size: int = 400,
    semantic_gateway: ModelGateway | None = None,
    separators: list[str] | None = None,
    heading_level: int = 3,
    rows_per_chunk: int = 1,
) -> list[Document]:
    if chunk_method == ChunkMethod.HEADING:
        return _heading_chunks(parsed, chunk_size, heading_level)
    if chunk_method == ChunkMethod.SEPARATOR:
        custom = [item for item in (separators or []) if item]
        if not custom:
            return _recursive_chunks(parsed, chunk_size, chunk_overlap)
        # 严格在分隔符处切开：字面分隔符保留在片段末尾；"re:" 前缀为正则（如 re:(?=第[一二三四五六七八九十百]+条)）。
        boundary = re.compile("|".join(item[3:] if item.startswith("re:") else f"(?<={re.escape(item)})" for item in custom))
        oversize = _splitter(chunk_size, chunk_overlap)

        def pieces(text: str) -> list[str]:
            result: list[str] = []
            for part in boundary.split(text):
                part = part.strip()
                if part:
                    result.extend(oversize.split_text(part) if len(part) > chunk_size else [part])
            return result

        chunks: list[Document] = []
        for unit_index, unit in enumerate(parsed.units):
            for content in pieces(unit.content):
                normalized = content.strip()
                if normalized:
                    chunks.append(
                        Document(
                            page_content=normalized,
                            metadata={
                                **_base_metadata(parsed, unit_index, unit),
                                "chunk_method": ChunkMethod.SEPARATOR,
                                "title": _derive_title(normalized, unit.title or "自定义分块"),
                            },
                        )
                    )
        return chunks
    if chunk_method == ChunkMethod.FIXED:
        chunks = []
        for unit_index, unit in enumerate(parsed.units):
            for split_index, content in enumerate(
                _splitter(chunk_size, chunk_overlap, [""]).split_text(unit.content)
            ):
                normalized = content.strip()
                if normalized:
                    chunks.append(
                        Document(
                            page_content=normalized,
                            metadata={
                                **_base_metadata(parsed, unit_index, unit),
                                "chunk_method": ChunkMethod.FIXED,
                                "title": unit.title or f"分块 {split_index + 1}",
                            },
                        )
                    )
        return chunks
    if chunk_method == ChunkMethod.PARENT_CHILD:
        return _parent_child_chunks(
            parsed,
            parent_chunk_size=parent_chunk_size,
            child_chunk_size=child_chunk_size,
            chunk_overlap=chunk_overlap,
        )
    if chunk_method == ChunkMethod.SEMANTIC:
        if semantic_gateway is None:
            raise ValueError("语义切分需要配置可用的 LLM 模型")
        return await _semantic_chunks(
            parsed,
            gateway=semantic_gateway,
            safe_input_size=max(2000, min(parent_chunk_size, 8000)),
        )
    if chunk_method == ChunkMethod.PAGE:
        return _direct_chunks(parsed, ChunkMethod.PAGE)
    if chunk_method == ChunkMethod.TABLE_ROW:
        return _table_row_chunks(parsed, rows_per_chunk)
    if chunk_method == ChunkMethod.QA:
        return _qa_chunks(parsed)
    return _recursive_chunks(parsed, chunk_size, chunk_overlap)
