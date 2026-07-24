import app.services.retrieval_service as retrieval_service
from app.config import get_settings
from app.services.retrieval_service import (
    RetrievedChunk,
    _apply_threshold,
    _dedup_by_embedding,
    retrieve,
)


def _rc(cid, score, emb, content="内容"):
    return RetrievedChunk(
        chunk_id=cid, doc_id=1, filename="a.pdf", page_num=1, content=content,
        score=score, section_path=None, parent_chunk_id=None, embedding=emb,
    )


def test_apply_threshold_drops_low_scores():
    kept = _apply_threshold([_rc(1, 0.9, None), _rc(2, 0.3, None)], 0.4)
    assert [c.chunk_id for c in kept] == [1]


def test_apply_threshold_can_return_empty():
    """全部低于阈值时必须返回空（触发拒答），不得保留 top-1。"""
    assert _apply_threshold([_rc(1, 0.2, None), _rc(2, 0.1, None)], 0.4) == []


def test_dedup_by_embedding_keeps_higher_score():
    a = _rc(1, 0.9, [1.0, 0.0])
    b = _rc(2, 0.5, [1.0, 0.0])   # 与 a 余弦=1.0 -> 判重
    c = _rc(3, 0.7, [0.0, 1.0])   # 正交 -> 保留
    kept = _dedup_by_embedding([a, b, c], 0.92)
    assert [x.chunk_id for x in kept] == [1, 3]


def test_dedup_skips_when_embedding_missing():
    a = _rc(1, 0.9, None)
    b = _rc(2, 0.5, None)
    assert len(_dedup_by_embedding([a, b], 0.92)) == 2


# ---------------------------------------------------------------------------
# retrieve(): rerank_min_score is calibrated for Cohere relevance, not raw
# cosine — it must only be applied when rerank actually ran (regression guard).
# ---------------------------------------------------------------------------


def test_retrieve_no_threshold_without_cohere(monkeypatch):
    """无 COHERE_API_KEY 时走纯余弦路径：即使分数低于 rerank_min_score(0.4) 也不得被丢弃。"""
    monkeypatch.setenv("COHERE_API_KEY", "")
    get_settings.cache_clear()
    try:
        candidates = [
            _rc(1, 0.3, None),
            _rc(2, 0.2, None),
        ]
        monkeypatch.setattr(retrieval_service, "embed_query", lambda q: [0.0])
        monkeypatch.setattr(
            retrieval_service, "_cosine_candidates", lambda db, q_vec, limit: candidates
        )

        def _boom(*args, **kwargs):
            raise AssertionError("_rerank_with_cohere must not be called without COHERE_API_KEY")

        monkeypatch.setattr(retrieval_service, "_rerank_with_cohere", _boom)

        result = retrieve(db=None, query="问题")

        assert [c.chunk_id for c in result] == [1, 2]
    finally:
        get_settings.cache_clear()


def test_retrieve_applies_threshold_when_reranked(monkeypatch):
    """COHERE_API_KEY 已配置且触发了重排时，rerank_min_score(0.4) 硬阈值生效。"""
    monkeypatch.setenv("COHERE_API_KEY", "test")
    get_settings.cache_clear()
    try:
        # More candidates than top_k so rerank is triggered.
        cosine_candidates = [_rc(i, 0.5, None) for i in range(1, 8)]
        reranked = [
            _rc(10, 0.9, None),
            _rc(11, 0.6, None),
            _rc(12, 0.5, None),
            _rc(13, 0.3, None),
            _rc(14, 0.1, None),
        ]
        monkeypatch.setattr(retrieval_service, "embed_query", lambda q: [0.0])
        monkeypatch.setattr(
            retrieval_service,
            "_cosine_candidates",
            lambda db, q_vec, limit: cosine_candidates,
        )
        monkeypatch.setattr(
            retrieval_service,
            "_rerank_with_cohere",
            lambda query, candidates, top_n: reranked,
        )

        result = retrieve(db=None, query="问题")

        assert [c.chunk_id for c in result] == [10, 11, 12]
    finally:
        get_settings.cache_clear()
