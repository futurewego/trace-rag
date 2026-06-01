"""initial tables

Revision ID: 001
Revises:
Create Date: 2026-03-31
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── knowledge_bases ─────────────────────────────────────────────────────
    op.create_table(
        "knowledge_bases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("config", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── documents ────────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("file_type", sa.String(32), nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("parser_used", sa.String(64)),
        sa.Column("error_message", sa.Text),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("metadata", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_documents_kb_id", "documents", ["knowledge_base_id"])
    op.create_index("idx_documents_status", "documents", ["status"])

    # ── document_chunks ──────────────────────────────────────────────────────
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("chunk_type", sa.String(32), nullable=False, server_default="text"),
        sa.Column("page_number", sa.Integer),
        sa.Column("section_path", postgresql.ARRAY(sa.Text)),
        sa.Column("metadata", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parse_confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("idx_chunks_kb_id", "document_chunks", ["knowledge_base_id"])
    op.create_index("idx_chunks_qdrant_point", "document_chunks", ["qdrant_point_id"])

    # ── chat_sessions ─────────────────────────────────────────────────────────
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(512)),
        sa.Column("config", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── retrieval_logs（先创建，chat_messages 引用它）────────────────────────
    op.create_table(
        "retrieval_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        # message_id 的外键在 chat_messages 创建后通过 alter table 添加
        sa.Column("original_query", sa.Text, nullable=False),
        sa.Column("rewritten_query", sa.Text),
        sa.Column("dense_results", postgresql.JSON),
        sa.Column("sparse_results", postgresql.JSON),
        sa.Column("rrf_results", postgresql.JSON),
        sa.Column("reranked_results", postgresql.JSON),
        sa.Column("final_chunks", postgresql.JSON, nullable=False, server_default="[]"),
        sa.Column("dense_latency_ms", sa.Integer),
        sa.Column("sparse_latency_ms", sa.Integer),
        sa.Column("rerank_latency_ms", sa.Integer),
        sa.Column("total_latency_ms", sa.Integer),
        sa.Column("fallback_triggered", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("fallback_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_retrieval_logs_session", "retrieval_logs", ["session_id"])
    op.create_index("idx_retrieval_logs_created", "retrieval_logs", ["created_at"])

    # ── chat_messages ─────────────────────────────────────────────────────────
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations", postgresql.JSON),
        sa.Column("retrieval_log_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("retrieval_logs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_used", sa.String(64)),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("idx_messages_created_at", "chat_messages", ["session_id", "created_at"])

    # 补充 retrieval_logs.message_id 外键
    op.create_foreign_key(
        "fk_retrieval_logs_message_id",
        "retrieval_logs", "chat_messages",
        ["message_id"], ["id"],
        ondelete="SET NULL",
    )

    # ── feedback ──────────────────────────────────────────────────────────────
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("message_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("feedback_type", sa.String(32)),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_feedback_message_id", "feedback", ["message_id"])


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_constraint("fk_retrieval_logs_message_id", "retrieval_logs", type_="foreignkey")
    op.drop_table("chat_messages")
    op.drop_table("retrieval_logs")
    op.drop_table("chat_sessions")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
