"""P1a ingestion foundation: chunk/document metadata + parent_chunks

Revision ID: 003_p1a_foundation
Revises: 002_m1_schema
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "003_p1a_foundation"
down_revision = "002_m1_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # documents
    op.add_column(
        "documents",
        sa.Column("doc_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "documents",
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("documents", sa.Column("doc_group_id", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("knowledge_base_id", sa.BigInteger(), nullable=True))
    op.execute("UPDATE documents SET doc_group_id = id WHERE doc_group_id IS NULL")
    op.create_index("ix_documents_doc_group_id", "documents", ["doc_group_id"])
    op.create_index("ix_documents_is_latest", "documents", ["is_latest"])

    # doc_group_id defaults to self (new document = new version lineage) but stays
    # overridable — inserting a new version of an existing group sets it explicitly.
    # A plain server_default can't express "= own id" so a BEFORE INSERT trigger
    # fills it in only when the caller left it NULL.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_documents_doc_group_id() RETURNS trigger AS $$
        BEGIN
            IF NEW.doc_group_id IS NULL THEN
                NEW.doc_group_id := NEW.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_documents_doc_group_id_default
        BEFORE INSERT ON documents
        FOR EACH ROW EXECUTE FUNCTION set_documents_doc_group_id()
        """
    )

    # parent_chunks (empty until P2)
    op.create_table(
        "parent_chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "document_id", sa.BigInteger,
            sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("section_path", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("page_num", sa.Integer, nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_parent_chunks_document_id", "parent_chunks", ["document_id"])

    # chunks
    op.add_column(
        "chunks",
        sa.Column("chunk_type", sa.String(32), nullable=False, server_default="text"),
    )
    op.add_column("chunks", sa.Column("section_path", postgresql.ARRAY(sa.Text), nullable=True))
    op.add_column("chunks", sa.Column("parse_confidence", sa.Float(), nullable=True))
    op.add_column("chunks", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("chunks", sa.Column("knowledge_base_id", sa.BigInteger(), nullable=True))
    op.add_column("chunks", sa.Column("parent_chunk_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_chunks_parent_chunk_id", "chunks", "parent_chunks",
        ["parent_chunk_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_chunks_is_latest", "chunks", ["is_latest"])
    op.create_index("ix_chunks_parent_chunk_id", "chunks", ["parent_chunk_id"])


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_documents_doc_group_id_default ON documents")
    op.execute("DROP FUNCTION IF EXISTS set_documents_doc_group_id()")

    op.drop_index("ix_chunks_parent_chunk_id", table_name="chunks")
    op.drop_index("ix_chunks_is_latest", table_name="chunks")
    op.drop_constraint("fk_chunks_parent_chunk_id", "chunks", type_="foreignkey")
    op.drop_column("chunks", "parent_chunk_id")
    op.drop_column("chunks", "knowledge_base_id")
    op.drop_column("chunks", "is_latest")
    op.drop_column("chunks", "content_hash")
    op.drop_column("chunks", "parse_confidence")
    op.drop_column("chunks", "section_path")
    op.drop_column("chunks", "chunk_type")

    op.drop_index("ix_parent_chunks_document_id", table_name="parent_chunks")
    op.drop_table("parent_chunks")

    op.drop_index("ix_documents_is_latest", table_name="documents")
    op.drop_index("ix_documents_doc_group_id", table_name="documents")
    op.drop_column("documents", "knowledge_base_id")
    op.drop_column("documents", "doc_group_id")
    op.drop_column("documents", "is_latest")
    op.drop_column("documents", "doc_version")
