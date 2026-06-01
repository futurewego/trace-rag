from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 应用基础 ──────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = "change-me-in-production"
    app_log_level: str = "INFO"
    app_cors_origins: list[str] = ["http://localhost:3000"]
    app_max_upload_size_mb: int = 100

    # ── 数据库 ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://raguser:ragpass@localhost:5432/ragdb"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # ── Redis ──────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Qdrant ─────────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_use_grpc: bool = False

    # ── OpenAI ─────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-large"
    openai_embedding_batch_size: int = 100
    openai_chat_model: str = "gpt-4o"
    openai_timeout_seconds: int = 30

    # ── Anthropic ──────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    anthropic_max_tokens: int = 4096
    anthropic_timeout_seconds: int = 60

    # ── Azure Document Intelligence ────────────────────────────────────────
    azure_di_endpoint: str = ""
    azure_di_key: str = ""
    azure_di_enabled: bool = False

    # ── Unstructured ──────────────────────────────────────────────────────
    unstructured_api_key: str = ""
    unstructured_api_url: str = ""

    # ── 本地模型 ────────────────────────────────────────────────────────────
    splade_model_path: str = "/models/splade-v3"
    splade_device: str = "cpu"
    reranker_model_path: str = "/models/bge-reranker-v2-m3"
    reranker_device: str = "cpu"
    reranker_batch_size: int = 32

    # ── 文件存储 ────────────────────────────────────────────────────────────
    storage_backend: Literal["minio", "aliyun_oss"] = "minio"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "rag-documents"
    minio_secure: bool = False

    # ── 熔断器 ─────────────────────────────────────────────────────────────
    circuit_breaker_fail_max: int = 5
    circuit_breaker_reset_timeout: int = 60

    # ── Celery ─────────────────────────────────────────────────────────────
    celery_worker_concurrency: int = 4

    # ── 检索参数默认值 ──────────────────────────────────────────────────────
    retrieval_top_k: int = 20           # 向量检索召回数
    retrieval_rerank_top_n: int = 5     # reranker 输出数
    retrieval_min_score: float = 0.4    # reranker 最低分阈值
    retrieval_rrf_k: int = 60           # RRF k 参数

    @field_validator("app_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.app_max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
