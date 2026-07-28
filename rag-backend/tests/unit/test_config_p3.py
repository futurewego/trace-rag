from app.config import get_settings


def test_p3_defaults():
    s = get_settings()
    assert s.history_max_turns == 5
    assert s.history_content_max_chars == 500
    assert s.enable_query_rewrite is True
    assert s.rewrite_max_chars == 200
