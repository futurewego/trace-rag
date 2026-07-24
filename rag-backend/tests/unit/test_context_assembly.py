"""上下文组装测试。

除了 brief 里给的 `_order_and_budget` 三个用例外，额外补了 `assemble_context`
本身的用例——父块去重/代表子块选取、NULL 父块回落、父块查询失败/缺失时的回落、
以及「一条 SQL 取完所有父块」这几条是本任务的核心验收点，只测 `_order_and_budget`
覆盖不到。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.context_service import ContextBlock, _order_and_budget, assemble_context
from app.services.retrieval_service import RetrievedChunk


def _blk(cid, score, tokens, content="x"):
    return ContextBlock(
        content=content,
        chunk_id=cid,
        doc_id=1,
        filename="a.pdf",
        page_num=1,
        section_path=None,
        score=score,
        token_count=tokens,
    )


def _rc(cid, score, parent_id, content="子块内容", page_num=1, section_path=None):
    return RetrievedChunk(
        chunk_id=cid,
        doc_id=1,
        filename="a.pdf",
        page_num=page_num,
        content=content,
        score=score,
        section_path=section_path,
        parent_chunk_id=parent_id,
    )


def _mock_db(parent_rows):
    """parent_rows: list[(id, content)]；返回一个记录 execute 调用次数的 MagicMock session。"""
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        SimpleNamespace(id=pid, content=content) for pid, content in parent_rows
    ]
    return db


def test_highest_score_goes_last_lost_in_the_middle():
    ordered = _order_and_budget([_blk(1, 0.9, 10), _blk(2, 0.5, 10), _blk(3, 0.7, 10)], 1000)
    assert [b.chunk_id for b in ordered] == [2, 3, 1]


def test_token_budget_drops_lowest_scoring_first():
    """预算不足时先丢最不相关的，保留高分块。"""
    ordered = _order_and_budget([_blk(1, 0.9, 100), _blk(2, 0.5, 100), _blk(3, 0.7, 100)], 250)
    assert [b.chunk_id for b in ordered] == [3, 1]


def test_empty_input_returns_empty():
    assert _order_and_budget([], 100) == []


def test_assemble_context_empty_chunks_returns_empty_without_db_hit():
    db = MagicMock()
    assert assemble_context(db, []) == []
    db.execute.assert_not_called()


def test_assemble_context_dedupes_parent_and_keeps_best_child_as_representative():
    """两个子块共享同一父块 -> 只产出一个块；代表子块是该父块下分数最高的那个，
    block.content 用父块内容（不是任一子块内容）。"""
    db = _mock_db([(100, "父块完整内容")])
    chunks = [
        _rc(cid=1, score=0.4, parent_id=100, content="子块A"),
        _rc(cid=2, score=0.9, parent_id=100, content="子块B"),  # 应作为代表
    ]

    blocks = assemble_context(db, chunks)

    assert len(blocks) == 1
    assert blocks[0].chunk_id == 2  # 高分子块代表整个父块
    assert blocks[0].content == "父块完整内容"
    assert blocks[0].score == 0.9
    # page_num / section_path 必须来自子块本身（父块可能跨页），不是父块的。
    assert blocks[0].page_num == chunks[1].page_num


def test_assemble_context_distinct_parents_each_produce_one_block():
    db = _mock_db([(100, "父块1"), (200, "父块2")])
    chunks = [_rc(cid=1, score=0.4, parent_id=100), _rc(cid=2, score=0.9, parent_id=200)]

    blocks = assemble_context(db, chunks)

    assert {b.chunk_id for b in blocks} == {1, 2}
    assert len(blocks) == 2


def test_assemble_context_null_parent_falls_back_to_child_content_and_survives():
    """P2a 之前摄入的旧数据 parent_chunk_id=NULL：必须回落到子块自身内容，且不能被丢弃。"""
    db = _mock_db([])  # 没有任何父块需要查
    chunks = [_rc(cid=7, score=0.6, parent_id=None, content="旧数据子块内容")]

    blocks = assemble_context(db, chunks)

    assert len(blocks) == 1
    assert blocks[0].chunk_id == 7
    assert blocks[0].content == "旧数据子块内容"
    # 没有任何 parent_id 需要查询时不应该发起父块查询。
    db.execute.assert_not_called()


def test_assemble_context_missing_parent_row_degrades_to_child_content():
    """parent_chunk_id 非空但查询不到该父块（已删/查询失败上游已兜底成空结果）时，
    必须和 NULL 父块一样回落到子块内容，而不是丢弃这个块。"""
    db = _mock_db([])  # 父块 id=999 查不到任何行
    chunks = [_rc(cid=8, score=0.5, parent_id=999, content="子块兜底内容")]

    blocks = assemble_context(db, chunks)

    assert len(blocks) == 1
    assert blocks[0].chunk_id == 8
    assert blocks[0].content == "子块兜底内容"


def test_assemble_context_fetches_all_parents_in_one_query():
    """多个不同父块必须一条 SQL（一次 db.execute）取完，不能逐子块查询。"""
    db = _mock_db([(100, "父块1"), (200, "父块2"), (300, "父块3")])
    chunks = [
        _rc(cid=1, score=0.4, parent_id=100),
        _rc(cid=2, score=0.5, parent_id=100),  # 同一父块的第二个子块，不应触发额外查询
        _rc(cid=3, score=0.6, parent_id=200),
        _rc(cid=4, score=0.7, parent_id=300),
    ]

    assemble_context(db, chunks)

    assert db.execute.call_count == 1


def test_assemble_context_orders_and_budgets_result():
    """assemble_context 的输出要经过 _order_and_budget：验证端到端也遵守 LiM 排序。"""
    db = _mock_db([(100, "父块1"), (200, "父块2")])
    chunks = [_rc(cid=1, score=0.9, parent_id=100), _rc(cid=2, score=0.3, parent_id=200)]

    blocks = assemble_context(db, chunks)

    assert [b.chunk_id for b in blocks] == [2, 1]  # 低分先出现，最高分放最后
