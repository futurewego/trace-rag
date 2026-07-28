"""P3 multi-turn: record the pre-rewrite original query on retrieval logs

Revision ID: 005_p3_multi_turn
Revises: 004_p2b_sparse
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "005_p3_multi_turn"
down_revision = "004_p2b_sparse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # query 列存改写后的检索用查询；original_query 存用户原话。
    # P5 诊断"答得不好"时必须能区分"用户问得含糊"与"改写改坏了"。
    op.add_column("retrieval_logs", sa.Column("original_query", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("retrieval_logs", "original_query")
