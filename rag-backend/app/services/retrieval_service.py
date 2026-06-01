from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document
from app.services.embedding_service import embed_query


@dataclass
class RetrievedChunk:
    chunk_id: int
    doc_id: int
    filename: str
    page_num: int | None
    content: str
    score: float  # 余弦相似度，越大越相关


def retrieve(db: Session, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    top_k = top_k or get_settings().top_k
    q_vec = embed_query(query)

    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page_num,
            Chunk.content,
            (1 - Chunk.embedding.cosine_distance(q_vec)).label("score"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .order_by(Chunk.embedding.cosine_distance(q_vec))
        .limit(top_k)
    )
    rows = db.execute(stmt).all()
    return [
        RetrievedChunk(
            chunk_id=r.id,
            doc_id=r.document_id,
            filename=r.filename,
            page_num=r.page_num,
            content=r.content,
            score=float(r.score),
        )
        for r in rows
    ]
