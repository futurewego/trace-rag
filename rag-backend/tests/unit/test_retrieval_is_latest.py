from sqlalchemy.dialects import postgresql

from app.services.retrieval_service import _candidates_stmt


def test_candidates_stmt_filters_is_latest():
    stmt = _candidates_stmt([0.0] * 1536, 5)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "is_latest" in sql
    assert "LIMIT" in sql.upper()
