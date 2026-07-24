from app.config import get_settings


def test_p2b_defaults():
    s = get_settings()
    assert s.sparse_candidate_k == 20
    # Calibrated for candidate depth ~20 (not TREC's k=60 for ~1000-item runs):
    # at k=10 with equal weights, a sparse-only rank-1 hit (0.5/11 = 0.04545)
    # outranks a dense rank-5 hit (0.5/15 = 0.03333), so it survives into a
    # top-5 answer.
    assert s.rrf_k == 10
    assert s.rrf_dense_weight == 0.5
    assert s.rrf_sparse_weight == 0.5
    assert s.enable_sparse is True
