from __future__ import annotations

import uuid

from sqlalchemy import DateTime, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # 1=thumbs_up, -1=thumbs_down
    feedback_type: Mapped[str | None] = mapped_column(String(32))
    # wrong_answer | missing_info | citation_error | hallucination | other
    comment: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
