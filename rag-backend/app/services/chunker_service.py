from dataclasses import dataclass

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    chunk_index: int
    content: str
    page_num: int
    token_count: int


def chunk_page(
    text: str, page_num: int, chunk_size: int = 512, overlap: int = 64
) -> list[Chunk]:
    text = text.strip()
    if not text:
        return []

    tokens = _ENC.encode(text)
    if len(tokens) <= chunk_size:
        return [Chunk(0, text, page_num, len(tokens))]

    chunks: list[Chunk] = []
    step = chunk_size - overlap
    idx = 0
    pos = 0
    while pos < len(tokens):
        window = tokens[pos : pos + chunk_size]
        if not window:
            break
        content = _ENC.decode(window)
        chunks.append(Chunk(idx, content, page_num, len(window)))
        idx += 1
        pos += step
    return chunks
