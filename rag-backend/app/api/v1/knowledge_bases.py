from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.dependencies import DBSession
from app.models.knowledge_base import KnowledgeBase
from app.core.exceptions import KnowledgeBaseNotFoundError

router = APIRouter()


@router.get("")
async def list_knowledge_bases(db: DBSession, skip: int = 0, limit: int = 20) -> list[dict[str, Any]]:
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.status == "active").offset(skip).limit(limit)
    )
    kbs = result.scalars().all()
    return [
        {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "status": kb.status,
            "config": kb.config,
            "created_at": kb.created_at.isoformat(),
        }
        for kb in kbs
    ]


@router.post("", status_code=201)
async def create_knowledge_base(body: dict[str, Any], db: DBSession) -> dict[str, Any]:
    kb = KnowledgeBase(
        name=body["name"],
        description=body.get("description"),
        config=body.get("config", {}),
    )
    db.add(kb)
    await db.flush()
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "status": kb.status,
        "config": kb.config,
        "created_at": kb.created_at.isoformat(),
    }


@router.get("/{kb_id}")
async def get_knowledge_base(kb_id: uuid.UUID, db: DBSession) -> dict[str, Any]:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or kb.status == "archived":
        raise KnowledgeBaseNotFoundError(str(kb_id))
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "status": kb.status,
        "config": kb.config,
        "created_at": kb.created_at.isoformat(),
        "updated_at": kb.updated_at.isoformat(),
    }


@router.patch("/{kb_id}")
async def update_knowledge_base(
    kb_id: uuid.UUID, body: dict[str, Any], db: DBSession
) -> dict[str, Any]:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or kb.status == "archived":
        raise KnowledgeBaseNotFoundError(str(kb_id))
    if "name" in body:
        kb.name = body["name"]
    if "description" in body:
        kb.description = body["description"]
    if "config" in body:
        kb.config = {**kb.config, **body["config"]}
    await db.flush()
    return {"id": str(kb.id), "name": kb.name, "status": kb.status}


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(kb_id: uuid.UUID, db: DBSession) -> None:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise KnowledgeBaseNotFoundError(str(kb_id))
    kb.status = "archived"
    await db.flush()
