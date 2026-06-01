from __future__ import annotations

from prometheus_client import Counter, Histogram

# ── 检索延迟 ──────────────────────────────────────────────────────────────────
retrieval_latency = Histogram(
    "rag_retrieval_latency_seconds",
    "End-to-end retrieval pipeline latency",
    labelnames=["kb_id"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

dense_retrieval_latency = Histogram(
    "rag_dense_retrieval_latency_seconds",
    "Dense vector retrieval latency",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
)

sparse_retrieval_latency = Histogram(
    "rag_sparse_retrieval_latency_seconds",
    "Sparse (SPLADE) retrieval latency",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
)

rerank_latency = Histogram(
    "rag_rerank_latency_seconds",
    "BGE Reranker latency",
    buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0],
)

# ── 生成延迟 ──────────────────────────────────────────────────────────────────
generation_latency = Histogram(
    "rag_generation_latency_seconds",
    "LLM generation latency (time to first token)",
    labelnames=["model"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ── Fallback 计数 ─────────────────────────────────────────────────────────────
fallback_total = Counter(
    "rag_fallback_total",
    "Number of fallback activations",
    labelnames=["service", "reason"],
)

circuit_breaker_failures = Counter(
    "rag_circuit_breaker_failures_total",
    "Circuit breaker failure count",
    labelnames=["service"],
)

# ── 文档处理 ──────────────────────────────────────────────────────────────────
documents_processed_total = Counter(
    "rag_documents_processed_total",
    "Total documents processed",
    labelnames=["status", "file_type"],
)

document_chunks_created_total = Counter(
    "rag_document_chunks_created_total",
    "Total document chunks created",
)

# ── 对话 ──────────────────────────────────────────────────────────────────────
chat_requests_total = Counter(
    "rag_chat_requests_total",
    "Total chat requests",
    labelnames=["kb_id"],
)

empty_retrieval_total = Counter(
    "rag_empty_retrieval_total",
    "Queries that returned no relevant chunks",
)
