from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.config import get_settings
from app.observability.logger import get_logger
from app.observability.metrics import rerank_latency
from app.pipeline.retrieval.rrf_fusion import FusedResult

logger = get_logger(__name__)

RERANKER_TIMEOUT_MS = 500   # 超过 500ms 触发降级


@dataclass
class RankedResult:
    point_id: str
    rerank_score: float
    rrf_score: float
    dense_score: float | None = None
    sparse_score: float | None = None
    payload: dict = field(default_factory=dict)


class BGEReranker:
    """
    BGE-Reranker-v2-m3 本地 CPU 推理。
    使用 asyncio.to_thread() 包裹，避免阻塞事件循环。
    超时（> RERANKER_TIMEOUT_MS）时降级跳过，直接返回 RRF 顺序。
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._model = None

    def _load_model(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import CrossEncoder
        logger.info("loading_reranker_model", path=self._settings.reranker_model_path)
        self._model = CrossEncoder(
            self._settings.reranker_model_path,
            device=self._settings.reranker_device,
            max_length=512,
        )

    def _rerank_sync(self, query: str, candidates: list[FusedResult]) -> list[RankedResult]:
        """同步执行 reranking（在线程池中运行）"""
        self._load_model()
        pairs = [(query, c.payload.get("content", "")) for c in candidates]
        scores = self._model.predict(
            pairs,
            batch_size=self._settings.reranker_batch_size,
            show_progress_bar=False,
        )
        ranked = []
        for candidate, score in zip(candidates, scores):
            ranked.append(
                RankedResult(
                    point_id=candidate.point_id,
                    rerank_score=float(score),
                    rrf_score=candidate.rrf_score,
                    dense_score=candidate.dense_score,
                    sparse_score=candidate.sparse_score,
                    payload=candidate.payload,
                )
            )
        return sorted(ranked, key=lambda x: x.rerank_score, reverse=True)

    async def rerank(
        self,
        query: str,
        candidates: list[FusedResult],
        top_n: int = 5,
        min_score: float = 0.4,
    ) -> list[RankedResult]:
        """
        异步 reranking。
        超时时降级：直接将 FusedResult 转为 RankedResult（使用 RRF 分数）。
        """
        if not candidates:
            return []

        t0 = time.monotonic()
        try:
            ranked = await asyncio.wait_for(
                asyncio.to_thread(self._rerank_sync, query, candidates),
                timeout=RERANKER_TIMEOUT_MS / 1000.0,
            )
            elapsed = time.monotonic() - t0
            rerank_latency.observe(elapsed)
            logger.debug("rerank_done", count=len(ranked), latency_ms=int(elapsed * 1000))

        except TimeoutError:
            logger.warning(
                "reranker_timeout_degraded",
                timeout_ms=RERANKER_TIMEOUT_MS,
                candidates=len(candidates),
            )
            # 降级：用 RRF 分数代替 rerank 分数
            ranked = [
                RankedResult(
                    point_id=c.point_id,
                    rerank_score=c.rrf_score,
                    rrf_score=c.rrf_score,
                    dense_score=c.dense_score,
                    sparse_score=c.sparse_score,
                    payload=c.payload,
                )
                for c in candidates
            ]

        # 过滤低分 + 取 top_n
        filtered = [r for r in ranked if r.rerank_score >= min_score]
        if not filtered:
            # 如果全部被过滤，返回分数最高的一个（避免完全无结果）
            filtered = ranked[:1]

        return filtered[:top_n]

    @staticmethod
    def dedup_similar_chunks(results: list[RankedResult], similarity_threshold: float = 0.92) -> list[RankedResult]:
        """
        近重复去重：如果两个 chunk 的内容高度相似，只保留分数更高的。
        使用简单的 Jaccard 相似度（token 级别）进行快速去重。
        """
        if len(results) <= 1:
            return results

        def tokenize(text: str) -> set[str]:
            return set(text.lower().split())

        kept = []
        for result in results:
            content = result.payload.get("content", "")
            tokens = tokenize(content)
            is_dup = False
            for existing in kept:
                existing_tokens = tokenize(existing.payload.get("content", ""))
                if not tokens or not existing_tokens:
                    continue
                intersection = len(tokens & existing_tokens)
                union = len(tokens | existing_tokens)
                jaccard = intersection / union if union > 0 else 0
                if jaccard > similarity_threshold:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(result)

        return kept
