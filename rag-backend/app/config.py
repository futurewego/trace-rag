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

    # Cohere Rerank (optional)
    cohere_api_key: str = Field("", alias="COHERE_API_KEY")
    cohere_rerank_model: str = Field(
        "rerank-multilingual-v3.0", alias="COHERE_RERANK_MODEL"
    )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
