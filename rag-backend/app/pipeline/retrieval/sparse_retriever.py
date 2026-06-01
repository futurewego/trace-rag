from __future__ import annotations

from app.integrations.qdrant_client import QdrantClientWrapper
from app.observability.logger import get_logger
from app.observability.metrics import sparse_retrieval_latency

logger = get_logger(__name__)


class SparseRetriever:
    def __init__(self) -> None:
        self._qdrant = QdrantClientWrapper()

    async def search(
        self,
        collection_name: str,
        sparse_indices: list[int],
        sparse_values: list[float],
        top_k: int = 20,
        filter_conditions: dict | None = None,
    ) -> list[dict]:
        if not sparse_indices:
            logger.debug("sparse_retrieval_skipped_empty_vector")
            return []

        import time
        t0 = time.monotonic()
        results = await self._qdrant.search_sparse(
            collection_name, sparse_indices, sparse_values, top_k, filter_conditions
        )
        elapsed = time.monotonic() - t0
        sparse_retrieval_latency.observe(elapsed)
        logger.debug("sparse_retrieval_done", count=len(results), latency_ms=int(elapsed * 1000))
        return results
