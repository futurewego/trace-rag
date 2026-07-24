import hashlib
import logging
from contextlib import contextmanager

from sqlalchemy.orm import Session as SASession

from app.dependencies import _SessionLocal
from app.models import Chunk, Document, ParentChunk
from app.services.chunker_service import chunk_unit
from app.services.embedding_service import embed_texts
from app.services.parser_service import parse

logger = logging.getLogger(__name__)


@contextmanager
def _db_scope():
    db: SASession = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_KIND_TO_CHUNK_TYPE = {"page": "text", "section": "text", "slide": "text", "sheet": "table"}


def build_rows(
    parsed_units: list[dict],
    doc_id: int,
    source_mime: str | None,
) -> tuple[list[ParentChunk], list[tuple[Chunk, int]]]:
    """返回 (父块行, [(子块行, 父块下标)])。子块尚未带 embedding/parent_chunk_id。"""
    parents: list[ParentChunk] = []
    child_pairs: list[tuple[Chunk, int]] = []
    idx = 0
    for p in parsed_units:
        chunk_type = _KIND_TO_CHUNK_TYPE.get(p.get("kind"), "text")
        for group in chunk_unit(p["text"], p["page_num"], chunk_type=chunk_type):
            parents.append(
                ParentChunk(
                    document_id=doc_id,
                    content=group.content,
                    section_path=p.get("section_path"),
                    page_num=group.page_num,
                    token_count=group.token_count,
                )
            )
            parent_idx = len(parents) - 1
            for child in group.children:
                child_pairs.append((
                    Chunk(
                        document_id=doc_id,
                        chunk_index=idx,
                        content=child.content,
                        page_num=child.page_num,
                        token_count=child.token_count,
                        chunk_type=chunk_type,
                        content_hash=hashlib.sha256(child.content.encode()).hexdigest(),
                        parse_confidence=p.get("parse_confidence"),
                        section_path=p.get("section_path"),
                        is_latest=True,
                        knowledge_base_id=None,
                        metadata_={"source_mime": source_mime, "kind": p.get("kind")},
                    ),
                    parent_idx,
                ))
                idx += 1
    return parents, child_pairs


def ingest_document(doc_id: int) -> None:
    """BackgroundTask 入口；后台执行解析→分块→嵌入→入库。"""
    with _db_scope() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            logger.error("doc %s not found", doc_id)
            return
        doc.status = "parsing"
        doc_path = doc.file_path
        doc_mime = doc.mime_type
        doc_filename = doc.filename

    try:
        parsed_units = parse(doc_path, mime_type=doc_mime, filename=doc_filename)
        parents, child_pairs = build_rows(parsed_units, doc_id, doc_mime)

        if not child_pairs:
            with _db_scope() as db:
                doc = db.get(Document, doc_id)
                doc.status = "indexed"
                doc.page_count = len(parsed_units)
                doc.chunk_count = 0
            return

        vectors = embed_texts([c.content for c, _ in child_pairs])

        with _db_scope() as db:
            for parent in parents:
                db.add(parent)
            db.flush()  # 拿到父块自增 id
            for (child, parent_idx), vec in zip(child_pairs, vectors, strict=True):
                child.embedding = vec
                child.parent_chunk_id = parents[parent_idx].id
                db.add(child)
            doc = db.get(Document, doc_id)
            doc.status = "indexed"
            doc.page_count = len(parsed_units)
            doc.chunk_count = len(child_pairs)
    except Exception as e:
        logger.exception("ingest failed for doc %s", doc_id)
        with _db_scope() as db:
            doc = db.get(Document, doc_id)
            if doc:
                doc.status = "failed"
                doc.error_msg = str(e)[:1000]
