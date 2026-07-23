from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document

_dim = get_settings().openai_embed_dim


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(_dim))
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata_", JSONB, nullable=True)
    chunk_type: Mapped[str] = mapped_column(
        String(32), server_default="text", nullable=False
    )
    section_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    parse_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_latest: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )
    knowledge_base_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    parent_chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("parent_chunks.id", ondelete="SET NULL"), nullable=True
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
