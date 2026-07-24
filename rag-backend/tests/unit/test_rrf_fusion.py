from app.services.retrieval_service import RetrievedChunk, _rrf_fuse


def _rc(cid: int, score: float = 0.0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, doc_id=1, filename="a.pdf", page_num=1, content=f"c{cid}",
        score=score, section_path=["S"], parent_chunk_id=cid * 10, embedding=[0.1],
    )


def test_chunk_in_both_lists_outranks_single_list_chunks():
    dense = [_rc(1), _rc(2)]
    sparse = [_rc(3), _rc(1)]
    fused = _rrf_fuse(dense, sparse, k=60, dense_w=0.6, sparse_w=0.4)
    assert fused[0].chunk_id == 1  # 两路都命中 -> RRF 分最高


def test_empty_sparse_degrades_to_dense_order():
    dense = [_rc(1), _rc(2), _rc(3)]
    fused = _rrf_fuse(dense, [], k=60, dense_w=0.6, sparse_w=0.4)
    assert [c.chunk_id for c in fused] == [1, 2, 3]


def test_empty_dense_degrades_to_sparse_order():
    sparse = [_rc(7), _rc(8)]
    fused = _rrf_fuse([], sparse, k=60, dense_w=0.6, sparse_w=0.4)
    assert [c.chunk_id for c in fused] == [7, 8]


def test_both_empty_returns_empty():
    assert _rrf_fuse([], [], k=60, dense_w=0.6, sparse_w=0.4) == []


def test_representative_keeps_downstream_fields():
    fused = _rrf_fuse([_rc(5)], [], k=60, dense_w=0.6, sparse_w=0.4)
    c = fused[0]
    assert c.parent_chunk_id == 50
    assert c.section_path == ["S"]
    assert c.embedding == [0.1]


def test_score_is_overwritten_with_rrf_score():
    fused = _rrf_fuse([_rc(1, score=0.99)], [], k=60, dense_w=0.6, sparse_w=0.4)
    assert fused[0].score == 0.6 * (1 / 61)
