from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from ..providers.base import ModelGateway
from .parsers import ParsedDocument


MAX_SOURCE_CHARS = 24000
MAX_KEYWORDS = 20
MAX_SUBJECTS = 10
MAX_QUESTIONS = 15

_OWNER_LABELS = "负责人|责任人|维护人|文档所有者|归口部门|编制部门|发布部门|发布单位"
_STOPWORDS = {
    "以及",
    "一个",
    "为了",
    "进行",
    "相关",
    "可以",
    "需要",
    "工作",
    "内容",
    "文档",
    "说明",
    "要求",
    "管理",
    "规定",
    "使用",
    "根据",
    "其中",
    "如果",
}


def _unique_strings(values: Any, *, limit: int, max_length: int) -> list[str]:
    if not isinstance(values, list):
        values = [values] if isinstance(values, str) else []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip(" -|，,；;。")
        if not normalized or len(normalized) > max_length:
            continue
        identity = normalized.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _clean_optional(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", str(value)).strip(" -|，,；;。")
    return normalized[:max_length] if normalized else None


def _normalize_date(value: Any) -> str | None:
    cleaned = _clean_optional(value, max_length=40)
    if not cleaned:
        return None
    exact = re.search(r"(?<!\d)(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?", cleaned)
    if exact:
        year, month, day = (int(part) for part in exact.groups())
        try:
            return datetime(year, month, day, tzinfo=UTC).date().isoformat()
        except ValueError:
            return cleaned
    month_only = re.search(r"(?<!\d)(20\d{2})[年./-](\d{1,2})月?", cleaned)
    if month_only:
        year, month = (int(part) for part in month_only.groups())
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    year_only = re.fullmatch(r"20\d{2}年?", cleaned)
    if year_only:
        return cleaned[:4]
    return cleaned


def normalize_document_metadata(
    raw: dict[str, Any] | None,
    *,
    extraction_method: str,
    model_id: str | None = None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = {**(defaults or {}), **(raw or {})}
    return {
        "document_time": _normalize_date(source.get("document_time")),
        "version": _clean_optional(source.get("version"), max_length=80),
        "subjects": _unique_strings(source.get("subjects"), limit=MAX_SUBJECTS, max_length=120),
        "owner": _clean_optional(source.get("owner"), max_length=160),
        "keywords": _unique_strings(source.get("keywords"), limit=MAX_KEYWORDS, max_length=60),
        "likely_questions": _unique_strings(
            source.get("likely_questions"), limit=MAX_QUESTIONS, max_length=240
        ),
        "extraction_method": extraction_method,
        "extraction_status": "completed",
        "extracted_at": datetime.now(UTC).isoformat(),
        "model_id": model_id,
    }


def _source_text(parsed: ParsedDocument) -> str:
    sections: list[str] = []
    for unit in parsed.units:
        if unit.title:
            sections.append(f"# {unit.title}")
        sections.append(unit.content)
    return "\n\n".join(sections)


def build_source_sample(parsed: ParsedDocument, *, max_chars: int = MAX_SOURCE_CHARS) -> str:
    sections: list[str] = []
    remaining = max_chars
    for index, unit in enumerate(parsed.units):
        if remaining <= 0:
            break
        heading = f"[内容单元 {index + 1}：{unit.title or '无标题'}]\n"
        allowance = min(max(600, max_chars // max(len(parsed.units), 1)), 4000, remaining)
        content = unit.content.strip()
        if len(content) > allowance:
            head_size = max(300, allowance * 3 // 4)
            tail_size = max(120, allowance - head_size)
            content = f"{content[:head_size]}\n…（中间内容已截断）…\n{content[-tail_size:]}"
        section = f"{heading}{content}"[:remaining]
        sections.append(section)
        remaining -= len(section)
    return "\n\n".join(sections)[:max_chars]


def _extract_rule_metadata(parsed: ParsedDocument, filename: str) -> dict[str, Any]:
    text = _source_text(parsed)
    first_date = re.search(
        r"(?<!\d)20\d{2}(?:[年./-]\d{1,2}(?:[月./-]\d{1,2}日?)?|年)", text
    )
    version = re.search(
        r"(?:版本(?:号)?|版次|version)\s*[:：]?\s*([Vv]?\d+(?:\.\d+){0,3}(?:[-_A-Za-z0-9]+)?)",
        text,
        flags=re.IGNORECASE,
    ) or re.search(r"(?<![A-Za-z0-9])[Vv]\d+(?:\.\d+){0,3}(?![A-Za-z0-9])", text)
    owner_match = re.search(
        rf"(?:{_OWNER_LABELS})\s*(?:\||[:：])\s*([^\n|]{{1,160}})", text, flags=re.IGNORECASE
    )

    stem = Path(filename).stem.strip()
    headings = _unique_strings(
        [unit.title for unit in parsed.units if unit.title and not re.fullmatch(r"第\s*\d+\s*页", unit.title)]
        + re.findall(r"(?m)^#{1,4}\s+(.{2,80})$", text),
        limit=10,
        max_length=120,
    )
    entities = re.findall(
        r"[\u4e00-\u9fffA-Za-z0-9·（）()_-]{2,40}(?:公司|集团|部门|中心|项目|产品|平台|制度)",
        text[:12000],
    )
    subjects = _unique_strings([stem, *headings[:4], *entities], limit=MAX_SUBJECTS, max_length=120)

    keyword_candidates: list[str] = [stem, *headings]
    keyword_candidates.extend(
        re.findall(r"(?m)^(?:[-*]\s*)?([^\n：:|]{2,24})[：:]", text[:16000])
    )
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,30}|[\u4e00-\u9fff]{2,6}", text[:16000])
    frequencies = Counter(token for token in tokens if token not in _STOPWORDS)
    keyword_candidates.extend(token for token, count in frequencies.most_common(30) if count >= 2)
    keywords = _unique_strings(keyword_candidates, limit=MAX_KEYWORDS, max_length=60)

    questions = ["这份文档的主要内容和适用范围是什么？"]
    if first_date:
        questions.append("该文档何时发布、生效或更新？")
    if version:
        questions.append("当前文档的版本是什么？")
    if owner_match:
        questions.append("该文档由谁负责或维护？")
    questions.extend(f"{heading}有哪些具体要求？" for heading in headings[:6])

    raw = {
        "document_time": first_date.group(0) if first_date else None,
        "version": version.group(1) if version and version.lastindex else version.group(0) if version else None,
        "subjects": subjects,
        "owner": owner_match.group(1) if owner_match else None,
        "keywords": keywords,
        "likely_questions": questions,
    }
    return normalize_document_metadata(raw, extraction_method="rules")


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


def _parse_llm_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("元数据抽取模型未返回 JSON 对象")
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("元数据抽取模型返回了无效 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("元数据抽取模型返回的数据结构无效")
    return value


async def extract_document_metadata(
    parsed: ParsedDocument,
    filename: str,
    *,
    gateway: ModelGateway | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    rule_metadata = _extract_rule_metadata(parsed, filename)
    if gateway is None:
        return rule_metadata

    prompt = (
        "你是企业知识库的文档元数据抽取器。只能依据给定文档，不得猜测或补造。"
        "找不到的信息必须返回 null 或空数组。仅返回一个 JSON 对象，不要使用 Markdown。\n"
        "字段固定为：\n"
        "- document_time: 文档发布、生效或更新时间，无法确定则 null\n"
        "- version: 版本号或版次，无法确定则 null\n"
        "- subjects: 文档涉及的企业、产品、制度对象、项目或业务主体数组，最多 10 项\n"
        "- owner: 负责人、责任部门、归口部门或发布单位，无法确定则 null\n"
        "- keywords: 有助于企业检索且能区分本文的关键词，5 到 20 项\n"
        "- likely_questions: 用户可能用来检索本文的自然语言问题，5 到 15 条；问题必须可由本文回答\n\n"
        f"文件名：{filename}\n"
        f"规则抽取候选（仅供核对，可能不准确）：{json.dumps(rule_metadata, ensure_ascii=False)}\n\n"
        f"文档内容：\n{build_source_sample(parsed)}"
    )
    try:
        response = await gateway.chat_model(temperature=0, max_tokens=2400).ainvoke(
            [HumanMessage(content=prompt)]
        )
    except Exception as exc:
        raise ValueError(f"元数据抽取模型调用失败：{type(exc).__name__}") from exc
    llm_value = _parse_llm_json(_message_text(response.content))
    return normalize_document_metadata(
        llm_value,
        extraction_method="llm",
        model_id=model_id,
        defaults=rule_metadata,
    )


def build_embedding_text(content: str, metadata: dict[str, Any] | None) -> str:
    value = metadata or {}
    lines = ["[文档元数据]"]
    if value.get("document_time"):
        lines.append(f"时间：{value['document_time']}")
    if value.get("version"):
        lines.append(f"版本：{value['version']}")
    if value.get("subjects"):
        lines.append(f"主体：{'、'.join(value['subjects'])}")
    if value.get("owner"):
        lines.append(f"负责人或部门：{value['owner']}")
    if value.get("keywords"):
        lines.append(f"关键词：{'、'.join(value['keywords'])}")
    questions = value.get("likely_questions") or []
    if questions:
        lines.append("可能被问到的问题：")
        lines.extend(f"- {question}" for question in questions)
    lines.extend(["[正文]", content])
    return "\n".join(lines)
