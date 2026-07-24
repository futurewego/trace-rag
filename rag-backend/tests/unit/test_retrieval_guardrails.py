from app.services.retrieval_service import (
    RetrievedChunk,
    _apply_threshold,
    _dedup_by_embedding,
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
