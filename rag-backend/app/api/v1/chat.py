import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.dependencies import _SessionLocal, get_db
from app.models import Message, RetrievalLog
from app.models import Session as ChatSession
from app.schemas.citation import Citation
from app.services.context_service import assemble_context
from app.services.generation_service import (
    generate_answer,
    generate_answer_stream,
    is_low_confidence,
)
from app.services.history_service import get_history
from app.services.query_rewriter import rewrite_query
from app.services.retrieval_service import retrieve

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: int | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: int
    answer: str
    citations: list[Citation]


def _get_or_create_session(db: Session, req: ChatRequest) -> ChatSession:
    if req.session_id:
        session = db.get(ChatSession, req.session_id)
        if session is None:
            raise HTTPException(404, "session not found")
        return session
    session = ChatSession(title=req.message[:50])
    db.add(session)
    db.flush()
    return session


def _build_retrieval_log_payload(retrieved):
    return [
        {
            "chunk_id": r.chunk_id,
            "doc": r.filename,
            "page": r.page_num,
            "score": r.score,
        }
        for r in retrieved
    ]


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    session = _get_or_create_session(db, req)
    settings = get_settings()
    history = get_history(
        db, session.id, settings.history_max_turns, settings.history_content_max_chars
    )
    db.add(Message(session_id=session.id, role="user", content=req.message))
    db.flush()

    search_query = rewrite_query(req.message, history)

    t0 = time.perf_counter()
    retrieved = retrieve(db, search_query)
    retrieval_ms = int((time.perf_counter() - t0) * 1000)

    blocks = assemble_context(db, retrieved)
    low_conf = is_low_confidence(retrieved)

    t1 = time.perf_counter()
    answer, citations = generate_answer(req.message, blocks, low_conf, history=history)
    generation_ms = int((time.perf_counter() - t1) * 1000)

    db.add(
        RetrievalLog(
            session_id=session.id,
            query=search_query,
            original_query=req.message,
            retrieved_chunks=_build_retrieval_log_payload(retrieved),
            chunks_sent_to_llm=len(blocks),
            total_tokens=sum(b.token_count for b in blocks),
            retrieval_latency_ms=retrieval_ms,
            generation_latency_ms=generation_ms,
        )
    )
    db.add(
        Message(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=[c.model_dump() for c in citations],
        )
    )

    return ChatResponse(session_id=session.id, answer=answer, citations=citations)


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, db: Session = Depends(get_db)):
    """SSE endpoint. Events: session / text / citations / done."""
    session = _get_or_create_session(db, req)
    settings = get_settings()
    history = get_history(
        db, session.id, settings.history_max_turns, settings.history_content_max_chars
    )
    db.add(Message(session_id=session.id, role="user", content=req.message))
    db.flush()

    search_query = rewrite_query(req.message, history)

    t0 = time.perf_counter()
    retrieved = retrieve(db, search_query)
    retrieval_ms = int((time.perf_counter() - t0) * 1000)

    blocks = assemble_context(db, retrieved)
    low_conf = is_low_confidence(retrieved)

    session_id = session.id
    user_message = req.message
    retrieval_payload = _build_retrieval_log_payload(retrieved)

    def event_gen():
        yield {"event": "session", "data": json.dumps({"session_id": session_id})}

        full_answer_parts: list[str] = []
        final_citations: list[Citation] = []

        t1 = time.perf_counter()
        try:
            for event_type, payload in generate_answer_stream(
                user_message, blocks, low_conf, history=history
            ):
                if event_type == "text":
                    full_answer_parts.append(payload)
                    yield {"event": "text", "data": json.dumps({"delta": payload})}
                elif event_type == "citations":
                    final_citations.extend(payload)
                    yield {
                        "event": "citations",
                        "data": json.dumps(
                            {"citations": [c.model_dump() for c in payload]}
                        ),
                    }
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)[:200]})}

        generation_ms = int((time.perf_counter() - t1) * 1000)
        yield {
            "event": "done",
            "data": json.dumps(
                {"retrieval_ms": retrieval_ms, "generation_ms": generation_ms}
            ),
        }

        # Persist in a separate session (the request-scoped one will be closed)
        full_answer = "".join(full_answer_parts)
        with _SessionLocal() as db2:
            db2.add(
                Message(
                    session_id=session_id,
                    role="assistant",
                    content=full_answer,
                    citations=[c.model_dump() for c in final_citations],
                )
            )
            db2.add(
                RetrievalLog(
                    session_id=session_id,
                    query=search_query,
                    original_query=user_message,
                    retrieved_chunks=retrieval_payload,
                    chunks_sent_to_llm=len(blocks),
                    total_tokens=sum(b.token_count for b in blocks),
                    retrieval_latency_ms=retrieval_ms,
                    generation_latency_ms=generation_ms,
                )
            )
            db2.commit()

    return EventSourceResponse(event_gen())
