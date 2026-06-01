"""M1 transitional: only Base is exported here.

Old SA 1.x-style models in this directory (document.py, knowledge_base.py,
session.py, feedback.py, retrieval_log.py) are NOT imported yet because they
use legacy `Mapped`-less annotations incompatible with SA 2.0.

They will be rewritten in Task 8 of the M1 plan.

Alembic uses explicit `op.create_table` in 002_m1_schema.py — it does NOT
need Base.metadata to be populated for migrations to work.
"""
from app.models.base import Base, TimestampMixin

__all__ = ["Base", "TimestampMixin"]
