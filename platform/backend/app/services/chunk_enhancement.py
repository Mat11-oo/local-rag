"""分块增强：为每个分块抽取关键词、生成可由该分块回答的问答对。

结果写入分块元数据，并拼进向量化文本，使口语化提问和同义表达也能命中原文。
关键词在没有模型时用规则抽取；问答对必须使用文本理解模型。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from ..providers.base import ModelGateway

BATCH_SIZE = 6
MAX_CHUNK_CHARS = 1800
MAX_KEYWORDS = 8
MAX_QA = 5

_STOPWORDS = {"以及", "一个", "进行", "相关", "可以", "需要", "内容", "说明", "要求", "根据", "其中", "如果", "我们", "他们", "这个", "那个", "没有", "不是", "因为", "所以", "the", "and", "for", "with", "that", "this"}


def rule_keywords(text: str, limit: int = MAX_KEYWORDS) -> list[str]:
    """无模型时的关键词：取高频的中文 2-4 字片段与英文/编号词，去掉常见虚词。"""
    counter: Counter[str] = Counter()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}|[A-Z0-9]{2,}[\-0-9A-Z]*", text):
        counter[word] += 2
    for run in re.findall(r"[一-鿿]{2,}", text):
        for size in (4, 3, 2):
            for index in range(len(run) - size + 1):
                counter[run[index : index + size]] += 1
    result: list[str] = []
    for word, count in counter.most_common():
        if count < 2 or word.lower() in _STOPWORDS or any(word in kept for kept in result):
            continue
        result.append(word)
        if len(result) >= limit:
            break
    return result


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
    return str(content)


def _parse_items(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON 数组")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, list):
        raise ValueError("模型返回的不是数组")
    return [item for item in value if isinstance(item, dict)]


def _clean_keywords(values: Any) -> list[str]:
    result: list[str] = []
    for value in values if isinstance(values, list) else []:
        word = re.sub(r"\s+", " ", str(value or "")).strip(" ，,。；;")
        if word and len(word) <= 40 and word not in result:
            result.append(word)
    return result[:MAX_KEYWORDS]


def _clean_qa(values: Any, limit: int) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        question = str(value.get("q") or value.get("question") or "").strip()
        answer = str(value.get("a") or value.get("answer") or "").strip()
        if question and answer and len(question) <= 300 and len(answer) <= 2000:
            result.append({"q": question, "a": answer})
    return result[:limit]


async def _llm_batch(gateway: ModelGateway, contents: list[str], *, qa: bool, keywords: bool, qa_count: int) -> list[dict[str, Any]]:
    fields = []
    if keywords:
        fields.append('"keywords": 3 到 8 个能区分该片段的检索关键词')
    if qa:
        fields.append(f'"qa": 1 到 {qa_count} 组 {{"q": 用户可能的提问, "a": 仅依据该片段的回答}}')
    blocks = "\n\n".join(f"[片段 {index}]\n{content[:MAX_CHUNK_CHARS]}" for index, content in enumerate(contents))
    prompt = (
        "你是企业知识库的索引增强器。只能依据给定片段，不得补造事实；片段信息不足时返回空数组。\n"
        f"为每个片段输出一个对象，字段为 \"index\"（片段编号）、{'、'.join(fields)}。\n"
        "仅返回 JSON 数组，不要使用 Markdown。\n\n"
        f"{blocks}"
    )
    try:
        response = await gateway.chat_model(temperature=0, max_tokens=4000).ainvoke([HumanMessage(content=prompt)])
    except Exception as exc:
        raise ValueError(f"分块增强模型调用失败：{type(exc).__name__}") from exc
    items = _parse_items(_message_text(response.content))
    by_index = {int(item["index"]): item for item in items if str(item.get("index", "")).lstrip("-").isdigit()}
    # 模型漏写 index 时按顺序对应
    if not by_index and len(items) == len(contents):
        by_index = dict(enumerate(items))
    return [by_index.get(index, {}) for index in range(len(contents))]


async def enhance_chunks(
    documents: list[Document],
    *,
    qa: bool,
    keywords: bool,
    qa_count: int = 3,
    gateway: ModelGateway | None = None,
) -> tuple[int, int]:
    """原地为分块补充 metadata["keywords"] / metadata["qa_pairs"]。

    返回 (生成的问答对数量, 模型输出无法使用的批次数)。单批失败不影响整个导入：
    该批关键词退回规则抽取、问答对留空。
    """
    if not (qa or keywords):
        return 0, 0
    if qa and gateway is None:
        raise ValueError("问答对生成需要先在知识库配置中设置文本理解模型")
    qa_count = max(1, min(qa_count, MAX_QA))
    generated = 0
    failed_batches = 0
    for start in range(0, len(documents), BATCH_SIZE):
        batch = documents[start : start + BATCH_SIZE]
        results: list[dict[str, Any]] = [{} for _ in batch]
        if gateway is not None:
            try:
                results = await _llm_batch(gateway, [item.page_content for item in batch], qa=qa, keywords=keywords, qa_count=qa_count)
            except (ValueError, json.JSONDecodeError):
                failed_batches += 1
        for document, result in zip(batch, results, strict=True):
            if keywords:
                document.metadata["keywords"] = _clean_keywords(result.get("keywords")) or rule_keywords(document.page_content)
            if qa:
                pairs = _clean_qa(result.get("qa"), qa_count)
                document.metadata["qa_pairs"] = pairs
                generated += len(pairs)
    return generated, failed_batches


def chunk_index_text(content: str, metadata: dict[str, Any] | None) -> str:
    """拼进向量化文本的分块级增强内容；没有增强时返回原文。"""
    value = metadata or {}
    lines: list[str] = []
    if value.get("keywords"):
        lines.append(f"[本段关键词] {'、'.join(value['keywords'])}")
    pairs = value.get("qa_pairs") or []
    if pairs:
        lines.append("[本段可回答的问题]")
        lines.extend(f"- {item['q']}" for item in pairs)
    return "\n".join([*lines, content]) if lines else content
