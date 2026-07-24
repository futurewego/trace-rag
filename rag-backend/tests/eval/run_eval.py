"""对已入库的语料跑最小评估，输出 Precision@3 与命中率。

用法（需已配置 .env 且语料已入库）：
    uv run python -m tests.eval.run_eval
"""
from __future__ import annotations


def run_eval(db) -> dict:
    from app.services.retrieval_service import retrieve
    from tests.eval.golden_set import GOLDEN

    hits = 0
    prec_sum = 0.0
    for case in GOLDEN:
        results = retrieve(db, case["question"], top_k=3)
        matched = [
            r
            for r in results
            if r.filename == case["expected_filename"]
            and (case["expected_page"] is None or r.page_num == case["expected_page"])
        ]
        if matched:
            hits += 1
        prec_sum += (len(matched) / len(results)) if results else 0.0
    n = len(GOLDEN)
    return {
        "n": n,
        "hit_rate": round(hits / n, 3) if n else 0.0,
        "precision_at_3": round(prec_sum / n, 3) if n else 0.0,
    }


def main() -> None:
    from app.dependencies import _SessionLocal

    with _SessionLocal() as db:
        print(run_eval(db))


if __name__ == "__main__":
    main()
