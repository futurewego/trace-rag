from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(..., alias="DATABASE_URL")

    # OpenAI
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_embed_model: str = Field("text-embedding-3-small", alias="OPENAI_EMBED_MODEL")
    openai_embed_dim: int = Field(1536, alias="OPENAI_EMBED_DIM")

    # Anthropic
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    # Storage
    upload_dir: Path = Field(Path("./uploads"), alias="UPLOAD_DIR")

    # App
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # Retrieval params
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    top_k: int = 5
    retrieval_candidate_k: int = 20  # cosine 召回数，重排前

    # Chunking (P2a: small-to-big)
    child_chunk_tokens: int = 200
    parent_chunk_tokens: int = 800
    child_overlap_tokens: int = 32
    table_max_tokens: int = 1024

    # Retrieval guardrails / assembly (P2a)
    rerank_min_score: float = 0.4
    low_confidence_score: float = 0.6
    dedup_cosine_threshold: float = 0.92
    context_token_budget: int = 8000

    # Hybrid sparse retrieval (P2b)
    sparse_candidate_k: int = 20
    rrf_k: int = 60
    rrf_dense_weight: float = 0.6
    rrf_sparse_weight: float = 0.4
    enable_sparse: bool = Field(True, alias="ENABLE_SPARSE")

    # Cohere Rerank (optional)
    cohere_api_key: str = Field("", alias="COHERE_API_KEY")
    cohere_rerank_model: str = Field(
        "rerank-multilingual-v3.0", alias="COHERE_RERANK_MODEL"
    )

    # Aliyun OCR (optional; empty key = OCR disabled, falls back to M2 behavior)
    aliyun_ocr_access_key_id: str = Field("", alias="ALIYUN_OCR_ACCESS_KEY_ID")
    aliyun_ocr_access_key_secret: str = Field("", alias="ALIYUN_OCR_ACCESS_KEY_SECRET")
    aliyun_ocr_endpoint: str = Field(
        "ocr-api.cn-hangzhou.aliyuncs.com", alias="ALIYUN_OCR_ENDPOINT"
    )
    ocr_fallback_char_threshold: int = 50


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
