from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from app.config import get_settings
from app.integrations.minio_client import MinIOClient
from app.integrations.qdrant_client import QdrantClientWrapper
from app.observability.logger import get_logger
from app.observability.metrics import document_chunks_created_total, documents_processed_total
from app.pipeline.ingestion.parsers.factory import ParserFactory
from app.pipeline.ingestion.steps.chunk import RecursiveChunker
from app.services.embedding_service import EmbeddingService

logger = get_logger(__name__)


class IngestionPipeline:
    """
    文档入库 Pipeline（6步串联）：
    Step1: 从 MinIO 下载文件
    Step2: 解析文档（ParsedDocument）
    Step3: 语义分块（List[Chunk]）
    Step4: Embedding（稠密+稀疏）
    Step5: 写入 Qdrant
    Step6: 写入 PostgreSQL
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._minio = MinIOClient()
        self._chunker = RecursiveChunker()
        self._embedding = EmbeddingService()
        self._qdrant = QdrantClientWrapper()

    async def run(self, doc_id: str) -> dict:
        """执行完整 Pipeline，返回 {chunk_count, parser_used}"""
        from datetime import datetime, timezone

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.models.document import Document, DocumentChunk

        engine = create_async_engine(self._settings.database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        doc_uuid = uuid.UUID(doc_id)

        async with session_factory() as session:
            doc = await session.get(Document, doc_uuid)
            if not doc:
                raise ValueError(f"Document {doc_id} not found")

            logger.info("ingestion_pipeline_start", doc_id=doc_id, filename=doc.original_name)

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir) / doc.filename

                # ── Step 1: 下载文件 ───────────────────────────────────────
                logger.info("ingestion_step1_download", doc_id=doc_id)
                await self._minio.download_to_path(doc.storage_path, tmp_path)

                # ── Step 2: 解析文档 ───────────────────────────────────────
                logger.info("ingestion_step2_parse", doc_id=doc_id)
                parser = ParserFactory.get(doc.file_type)
                parsed_doc = await parser.parse(tmp_path)
                logger.info(
                    "ingestion_step2_done",
                    doc_id=doc_id,
                    elements=len(parsed_doc.elements),
                    parser=parsed_doc.parser_used,
                )

                # ── Step 3: 分块 ───────────────────────────────────────────
                logger.info("ingestion_step3_chunk", doc_id=doc_id)
                # 从 KB config 读取分块参数
                kb_config = doc.metadata_.get("kb_config", {})
                chunks = self._chunker.chunk(
                    parsed_doc,
                    chunk_size=kb_config.get("chunk_size"),
                    overlap=kb_config.get("chunk_overlap"),
                )
                logger.info("ingestion_step3_done", doc_id=doc_id, chunks=len(chunks))

                # ── Step 4: Embedding ──────────────────────────────────────
                logger.info("ingestion_step4_embed", doc_id=doc_id)
                embedded_chunks = await self._embedding.embed_for_ingestion(chunks)

                # ── Step 5: 写入 Qdrant ────────────────────────────────────
                logger.info("ingestion_step5_qdrant", doc_id=doc_id)
                kb_id = str(doc.knowledge_base_id)
                collection_name = await self._qdrant.ensure_collection(kb_id)

                qdrant_points = [
                    {
                        "point_id": ec.chunk.qdrant_point_id,
                        "dense_vector": ec.dense_vector,
                        "sparse_indices": ec.sparse_indices,
                        "sparse_values": ec.sparse_values,
                        "payload": {
                            "chunk_id": str(ec.chunk.chunk_id),
                            "document_id": doc_id,
                            "knowledge_base_id": kb_id,
                            "content": ec.chunk.content,
                            "chunk_type": ec.chunk.chunk_type,
                            "page_number": ec.chunk.page_number,
                            "section_path": ec.chunk.section_path,
                            "token_count": ec.chunk.token_count,
                            "document_name": doc.original_name,
                            "parse_confidence": ec.chunk.parse_confidence,
                        },
                    }
                    for ec in embedded_chunks
                ]
                await self._qdrant.upsert_points(collection_name, qdrant_points)

                # ── Step 6: 写入 PostgreSQL ────────────────────────────────
                logger.info("ingestion_step6_postgres", doc_id=doc_id)
                now = datetime.now(timezone.utc)
                db_chunks = [
                    DocumentChunk(
                        id=ec.chunk.chunk_id,
                        document_id=doc_uuid,
                        knowledge_base_id=doc.knowledge_base_id,
                        chunk_index=ec.chunk.chunk_index,
                        content=ec.chunk.content,
                        content_hash=ec.chunk.content_hash,
                        token_count=ec.chunk.token_count,
                        chunk_type=ec.chunk.chunk_type,
                        page_number=ec.chunk.page_number,
                        section_path=ec.chunk.section_path,
                        metadata_=ec.chunk.metadata,
                        qdrant_point_id=ec.chunk.qdrant_point_id,
                        parse_confidence=ec.chunk.parse_confidence,
                        parent_chunk_id=ec.chunk.parent_chunk_id,
                        created_at=now,
                    )
                    for ec in embedded_chunks
                ]

                # 批量插入
                for i in range(0, len(db_chunks), 100):
                    batch = db_chunks[i : i + 100]
                    session.add_all(batch)
                    await session.flush()

                await session.commit()

        # 更新指标
        documents_processed_total.labels(status="completed", file_type=doc.file_type).inc()
        document_chunks_created_total.inc(len(embedded_chunks))

        logger.info(
            "ingestion_pipeline_done",
            doc_id=doc_id,
            chunk_count=len(embedded_chunks),
            parser_used=parsed_doc.parser_used,
        )

        await engine.dispose()
        return {
            "chunk_count": len(embedded_chunks),
            "parser_used": parsed_doc.parser_used,
        }
