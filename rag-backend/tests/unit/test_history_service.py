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
    db = _db_returning([_msg(2, "assistant", "长" * 999), _msg(1, "user", "问")])
    out = get_history(db, session_id=7, max_turns=5, content_max_chars=100)
    assert len(out[-1]["content"]) == 100


def test_history_empty_session_returns_empty():
    db = _db_returning([])
    assert get_history(db, session_id=7, max_turns=5, content_max_chars=500) == []


def test_history_limit_is_two_messages_per_turn():
    db = _db_returning([])
    get_history(db, session_id=7, max_turns=3, content_max_chars=500)
    stmt = db.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 6" in sql


def test_history_drops_leading_assistant_after_orphan_shift():
    """孤儿 user 消息使窗口错位成 assistant 开头时，必须弹出直到 user 开头。"""
    db = _db_returning([_msg(4, "assistant", "答2"), _msg(3, "user", "问2"),
                        _msg(2, "user", "孤儿问"), _msg(1, "assistant", "答0")])
    out = get_history(db, session_id=7, max_turns=2, content_max_chars=500)
    assert out[0]["role"] == "user"


def test_history_skips_empty_content():
    db = _db_returning([_msg(2, "assistant", ""), _msg(1, "user", "问")])
    out = get_history(db, session_id=7, max_turns=5, content_max_chars=500)
    assert all(m["content"] for m in out)


def test_history_strips_stale_citation_markers_and_notice():
    from app.services.generation_service import LOW_CONFIDENCE_NOTE
    db = _db_returning([
        _msg(2, "assistant", LOW_CONFIDENCE_NOTE + "甲方是星曜科技 [1]，金额125万 [2]。"),
        _msg(1, "user", "甲方是谁？"),
    ])
    out = get_history(db, session_id=7, max_turns=5, content_max_chars=500)
    assert "[1]" not in out[1]["content"] and "[2]" not in out[1]["content"]
    assert not out[1]["content"].startswith("⚠️")
    assert "星曜科技" in out[1]["content"]
