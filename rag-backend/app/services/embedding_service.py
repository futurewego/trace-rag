from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.config import get_settings
from app.core.circuit_breaker import get_breaker, with_circuit_breaker
from app.core.exceptions import EmbeddingError
from app.core.retry import with_retry
from app.observability.logger import get_logger
from app.pipeline.ingestion.steps.chunk import Chunk

logger = get_logger(__name__)


@dataclass
class EmbeddedChunk:
    chunk: Chunk
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


class EmbeddingService:
    """稠密 + 稀疏 Embedding 服务，并发执行，各自带降级"""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def embed_for_ingestion(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        """并发生成稠密+稀疏向量"""
        texts = [c.content for c in chunks]

        dense_vectors, sparse_vectors = await asyncio.gather(
            self._embed_dense_batch(texts),
            self._embed_sparse_batch(texts),
            return_exceptions=True,
        )

        # 处理单个失败的情况
        if isinstance(dense_vectors, Exception):
            raise EmbeddingError(f"Dense embedding failed: {dense_vectors}")

        if isinstance(sparse_vectors, Exception):
            logger.warning("sparse_embedding_failed_using_empty", error=str(sparse_vectors))
            # 稀疏失败时降级为空向量（仍可用稠密检索）
            sparse_vectors = [{"indices": [], "values": []}] * len(chunks)

        result = []
        for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors):
            result.append(
                EmbeddedChunk(
                    chunk=chunk,
                    dense_vector=dense,
                    sparse_indices=sparse.get("indices", []),
                    sparse_values=sparse.get("values", []),
                )
            )
        return result

    async def embed_query(self, text: str) -> tuple[list[float], dict]:
        """查询时生成稠密+稀疏向量"""
        dense, sparse = await asyncio.gather(
            self._embed_dense_batch([text]),
            self._embed_sparse_batch([text]),
            return_exceptions=True,
        )

        dense_vec = dense[0] if not isinstance(dense, Exception) else []
        sparse_vec = sparse[0] if not isinstance(sparse, Exception) else {"indices": [], "values": []}

        if isinstance(dense, Exception):
            raise EmbeddingError(f"Query dense embedding failed: {dense}")

        return dense_vec, sparse_vec

    @with_retry(max_attempts=3, min_wait=1.0, max_wait=8.0)
    async def _embed_dense_batch(self, texts: list[str]) -> list[list[float]]:
        """批量调用 OpenAI Embedding API，每批 100 条"""
        import openai
        from app.observability.metrics import dense_retrieval_latency
        import time

        client = openai.AsyncOpenAI(api_key=self._settings.openai_api_key)
        batch_size = self._settings.openai_embedding_batch_size
        all_vectors: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            t0 = time.monotonic()
            try:
                response = await client.embeddings.create(
                    model=self._settings.openai_embedding_model,
                    input=batch,
                )
                vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
                all_vectors.extend(vectors)
                logger.debug("dense_embed_batch_ok", batch_idx=i // batch_size, count=len(batch))
            except Exception as e:
                logger.exception("dense_embed_batch_failed", batch_idx=i // batch_size, error=str(e))
                raise EmbeddingError(f"OpenAI embedding failed: {e}") from e

        return all_vectors

    async def _embed_sparse_batch(self, texts: list[str]) -> list[dict]:
        """使用本地 SPLADE 模型生成稀疏向量"""
        return await asyncio.to_thread(self._splade_encode_sync, texts)

    def _splade_encode_sync(self, texts: list[str]) -> list[dict]:
        """同步执行 SPLADE 推理（CPU 密集型，在线程池中运行）"""
        try:
            from transformers import AutoModelForMaskedLM, AutoTokenizer
            import torch

            # 延迟加载模型（首次调用时加载）
            if not hasattr(self, "_splade_model"):
                logger.info("loading_splade_model", path=self._settings.splade_model_path)
                self._splade_tokenizer = AutoTokenizer.from_pretrained(
                    self._settings.splade_model_path
                )
                self._splade_model = AutoModelForMaskedLM.from_pretrained(
                    self._settings.splade_model_path
                )
                self._splade_model.eval()

            results = []
            batch_size = 32
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                inputs = self._splade_tokenizer(
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=512,
                )
                with torch.no_grad():
                    outputs = self._splade_model(**inputs)
                    # SPLADE 激活：max over sequence * log(1 + ReLU(logits))
                    logits = outputs.logits
                    activations = torch.log1p(torch.relu(logits))
                    sparse_vecs = activations.max(dim=1).values  # (batch, vocab)

                for vec in sparse_vecs:
                    nonzero_mask = vec > 0
                    indices = nonzero_mask.nonzero(as_tuple=True)[0].tolist()
                    values = vec[nonzero_mask].tolist()
                    results.append({"indices": indices, "values": values})

            return results
        except Exception as e:
            logger.warning("splade_encode_failed", error=str(e))
            # 降级：返回空稀疏向量
            return [{"indices": [], "values": []}] * len(texts)
