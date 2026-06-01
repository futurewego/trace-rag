import hashlib
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_db
from app.models import Document

router = APIRouter()


class DocumentOut(BaseModel):
    id: int
    filename: str
    status: str
    error_msg: str | None
    page_count: int | None
    chunk_count: int

    model_config = {"from_attributes": True}


@router.post("/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Document:
    settings = get_settings()
    raw = file.file.read()
    file_hash = hashlib.sha256(raw).hexdigest()

    existing = db.query(Document).filter_by(file_hash=file_hash).first()
    if existing:
        return existing

    target_path: Path = settings.upload_dir / f"{file_hash}_{file.filename}"
    target_path.write_bytes(raw)

    doc = Document(
        filename=file.filename or "untitled",
        file_hash=file_hash,
        file_path=str(target_path),
        file_size=len(raw),
        mime_type=file.content_type,
        status="queued",
    )
    db.add(doc)
    db.flush()
    doc_id = doc.id

    from app.services.ingestion_service import ingest_document
    background_tasks.add_task(ingest_document, doc_id)

    return doc


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)) -> list[Document]:
    return db.query(Document).order_by(Document.created_at.desc()).all()


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return doc
