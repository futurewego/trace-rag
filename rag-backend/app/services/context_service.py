"""上下文组装：父块去重扩展 + Token 预算 + Lost-in-the-Middle 排序。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ParentChunk
from app.services.chunker_service import count_tokens
from app.services.retrieval_service import RetrievedChunk


@dataclass
class ContextBlock:
    content: str  # 父块内容（无父块时回落为子块自身内容）
    chunk_id: int  # 代表子块 id —— citation 指向它
    doc_id: int
    filename: str
    page_num: int | None  # 取自子块，父块可能跨页
    section_path: list[str] | None
    score: float  # 该父块下最佳子块分数
    token_count: int


def _order_and_budget(blocks: list[ContextBlock], budget: int) -> list[ContextBlock]:
    """预算内保留最高分的若干块，再按分数升序排列（最相关放最后）。"""
    kept: list[ContextBlock] = []
    used = 0
    for b in sorted(blocks, key=lambda x: x.score, reverse=True):
        if used + b.token_count > budget:
            continue
        kept.append(b)
        used += b.token_count
    return sorted(kept, key=lambda x: x.score)


def assemble_context(db: Session, chunks: list[RetrievedChunk]) -> list[ContextBlock]:
    """把命中的子块折叠成去重后的父块上下文块。

    多个子块命中同一父块时只产出一个块，代表子块取分数最高者。
    无父块的老数据回落到子块自身内容。
    """
    if not chunks:
        return []

    parent_ids = {c.parent_chunk_id for c in chunks if c.parent_chunk_id is not None}
    parent_content: dict[int, str] = {}
    if parent_ids:
        rows = db.execute(
            select(ParentChunk.id, ParentChunk.content).where(ParentChunk.id.in_(parent_ids))
        ).all()
        parent_content = {r.id: r.content for r in rows}

    best: dict[object, ContextBlock] = {}
    for c in chunks:
        key = ("p", c.parent_chunk_id) if c.parent_chunk_id is not None else ("c", c.chunk_id)
        existing = best.get(key)
        if existing is not None and existing.score >= c.score:
            continue

        # 默认用子块自身内容；仅当父块存在且非空时才扩展为父块。
        # 空父块属异常情况（chunk_unit 不产出空组），此时回落到子块内容——
        # 注入一个空上下文块对生成毫无价值。
        content = c.content
        if c.parent_chunk_id is not None:
            parent_text = parent_content.get(c.parent_chunk_id)
            if parent_text:
                content = parent_text

        best[key] = ContextBlock(
            content=content,
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            filename=c.filename,
            page_num=c.page_num,
            section_path=c.section_path,
            score=c.score,
            token_count=count_tokens(content),
        )

    return _order_and_budget(list(best.values()), get_settings().context_token_budget)
