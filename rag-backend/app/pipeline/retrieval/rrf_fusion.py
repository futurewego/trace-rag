from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FusedResult:
    point_id: str
    rrf_score: float
    dense_score: float | None = None
    sparse_score: float | None = None
    payload: dict = field(default_factory=dict)


class RRFFusion:
    """
    Reciprocal Rank Fusion：合并稠密和稀疏检索结果。
    RRF(d) = Σ 1/(k + rank(d))，k=60 为标准默认值。
    """

    def __init__(self, k: int = 60) -> None:
        self.k = k

    def merge(
        self,
        dense_results: list[dict],
        sparse_results: list[dict],
        dense_weight: float = 0.6,
        sparse_weight: float = 0.4,
    ) -> list[FusedResult]:
        """合并两路检索结果，返回按 RRF 分数降序排列的列表"""
        scores: dict[str, FusedResult] = {}

        # 处理稠密检索结果
        for rank, result in enumerate(dense_results, 1):
            pid = result["point_id"]
            rrf = dense_weight * (1.0 / (self.k + rank))
            if pid not in scores:
                scores[pid] = FusedResult(
                    point_id=pid,
                    rrf_score=0.0,
                    payload=result.get("payload", {}),
                )
            scores[pid].rrf_score += rrf
            scores[pid].dense_score = result["score"]

        # 处理稀疏检索结果
        for rank, result in enumerate(sparse_results, 1):
            pid = result["point_id"]
            rrf = sparse_weight * (1.0 / (self.k + rank))
            if pid not in scores:
                scores[pid] = FusedResult(
                    point_id=pid,
                    rrf_score=0.0,
                    payload=result.get("payload", {}),
                )
            scores[pid].rrf_score += rrf
            scores[pid].sparse_score = result["score"]

        return sorted(scores.values(), key=lambda x: x.rrf_score, reverse=True)
