import asyncio
from unittest.mock import MagicMock, patch

import app.api.v1.chat as chat_mod
from app.api.v1.chat import ChatRequest, chat
from app.models import Message, RetrievalLog

HISTORY = [{"role": "user", "content": "甲方是谁？"},
           {"role": "assistant", "content": "星曜科技 [1]。"}]


def _mock_db_with_session(session_id=7):
    db = MagicMock()
    fake_session = MagicMock()
    fake_session.id = session_id
    db.get.return_value = fake_session
    return db


def _drain_sse(body_iterator):
    """Drain an EventSourceResponse's body_iterator synchronously.

    chat_stream's event_gen is a plain *sync* generator, so sse_starlette
    (via starlette.concurrency.iterate_in_threadpool) wraps it into an async
    generator rather than storing it as-is. Running it to completion on a
    throwaway event loop is what actually executes the generator body past
    its final `yield` — including the db2 persistence block.
    """

    async def _consume():
        return [event async for event in body_iterator]

    return asyncio.run(_consume())


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


@patch.object(chat_mod, "_SessionLocal")
@patch.object(chat_mod, "generate_answer_stream")
@patch.object(chat_mod, "is_low_confidence", return_value=False)
@patch.object(chat_mod, "assemble_context", return_value=[])
@patch.object(chat_mod, "retrieve", return_value=[])
@patch.object(chat_mod, "rewrite_query", return_value="HT-2026-0087 合同的乙方是谁")
@patch.object(chat_mod, "get_history", return_value=HISTORY)
def test_chat_stream_uses_rewritten_for_retrieval_and_original_for_generation(
    mock_hist, mock_rw, mock_ret, mock_asm, mock_low, mock_gen_stream, mock_sessionlocal
):
    mock_gen_stream.return_value = iter([("text", "答"), ("citations", [])])
    db2 = MagicMock()
    mock_sessionlocal.return_value.__enter__.return_value = db2

    db = _mock_db_with_session()
    resp = chat_mod.chat_stream(ChatRequest(session_id=7, message="那乙方呢？"), db)

    # Drive the generator to completion; this is also where the SSE protocol
    # (event order) gets locked down.
    events = _drain_sse(resp.body_iterator)
    assert [e["event"] for e in events] == ["session", "text", "citations", "done"]

    # 改写收到原句 + 历史
    mock_rw.assert_called_once_with("那乙方呢？", HISTORY)
    # 检索用改写后
    assert mock_ret.call_args.args[1] == "HT-2026-0087 合同的乙方是谁"
    # 生成用原句 + 历史
    gen_call = mock_gen_stream.call_args
    assert gen_call.args[0] == "那乙方呢？"
    assert gen_call.kwargs["history"] == HISTORY

    # db2 persistence (separate session, after the request-scoped one closes):
    # RetrievalLog carries BOTH query fields.
    logs = [c.args[0] for c in db2.add.call_args_list
            if isinstance(c.args[0], RetrievalLog)]
    assert len(logs) == 1
    assert logs[0].query == "HT-2026-0087 合同的乙方是谁"
    assert logs[0].original_query == "那乙方呢？"


@patch.object(chat_mod, "_SessionLocal")
@patch.object(chat_mod, "generate_answer_stream")
@patch.object(chat_mod, "is_low_confidence", return_value=False)
@patch.object(chat_mod, "assemble_context", return_value=[])
@patch.object(chat_mod, "retrieve", return_value=[])
@patch.object(chat_mod, "rewrite_query", side_effect=lambda q, h: q)
@patch.object(chat_mod, "get_history", return_value=[])
def test_chat_stream_error_before_first_chunk_persists_no_empty_assistant(
    mock_hist, mock_rw, mock_ret, mock_asm, mock_low, mock_gen_stream, mock_sessionlocal
):
    """流在首个 chunk 前就抛错（如连接错误）：db2 不能写入空 assistant 消息——
    否则下一轮历史会被污染成孤儿 user 结尾，与追加的当前 user 连续同角色 -> 400，
    进而再产生一条空 assistant，会话永远无法自愈。RetrievalLog 仍应照常记录。"""

    def _raises_before_yield():
        raise RuntimeError("connection error")
        yield  # pragma: no cover - keeps this a generator function

    mock_gen_stream.return_value = _raises_before_yield()
    db2 = MagicMock()
    mock_sessionlocal.return_value.__enter__.return_value = db2

    db = _mock_db_with_session()
    resp = chat_mod.chat_stream(ChatRequest(session_id=7, message="问题"), db)
    events = _drain_sse(resp.body_iterator)
    assert [e["event"] for e in events] == ["session", "error", "done"]

    logs = [c.args[0] for c in db2.add.call_args_list
            if isinstance(c.args[0], RetrievalLog)]
    assert len(logs) == 1

    messages = [c.args[0] for c in db2.add.call_args_list
                if isinstance(c.args[0], Message)]
    assert messages == []
