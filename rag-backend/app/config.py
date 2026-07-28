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
    # rrf_k / weights are calibrated for OUR candidate-list depth (~20 items:
    # retrieval_candidate_k / sparse_candidate_k), NOT the TREC convention of
    # k=60 which assumes ~1000-item runs. At k=60 with 0.6/0.4 weights, a
    # sparse-only rank-1 hit (0.4/61 = 0.00656) scores below a dense rank-5 hit
    # (0.6/65 = 0.00923), so a chunk found only by the sparse arm could never
    # reach a top-5 answer. At k=10 with equal 0.5/0.5 weights, sparse#1
    # (0.5/11 = 0.04545) beats dense#5 (0.5/15 = 0.03333), so a sparse-only top
    # hit does enter the top-5. Re-tune with tests/eval/run_eval.py once API
    # keys are available for a real eval run.
    rrf_k: int = 10
    rrf_dense_weight: float = 0.5
    rrf_sparse_weight: float = 0.5
    enable_sparse: bool = Field(True, alias="ENABLE_SPARSE")

    # Multi-turn conversation (P3)
    history_max_turns: int = 5
    history_content_max_chars: int = 500
    enable_query_rewrite: bool = True
    rewrite_max_chars: int = 200

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
