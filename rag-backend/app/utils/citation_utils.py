from __future__ import annotations

import re
from dataclasses import dataclass

from app.pipeline.retrieval.reranker import RankedResult


@dataclass
class Citation:
    index: int
    chunk_id: str
    document_id: str
    document_name: str
    page_number: int | None
    snippet: str
    presigned_url: str | None = None


def build_system_prompt(chunks: list[RankedResult], base_prompt: str | None = None) -> str:
    """
    将检索到的 chunks 编号注入 system prompt。
    要求模型使用 [^N] 格式标注每个事实的来源。
    """
    if not chunks:
        return (base_prompt or "") + "\n\n知识库中暂无相关内容，请告知用户无法从知识库中找到答案。"

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        payload = chunk.payload
        doc_name = payload.get("document_name", "未知文档")
        page = payload.get("page_number")
        chunk_type = payload.get("chunk_type", "text")
        content = payload.get("content", "")

        # 低置信度标注
        confidence = payload.get("parse_confidence", 1.0)
        confidence_note = " [⚠️内容提取置信度较低]" if confidence < 0.7 else ""

        location = f"第{page}页" if page else "位置未知"
        context_parts.append(
            f"[{i}] 来源：{doc_name} {location}{confidence_note}\n"
            f"类型：{chunk_type}\n"
            f"内容：{content}"
        )

    context_str = "\n\n---\n\n".join(context_parts)

    system_prompt = f"""{base_prompt or '你是一个企业知识库助手。'}

## 检索到的相关内容

{context_str}

## 回答规则（严格遵守）

1. 只基于上方 <检索到的相关内容> 中的信息回答，不允许使用训练知识补充
2. 每个具体事实必须用 [^N] 标注来源编号（N 对应上方内容的编号）
3. 如果检索内容无法回答问题，明确说"根据当前知识库无法回答此问题"
4. 禁止说"根据我的知识"、"通常来说"等暗示使用训练知识的表述
5. 回答要简洁准确，不要重复检索内容的原文"""

    return system_prompt


def parse_citations(response_text: str, chunks: list[RankedResult]) -> list[Citation]:
    """
    从生成的回答文本中解析 [^N] 格式的引用，映射到对应的 chunk。
    """
    # 找出所有引用编号
    pattern = re.compile(r"\[\^(\d+)\]")
    matches = pattern.findall(response_text)
    used_indices = sorted(set(int(m) for m in matches))

    citations = []
    for idx in used_indices:
        chunk_idx = idx - 1  # [^1] 对应 chunks[0]
        if chunk_idx < 0 or chunk_idx >= len(chunks):
            continue
        chunk = chunks[chunk_idx]
        payload = chunk.payload
        content = payload.get("content", "")
        snippet = content[:200] + ("..." if len(content) > 200 else "")

        citations.append(
            Citation(
                index=idx,
                chunk_id=payload.get("chunk_id", ""),
                document_id=payload.get("document_id", ""),
                document_name=payload.get("document_name", ""),
                page_number=payload.get("page_number"),
                snippet=snippet,
            )
        )

    return citations


def citations_to_dict(citations: list[Citation]) -> list[dict]:
    return [
        {
            "index": c.index,
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "document_name": c.document_name,
            "page_number": c.page_number,
            "snippet": c.snippet,
            "presigned_url": c.presigned_url,
        }
        for c in citations
    ]
