import logging
from dataclasses import dataclass
from functools import lru_cache

import cohere
from sqlalchemy import Select, func, select
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
    section_path: list[str] | None = None
    parent_chunk_id: int | None = None
    embedding: list[float] | None = None


@lru_cache
def _cohere_client():
    return cohere.ClientV2(api_key=get_settings().cohere_api_key)


def _candidates_stmt(q_vec: list[float], limit: int) -> Select:
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page_num,
            Chunk.content,
            Chunk.section_path,
            Chunk.parent_chunk_id,
            Chunk.embedding,
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
            section_path=r.section_path,
            parent_chunk_id=r.parent_chunk_id,
            embedding=list(r.embedding) if r.embedding is not None else None,
        )
        for r in rows
    ]


# NOTE: this expression must stay byte-identical to the one in migration 004's
# `CREATE INDEX ... USING gin (to_tsvector('zh', content))`, otherwise Postgres
# will not use the GIN index.
def _zh_tsvector():
    return func.to_tsvector("zh", Chunk.content)


def _sparse_stmt(query: str, limit: int) -> Select:
    tsq = func.plainto_tsquery("zh", query)
    tsv = _zh_tsvector()
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page_num,
            Chunk.content,
            Chunk.section_path,
            Chunk.parent_chunk_id,
            Chunk.embedding,
            func.ts_rank(tsv, tsq).label("score"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.is_latest)
        .where(tsv.op("@@")(tsq))
        .order_by(func.ts_rank(tsv, tsq).desc())
        .limit(limit)
    )


def _sparse_candidates(
    db: Session, query: str, limit: int
) -> list[RetrievedChunk]:
    """zhparser 词面召回。无匹配时返回 []（RRF 会退化为纯稠密）。"""
    rows = db.execute(_sparse_stmt(query, limit)).all()
    return [
        RetrievedChunk(
            chunk_id=r.id,
            doc_id=r.document_id,
            filename=r.filename,
            page_num=r.page_num,
            content=r.content,
            score=float(r.score),
            section_path=r.section_path,
            parent_chunk_id=r.parent_chunk_id,
            embedding=list(r.embedding) if r.embedding is not None else None,
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
                section_path=original.section_path,
                parent_chunk_id=original.parent_chunk_id,
                embedding=original.embedding,
            )
        )
    return out


def _apply_threshold(
    chunks: list[RetrievedChunk], min_score: float
) -> list[RetrievedChunk]:
    """低于阈值一律丢弃；可以返回空（由调用方触发无据拒答）。"""
    return [c for c in chunks if c.score >= min_score]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _dedup_by_embedding(
    chunks: list[RetrievedChunk], threshold: float
) -> list[RetrievedChunk]:
    """近重复去重：向量余弦 >= threshold 视为重复，保留先出现（分数更高）的那个。

    用 embedding 而非分词 Jaccard —— 中文无空格，分词 Jaccard 不可用。
    """
    kept: list[RetrievedChunk] = []
    for c in chunks:
        if c.embedding is None:
            kept.append(c)
            continue
        if any(
            k.embedding is not None and _cosine(c.embedding, k.embedding) >= threshold
            for k in kept
        ):
            continue
        kept.append(c)
    return kept


def retrieve(db: Session, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    settings = get_settings()
    top_k = top_k or settings.top_k

    q_vec = embed_query(query)

    # If Cohere is configured, oversample → rerank; else pure cosine
    use_rerank = bool(settings.cohere_api_key)
    candidate_n = settings.retrieval_candidate_k if use_rerank else top_k
    candidates = _cosine_candidates(db, q_vec, limit=candidate_n)

    reranked = False
    if use_rerank and len(candidates) > top_k:
        try:
            candidates = _rerank_with_cohere(query, candidates, top_n=candidate_n)
            reranked = True
        except Exception as e:
            logger.warning("cohere rerank failed, fallback to cosine: %s", e)

    # rerank_min_score is calibrated for Cohere relevance (0..1), NOT for raw
    # cosine (text-embedding-3-small on Chinese scores far lower). Apply the hard
    # relevance threshold only when rerank actually produced the scores, so a
    # pure-cosine (no COHERE_API_KEY) or rerank-failed path keeps P1a's top_k
    # behaviour instead of over-refusing.
    if reranked:
        candidates = _apply_threshold(candidates, settings.rerank_min_score)
    candidates = _dedup_by_embedding(candidates, settings.dedup_cosine_threshold)
    return candidates[:top_k]
