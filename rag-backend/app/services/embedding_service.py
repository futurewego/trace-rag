from functools import lru_cache

from openai import OpenAI

from app.config import get_settings


@lru_cache
def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


def embed_texts(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """同步批量嵌入；输入空列表返回空列表。"""
    if not texts:
        return []
    settings = get_settings()
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = _client().embeddings.create(model=settings.openai_embed_model, input=batch)
        out.extend([d.embedding for d in resp.data])
    return out


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
