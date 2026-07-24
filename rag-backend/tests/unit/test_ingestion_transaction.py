"""覆盖 ingest_document 的事务时序：parent flush→backfill 以及 OCR 全失败路径。

这两条路径是 P2a Task 3 review 中标出的覆盖缺口——之前只有纯函数 build_rows 被测过，
ingest_document 本身（含 db.flush() 拿自增 id 再回填 child.parent_chunk_id 的时序）
完全没有测试执行到。用一个 MagicMock session 模拟 SQLAlchemy 的自增 id 分配，
不接真实数据库。
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models import Chunk, Document, ParentChunk
from app.services.ingestion_service import ingest_document
from app.services.ocr_service import OcrError


def _make_long_text(n_paragraphs: int) -> str:
    """生成 n 个独立段落（每段 ~110 token），足以让 chunk_unit 切出多个父块，
    每个父块又含多个子块（child_chunk_tokens=200, parent_chunk_tokens=800）。
    """
    paragraphs = [
        f"第{i}段内容。这是用于测试的重复文本内容片段，编号{i}。" * 5 for i in range(n_paragraphs)
    ]
    return "\n\n".join(paragraphs)


def _make_session(fake_doc: MagicMock) -> tuple[MagicMock, list]:
    """构造一个吸收 commit/rollback/close 的 MagicMock session，并记录
    session.add(...) 的调用顺序；session.flush() 模拟数据库分配自增 id。
    """
    added: list = []
    session = MagicMock()
    session.add.side_effect = added.append
    session.get.return_value = fake_doc

    id_counter = iter(range(1, 100_000))

    def _fake_flush() -> None:
        for obj in added:
            if isinstance(obj, ParentChunk) and obj.id is None:
                obj.id = next(id_counter)

    session.flush.side_effect = _fake_flush
    return session, added


def _make_fake_doc() -> MagicMock:
    doc = MagicMock(spec=Document)
    doc.file_path = "/tmp/fake.pdf"
    doc.mime_type = "application/pdf"
    doc.filename = "fake.pdf"
    return doc


def test_ingest_document_backfills_parent_id_after_flush() -> None:
    """回归防护：如果生产代码在 flush() 之前读取 parents[idx].id（全是 None），
    这条测试必须失败——它是本次覆盖缺口要补的核心场景。
    """
    fake_doc = _make_fake_doc()
    session, added = _make_session(fake_doc)

    text = _make_long_text(10)
    parsed_units = [
        {
            "page_num": 1,
            "text": text,
            "kind": "page",
            "parse_confidence": 0.87,
            "section_path": ["第一章"],
        }
    ]

    with (
        patch("app.services.ingestion_service._SessionLocal", return_value=session),
        patch("app.services.ingestion_service.parse", return_value=parsed_units) as mock_parse,
        patch("app.services.ingestion_service.embed_texts") as mock_embed,
    ):
        mock_embed.side_effect = lambda texts: [[float(i)] * 4 for i in range(len(texts))]

        ingest_document(doc_id=42)

        mock_parse.assert_called_once()
        mock_embed.assert_called_once()

    added_parents = [o for o in added if isinstance(o, ParentChunk)]
    added_children = [o for o in added if isinstance(o, Chunk)]

    # 至少 2 个父块，每个父块至少 2 个子块——否则下标错位/None 都可能巧合通过。
    assert len(added_parents) >= 2
    parent_child_counts: dict[int, int] = {}
    for child in added_children:
        parent_child_counts[child.parent_chunk_id] = (
            parent_child_counts.get(child.parent_chunk_id, 0) + 1
        )
    assert len(parent_child_counts) >= 2
    assert all(count >= 2 for count in parent_child_counts.values())

    # 1) 每个 child 的 parent_chunk_id 都不是 None —— flush-before-read 的核心断言。
    assert all(child.parent_chunk_id is not None for child in added_children)

    # 2) parent_chunk_id 必须指向一个真实被 add 过的 ParentChunk，且内容归属正确。
    parents_by_id = {p.id: p for p in added_parents}
    assert len(parents_by_id) == len(added_parents)  # id 两两不同
    for child in added_children:
        assert child.parent_chunk_id in parents_by_id
        owning_parent = parents_by_id[child.parent_chunk_id]
        assert child.content in owning_parent.content

    # 3) flush 确实被调用过；且第一个 ParentChunk 的 add 发生在第一个 Chunk 的 add 之前。
    session.flush.assert_called()
    first_parent_pos = next(i for i, o in enumerate(added) if isinstance(o, ParentChunk))
    first_child_pos = next(i for i, o in enumerate(added) if isinstance(o, Chunk))
    assert first_parent_pos < first_child_pos

    # 4) embedding 与子块一一对应，不能错位/洗牌——按 add 顺序（等于 embed_texts 输入顺序）核对。
    assert [c.embedding for c in added_children] == [
        [float(i)] * 4 for i in range(len(added_children))
    ]

    # 5) ParentChunk 上不应该被塞 embedding（该模型压根没有这个列）。
    for parent in added_parents:
        assert not hasattr(parent, "embedding")

    # 6) 文档最终状态：indexed，chunk_count 等于子块数。
    assert fake_doc.status == "indexed"
    assert fake_doc.chunk_count == len(added_children)
    assert fake_doc.page_count == len(parsed_units)


def test_ingest_document_marks_failed_when_ocr_fully_fails() -> None:
    """M3 保证：整份文档 OCR 全失败时必须落库为 failed + error_msg，不能被静默当作成功。"""
    fake_doc = _make_fake_doc()
    session, _added = _make_session(fake_doc)

    with (
        patch("app.services.ingestion_service._SessionLocal", return_value=session),
        patch(
            "app.services.ingestion_service.parse",
            side_effect=OcrError("all scanned pages failed OCR"),
        ),
        patch("app.services.ingestion_service.embed_texts") as mock_embed,
    ):
        ingest_document(doc_id=99)
        mock_embed.assert_not_called()

    assert fake_doc.status == "failed"
    assert fake_doc.error_msg
    assert "OCR" in fake_doc.error_msg


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
