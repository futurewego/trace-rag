import hashlib
import logging
from contextlib import contextmanager

from sqlalchemy.orm import Session as SASession

from app.dependencies import _SessionLocal
from app.models import Chunk, Document
from app.services.chunker_service import Chunk as PageChunk
from app.services.chunker_service import chunk_page
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


def _chunk_units(parsed_units: list[dict]) -> list[tuple[PageChunk, dict]]:
    rows: list[tuple[PageChunk, dict]] = []
    for p in parsed_units:
        for ck in chunk_page(p["text"], page_num=p["page_num"]):
            rows.append((ck, p))
    return rows


def build_chunk_rows(
    chunked: list[tuple[PageChunk, dict]],
    vectors: list[list[float]],
    doc_id: int,
    source_mime: str | None,
) -> list[Chunk]:
    out: list[Chunk] = []
    for (ck, p), vec in zip(chunked, vectors, strict=True):
        out.append(
            Chunk(
                document_id=doc_id,
                chunk_index=ck.chunk_index,
                content=ck.content,
                page_num=ck.page_num,
                token_count=ck.token_count,
                embedding=vec,
                chunk_type=_KIND_TO_CHUNK_TYPE.get(p.get("kind"), "text"),
                content_hash=hashlib.sha256(ck.content.encode()).hexdigest(),
                parse_confidence=p.get("parse_confidence"),
                section_path=p.get("section_path"),
                is_latest=True,
                parent_chunk_id=None,
                knowledge_base_id=None,
                metadata_={"source_mime": source_mime, "kind": p.get("kind")},
            )
        )
    return out


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
        chunked = _chunk_units(parsed_units)

        if not chunked:
            with _db_scope() as db:
                doc = db.get(Document, doc_id)
                doc.status = "indexed"
                doc.page_count = len(parsed_units)
                doc.chunk_count = 0
            return

        contents = [ck.content for ck, _ in chunked]
        vectors = embed_texts(contents)
        rows = build_chunk_rows(chunked, vectors, doc_id, doc_mime)

        with _db_scope() as db:
            for row in rows:
                db.add(row)
            doc = db.get(Document, doc_id)
            doc.status = "indexed"
            doc.page_count = len(parsed_units)
            doc.chunk_count = len(rows)
    except Exception as e:
        logger.exception("ingest failed for doc %s", doc_id)
        with _db_scope() as db:
            doc = db.get(Document, doc_id)
            if doc:
                doc.status = "failed"
                doc.error_msg = str(e)[:1000]
