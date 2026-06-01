# M1 现有代码取舍清单

> Date: 2026-06-01
> Plan ref: `docs/plans/2026-05-26-m1-rag-mvp.md` §Task 4

## ✅ 保留（直接复用或微调）
- `alembic.ini` — 改 URL，去掉 async 配置
- `app/models/base.py` — SQLAlchemy declarative base
- `app/utils/citation_utils.py` — citation 解析工具
- `app/observability/logger.py` — structlog 配置
- `app/api/v1/health.py` — 健康检查接口

## 🔄 重写（保留文件名但内容重写）
- `app/main.py`
- `app/config.py`
- `app/dependencies.py`
- `app/models/document.py`（pgvector + 简化字段，删 knowledge_base_id 关联）
- `app/models/session.py`（拆出 chat_messages 改名 messages）
- `app/models/retrieval_log.py`
- `app/services/embedding_service.py`（保留接口，重写实现）
- `app/services/generation_service.py`
- `alembic/env.py`（async → sync）

## 🆕 新建
- `app/models/chunk.py`
- `app/models/message.py`
- `app/api/v1/documents.py`
- `app/api/v1/chat.py`
- `app/services/parser_service.py`
- `app/services/chunker_service.py`
- `app/services/retrieval_service.py`
- `app/services/ingestion_service.py`
- `alembic/versions/002_m1_schema.py`（M1 完整 schema，`down_revision=None`）

## ❌ 弃用（M1 不调用，文件保留待 M2 视情况）
- `app/integrations/qdrant_client.py`
- `app/integrations/minio_client.py`
- `app/workers/*`
- `app/core/circuit_breaker.py`
- `app/core/fallback_chain.py`
- `app/core/retry.py`
- `app/pipeline/*`
- `app/observability/metrics.py`
- `app/models/feedback.py`、`app/models/knowledge_base.py`（M1 不用）

## ⚠️ 偏离原 plan
- **001_initial_tables.py 删除**（原 plan 说「不删」，但 001 schema 与 002 冲突且 DB 全新，删更干净）
- **002 down_revision = None**（原 plan 说 `"001_initial_tables"`，与实际 `revision="001"` 不一致；改 None 起新链）
- **docker host port 5435**（原 plan 5432，但本机被 `ai-copywriter-postgres` 占）
