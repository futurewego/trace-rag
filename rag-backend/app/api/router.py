from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api")

# v1 路由（各模块实现后逐步注册）
from app.api.v1 import health, knowledge_bases

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health.router, tags=["Health"])
v1_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["Knowledge Bases"])

router.include_router(v1_router)
