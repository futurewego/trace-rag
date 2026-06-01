from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception as e:  # noqa: BLE001
        return {"status": "degraded", "db": "down", "error": str(e)[:200]}


@router.get("/health/live")
def liveness() -> dict:
    return {"status": "ok"}
