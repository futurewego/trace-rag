import hashlib

from app.services.chunker_service import Chunk as PageChunk
from app.services.ingestion_service import build_chunk_rows


def test_build_chunk_rows_maps_metadata():
    ck = PageChunk(chunk_index=0, content="合同编号 HT-2026-0087", page_num=3, token_count=6)
    unit = {"page_num": 3, "kind": "sheet", "parse_confidence": 0.95, "section_path": ["Sheet1"]}
    rows = build_chunk_rows([(ck, unit)], [[0.1] * 1536], doc_id=7, source_mime="application/pdf")

    assert len(rows) == 1
    r = rows[0]
    assert r.document_id == 7
    assert r.chunk_type == "table"            # sheet -> table
    assert r.parse_confidence == 0.95
    assert r.section_path == ["Sheet1"]
    assert r.is_latest is True
    assert r.parent_chunk_id is None
    assert r.knowledge_base_id is None
    assert r.content_hash == hashlib.sha256("合同编号 HT-2026-0087".encode()).hexdigest()


def test_build_chunk_rows_kind_defaults_to_text():
    ck = PageChunk(chunk_index=0, content="正文段落", page_num=1, token_count=2)
    unit = {"page_num": 1, "kind": "page", "parse_confidence": 0.9, "section_path": []}
    rows = build_chunk_rows([(ck, unit)], [[0.0] * 1536], doc_id=1, source_mime=None)
    assert rows[0].chunk_type == "text"
