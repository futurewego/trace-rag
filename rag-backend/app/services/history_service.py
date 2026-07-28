"""读取会话历史，供 query 改写与生成共用。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Message


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
    return [
        {"role": m.role, "content": (m.content or "")[:content_max_chars]}
        for m in reversed(rows)
    ]
