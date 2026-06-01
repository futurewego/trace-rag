from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

import tiktoken

from app.pipeline.ingestion.parsers.base import ParsedDocument, ParsedElement

# 按文档类型的分块参数
CHUNK_CONFIGS = {
    "text": {"chunk_size": 512, "overlap": 64},
    "heading": {"chunk_size": 512, "overlap": 64},
    "table": {"chunk_size": 1024, "overlap": 0},     # 表格不切，整体保留
    "image_caption": {"chunk_size": 256, "overlap": 0},
    "default": {"chunk_size": 512, "overlap": 64},
}

_tokenizer = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    """单个文档块"""
    chunk_id: uuid.UUID = field(default_factory=uuid.uuid4)
    qdrant_point_id: uuid.UUID = field(default_factory=uuid.uuid4)
    content: str = ""
    content_hash: str = ""
    chunk_index: int = 0
    chunk_type: str = "text"
    token_count: int = 0
    page_number: int | None = None
    section_path: list[str] = field(default_factory=list)
    parse_confidence: float = 1.0
    metadata: dict = field(default_factory=dict)

    # 父子块
    parent_chunk_id: uuid.UUID | None = None
    is_parent: bool = False


def count_tokens(text: str) -> int:
    return len(_tokenizer.encode(text))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class RecursiveChunker:
    """
    语义感知分块器。
    - 表格/图片描述：整体为单块（不切分）
    - 普通文本：按段落边界切，超长时递归切分
    - 构建父子块关系：子块用于检索，父块用于生成上下文
    """

    PARENT_CHUNK_TOKENS = 800
    CHILD_CHUNK_TOKENS = 200

    def chunk(
        self,
        parsed_doc: ParsedDocument,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[Chunk]:
        """
        主入口。返回所有 chunks（含父子块）。
        子块带有 parent_chunk_id 指向父块。
        """
        all_chunks: list[Chunk] = []
        chunk_index = 0

        for element in parsed_doc.elements:
            if not element.content.strip():
                continue

            config = CHUNK_CONFIGS.get(element.element_type, CHUNK_CONFIGS["default"])
            effective_size = chunk_size or config["chunk_size"]
            effective_overlap = overlap if overlap is not None else config["overlap"]

            # 表格和图片描述：整体为单块
            if element.element_type in ("table", "image_caption"):
                chunk = self._make_chunk(element, chunk_index)
                all_chunks.append(chunk)
                chunk_index += 1
            else:
                # 文本类型：构建父子块
                text_chunks = self._split_text(
                    element.content, effective_size, effective_overlap
                )

                if len(text_chunks) == 1:
                    # 内容本身就很短，直接作为单块
                    chunk = self._make_chunk(element, chunk_index, content=text_chunks[0])
                    all_chunks.append(chunk)
                    chunk_index += 1
                else:
                    # 构建父块（原始完整内容，截断到 PARENT_CHUNK_TOKENS）
                    parent_content = self._truncate_tokens(element.content, self.PARENT_CHUNK_TOKENS)
                    parent_chunk = self._make_chunk(
                        element, chunk_index, content=parent_content, is_parent=True
                    )
                    all_chunks.append(parent_chunk)
                    chunk_index += 1

                    # 构建子块
                    for sub_text in text_chunks:
                        child_chunk = self._make_chunk(
                            element,
                            chunk_index,
                            content=sub_text,
                            parent_chunk_id=parent_chunk.chunk_id,
                        )
                        all_chunks.append(child_chunk)
                        chunk_index += 1

        return all_chunks

    def _make_chunk(
        self,
        element: ParsedElement,
        chunk_index: int,
        content: str | None = None,
        is_parent: bool = False,
        parent_chunk_id: uuid.UUID | None = None,
    ) -> Chunk:
        text = content or element.content
        return Chunk(
            content=text,
            content_hash=_sha256(text),
            chunk_index=chunk_index,
            chunk_type=element.element_type,
            token_count=count_tokens(text),
            page_number=element.page_number,
            section_path=element.section_path,
            parse_confidence=element.confidence,
            metadata=element.metadata,
            is_parent=is_parent,
            parent_chunk_id=parent_chunk_id,
        )

    def _split_text(self, text: str, max_tokens: int, overlap: int) -> list[str]:
        """按段落边界切分，超长时递归"""
        tokens = _tokenizer.encode(text)
        if len(tokens) <= max_tokens:
            return [text]

        # 按段落分割
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        chunks: list[str] = []
        current_tokens: list[int] = []
        overlap_buffer: list[int] = []

        for para in paragraphs:
            para_tokens = _tokenizer.encode(para)

            if len(current_tokens) + len(para_tokens) > max_tokens:
                if current_tokens:
                    chunks.append(_tokenizer.decode(current_tokens))
                    # 保留 overlap
                    overlap_buffer = current_tokens[-overlap:] if overlap > 0 else []
                current_tokens = overlap_buffer + para_tokens
            else:
                current_tokens.extend(para_tokens)

        if current_tokens:
            chunks.append(_tokenizer.decode(current_tokens))

        return chunks if chunks else [text[:max_tokens * 4]]  # 粗略截断作为 fallback

    def _truncate_tokens(self, text: str, max_tokens: int) -> str:
        tokens = _tokenizer.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return _tokenizer.decode(tokens[:max_tokens])
