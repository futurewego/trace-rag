from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.message import Message


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)

    messages: Mapped[list[Message]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
