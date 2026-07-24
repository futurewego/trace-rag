"""P2b sparse retrieval: zhparser extension + zh config + expression GIN index

Revision ID: 004_p2b_sparse
Revises: 003_p1a_foundation
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op

revision = "004_p2b_sparse"
down_revision = "003_p1a_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # zhparser must be present in the image (deploy/postgres-zhparser).
    op.execute("CREATE EXTENSION IF NOT EXISTS zhparser")

    # 'zh' text-search configuration (idempotent).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'zh') THEN
                CREATE TEXT SEARCH CONFIGURATION zh (PARSER = zhparser);
                ALTER TEXT SEARCH CONFIGURATION zh
                    ADD MAPPING FOR n,v,a,i,e,l,j,x,t,z WITH simple;
            END IF;
        END
        $$
        """
    )

    # Expression GIN index: no new column, no table rewrite, covers existing rows.
    # The retrieval query MUST use the identical expression to hit this index.
    op.execute(
        "CREATE INDEX ix_chunks_content_zh ON chunks "
        "USING gin (to_tsvector('zh', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_zh")
    # The 'zh' configuration and the zhparser extension are intentionally kept:
    # other objects may reference them and dropping is riskier than leaving them.
