import logging
from dataclasses import dataclass
from functools import lru_cache

import cohere
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document
from app.services.embedding_service import embed_query

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: int
    doc_id: int
    filename: str
    page_num: int | None
    content: str
    score: float  # cosine similarity OR rerank relevance (depends on path)


@lru_cache
def _cohere_client():
    return cohere.ClientV2(api_key=get_settings().cohere_api_key)


def _candidates_stmt(q_vec: list[float], limit: int):
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page_num,
            Chunk.content,
            (1 - Chunk.embedding.cosine_distance(q_vec)).label("score"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.is_latest)
        .order_by(Chunk.embedding.cosine_distance(q_vec))
        .limit(limit)
    )


def _cosine_candidates(
    db: Session, q_vec: list[float], limit: int
) -> list[RetrievedChunk]:
    stmt = _candidates_stmt(q_vec, limit)
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


def _rerank_with_cohere(
    query: str, candidates: list[RetrievedChunk], top_n: int
) -> list[RetrievedChunk]:
    settings = get_settings()
    resp = _cohere_client().rerank(
        model=settings.cohere_rerank_model,
        query=query,
        documents=[c.content for c in candidates],
        top_n=top_n,
    )
    out: list[RetrievedChunk] = []
    for r in resp.results:
        original = candidates[r.index]
        out.append(
            RetrievedChunk(
                chunk_id=original.chunk_id,
                doc_id=original.doc_id,
                filename=original.filename,
                page_num=original.page_num,
                content=original.content,
                score=float(r.relevance_score),
            )
        )
    return out


def retrieve(db: Session, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    settings = get_settings()
    top_k = top_k or settings.top_k

    q_vec = embed_query(query)

    # If Cohere is configured, oversample → rerank; else pure cosine
    use_rerank = bool(settings.cohere_api_key)
    candidate_n = settings.retrieval_candidate_k if use_rerank else top_k
    candidates = _cosine_candidates(db, q_vec, limit=candidate_n)

    if not use_rerank or len(candidates) <= top_k:
        return candidates[:top_k]

    try:
        return _rerank_with_cohere(query, candidates, top_n=top_k)
    except Exception as e:
        logger.warning("cohere rerank failed, fallback to cosine: %s", e)
        return candidates[:top_k]
