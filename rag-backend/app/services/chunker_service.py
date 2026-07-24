import re
from dataclasses import dataclass, field

import tiktoken

from app.config import get_settings

_ENC = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    chunk_index: int
    content: str
    page_num: int | None
    token_count: int


def chunk_page(
    text: str, page_num: int | None, chunk_size: int = 512, overlap: int = 64
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


# 中英文句子边界
_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;\.])\s*")


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


@dataclass
class ChildChunk:
    content: str
    token_count: int
    page_num: int | None


@dataclass
class ParentGroup:
    content: str
    token_count: int
    page_num: int | None
    children: list[ChildChunk] = field(default_factory=list)


def _window_tokens(text: str, max_tokens: int, overlap: int) -> list[str]:
    """定长 token 窗兜底切分（保证每片 <= max_tokens）。"""
    tokens = _ENC.encode(text)
    if len(tokens) <= max_tokens:
        return [text]
    step = max(1, max_tokens - overlap)
    out: list[str] = []
    pos = 0
    while pos < len(tokens):
        window = tokens[pos : pos + max_tokens]
        if not window:
            break
        out.append(_ENC.decode(window))
        pos += step
    return out


def _split_to_children(text: str, max_tokens: int, overlap: int) -> list[str]:
    """段落 -> 句子 -> 定长窗，逐级递归，确保没有任何片段超过 max_tokens。"""
    pieces: list[str] = []
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        if count_tokens(para) <= max_tokens:
            pieces.append(para)
            continue
        # 段落超限 -> 按句子聚合
        buf: list[str] = []
        for sent in (s.strip() for s in _SENT_SPLIT.split(para)):
            if not sent:
                continue
            if count_tokens(sent) > max_tokens:
                if buf:
                    pieces.append(" ".join(buf))
                    buf = []
                pieces.extend(_window_tokens(sent, max_tokens, overlap))
                continue
            candidate = " ".join([*buf, sent])
            if buf and count_tokens(candidate) > max_tokens:
                pieces.append(" ".join(buf))
                buf = [sent]
            else:
                buf.append(sent)
        if buf:
            pieces.append(" ".join(buf))
    return [p for p in pieces if p.strip()]


def _split_oversized_row(header: str, row: str, cap: int) -> list[str]:
    """单行数据本身（连同表头）就超过 cap 时，对这一行做定长窗口切分，
    每片重新拼上表头，保证不产出超限块。

    先用「cap - 表头 token 数」的近似预算切窗口，再对每片**实际拼接后**的
    字符串重新计数——BPE 在表头/数据拼接处的边界效应可能让近似预算仍然
    超限，这时就收紧预算重切这一片，直到实测不超限为止。
    """
    header_tokens = count_tokens(header)
    budget = max(1, cap - header_tokens - 1)
    row_tokens = _ENC.encode(row)
    out: list[str] = []
    pos = 0
    while pos < len(row_tokens):
        size = min(budget, len(row_tokens) - pos)
        piece = _ENC.decode(row_tokens[pos : pos + size])
        candidate = "\n".join([header, piece])
        while count_tokens(candidate) > cap and size > 1:
            size -= 1
            piece = _ENC.decode(row_tokens[pos : pos + size])
            candidate = "\n".join([header, piece])
        out.append(candidate)
        pos += size
    return out


def _split_table(text: str, cap: int) -> list[str]:
    """表格：整体不超限则整块；超限则按行分组并在每组重复表头。

    分组判定必须用**实际拼接后**的 token 数，不能用逐行 token 数之和做近似——
    BPE 分词在跨行拼接（换行符）处会产生额外 token，逐行求和会系统性低估，
    导致真正拼出来的分组超过 cap（旧实现的 bug）。
    """
    if count_tokens(text) <= cap:
        return [text]
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    if len(lines) == 1:
        # 整表挤在一行（没有换行）或只有表头一行：没有「表头 + 数据行」的
        # 结构可分组，退化为定长 token 窗口切分，避免静默丢弃整个表格。
        return _window_tokens(text, cap, 0)
    header = lines[0]
    out: list[str] = []
    buf: list[str] = []
    for row in lines[1:]:
        # 这一行单独（连同表头）就已经超过 cap：无论 buf 是否为空都要特殊处理，
        # 否则 buf 为空时旧逻辑会无条件放行，产出一个超限块。
        if count_tokens("\n".join([header, row])) > cap:
            if buf:
                out.append("\n".join([header, *buf]))
                buf = []
            out.extend(_split_oversized_row(header, row, cap))
            continue
        candidate = "\n".join([header, *buf, row])
        if buf and count_tokens(candidate) > cap:
            out.append("\n".join([header, *buf]))
            buf = [row]
        else:
            buf.append(row)
    if buf:
        out.append("\n".join([header, *buf]))
    return out


def chunk_unit(
    text: str, page_num: int | None, chunk_type: str = "text"
) -> list[ParentGroup]:
    """把一个解析单元切成「父块（含其子块）」列表。

    - text 类型：段落/句子/定长窗递归切子块，再把**连续**子块聚成 <= parent_chunk_tokens 的父块。
    - table 类型：不超限整块；超限按行分组（每组重复表头），每个行组自成一个父块。
    """
    text = (text or "").strip()
    if not text:
        return []

    s = get_settings()

    if chunk_type == "table":
        groups: list[ParentGroup] = []
        for part in _split_table(text, s.table_max_tokens):
            tc = count_tokens(part)
            child = ChildChunk(content=part, token_count=tc, page_num=page_num)
            groups.append(
                ParentGroup(content=part, token_count=tc, page_num=page_num, children=[child])
            )
        return groups

    child_texts = _split_to_children(text, s.child_chunk_tokens, s.child_overlap_tokens)
    if not child_texts:
        return []

    # 分组判定同样必须用**实际拼接后**的 token 数，理由同 _split_table：逐子块
    # token 数之和是近似值，用 "\n\n" 拼接后重新编码可能比求和更多（英文/数字内容更明显），
    # 求和判定会让真正拼出来的父块超过 parent_chunk_tokens。
    groups = []
    buf: list[ChildChunk] = []
    for ct in child_texts:
        tc = count_tokens(ct)
        candidate = "\n\n".join([*(c.content for c in buf), ct])
        if buf and count_tokens(candidate) > s.parent_chunk_tokens:
            content = "\n\n".join(c.content for c in buf)
            groups.append(
                ParentGroup(
                    content=content,
                    token_count=count_tokens(content),
                    page_num=page_num,
                    children=buf,
                )
            )
            buf = []
        buf.append(ChildChunk(content=ct, token_count=tc, page_num=page_num))

    if buf:
        content = "\n\n".join(c.content for c in buf)
        groups.append(
            ParentGroup(
                content=content,
                token_count=count_tokens(content),
                page_num=page_num,
                children=buf,
            )
        )
    return groups
