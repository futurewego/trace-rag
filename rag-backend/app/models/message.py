from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.session import Session


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    session: Mapped[Session] = relationship(back_populates="messages")
