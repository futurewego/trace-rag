from __future__ import annotations

import asyncio

from celery import Task
from celery.utils.log import get_task_logger

from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,          # 第一次重试等 60s
    autoretry_for=(Exception,),
    retry_backoff=True,              # 指数退避
    retry_backoff_max=300,           # 最多等 5 分钟
    retry_jitter=True,
    name="app.workers.tasks.ingestion_task.process_document",
)
def process_document(self: Task, doc_id: str) -> dict:
    """
    文档入库 Celery 任务（幂等）。
    步骤：检查状态 → IngestionPipeline.run() → 更新状态
    """
    logger.info(f"Starting ingestion for document {doc_id}, attempt {self.request.retries + 1}")

    try:
        result = asyncio.run(_process_document_async(doc_id))
        logger.info(f"Ingestion completed for document {doc_id}: {result}")
        return result
    except Exception as exc:
        logger.error(f"Ingestion failed for document {doc_id}: {exc}")
        raise


async def _process_document_async(doc_id: str) -> dict:
    """异步执行文档入库，包含幂等检查"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

    from app.config import get_settings
    from app.models.document import Document

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # ── 幂等检查 ────────────────────────────────────────────────────────
        doc = await session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"Document {doc_id} not found")

        if doc.status == "completed":
            logger.info(f"Document {doc_id} already completed, skipping")
            return {"status": "skipped", "reason": "already_completed"}

        if doc.status == "deleted":
            logger.info(f"Document {doc_id} was deleted, skipping")
            return {"status": "skipped", "reason": "deleted"}

        # 标记为处理中
        doc.status = "processing"
        await session.commit()

    # ── 执行 Pipeline ────────────────────────────────────────────────────────
    try:
        from app.pipeline.ingestion.pipeline import IngestionPipeline

        pipeline = IngestionPipeline()
        result = await pipeline.run(doc_id)

        # 更新为完成
        async with session_factory() as session:
            doc = await session.get(Document, doc_id)
            if doc:
                doc.status = "completed"
                doc.chunk_count = result.get("chunk_count", 0)
                doc.parser_used = result.get("parser_used")
                await session.commit()

        return result

    except Exception as exc:
        # 更新为失败
        async with session_factory() as session:
            doc = await session.get(Document, doc_id)
            if doc:
                doc.status = "failed"
                doc.error_message = str(exc)[:1000]
                await session.commit()
        raise

    finally:
        await engine.dispose()
