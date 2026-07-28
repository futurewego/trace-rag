from unittest.mock import MagicMock

import app.services.generation_service as gen_service
from app.services.context_service import ContextBlock
from app.services.generation_service import (
    _build_user_prompt,
    _map_citations,
    generate_answer,
    generate_answer_stream,
    is_low_confidence,
)
from app.services.retrieval_service import RetrievedChunk


def _blk(cid, content, page=3, sec=None, score=0.8, doc_id=1, filename="合同.pdf"):
    return ContextBlock(
        content=content, chunk_id=cid, doc_id=doc_id, filename=filename,
        page_num=page, section_path=sec, score=score, token_count=5,
    )


def _rc(score, cid=1, reranked=False):
    return RetrievedChunk(
        chunk_id=cid, doc_id=1, filename="a", page_num=1, content="c", score=score,
        reranked=reranked,
    )


# ---------------------------------------------------------------------------
# _build_user_prompt: section breadcrumbs
# ---------------------------------------------------------------------------


def test_prompt_includes_section_path_and_page():
    prompt = _build_user_prompt("甲方是谁？", [_blk(1, "甲方为星曜科技", sec=["第一章", "总则"])])
    assert "合同.pdf" in prompt
    assert "P3" in prompt
    assert "第一章 > 总则" in prompt
    assert "甲方为星曜科技" in prompt


def test_prompt_omits_missing_page_and_section():
    prompt = _build_user_prompt("问题", [_blk(1, "内容", page=None, sec=None)])
    header_line = prompt.splitlines()[1]
    assert header_line == "[文档1] 合同.pdf"


# ---------------------------------------------------------------------------
# is_low_confidence
# ---------------------------------------------------------------------------


def test_is_low_confidence_between_thresholds(monkeypatch):
    """低置信判定基于校准过的 rerank 分数：chunk 必须携带 reranked=True。
    仅设置 COHERE_API_KEY 已不足够 —— retrieve() 只有在实际调用 Cohere 重排
    成功时才会把 reranked 标记为 True。"""
    monkeypatch.setenv("COHERE_API_KEY", "test")
    gen_service.get_settings.cache_clear()
    try:
        assert is_low_confidence([_rc(0.5, reranked=True)]) is True
        assert is_low_confidence([_rc(0.9, reranked=True)]) is False
        assert is_low_confidence([]) is False
    finally:
        gen_service.get_settings.cache_clear()


def test_is_low_confidence_false_without_cohere(monkeypatch):
    """未启用 Cohere（纯余弦部署）时分数不可比，即便处于中间档也不判定为低置信。"""
    monkeypatch.setenv("COHERE_API_KEY", "")
    gen_service.get_settings.cache_clear()
    try:
        assert is_low_confidence([_rc(0.5)]) is False
    finally:
        gen_service.get_settings.cache_clear()


def test_is_low_confidence_false_for_rrf_scores_even_with_cohere_key(monkeypatch):
    """chunk.reranked=False（RRF 融合序或 rerank 失败降级）时，即便配置了
    COHERE_API_KEY，也不能仅凭 key 存在就判定分数已校准 —— RRF 分数量级
    ~0.0098，恒小于 low_confidence_score，若沿用旧的 proxy 逻辑会导致每次
    回答都被误标为低置信。"""
    monkeypatch.setenv("COHERE_API_KEY", "test")
    gen_service.get_settings.cache_clear()
    try:
        assert is_low_confidence([_rc(0.0098, reranked=False)]) is False
    finally:
        gen_service.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# _map_citations: maps back to the representative CHILD chunk, not the parent
# ---------------------------------------------------------------------------


def test_map_citations_maps_to_representative_child():
    blocks = [
        _blk(101, "父块扩展内容...", page=5, sec=["A"], score=0.91, doc_id=7, filename="x.pdf"),
    ]
    citations = _map_citations("回答内容 [1]", blocks)
    assert len(citations) == 1
    c = citations[0]
    assert c.chunk_id == 101
    assert c.doc_id == 7
    assert c.page_num == 5
    assert c.score == 0.91


# ---------------------------------------------------------------------------
# 无据拒答：no blocks must short-circuit WITHOUT ever touching the Anthropic
# client (constructing it OR calling it).
# ---------------------------------------------------------------------------


def _boom():
    raise AssertionError("Anthropic client must not be constructed when there are no blocks")


def test_generate_answer_no_blocks_short_circuits_without_client(monkeypatch):
    monkeypatch.setattr(gen_service, "_client", _boom)
    answer, citations = generate_answer("甲方是谁？", [])
    assert answer == "根据现有知识库无法回答这个问题。"
    assert citations == []


def test_generate_answer_stream_no_blocks_short_circuits_without_client(monkeypatch):
    monkeypatch.setattr(gen_service, "_client", _boom)
    events = list(generate_answer_stream("甲方是谁？", []))
    assert events[0] == ("text", "根据现有知识库无法回答这个问题。")
    assert events[1] == ("citations", [])


# ---------------------------------------------------------------------------
# Fake Anthropic client plumbing for the "has blocks" paths.
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]


class _FakeMessagesSync:
    def __init__(self, text):
        self._text = text

    def create(self, **kwargs):
        return _FakeResp(self._text)


class _FakeStreamCtx:
    def __init__(self, deltas):
        self._deltas = deltas

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(self._deltas)


class _FakeMessagesStream:
    def __init__(self, deltas):
        self._deltas = deltas

    def stream(self, **kwargs):
        return _FakeStreamCtx(self._deltas)


class _FakeSyncClient:
    def __init__(self, text):
        self.messages = _FakeMessagesSync(text)


class _FakeStreamClient:
    def __init__(self, deltas):
        self.messages = _FakeMessagesStream(deltas)


# ---------------------------------------------------------------------------
# generate_answer: low-confidence notice prefixed only when flagged
# ---------------------------------------------------------------------------


def test_generate_answer_low_confidence_prefixes_notice(monkeypatch):
    monkeypatch.setattr(gen_service, "_client", lambda: _FakeSyncClient("甲方为星曜科技 [1]"))
    blocks = [_blk(1, "甲方为星曜科技", sec=["第一章"])]

    answer, citations = generate_answer("甲方是谁？", blocks, low_confidence=True)

    assert answer.startswith("⚠️")
    assert "甲方为星曜科技 [1]" in answer
    assert citations[0].chunk_id == 1


def test_generate_answer_without_low_confidence_no_notice(monkeypatch):
    monkeypatch.setattr(gen_service, "_client", lambda: _FakeSyncClient("甲方为星曜科技 [1]"))
    blocks = [_blk(1, "甲方为星曜科技")]

    answer, _citations = generate_answer("甲方是谁？", blocks, low_confidence=False)

    assert not answer.startswith("⚠️")


# ---------------------------------------------------------------------------
# generate_answer_stream: low-confidence notice yielded first, protocol intact
# ---------------------------------------------------------------------------


def test_generate_answer_stream_low_confidence_yields_notice_first(monkeypatch):
    monkeypatch.setattr(
        gen_service, "_client", lambda: _FakeStreamClient(["回答内容 [1]"])
    )
    blocks = [_blk(1, "内容")]

    events = list(generate_answer_stream("问题", blocks, low_confidence=True))

    assert events[0] == ("text", gen_service.LOW_CONFIDENCE_NOTE)
    text_deltas = [payload for etype, payload in events if etype == "text"]
    assert "".join(text_deltas[1:]) == "回答内容 [1]"
    assert events[-1][0] == "citations"
    assert events[-1][1][0].chunk_id == 1


def test_generate_answer_stream_without_low_confidence_no_notice(monkeypatch):
    monkeypatch.setattr(gen_service, "_client", lambda: _FakeStreamClient(["回答"]))
    blocks = [_blk(1, "内容")]

    events = list(generate_answer_stream("问题", blocks, low_confidence=False))

    assert ("text", gen_service.LOW_CONFIDENCE_NOTE) not in events


# ---------------------------------------------------------------------------
# generate_answer: conversation history passed as native multi-turn messages
# ---------------------------------------------------------------------------


def test_generate_answer_passes_history_before_user_prompt(monkeypatch):
    import app.services.generation_service as gen

    captured = {}

    class _FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            resp = MagicMock()
            resp.content = [MagicMock(text="回答 [1]")]
            return resp

    fake = MagicMock()
    fake.messages = _FakeMessages()
    monkeypatch.setattr(gen, "_client", lambda: fake)

    history = [
        {"role": "user", "content": "甲方是谁？"},
        {"role": "assistant", "content": "星曜科技 [1]。"},
    ]
    blocks = [_blk(1, "乙方为黄河智能装备厂")]
    gen.generate_answer("那乙方呢？", blocks, history=history)

    msgs = captured["messages"]
    assert msgs[0] == {"role": "user", "content": "甲方是谁？"}
    assert msgs[1] == {"role": "assistant", "content": "星曜科技 [1]。"}
    assert msgs[-1]["role"] == "user"
    assert "那乙方呢？" in msgs[-1]["content"]
    assert "<context>" in msgs[-1]["content"]


def test_generate_answer_no_blocks_refuses_even_with_history(monkeypatch):
    import app.services.generation_service as gen

    def _boom():
        raise AssertionError("client must not be constructed")

    monkeypatch.setattr(gen, "_client", _boom)
    answer, cites = gen.generate_answer(
        "那乙方呢？", [], history=[{"role": "user", "content": "x"}]
    )
    assert answer == "根据现有知识库无法回答这个问题。"
    assert cites == []
