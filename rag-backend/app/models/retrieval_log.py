from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # 查询信息
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text)

    # 各阶段检索结果快照（完整可观测性）
    dense_results: Mapped[list | None] = mapped_column(JSON)
    # [{"chunk_id": "uuid", "score": 0.89}, ...]
    sparse_results: Mapped[list | None] = mapped_column(JSON)
    rrf_results: Mapped[list | None] = mapped_column(JSON)
    reranked_results: Mapped[list | None] = mapped_column(JSON)
    # [{"chunk_id": "uuid", "score": 0.96, "doc": "xx.pdf", "page": 7}, ...]
    final_chunks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 实际送入 LLM 的 chunks

    # 延迟统计
    dense_latency_ms: Mapped[int | None] = mapped_column(Integer)
    sparse_latency_ms: Mapped[int | None] = mapped_column(Integer)
    rerank_latency_ms: Mapped[int | None] = mapped_column(Integer)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer)

    # 降级信息
    fallback_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<RetrievalLog id={self.id} session={self.session_id}>"
