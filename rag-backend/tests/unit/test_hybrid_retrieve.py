from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.services.retrieval_service import RetrievedChunk, retrieve


def _rc(cid: int, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, doc_id=1, filename="a.pdf", page_num=1, content=f"c{cid}",
        score=score, section_path=None, parent_chunk_id=None, embedding=None,
    )


@patch("app.services.retrieval_service._sparse_candidates")
@patch("app.services.retrieval_service._cosine_candidates")
@patch("app.services.retrieval_service.embed_query", return_value=[0.0] * 1536)
def test_hybrid_fuses_dense_and_sparse(mock_embed, mock_dense, mock_sparse, monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "")
    get_settings.cache_clear()
    mock_dense.return_value = [_rc(1, 0.9), _rc(2, 0.8)]
    mock_sparse.return_value = [_rc(3, 0.7), _rc(1, 0.6)]

    out = retrieve(MagicMock(), "合同编号", top_k=5)

    mock_sparse.assert_called_once()
    assert out[0].chunk_id == 1          # 两路都命中 -> 融合后第一
    assert {c.chunk_id for c in out} == {1, 2, 3}
    get_settings.cache_clear()


@patch("app.services.retrieval_service._sparse_candidates")
@patch("app.services.retrieval_service._cosine_candidates")
@patch("app.services.retrieval_service.embed_query", return_value=[0.0] * 1536)
def test_enable_sparse_false_skips_sparse(mock_embed, mock_dense, mock_sparse, monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "")
    monkeypatch.setenv("ENABLE_SPARSE", "false")
    get_settings.cache_clear()
    mock_dense.return_value = [_rc(1, 0.9)]

    out = retrieve(MagicMock(), "合同编号", top_k=5)

    mock_sparse.assert_not_called()
    assert [c.chunk_id for c in out] == [1]
    get_settings.cache_clear()


@patch("app.services.retrieval_service._sparse_candidates", return_value=[])
@patch("app.services.retrieval_service._cosine_candidates")
@patch("app.services.retrieval_service.embed_query", return_value=[0.0] * 1536)
def test_low_scores_survive_without_cohere(mock_embed, mock_dense, mock_sparse, monkeypatch):
    """无 Cohere 时不得因 rerank 阈值误拒（P2a 修复不可倒退）。"""
    monkeypatch.setenv("COHERE_API_KEY", "")
    get_settings.cache_clear()
    mock_dense.return_value = [_rc(1, 0.2), _rc(2, 0.3)]

    out = retrieve(MagicMock(), "查询", top_k=5)

    assert {c.chunk_id for c in out} == {1, 2}
    get_settings.cache_clear()


@patch(
    "app.services.retrieval_service._sparse_candidates",
    side_effect=RuntimeError("zh config missing"),
)
@patch("app.services.retrieval_service._cosine_candidates")
@patch("app.services.retrieval_service.embed_query", return_value=[0.0] * 1536)
def test_sparse_failure_degrades_to_dense(mock_embed, mock_dense, mock_sparse, monkeypatch):
    """稀疏不可用（如未跑迁移 004）必须降级为纯稠密，而不是整个查询失败。"""
    monkeypatch.setenv("COHERE_API_KEY", "")
    get_settings.cache_clear()
    mock_dense.return_value = [_rc(1, 0.9), _rc(2, 0.8)]

    out = retrieve(MagicMock(), "合同编号", top_k=5)

    assert [c.chunk_id for c in out] == [1, 2]
    get_settings.cache_clear()
