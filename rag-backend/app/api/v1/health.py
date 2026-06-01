from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


async def _check_postgres() -> dict:
    start = time.monotonic()
    try:
        from app.dependencies import get_db_session
        async for session in get_db_session():
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
            break
        return {"status": "ok", "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"status": "down", "error": str(e)[:100]}


async def _check_redis() -> dict:
    start = time.monotonic()
    try:
        from app.dependencies import get_redis
        r = await get_redis()
        await r.ping()
        return {"status": "ok", "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"status": "down", "error": str(e)[:100]}


async def _check_qdrant() -> dict:
    start = time.monotonic()
    try:
        from app.dependencies import get_qdrant_client
        client = await get_qdrant_client()
        await client.get_collections()
        return {"status": "ok", "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"status": "down", "error": str(e)[:100]}


async def _check_openai() -> dict:
    start = time.monotonic()
    try:
        import openai
        from app.config import get_settings
        settings = get_settings()
        if not settings.openai_api_key:
            return {"status": "unconfigured"}
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        await client.models.list()
        return {"status": "ok", "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"status": "degraded", "error": str(e)[:100]}


async def _check_anthropic() -> dict:
    start = time.monotonic()
    try:
        import anthropic
        from app.config import get_settings
        settings = get_settings()
        if not settings.anthropic_api_key:
            return {"status": "unconfigured"}
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        await client.models.list()
        return {"status": "ok", "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"status": "degraded", "error": str(e)[:100]}


@router.get("/health")
async def health_check():
    """并发探测所有组件健康状态"""
    results = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_qdrant(),
        _check_openai(),
        _check_anthropic(),
        return_exceptions=True,
    )
    labels = ["postgres", "redis", "qdrant", "openai", "anthropic"]
    components = {}
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            components[label] = {"status": "down", "error": str(result)[:100]}
        else:
            components[label] = result

    # 计算整体状态
    statuses = [c.get("status", "down") for c in components.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
        http_status = 200
    elif any(s == "down" for s in statuses):
        overall = "degraded"
        http_status = 200  # 仍然返回 200，让调用方根据 status 字段判断
    else:
        overall = "degraded"
        http_status = 200

    return JSONResponse(
        status_code=http_status,
        content={
            "status": overall,
            "components": components,
        },
    )


@router.get("/health/live")
async def liveness():
    """K8s liveness probe - 只检查进程是否存活"""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness():
    """K8s readiness probe - 检查核心依赖是否就绪"""
    pg = await _check_postgres()
    if pg.get("status") != "ok":
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "postgres_down"})
    return {"status": "ready"}
