from app.models import Chunk, Document, ParentChunk


def test_chunk_has_p1a_columns():
    cols = Chunk.__table__.columns
    for c in (
        "chunk_type", "section_path", "parse_confidence", "content_hash",
        "is_latest", "knowledge_base_id", "parent_chunk_id",
    ):
        assert c in cols, f"missing chunks.{c}"
    assert cols["chunk_type"].nullable is False
    assert cols["is_latest"].nullable is False
    assert cols["parse_confidence"].nullable is True
    assert cols["knowledge_base_id"].nullable is True


def test_document_has_versioning_columns():
    cols = Document.__table__.columns
    for c in ("doc_version", "is_latest", "doc_group_id", "knowledge_base_id"):
        assert c in cols, f"missing documents.{c}"
    assert cols["doc_version"].nullable is False
    assert cols["is_latest"].nullable is False


def test_parent_chunk_model():
    assert ParentChunk.__tablename__ == "parent_chunks"
    cols = ParentChunk.__table__.columns
    for c in ("id", "document_id", "content", "section_path", "page_num", "token_count", "created_at"):
        assert c in cols, f"missing parent_chunks.{c}"
