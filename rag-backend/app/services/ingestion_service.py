import logging
from contextlib import contextmanager

from sqlalchemy.orm import Session as SASession

from app.dependencies import _SessionLocal
from app.models import Chunk, Document
from app.services.chunker_service import chunk_page
from app.services.embedding_service import embed_texts
from app.services.parser_service import parse_pdf

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


def _get_path(doc_id: int) -> str:
    with _db_scope() as db:
        doc = db.get(Document, doc_id)
        return doc.file_path


def ingest_document(doc_id: int) -> None:
    """BackgroundTask 入口；后台执行解析→分块→嵌入→入库。"""
    with _db_scope() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            logger.error("doc %s not found", doc_id)
            return
        doc.status = "parsing"

    try:
        pages = parse_pdf(_get_path(doc_id))
        all_chunks = []
        for p in pages:
            all_chunks.extend(chunk_page(p.text, page_num=p.page_num))

        if not all_chunks:
            with _db_scope() as db:
                doc = db.get(Document, doc_id)
                doc.status = "indexed"
                doc.page_count = len(pages)
                doc.chunk_count = 0
            return

        contents = [c.content for c in all_chunks]
        vectors = embed_texts(contents)

        with _db_scope() as db:
            for ck, vec in zip(all_chunks, vectors, strict=True):
                db.add(
                    Chunk(
                        document_id=doc_id,
                        chunk_index=ck.chunk_index,
                        content=ck.content,
                        page_num=ck.page_num,
                        token_count=ck.token_count,
                        embedding=vec,
                        metadata_={"source": "pdf"},
                    )
                )
            doc = db.get(Document, doc_id)
            doc.status = "indexed"
            doc.page_count = len(pages)
            doc.chunk_count = len(all_chunks)
    except Exception as e:
        logger.exception("ingest failed for doc %s", doc_id)
        with _db_scope() as db:
            doc = db.get(Document, doc_id)
            if doc:
                doc.status = "failed"
                doc.error_msg = str(e)[:1000]
