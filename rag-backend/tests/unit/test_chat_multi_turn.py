from unittest.mock import MagicMock, patch

import app.api.v1.chat as chat_mod
from app.api.v1.chat import ChatRequest, chat
from app.models import RetrievalLog

HISTORY = [{"role": "user", "content": "甲方是谁？"},
           {"role": "assistant", "content": "星曜科技 [1]。"}]


def _mock_db_with_session(session_id=7):
    db = MagicMock()
    fake_session = MagicMock()
    fake_session.id = session_id
    db.get.return_value = fake_session
    return db


@patch.object(chat_mod, "generate_answer", return_value=("答 [1]", []))
@patch.object(chat_mod, "is_low_confidence", return_value=False)
@patch.object(chat_mod, "assemble_context", return_value=[])
@patch.object(chat_mod, "retrieve", return_value=[])
@patch.object(chat_mod, "rewrite_query", return_value="HT-2026-0087 合同的乙方是谁")
@patch.object(chat_mod, "get_history", return_value=HISTORY)
def test_chat_uses_rewritten_for_retrieval_and_original_for_generation(
    mock_hist, mock_rw, mock_ret, mock_asm, mock_low, mock_gen
):
    db = _mock_db_with_session()
    chat(ChatRequest(session_id=7, message="那乙方呢？"), db)

    # 历史在写入当前问句之前读取
    assert mock_hist.call_args.args[1] == 7
    # 改写收到原句 + 历史
    mock_rw.assert_called_once_with("那乙方呢？", HISTORY)
    # 检索用改写后
    assert mock_ret.call_args.args[1] == "HT-2026-0087 合同的乙方是谁"
    # 生成用原句 + 历史
    gen_kwargs = mock_gen.call_args
    assert gen_kwargs.args[0] == "那乙方呢？"
    assert gen_kwargs.kwargs["history"] == HISTORY

    # RetrievalLog: query=改写后, original_query=原句
    logs = [c.args[0] for c in db.add.call_args_list
            if isinstance(c.args[0], RetrievalLog)]
    assert len(logs) == 1
    assert logs[0].query == "HT-2026-0087 合同的乙方是谁"
    assert logs[0].original_query == "那乙方呢？"


@patch.object(chat_mod, "generate_answer", return_value=("答", []))
@patch.object(chat_mod, "is_low_confidence", return_value=False)
@patch.object(chat_mod, "assemble_context", return_value=[])
@patch.object(chat_mod, "retrieve", return_value=[])
@patch.object(chat_mod, "rewrite_query", side_effect=lambda q, h: q)
@patch.object(chat_mod, "get_history", return_value=[])
def test_first_turn_behaves_like_before(
    mock_hist, mock_rw, mock_ret, mock_asm, mock_low, mock_gen
):
    db = _mock_db_with_session()
    chat(ChatRequest(session_id=7, message="甲方是谁？"), db)
    assert mock_ret.call_args.args[1] == "甲方是谁？"
    assert mock_gen.call_args.kwargs["history"] == []
