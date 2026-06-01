from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.config import get_settings
from app.integrations.qdrant_client import QdrantClientWrapper
from app.observability.logger import get_logger
from app.observability.metrics import empty_retrieval_total, retrieval_latency
from app.pipeline.retrieval.dense_retriever import DenseRetriever
from app.pipeline.retrieval.reranker import BGEReranker, RankedResult
from app.pipeline.retrieval.rrf_fusion import RRFFusion
from app.pipeline.retrieval.sparse_retriever import SparseRetriever
from app.services.embedding_service import EmbeddingService

logger = get_logger(__name__)


@dataclass
class RetrievalResult:
    query: str
    rewritten_query: str | None
    final_chunks: list[RankedResult]
    dense_results: list[dict] = field(default_factory=list)
    sparse_results: list[dict] = field(default_factory=list)
    rrf_results: list = field(default_factory=list)
    reranked_results: list[RankedResult] = field(default_factory=list)
    dense_latency_ms: int = 0
    sparse_latency_ms: int = 0
    rerank_latency_ms: int = 0
    total_latency_ms: int = 0
    fallback_triggered: bool = False
    fallback_reason: str | None = None


@dataclass
class RetrievalOptions:
    top_k: int = 20
    rerank_top_n: int = 5
    min_score: float = 0.4
    enable_query_rewrite: bool = True
    filter_conditions: dict | None = None


class RetrievalPipeline:
    """
    混合检索管道（含降级链）：
    L1: 稠密 + 稀疏 → RRF → Reranker
    L2: Reranker 超时 → 跳过重排，用 RRF top-N
    L3: Qdrant 稀疏不可用 → 仅稠密
    L4: Qdrant 完全不可用 → 抛出 RetrievalError
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._embedding = EmbeddingService()
        self._dense = DenseRetriever()
        self._sparse = SparseRetriever()
        self._rrf = RRFFusion(k=self._settings.retrieval_rrf_k)
        self._reranker = BGEReranker()
        self._qdrant = QdrantClientWrapper()

    async def run(
        self,
        query: str,
        kb_ids: list[str],
        options: RetrievalOptions | None = None,
        chat_history: list[dict] | None = None,
    ) -> RetrievalResult:
        opts = options or RetrievalOptions(
            top_k=self._settings.retrieval_top_k,
            rerank_top_n=self._settings.retrieval_rerank_top_n,
            min_score=self._settings.retrieval_min_score,
        )

        t_start = time.monotonic()
        result = RetrievalResult(query=query, rewritten_query=None, final_chunks=[])

        # ── Query Rewrite（可选）──────────────────────────────────────────────
        effective_query = query
        if opts.enable_query_rewrite and chat_history:
            try:
                from app.pipeline.retrieval.query_rewriter import QueryRewriter
                rewriter = QueryRewriter()
                rewritten = await rewriter.rewrite(query, chat_history)
                if rewritten and len(rewritten) >= 5:
                    effective_query = rewritten
                    result.rewritten_query = rewritten
            except Exception as e:
                logger.warning("query_rewrite_failed_degraded", error=str(e))
                # 降级 L6：使用原始问题

        # ── Embedding ────────────────────────────────────────────────────────
        dense_vec, sparse_vec = await self._embedding.embed_query(effective_query)

        # ── 多 KB 并发检索 ────────────────────────────────────────────────────
        all_dense: list[dict] = []
        all_sparse: list[dict] = []

        for kb_id in kb_ids:
            collection = self._qdrant.collection_name(kb_id)

            # 稠密 + 稀疏并发
            t_dense = time.monotonic()
            dense_task = self._dense.search(
                collection, dense_vec, opts.top_k, opts.filter_conditions
            )
            sparse_task = self._sparse.search(
                collection,
                sparse_vec.get("indices", []),
                sparse_vec.get("values", []),
                opts.top_k,
                opts.filter_conditions,
            )

            dense_res, sparse_res = await asyncio.gather(
                dense_task, sparse_task, return_exceptions=True
            )
            result.dense_latency_ms = int((time.monotonic() - t_dense) * 1000)

            if isinstance(dense_res, Exception):
                from app.core.exceptions import RetrievalError
                raise RetrievalError(f"Dense retrieval failed: {dense_res}")

            if isinstance(sparse_res, Exception):
                logger.warning("sparse_retrieval_failed_degraded", error=str(sparse_res))
                # 降级 L3：仅稠密
                sparse_res = []
                result.fallback_triggered = True
                result.fallback_reason = "sparse_retrieval_failed"

            all_dense.extend(dense_res)
            all_sparse.extend(sparse_res)

        result.dense_results = all_dense
        result.sparse_results = all_sparse

        if not all_dense and not all_sparse:
            empty_retrieval_total.inc()
            logger.info("retrieval_empty", query=effective_query)
            return result

        # ── RRF 融合 ──────────────────────────────────────────────────────────
        fused = self._rrf.merge(all_dense, all_sparse)
        result.rrf_results = [{"point_id": r.point_id, "rrf_score": r.rrf_score} for r in fused]

        # ── Reranking ─────────────────────────────────────────────────────────
        t_rerank = time.monotonic()
        try:
            ranked = await self._reranker.rerank(
                effective_query,
                fused[: opts.top_k],
                top_n=opts.rerank_top_n,
                min_score=opts.min_score,
            )
        except Exception as e:
            logger.warning("reranker_failed_degraded", error=str(e))
            # 降级 L2：跳过重排，直接用 RRF 结果
            from app.pipeline.retrieval.reranker import RankedResult as RR
            ranked = [
                RR(
                    point_id=r.point_id,
                    rerank_score=r.rrf_score,
                    rrf_score=r.rrf_score,
                    payload=r.payload,
                )
                for r in fused[: opts.rerank_top_n]
            ]
            result.fallback_triggered = True
            result.fallback_reason = "reranker_failed"

        result.rerank_latency_ms = int((time.monotonic() - t_rerank) * 1000)
        result.reranked_results = ranked

        # 近重复去重
        deduped = BGEReranker.dedup_similar_chunks(ranked)
        result.final_chunks = deduped

        # ── 总延迟 ────────────────────────────────────────────────────────────
        result.total_latency_ms = int((time.monotonic() - t_start) * 1000)
        retrieval_latency.labels(kb_id=kb_ids[0] if kb_ids else "unknown").observe(
            result.total_latency_ms / 1000
        )

        logger.info(
            "retrieval_done",
            query=effective_query[:80],
            final_chunks=len(result.final_chunks),
            total_ms=result.total_latency_ms,
            fallback=result.fallback_triggered,
        )

        return result
