from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
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

    document: Mapped[Document] = relationship(back_populates="chunks")
