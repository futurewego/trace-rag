import hashlib

from app.services.ingestion_service import build_rows


def _unit(text, kind="page", page=1):
    return {
        "page_num": page, "text": text, "kind": kind,
        "parse_confidence": 0.9, "section_path": ["第一章"],
    }


def test_build_rows_links_children_to_parents():
    units = [_unit("\n\n".join("段落内容。" * 40 for _ in range(20)))]
    parents, child_pairs = build_rows(units, doc_id=7, source_mime="application/pdf")

    assert parents
    assert child_pairs
    for child, parent_idx in child_pairs:
        assert 0 <= parent_idx < len(parents)
        assert child.document_id == 7
        assert child.is_latest is True
        assert child.parse_confidence == 0.9
        assert child.section_path == ["第一章"]
        assert child.content_hash == hashlib.sha256(child.content.encode()).hexdigest()
        # 覆盖性：子块文本必在其父块内容中
        assert child.content in parents[parent_idx].content


def test_sheet_unit_marked_table():
    units = [_unit("列A\t列B\n值1\t值2", kind="sheet")]
    _parents, child_pairs = build_rows(units, doc_id=1, source_mime=None)
    assert child_pairs[0][0].chunk_type == "table"


def test_empty_units_produce_nothing():
    assert build_rows([], doc_id=1, source_mime=None) == ([], [])
