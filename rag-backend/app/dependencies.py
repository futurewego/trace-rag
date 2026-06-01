from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings

# ── PostgreSQL ─────────────────────────────────────────────────────────────────

def _create_engine(settings: Settings):
    return create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        echo=False,
    )


def _create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    engine = _create_engine(settings)
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


# 模块级延迟初始化（main.py 的 lifespan 中调用 init_db）
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(settings: Settings) -> None:
    global _session_factory
    _session_factory = _create_session_factory(settings)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DBSession = Annotated[AsyncSession, Depends(get_db_session)]

# ── Redis ──────────────────────────────────────────────────────────────────────

_redis_pool: aioredis.ConnectionPool | None = None


def init_redis(settings: Settings) -> None:
    global _redis_pool
    _redis_pool = aioredis.ConnectionPool.from_url(
        settings.redis_url,
        max_connections=50,
        decode_responses=True,
    )


async def get_redis() -> aioredis.Redis:
    if _redis_pool is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return aioredis.Redis(connection_pool=_redis_pool)


RedisClient = Annotated[aioredis.Redis, Depends(get_redis)]

# ── Qdrant ─────────────────────────────────────────────────────────────────────

_qdrant_client: AsyncQdrantClient | None = None


def init_qdrant(settings: Settings) -> None:
    global _qdrant_client
    kwargs: dict = dict(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
    )
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    _qdrant_client = AsyncQdrantClient(**kwargs)


async def get_qdrant_client() -> AsyncQdrantClient:
    if _qdrant_client is None:
        raise RuntimeError("Qdrant not initialized. Call init_qdrant() first.")
    return _qdrant_client


QdrantClient = Annotated[AsyncQdrantClient, Depends(get_qdrant_client)]
