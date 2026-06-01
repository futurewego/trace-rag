from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class RAGException(Exception):
    """所有业务异常的基类"""

    def __init__(self, message: str, code: str = "RAG_ERROR", status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class ParseError(RAGException):
    def __init__(self, message: str, doc_id: str | None = None) -> None:
        super().__init__(message, code="PARSE_ERROR", status_code=422)
        self.doc_id = doc_id


class EmbeddingError(RAGException):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="EMBEDDING_ERROR", status_code=503)


class RetrievalError(RAGException):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="RETRIEVAL_ERROR", status_code=503)


class GenerationError(RAGException):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="GENERATION_ERROR", status_code=503)


class StorageError(RAGException):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="STORAGE_ERROR", status_code=503)


class CircuitOpenError(RAGException):
    """熔断器开启时抛出"""

    def __init__(self, service: str) -> None:
        super().__init__(
            f"Service '{service}' circuit breaker is open",
            code="CIRCUIT_OPEN",
            status_code=503,
        )
        self.service = service


class FallbackExhaustedError(RAGException):
    """所有 fallback 都失败时抛出"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="FALLBACK_EXHAUSTED", status_code=503)


class DocumentNotFoundError(RAGException):
    def __init__(self, doc_id: str) -> None:
        super().__init__(f"Document '{doc_id}' not found", code="DOC_NOT_FOUND", status_code=404)


class KnowledgeBaseNotFoundError(RAGException):
    def __init__(self, kb_id: str) -> None:
        super().__init__(
            f"Knowledge base '{kb_id}' not found", code="KB_NOT_FOUND", status_code=404
        )


class SessionNotFoundError(RAGException):
    def __init__(self, session_id: str) -> None:
        super().__init__(
            f"Session '{session_id}' not found", code="SESSION_NOT_FOUND", status_code=404
        )


class FileTooLargeError(RAGException):
    def __init__(self, max_mb: int) -> None:
        super().__init__(
            f"File exceeds maximum size of {max_mb}MB",
            code="FILE_TOO_LARGE",
            status_code=413,
        )


class UnsupportedFileTypeError(RAGException):
    def __init__(self, file_type: str) -> None:
        super().__init__(
            f"Unsupported file type: {file_type}",
            code="UNSUPPORTED_FILE_TYPE",
            status_code=415,
        )


# ── FastAPI 异常处理器 ────────────────────────────────────────────────────────

async def rag_exception_handler(request: Request, exc: RAGException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            }
        },
    )
