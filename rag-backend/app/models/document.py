from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.chunk import Chunk


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(512))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    file_path: Mapped[str] = mapped_column(String(1024))
    file_size: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
