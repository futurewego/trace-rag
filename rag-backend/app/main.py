from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.config import get_settings
from app.core.exceptions import RAGException, generic_exception_handler, rag_exception_handler
from app.dependencies import init_db, init_qdrant, init_redis
from app.observability.logger import bind_request_context, clear_request_context, configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """启动时初始化所有连接，关闭时清理"""
    settings = get_settings()
    configure_logging(settings.app_log_level)

    from app.observability.logger import get_logger
    logger = get_logger(__name__)

    logger.info("rag_system_starting", env=settings.app_env)

    # 初始化各连接
    init_db(settings)
    init_redis(settings)
    init_qdrant(settings)

    # 健康检查（确认基础设施可达）
    await _startup_health_check(settings)

    logger.info("rag_system_started")
    yield

    logger.info("rag_system_shutting_down")


async def _startup_health_check(settings) -> None:
    """启动时验证关键依赖可达，不可达打 warning 但不阻止启动（降级链会处理）"""
    from app.observability.logger import get_logger
    logger = get_logger(__name__)

    # 验证 Qdrant
    try:
        from app.dependencies import get_qdrant_client
        client = await get_qdrant_client()
        await client.get_collections()
        logger.info("startup_health_check_ok", service="qdrant")
    except Exception as e:
        logger.warning("startup_health_check_failed", service="qdrant", error=str(e))


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Enterprise RAG API",
        description="Enterprise Multimodal RAG System",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── 中间件 ────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        bind_request_context(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        clear_request_context()
        return response

    # ── 异常处理器 ─────────────────────────────────────────────────────────────
    app.add_exception_handler(RAGException, rag_exception_handler)  # type: ignore
    app.add_exception_handler(Exception, generic_exception_handler)  # type: ignore

    # ── 路由注册 ───────────────────────────────────────────────────────────────
    from app.api.router import router
    app.include_router(router)

    # ── Prometheus 指标暴露 ────────────────────────────────────────────────────
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    return app


app = create_app()
