from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.services.query_rewriter import rewrite_query

HISTORY = [
    {"role": "user", "content": "HT-2026-0087 合同的甲方是谁？"},
    {"role": "assistant", "content": "甲方是星曜科技有限公司 [1]。"},
]


def _mock_client(text):
    client = MagicMock()
    client.with_options.return_value = client
    client.messages.create.return_value.content = [MagicMock(text=text)]
    return client


@patch("app.services.query_rewriter._client")
def test_no_history_returns_original_without_llm(mock_client):
    assert rewrite_query("甲方是谁？", []) == "甲方是谁？"
    mock_client.assert_not_called()


@patch("app.services.query_rewriter._client")
def test_rewrites_coref_question(mock_client):
    mock_client.return_value = _mock_client("HT-2026-0087 合同的乙方是谁")
    assert rewrite_query("那乙方呢？", HISTORY) == "HT-2026-0087 合同的乙方是谁"


@patch("app.services.query_rewriter._client")
def test_short_chinese_query_long_rewrite_is_kept(mock_client):
    """锁死 Pipeline B 的 len*3 缺陷：3 字问句的 17 字正确改写必须保留。"""
    mock_client.return_value = _mock_client("HT-2026-0087 合同的乙方是谁")
    out = rewrite_query("乙方呢", HISTORY)
    assert out == "HT-2026-0087 合同的乙方是谁"


@patch("app.services.query_rewriter._client")
def test_llm_exception_falls_back(mock_client):
    mock_client.return_value.with_options.return_value = mock_client.return_value
    mock_client.return_value.messages.create.side_effect = RuntimeError("api down")
    assert rewrite_query("那乙方呢？", HISTORY) == "那乙方呢？"


@patch("app.services.query_rewriter._client")
def test_overlong_rewrite_falls_back(mock_client):
    mock_client.return_value = _mock_client("废" * 300)
    assert rewrite_query("那乙方呢？", HISTORY) == "那乙方呢？"


@patch("app.services.query_rewriter._client")
def test_empty_rewrite_falls_back(mock_client):
    mock_client.return_value = _mock_client("   ")
    assert rewrite_query("那乙方呢？", HISTORY) == "那乙方呢？"


@patch("app.services.query_rewriter._client")
def test_multiline_rewrite_takes_first_line(mock_client):
    mock_client.return_value = _mock_client("HT-2026-0087 合同的乙方是谁\n\n解释：因为上一轮…")
    assert rewrite_query("那乙方呢？", HISTORY) == "HT-2026-0087 合同的乙方是谁"


@patch("app.services.query_rewriter._client")
def test_disabled_via_env_skips_llm(mock_client, monkeypatch):
    monkeypatch.setenv("ENABLE_QUERY_REWRITE", "false")
    get_settings.cache_clear()
    try:
        assert rewrite_query("那乙方呢？", HISTORY) == "那乙方呢？"
        mock_client.assert_not_called()
    finally:
        get_settings.cache_clear()


@patch("app.services.query_rewriter._client")
def test_malformed_history_falls_back(mock_client):
    """畸形 history 条目（缺 key）必须回落原句，而不是抛 KeyError。"""
    bad_history = [{"rolle": "user"}]  # typo key, no 'content'
    assert rewrite_query("那乙方呢？", bad_history) == "那乙方呢？"
