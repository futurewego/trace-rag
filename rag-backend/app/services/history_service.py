"""读取会话历史，供 query 改写与生成共用。"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Message
from app.services.generation_service import LOW_CONFIDENCE_NOTE

_CITATION_MARKER_RE = re.compile(r"\s*\[\d+\]")


def _clean(text: str) -> str:
    """去掉旧轮的 [N] 引用标记与 ⚠️ 低置信前缀——它们只对产生它们的那一轮有意义，
    回放给模型会诱导其照抄失效编号（引用错位）或自我添加 ⚠️ 前缀。"""
    return _CITATION_MARKER_RE.sub("", text.removeprefix(LOW_CONFIDENCE_NOTE)).strip()


def get_history(
    db: Session, session_id: int, max_turns: int, content_max_chars: int
) -> list[dict]:
    """最近 max_turns 轮（=max_turns*2 条）消息，时间正序。

    必须在写入当前这轮 user Message 之前调用，否则当前问句会混入历史。
    以 id 倒序取最近 N 条再反转——id 自增即时间序，避免 created_at 同秒并列。
    """
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(max_turns * 2)
    )
    rows = db.execute(stmt).scalars().all()
    out = [
        {"role": m.role, "content": _clean(m.content or "")[:content_max_chars]}
        for m in reversed(rows)
        if m.role in ("user", "assistant") and (m.content or "").strip()
    ]
    # Anthropic 要求 messages 严格 user/assistant 交替，且我们随后会在末尾追加
    # 当前这一轮的 user 消息。因此窗口必须满足：user 开头、严格交替、assistant
    # 结尾（否则与追加的当前 user 相撞）。孤儿消息（流中断产生）会破坏这三条，
    # 宁可丢弃少量历史也不能让该会话永远 400。
    normalized: list[dict] = []
    for m in out:
        if not normalized:
            if m["role"] != "user":
                continue
            normalized.append(m)
        elif m["role"] != normalized[-1]["role"]:
            normalized.append(m)
        # 与上一条同角色（孤儿/并发交错）：丢弃后来者，保持交替
    while normalized and normalized[-1]["role"] != "assistant":
        normalized.pop()
    return normalized
