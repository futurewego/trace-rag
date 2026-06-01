from __future__ import annotations

from app.integrations.qdrant_client import QdrantClientWrapper
from app.observability.logger import get_logger
from app.observability.metrics import dense_retrieval_latency

logger = get_logger(__name__)


class DenseRetriever:
    def __init__(self) -> None:
        self._qdrant = QdrantClientWrapper()

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        top_k: int = 20,
        filter_conditions: dict | None = None,
    ) -> list[dict]:
        import time
        t0 = time.monotonic()
        results = await self._qdrant.search_dense(
            collection_name, query_vector, top_k, filter_conditions
        )
        elapsed = time.monotonic() - t0
        dense_retrieval_latency.observe(elapsed)
        logger.debug("dense_retrieval_done", count=len(results), latency_ms=int(elapsed * 1000))
        return results
