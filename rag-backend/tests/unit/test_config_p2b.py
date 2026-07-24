from app.config import get_settings


def test_p2b_defaults():
    s = get_settings()
    assert s.sparse_candidate_k == 20
    assert s.rrf_k == 60
    assert s.rrf_dense_weight == 0.6
    assert s.rrf_sparse_weight == 0.4
    assert s.enable_sparse is True
