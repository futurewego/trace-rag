from app.config import get_settings


def test_p2a_defaults():
    s = get_settings()
    assert s.child_chunk_tokens == 200
    assert s.parent_chunk_tokens == 800
    assert s.child_overlap_tokens == 32
    assert s.table_max_tokens == 1024
    assert s.rerank_min_score == 0.4
    assert s.low_confidence_score == 0.6
    assert s.dedup_cosine_threshold == 0.92
    assert s.context_token_budget == 8000
