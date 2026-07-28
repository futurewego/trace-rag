from unittest.mock import MagicMock

from app.services.history_service import get_history


def _msg(mid, role, content):
    m = MagicMock()
    m.id, m.role, m.content = mid, role, content
    return m


def _db_returning(msgs_desc):
    """模拟 db.execute(...).scalars().all() 返回 id 倒序的消息列表。"""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = msgs_desc
    return db


def test_history_reversed_to_chronological_order():
    db = _db_returning([_msg(4, "assistant", "答2"), _msg(3, "user", "问2"),
                        _msg(2, "assistant", "答1"), _msg(1, "user", "问1")])
    out = get_history(db, session_id=7, max_turns=5, content_max_chars=500)
    assert [m["content"] for m in out] == ["问1", "答1", "问2", "答2"]
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]


def test_history_truncates_long_content():
    db = _db_returning([_msg(1, "assistant", "长" * 999)])
    out = get_history(db, session_id=7, max_turns=5, content_max_chars=100)
    assert len(out[0]["content"]) == 100


def test_history_empty_session_returns_empty():
    db = _db_returning([])
    assert get_history(db, session_id=7, max_turns=5, content_max_chars=500) == []


def test_history_limit_is_two_messages_per_turn():
    db = _db_returning([])
    get_history(db, session_id=7, max_turns=3, content_max_chars=500)
    stmt = db.execute.call_args.args[0]
    assert "LIMIT" in str(stmt.compile()).upper()
    assert stmt._limit_clause.value == 6  # 3 轮 = 6 条
