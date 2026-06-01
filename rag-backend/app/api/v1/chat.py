from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Message
from app.models import Session as ChatSession
from app.schemas.citation import Citation
from app.services.generation_service import generate_answer
from app.services.retrieval_service import retrieve

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: int | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: int
    answer: str
    citations: list[Citation]


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    if req.session_id:
        session = db.get(ChatSession, req.session_id)
        if session is None:
            raise HTTPException(404, "session not found")
    else:
        session = ChatSession(title=req.message[:50])
        db.add(session)
        db.flush()

    db.add(Message(session_id=session.id, role="user", content=req.message))
    db.flush()

    retrieved = retrieve(db, req.message)
    answer, citations = generate_answer(req.message, retrieved)

    db.add(
        Message(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=[c.model_dump() for c in citations],
        )
    )

    return ChatResponse(session_id=session.id, answer=answer, citations=citations)
