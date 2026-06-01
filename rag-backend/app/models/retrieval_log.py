from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RetrievalLog(Base, TimestampMixin):
    __tablename__ = "retrieval_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    query: Mapped[str] = mapped_column(Text)
    retrieved_chunks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    chunks_sent_to_llm: Mapped[int] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieval_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
