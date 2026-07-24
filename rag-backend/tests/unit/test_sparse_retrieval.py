from sqlalchemy.dialects import postgresql

from app.services.retrieval_service import _sparse_stmt


def _sql() -> str:
    return str(_sparse_stmt("合同 编号", 20).compile(dialect=postgresql.dialect()))


def test_sparse_stmt_uses_zh_tsvector_and_tsquery():
    sql = _sql()
    assert "to_tsvector" in sql
    assert "plainto_tsquery" in sql
    assert "@@" in sql


def test_sparse_stmt_filters_is_latest_and_limits():
    sql = _sql()
    assert "is_latest" in sql
    assert "LIMIT" in sql.upper()


def test_sparse_stmt_orders_by_rank_desc():
    sql = _sql()
    assert "ts_rank" in sql
    assert "DESC" in sql.upper()
