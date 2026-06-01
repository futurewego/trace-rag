from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    PayloadSchemaType,
    PointStruct,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

from app.config import get_settings
from app.observability.logger import get_logger

logger = get_logger(__name__)

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
DENSE_VECTOR_SIZE = 3072  # text-embedding-3-large


def _kb_collection_name(kb_id: str) -> str:
    return f"kb_{kb_id[:8]}"


class QdrantClientWrapper:
    """Qdrant 操作封装，处理 collection 管理、upsert、删除"""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _get_client(self) -> AsyncQdrantClient:
        from app.dependencies import get_qdrant_client as _get
        import asyncio
        # 在同步上下文中获取（实际使用时通过 FastAPI Depends 注入）
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_get())

    async def ensure_collection(self, kb_id: str) -> str:
        """确保 KB 对应的 Qdrant Collection 存在，不存在则创建"""
        from app.dependencies import get_qdrant_client
        client = await get_qdrant_client()
        collection_name = _kb_collection_name(kb_id)

        try:
            await client.get_collection(collection_name)
            logger.debug("qdrant_collection_exists", collection=collection_name)
            return collection_name
        except Exception:
            pass  # Collection 不存在，创建它

        await client.create_collection(
            collection_name=collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: VectorParams(
                    size=DENSE_VECTOR_SIZE,
                    distance=Distance.COSINE,
                    on_disk=True,
                    hnsw_config=HnswConfigDiff(m=16, ef_construct=200),
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: SparseVectorParams(
                    index=SparseIndexParams(on_disk=False)
                )
            },
        )

        # 创建 payload 索引（加速过滤）
        for field_name, field_type in [
            ("document_id", PayloadSchemaType.KEYWORD),
            ("chunk_type", PayloadSchemaType.KEYWORD),
            ("page_number", PayloadSchemaType.INTEGER),
        ]:
            await client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=field_type,
            )

        logger.info("qdrant_collection_created", collection=collection_name, kb_id=kb_id)
        return collection_name

    async def upsert_points(
        self,
        collection_name: str,
        points: list[dict[str, Any]],
        batch_size: int = 64,
    ) -> None:
        """批量 upsert 向量点"""
        from app.dependencies import get_qdrant_client
        client = await get_qdrant_client()

        qdrant_points = []
        for p in points:
            vectors: dict[str, Any] = {DENSE_VECTOR_NAME: p["dense_vector"]}
            if p.get("sparse_indices"):
                vectors[SPARSE_VECTOR_NAME] = models.SparseVector(
                    indices=p["sparse_indices"],
                    values=p["sparse_values"],
                )
            qdrant_points.append(
                PointStruct(
                    id=str(p["point_id"]),
                    vector=vectors,
                    payload=p["payload"],
                )
            )

        for i in range(0, len(qdrant_points), batch_size):
            batch = qdrant_points[i : i + batch_size]
            await client.upsert(collection_name=collection_name, points=batch)
            logger.debug("qdrant_upsert_batch", collection=collection_name, count=len(batch))

        logger.info("qdrant_upsert_done", collection=collection_name, total=len(qdrant_points))

    async def delete_by_document(self, collection_name: str, document_id: str) -> None:
        """删除文档的所有向量点"""
        from app.dependencies import get_qdrant_client
        client = await get_qdrant_client()

        await client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
        )
        logger.info("qdrant_delete_by_document", collection=collection_name, doc_id=document_id)

    async def search_dense(
        self,
        collection_name: str,
        query_vector: list[float],
        top_k: int = 20,
        filter_conditions: dict | None = None,
    ) -> list[dict]:
        """稠密向量检索"""
        from app.dependencies import get_qdrant_client
        client = await get_qdrant_client()

        query_filter = self._build_filter(filter_conditions) if filter_conditions else None

        results = await client.query_points(
            collection_name=collection_name,
            query=query_vector,
            using=DENSE_VECTOR_NAME,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )

        return [
            {
                "point_id": str(r.id),
                "score": r.score,
                "payload": r.payload,
            }
            for r in results.points
        ]

    async def search_sparse(
        self,
        collection_name: str,
        sparse_indices: list[int],
        sparse_values: list[float],
        top_k: int = 20,
        filter_conditions: dict | None = None,
    ) -> list[dict]:
        """稀疏向量检索"""
        if not sparse_indices:
            return []

        from app.dependencies import get_qdrant_client
        client = await get_qdrant_client()

        query_filter = self._build_filter(filter_conditions) if filter_conditions else None

        results = await client.query_points(
            collection_name=collection_name,
            query=models.SparseVector(indices=sparse_indices, values=sparse_values),
            using=SPARSE_VECTOR_NAME,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )

        return [
            {
                "point_id": str(r.id),
                "score": r.score,
                "payload": r.payload,
            }
            for r in results.points
        ]

    def _build_filter(self, conditions: dict) -> models.Filter:
        """将简单的 {key: value} 字典转换为 Qdrant Filter"""
        must = []
        for key, value in conditions.items():
            if isinstance(value, list):
                must.append(
                    models.FieldCondition(key=key, match=models.MatchAny(any=value))
                )
            else:
                must.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                )
        return models.Filter(must=must)

    @staticmethod
    def collection_name(kb_id: str) -> str:
        return _kb_collection_name(kb_id)
