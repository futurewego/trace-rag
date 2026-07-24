# P2a 父子块与上下文组装 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 子块用于检索、父块用于生成：命中子块后按父块去重扩展，受 Token 预算约束、按 Lost-in-the-Middle 排序，并加上 PRD 的阈值/拒答/低置信护栏。

**Architecture:** 扩展 Pipeline A（同步栈 + pgvector）。分块器重写为「先切子块、再由连续子块分组拼成父块」——覆盖性由构造保证。检索管线顺序：稠密召回子块 → Cohere 重排(子块文本) → 阈值 → embedding 余弦去重 → top-k → 父块去重扩展 → Token 预算 → LiM 排序。Citation 取自子块。

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, pgvector, tiktoken, Cohere rerank, pytest 8。

Spec：`docs/specs/2026-07-23-p2a-parent-child-context-assembly-design.md`

## Global Constraints

- **父块 = 连续子块分组拼接**，绝不是「元素前 N token 截断」。硬不变量：**每个子块文本必是其父块文本的子串**。
- **任何子块 token ≤ `child_chunk_tokens`**：单段超限必须递归子切（句边界 → 定长窗+重叠），无 `\n\n` 的整页不得塌成巨块。
- **重排输入必须是子块文本**，不得用父块文本。
- **近重复去重用 embedding 余弦**（阈值 `dedup_cosine_threshold`），**不得**用空白切分的 Jaccard（中文无效）。
- **无有效块 → 拒答且不调用 LLM**；**不采用**「全被过滤则保留 top-1」兜底（与 PRD 冲突）。
- **Citation 取自命中的子块**（page_num / section_path / chunk_id），不取父块。
- **老块 `parent_chunk_id` 为 NULL 必须回落到子块自身内容**，不得因 JOIN 写法让 P1a 之前入库的文档消失。
- 父块**不嵌入、不进入召回**；只有子块写 `embedding`。
- 每个改动文件 `ruff check` 干净；沿用 `tests/unit/conftest.py`。
- 提交信息结尾：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## File Structure

**Create:**
- `app/services/context_service.py` — `ContextBlock` + `assemble_context()`（父块去重 / LiM 排序 / Token 预算）
- `tests/unit/test_chunker_parent_child.py`、`tests/unit/test_context_assembly.py`、`tests/unit/test_retrieval_guardrails.py`
- `tests/eval/__init__.py`、`tests/eval/golden_set.py`、`tests/eval/run_eval.py` — 最小评估夹具与运行器

**Modify:**
- `app/config.py` — 8 个新配置项
- `app/services/chunker_service.py` — 重写为父子块
- `app/services/ingestion_service.py` — 写 `parent_chunks` 并回填子块 `parent_chunk_id`
- `app/services/retrieval_service.py` — 阈值 / 余弦去重 / 携带 parent 与 section_path
- `app/services/generation_service.py` — 消费 `ContextBlock`、低置信提示
- `app/api/v1/chat.py` — 透传低置信标志（同步 + SSE）
- `tests/unit/test_chunker.py` — 随分块器 API 重写

---

## Task 1: 新增配置项

**Files:** Modify: `app/config.py`; Test: `tests/unit/test_config_p2a.py`

**Interfaces:** Produces: `Settings.child_chunk_tokens/parent_chunk_tokens/child_overlap_tokens/table_max_tokens/rerank_min_score/low_confidence_score/dedup_cosine_threshold/context_token_budget`

- [ ] **Step 1: 写失败测试** — `tests/unit/test_config_p2a.py`

```python
from app.config import get_settings


def test_p2a_defaults():
    s = get_settings()
    assert s.child_chunk_tokens == 200
    assert s.parent_chunk_tokens == 800
    assert s.child_overlap_tokens == 32
    assert s.table_max_tokens == 1024
    assert s.rerank_min_score == 0.4
    assert s.low_confidence_score == 0.6
    assert s.dedup_cosine_threshold == 0.92
    assert s.context_token_budget == 8000
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_config_p2a.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'child_chunk_tokens'`

- [ ] **Step 3: 实现** — 在 `app/config.py` 的 `retrieval_candidate_k` 行之后插入

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_config_p2a.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/config.py rag-backend/tests/unit/test_config_p2a.py
git commit -m "$(cat <<'EOF'
feat(p2a): config — child/parent chunk sizes + retrieval guardrail thresholds (T1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 分块器重写为父子块（核心）

**Files:** Modify: `app/services/chunker_service.py`, `tests/unit/test_chunker.py`; Test: `tests/unit/test_chunker_parent_child.py`

**Interfaces:**
- Consumes: `Settings` from Task 1。
- Produces: `ChildChunk(content, token_count, page_num)`；`ParentGroup(content, token_count, page_num, children: list[ChildChunk])`；`chunk_unit(text: str, page_num: int | None, chunk_type: str = "text") -> list[ParentGroup]`。旧的 `chunk_page` 被移除。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_chunker_parent_child.py`

```python
from app.config import get_settings
from app.services.chunker_service import chunk_unit, count_tokens


def test_no_child_exceeds_limit_even_without_paragraph_breaks():
    """整页无 '\\n\\n' 也必须递归子切，不得塌成巨块。"""
    limit = get_settings().child_chunk_tokens
    text = "这是一段没有任何空行的长文本。" * 400
    groups = chunk_unit(text, page_num=1)
    children = [c for g in groups for c in g.children]
    assert children
    assert all(c.token_count <= limit for c in children)


def test_every_child_is_substring_of_its_parent():
    """覆盖性不变量：父块必须包含它自己的每个子块。"""
    text = "\n\n".join(f"第{i}段内容，用于构造足够长的文本。" * 12 for i in range(40))
    groups = chunk_unit(text, page_num=2)
    assert groups
    for g in groups:
        for c in g.children:
            assert c.content in g.content


def test_long_element_yields_multiple_parents():
    """长元素必须产出多个父块，而不是一个被截断的父块。"""
    text = "\n\n".join(f"段落{i}：" + "内容" * 200 for i in range(30))
    groups = chunk_unit(text, page_num=3)
    assert len(groups) > 1
    limit = get_settings().parent_chunk_tokens
    assert all(count_tokens(g.content) <= limit for g in groups)


def test_short_text_single_parent_single_child():
    groups = chunk_unit("很短的一句话。", page_num=1)
    assert len(groups) == 1
    assert len(groups[0].children) == 1
    assert groups[0].children[0].content.strip() == "很短的一句话。"


def test_empty_text_returns_empty():
    assert chunk_unit("", page_num=1) == []
    assert chunk_unit("   ", page_num=1) == []


def test_table_kept_whole_when_under_cap():
    rows = "\n".join(f"列A\t列B\n值{i}\t值{i}" for i in range(3))
    groups = chunk_unit(rows, page_num=1, chunk_type="table")
    assert len(groups) == 1
    assert len(groups[0].children) == 1


def test_large_table_is_row_grouped_with_header_repeated():
    header = "订单号\t金额\t客户"
    body = "\n".join(f"HT-{i}\t{i*1000}\t客户{i}" for i in range(2000))
    groups = chunk_unit(f"{header}\n{body}", page_num=1, chunk_type="table")
    children = [c for g in groups for c in g.children]
    assert len(children) > 1
    cap = get_settings().table_max_tokens
    assert all(c.token_count <= cap for c in children)
    assert all(header in c.content for c in children)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_chunker_parent_child.py -q`
Expected: FAIL — `ImportError: cannot import name 'chunk_unit'`

- [ ] **Step 3: 在 `app/services/chunker_service.py` 中【追加】新 API**

> **重要（任务可独立验收的前提）**：本任务**不要删除**现有的 `Chunk` dataclass 与 `chunk_page`——`ingestion_service` 仍在用它们，删了会让 import 崩、整套测试在收集阶段失败。旧 API 在 T3 完成迁移后再移除。
> 现有文件顶部已有 `from dataclasses import dataclass`、`import tiktoken`、`_ENC = tiktoken.get_encoding("cl100k_base")`——**复用它们**，只需把 dataclass 的 import 补成 `from dataclasses import dataclass, field`，并新增 `import re` 与 `from app.config import get_settings`。以下内容追加到文件末尾（`_ENC` 不要重复定义）：

```python
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


def _split_table(text: str, cap: int) -> list[str]:
    """表格：整体不超限则整块；超限则按行分组并在每组重复表头。"""
    if count_tokens(text) <= cap:
        return [text]
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    header = lines[0]
    header_tokens = count_tokens(header)
    out: list[str] = []
    buf: list[str] = []
    buf_tokens = header_tokens
    for row in lines[1:]:
        row_tokens = count_tokens(row)
        if buf and buf_tokens + row_tokens > cap:
            out.append("\n".join([header, *buf]))
            buf = []
            buf_tokens = header_tokens
        buf.append(row)
        buf_tokens += row_tokens
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

    groups = []
    buf: list[ChildChunk] = []
    buf_tokens = 0
    for ct in child_texts:
        tc = count_tokens(ct)
        if buf and buf_tokens + tc > s.parent_chunk_tokens:
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
            buf_tokens = 0
        buf.append(ChildChunk(content=ct, token_count=tc, page_num=page_num))
        buf_tokens += tc

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
```

- [ ] **Step 4: 运行新测试 + 确认旧行为无回归**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全部 passed —— 新增 7 个父子块测试通过，且**现有 `test_chunker.py`（测旧 `chunk_page`）仍然通过**（旧 API 本任务刻意保持不动，T3 迁移后再删）。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/chunker_service.py rag-backend/tests/unit/test_chunker_parent_child.py
git commit -m "$(cat <<'EOF'
feat(p2a): small-to-big chunker — parents built from consecutive children (T2)

Parent content is the concatenation of the children it owns, so every child is
a substring of its parent by construction (no head-truncation). Oversized
paragraphs recurse paragraph -> sentence -> fixed token window, so no child can
exceed child_chunk_tokens even with no blank lines. Tables stay whole under the
cap and are row-grouped with a repeated header above it.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 入库写 parent_chunks 并回填子块

**Files:** Modify: `app/services/ingestion_service.py`; Test: `tests/unit/test_ingestion_parent_child.py`

**Interfaces:**
- Consumes: `chunk_unit`/`ParentGroup`（T2）、`ParentChunk` 模型（P1a）。
- Produces: `build_rows(parsed_units, doc_id, source_mime) -> tuple[list[ParentChunk], list[tuple[Chunk, int]]]` —— 返回父块行与「(子块行, 其父块在列表中的下标)」；`_chunk_units`/`build_chunk_rows` 被移除。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_ingestion_parent_child.py`

```python
import hashlib

from app.services.ingestion_service import build_rows


def _unit(text, kind="page", page=1):
    return {
        "page_num": page, "text": text, "kind": kind,
        "parse_confidence": 0.9, "section_path": ["第一章"],
    }


def test_build_rows_links_children_to_parents():
    units = [_unit("\n\n".join("段落内容。" * 40 for _ in range(20)))]
    parents, child_pairs = build_rows(units, doc_id=7, source_mime="application/pdf")

    assert parents
    assert child_pairs
    for child, parent_idx in child_pairs:
        assert 0 <= parent_idx < len(parents)
        assert child.document_id == 7
        assert child.is_latest is True
        assert child.parse_confidence == 0.9
        assert child.section_path == ["第一章"]
        assert child.content_hash == hashlib.sha256(child.content.encode()).hexdigest()
        # 覆盖性：子块文本必在其父块内容中
        assert child.content in parents[parent_idx].content


def test_sheet_unit_marked_table():
    units = [_unit("列A\t列B\n值1\t值2", kind="sheet")]
    _parents, child_pairs = build_rows(units, doc_id=1, source_mime=None)
    assert child_pairs[0][0].chunk_type == "table"


def test_empty_units_produce_nothing():
    assert build_rows([], doc_id=1, source_mime=None) == ([], [])
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_ingestion_parent_child.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_rows'`

- [ ] **Step 3: 修改 `app/services/ingestion_service.py`**

把 import 中的 `from app.services.chunker_service import Chunk as PageChunk` / `chunk_page` 换成：
```python
from app.models import Chunk, Document, ParentChunk
from app.services.chunker_service import chunk_unit
```
删除 `_chunk_units` 与 `build_chunk_rows`，替换为：

```python
def build_rows(
    parsed_units: list[dict],
    doc_id: int,
    source_mime: str | None,
) -> tuple[list[ParentChunk], list[tuple[Chunk, int]]]:
    """返回 (父块行, [(子块行, 父块下标)])。子块尚未带 embedding/parent_chunk_id。"""
    parents: list[ParentChunk] = []
    child_pairs: list[tuple[Chunk, int]] = []
    idx = 0
    for p in parsed_units:
        chunk_type = _KIND_TO_CHUNK_TYPE.get(p.get("kind"), "text")
        for group in chunk_unit(p["text"], p["page_num"], chunk_type=chunk_type):
            parents.append(
                ParentChunk(
                    document_id=doc_id,
                    content=group.content,
                    section_path=p.get("section_path"),
                    page_num=group.page_num,
                    token_count=group.token_count,
                )
            )
            parent_idx = len(parents) - 1
            for child in group.children:
                child_pairs.append((
                    Chunk(
                        document_id=doc_id,
                        chunk_index=idx,
                        content=child.content,
                        page_num=child.page_num,
                        token_count=child.token_count,
                        chunk_type=chunk_type,
                        content_hash=hashlib.sha256(child.content.encode()).hexdigest(),
                        parse_confidence=p.get("parse_confidence"),
                        section_path=p.get("section_path"),
                        is_latest=True,
                        knowledge_base_id=None,
                        metadata_={"source_mime": source_mime, "kind": p.get("kind")},
                    ),
                    parent_idx,
                ))
                idx += 1
    return parents, child_pairs
```

再把 `ingest_document` 的 try 块替换为：

```python
    try:
        parsed_units = parse(doc_path, mime_type=doc_mime, filename=doc_filename)
        parents, child_pairs = build_rows(parsed_units, doc_id, doc_mime)

        if not child_pairs:
            with _db_scope() as db:
                doc = db.get(Document, doc_id)
                doc.status = "indexed"
                doc.page_count = len(parsed_units)
                doc.chunk_count = 0
            return

        vectors = embed_texts([c.content for c, _ in child_pairs])

        with _db_scope() as db:
            for parent in parents:
                db.add(parent)
            db.flush()  # 拿到父块自增 id
            for (child, parent_idx), vec in zip(child_pairs, vectors, strict=True):
                child.embedding = vec
                child.parent_chunk_id = parents[parent_idx].id
                db.add(child)
            doc = db.get(Document, doc_id)
            doc.status = "indexed"
            doc.page_count = len(parsed_units)
            doc.chunk_count = len(child_pairs)
    except Exception as e:
        logger.exception("ingest failed for doc %s", doc_id)
        with _db_scope() as db:
            doc = db.get(Document, doc_id)
            if doc:
                doc.status = "failed"
                doc.error_msg = str(e)[:1000]
```

同时删除已失效的 `tests/unit/test_ingestion_metadata.py`（其针对被移除的 `build_chunk_rows`），其断言已被本任务测试覆盖。

- [ ] **Step 4: 迁移完成后，移除旧分块 API**

到这一步 `ingestion_service` 已不再引用旧 API，此时才可安全删除 `app/services/chunker_service.py` 中的 `Chunk` dataclass 与 `chunk_page` 函数（`_ENC` / `count_tokens` / 新的父子块 API 全部保留）。

Run: `cd rag-backend && grep -rn "chunk_page\|chunker_service import Chunk\b" app/ tests/ || echo "no remaining references"`
Expected: `app/` 下无任何残留引用；仅 `tests/unit/test_chunker.py` 命中（下一步重写）。

- [ ] **Step 5: 重写 `tests/unit/test_chunker.py`** 为新 API

```python
from app.services.chunker_service import chunk_unit, count_tokens


def test_short_page_single_parent():
    groups = chunk_unit("Hello world. " * 5, page_num=1)
    assert len(groups) == 1
    assert groups[0].page_num == 1
    assert groups[0].children[0].content.startswith("Hello world")


def test_long_page_splits_into_children_and_parents():
    text = "\n\n".join("word " * 120 for _ in range(30))
    groups = chunk_unit(text, page_num=2)
    children = [c for g in groups for c in g.children]
    assert len(children) >= 4
    assert all(g.page_num == 2 for g in groups)
    assert all(c.token_count <= 200 for c in children)


def test_empty_text_returns_empty():
    assert chunk_unit("", page_num=1) == []
    assert chunk_unit("   ", page_num=1) == []


def test_count_tokens_monotonic():
    assert count_tokens("abc") < count_tokens("abc abc abc")
```

- [ ] **Step 6: 运行确认通过 + 全量无回归**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全绿（旧 `chunk_page` 测试已被新 API 测试取代）。

- [ ] **Step 7: Commit**

```bash
git add rag-backend/app/services/ingestion_service.py rag-backend/app/services/chunker_service.py rag-backend/tests/unit/test_ingestion_parent_child.py rag-backend/tests/unit/test_chunker.py
git rm -q rag-backend/tests/unit/test_ingestion_metadata.py
git commit -m "$(cat <<'EOF'
feat(p2a): ingestion writes parent_chunks and links children (T3)

Only children are embedded; parents exist solely for context expansion.
Removes the legacy chunk_page API now that the last caller is migrated.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 检索携带 parent/section + 阈值过滤 + 余弦去重

**Files:** Modify: `app/services/retrieval_service.py`; Test: `tests/unit/test_retrieval_guardrails.py`

**Interfaces:**
- Produces: `RetrievedChunk` 新增字段 `section_path: list[str] | None`、`parent_chunk_id: int | None`、`embedding: list[float] | None`；`_apply_threshold(chunks, min_score)`；`_dedup_by_embedding(chunks, threshold)`。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_retrieval_guardrails.py`

```python
from app.services.retrieval_service import (
    RetrievedChunk,
    _apply_threshold,
    _dedup_by_embedding,
)


def _rc(cid, score, emb, content="内容"):
    return RetrievedChunk(
        chunk_id=cid, doc_id=1, filename="a.pdf", page_num=1, content=content,
        score=score, section_path=None, parent_chunk_id=None, embedding=emb,
    )


def test_apply_threshold_drops_low_scores():
    kept = _apply_threshold([_rc(1, 0.9, None), _rc(2, 0.3, None)], 0.4)
    assert [c.chunk_id for c in kept] == [1]


def test_apply_threshold_can_return_empty():
    """全部低于阈值时必须返回空（触发拒答），不得保留 top-1。"""
    assert _apply_threshold([_rc(1, 0.2, None), _rc(2, 0.1, None)], 0.4) == []


def test_dedup_by_embedding_keeps_higher_score():
    a = _rc(1, 0.9, [1.0, 0.0])
    b = _rc(2, 0.5, [1.0, 0.0])   # 与 a 余弦=1.0 -> 判重
    c = _rc(3, 0.7, [0.0, 1.0])   # 正交 -> 保留
    kept = _dedup_by_embedding([a, b, c], 0.92)
    assert [x.chunk_id for x in kept] == [1, 3]


def test_dedup_skips_when_embedding_missing():
    a = _rc(1, 0.9, None)
    b = _rc(2, 0.5, None)
    assert len(_dedup_by_embedding([a, b], 0.92)) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_retrieval_guardrails.py -q`
Expected: FAIL — `ImportError: cannot import name '_apply_threshold'`

- [ ] **Step 3: 修改 `app/services/retrieval_service.py`**

`RetrievedChunk` 改为：
```python
@dataclass
class RetrievedChunk:
    chunk_id: int
    doc_id: int
    filename: str
    page_num: int | None
    content: str
    score: float  # cosine similarity OR rerank relevance (depends on path)
    section_path: list[str] | None = None
    parent_chunk_id: int | None = None
    embedding: list[float] | None = None
```

`_candidates_stmt` 的 select 增加三列（放在 `Chunk.content` 之后）：
```python
            Chunk.section_path,
            Chunk.parent_chunk_id,
            Chunk.embedding,
```
`_cosine_candidates` 的构造相应补三个字段：
```python
            section_path=r.section_path,
            parent_chunk_id=r.parent_chunk_id,
            embedding=list(r.embedding) if r.embedding is not None else None,
```
`_rerank_with_cohere` 复制 original 的三个新字段（`section_path=original.section_path, parent_chunk_id=original.parent_chunk_id, embedding=original.embedding`）。

新增两个纯函数（放在 `retrieve` 之前）：
```python
def _apply_threshold(
    chunks: list[RetrievedChunk], min_score: float
) -> list[RetrievedChunk]:
    """低于阈值一律丢弃；可以返回空（由调用方触发无据拒答）。"""
    return [c for c in chunks if c.score >= min_score]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _dedup_by_embedding(
    chunks: list[RetrievedChunk], threshold: float
) -> list[RetrievedChunk]:
    """近重复去重：向量余弦 >= threshold 视为重复，保留先出现（分数更高）的那个。

    用 embedding 而非分词 Jaccard —— 中文无空格，分词 Jaccard 不可用。
    """
    kept: list[RetrievedChunk] = []
    for c in chunks:
        if c.embedding is None:
            kept.append(c)
            continue
        if any(
            k.embedding is not None and _cosine(c.embedding, k.embedding) >= threshold
            for k in kept
        ):
            continue
        kept.append(c)
    return kept
```

`retrieve()` 末尾改为在返回前套用两者（保持重排优先、失败回落）：
```python
def retrieve(db: Session, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    settings = get_settings()
    top_k = top_k or settings.top_k

    q_vec = embed_query(query)
    use_rerank = bool(settings.cohere_api_key)
    candidate_n = settings.retrieval_candidate_k if use_rerank else top_k
    candidates = _cosine_candidates(db, q_vec, limit=candidate_n)

    if use_rerank and len(candidates) > top_k:
        try:
            candidates = _rerank_with_cohere(query, candidates, top_n=candidate_n)
        except Exception as e:
            logger.warning("cohere rerank failed, fallback to cosine: %s", e)

    survivors = _apply_threshold(candidates, settings.rerank_min_score)
    survivors = _dedup_by_embedding(survivors, settings.dedup_cosine_threshold)
    return survivors[:top_k]
```

- [ ] **Step 4: 运行确认通过**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_retrieval_guardrails.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/retrieval_service.py rag-backend/tests/unit/test_retrieval_guardrails.py
git commit -m "$(cat <<'EOF'
feat(p2a): retrieval carries parent/section + score threshold + cosine dedup (T4)

Dedup uses embedding cosine, not whitespace Jaccard (unusable for Chinese).
Threshold may legitimately return empty -> caller refuses to answer.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 上下文组装（父块去重扩展 + LiM 排序 + Token 预算）

**Files:** Create: `app/services/context_service.py`, `tests/unit/test_context_assembly.py`

**Interfaces:**
- Consumes: `RetrievedChunk`（T4）、`ParentChunk` 模型。
- Produces: `ContextBlock(content, chunk_id, doc_id, filename, page_num, section_path, score, token_count)`；`assemble_context(db, chunks) -> list[ContextBlock]`；`_order_and_budget(blocks, budget)`。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_context_assembly.py`

```python
from app.services.context_service import ContextBlock, _order_and_budget


def _blk(cid, score, tokens, content="x"):
    return ContextBlock(
        content=content, chunk_id=cid, doc_id=1, filename="a.pdf",
        page_num=1, section_path=None, score=score, token_count=tokens,
    )


def test_highest_score_goes_last_lost_in_the_middle():
    ordered = _order_and_budget([_blk(1, 0.9, 10), _blk(2, 0.5, 10), _blk(3, 0.7, 10)], 1000)
    assert [b.chunk_id for b in ordered] == [2, 3, 1]


def test_token_budget_drops_lowest_scoring_first():
    """预算不足时先丢最不相关的，保留高分块。"""
    ordered = _order_and_budget([_blk(1, 0.9, 100), _blk(2, 0.5, 100), _blk(3, 0.7, 100)], 250)
    assert [b.chunk_id for b in ordered] == [3, 1]


def test_empty_input_returns_empty():
    assert _order_and_budget([], 100) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_context_assembly.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.context_service'`

- [ ] **Step 3: 创建 `app/services/context_service.py`**

```python
"""上下文组装：父块去重扩展 + Token 预算 + Lost-in-the-Middle 排序。"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ParentChunk
from app.services.chunker_service import count_tokens
from app.services.retrieval_service import RetrievedChunk


@dataclass
class ContextBlock:
    content: str            # 父块内容（无父块时回落为子块自身内容）
    chunk_id: int           # 代表子块 id —— citation 指向它
    doc_id: int
    filename: str
    page_num: int | None    # 取自子块，父块可能跨页
    section_path: list[str] | None
    score: float            # 该父块下最佳子块分数
    token_count: int


def _order_and_budget(blocks: list[ContextBlock], budget: int) -> list[ContextBlock]:
    """预算内保留最高分的若干块，再按分数升序排列（最相关放最后）。"""
    kept: list[ContextBlock] = []
    used = 0
    for b in sorted(blocks, key=lambda x: x.score, reverse=True):
        if used + b.token_count > budget:
            continue
        kept.append(b)
        used += b.token_count
    return sorted(kept, key=lambda x: x.score)


def assemble_context(db: Session, chunks: list[RetrievedChunk]) -> list[ContextBlock]:
    """把命中的子块折叠成去重后的父块上下文块。

    多个子块命中同一父块时只产出一个块，代表子块取分数最高者。
    无父块的老数据回落到子块自身内容。
    """
    if not chunks:
        return []

    parent_ids = {c.parent_chunk_id for c in chunks if c.parent_chunk_id is not None}
    parent_content: dict[int, str] = {}
    if parent_ids:
        rows = db.execute(
            select(ParentChunk.id, ParentChunk.content).where(ParentChunk.id.in_(parent_ids))
        ).all()
        parent_content = {r.id: r.content for r in rows}

    best: dict[object, ContextBlock] = {}
    for c in chunks:
        key = ("p", c.parent_chunk_id) if c.parent_chunk_id is not None else ("c", c.chunk_id)
        content = parent_content.get(c.parent_chunk_id or -1) or c.content
        existing = best.get(key)
        if existing is not None and existing.score >= c.score:
            continue
        best[key] = ContextBlock(
            content=content,
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            filename=c.filename,
            page_num=c.page_num,
            section_path=c.section_path,
            score=c.score,
            token_count=count_tokens(content),
        )

    return _order_and_budget(list(best.values()), get_settings().context_token_budget)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_context_assembly.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/context_service.py rag-backend/tests/unit/test_context_assembly.py
git commit -m "$(cat <<'EOF'
feat(p2a): context assembly — parent dedup, token budget, lost-in-the-middle (T5)

Children sharing a parent collapse into one block (best child represents it for
citation); NULL-parent legacy chunks fall back to their own content.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 生成侧消费 ContextBlock + 低置信提示

**Files:** Modify: `app/services/generation_service.py`, `app/api/v1/chat.py`; Test: `tests/unit/test_generation_context.py`

**Interfaces:**
- Consumes: `ContextBlock`（T5）。
- Produces: `generate_answer(query, blocks, low_confidence) -> (answer, citations)`；`generate_answer_stream(query, blocks, low_confidence)`；`is_low_confidence(chunks) -> bool`。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_generation_context.py`

```python
from app.services.context_service import ContextBlock
from app.services.generation_service import _build_user_prompt, is_low_confidence
from app.services.retrieval_service import RetrievedChunk


def _blk(cid, content, page=3, sec=None):
    return ContextBlock(
        content=content, chunk_id=cid, doc_id=1, filename="合同.pdf",
        page_num=page, section_path=sec, score=0.8, token_count=5,
    )


def test_prompt_includes_section_path_and_page():
    prompt = _build_user_prompt("甲方是谁？", [_blk(1, "甲方为星曜科技", sec=["第一章", "总则"])])
    assert "合同.pdf" in prompt
    assert "P3" in prompt
    assert "第一章 > 总则" in prompt
    assert "甲方为星曜科技" in prompt


def _rc(score):
    return RetrievedChunk(
        chunk_id=1, doc_id=1, filename="a", page_num=1, content="c", score=score
    )


def test_is_low_confidence_between_thresholds():
    assert is_low_confidence([_rc(0.5)]) is True
    assert is_low_confidence([_rc(0.9)]) is False
    assert is_low_confidence([]) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && .venv/bin/pytest tests/unit/test_generation_context.py -q`
Expected: FAIL — `ImportError: cannot import name 'is_low_confidence'`

- [ ] **Step 3: 修改 `app/services/generation_service.py`**

把 import 的 `RetrievedChunk` 改为同时引入 `ContextBlock`：
```python
from app.services.context_service import ContextBlock
from app.services.retrieval_service import RetrievedChunk
```
在 `SYSTEM_PROMPT` 之后加：
```python
LOW_CONFIDENCE_NOTE = "⚠️ 检索到的内容相关性较低，请核实。\n\n"


def is_low_confidence(chunks: list[RetrievedChunk]) -> bool:
    """top-1 分数落在 [rerank_min_score, low_confidence_score) 时提示低置信。"""
    if not chunks:
        return False
    s = get_settings()
    return max(c.score for c in chunks) < s.low_confidence_score
```
`_build_user_prompt` 改为吃 `ContextBlock` 并带上 section_path：
```python
def _build_user_prompt(query: str, blocks: list[ContextBlock]) -> str:
    parts = ["<context>"]
    for i, b in enumerate(blocks, start=1):
        page = f" P{b.page_num}" if b.page_num else ""
        sec = f" [{' > '.join(b.section_path)}]" if b.section_path else ""
        parts.append(f"\n[文档{i}] {b.filename}{page}{sec}\n{b.content}\n")
    parts.append("</context>\n")
    parts.append(f"用户问题：{query}")
    return "".join(parts)
```
`_map_citations` 的 `chunks[idx - 1]` 现在是 `ContextBlock`，字段名不变（`doc_id/filename/page_num/chunk_id/score`），无需改动。

`generate_answer` / `generate_answer_stream` 签名各加 `low_confidence: bool = False`，并在有内容时把提示前置：
```python
def generate_answer(
    query: str, blocks: list[ContextBlock], low_confidence: bool = False
) -> tuple[str, list[Citation]]:
    if not blocks:
        return ("根据现有知识库无法回答这个问题。", [])
    ...
    answer = resp.content[0].text
    if low_confidence:
        answer = LOW_CONFIDENCE_NOTE + answer
    return (answer, _map_citations(answer, blocks))
```
流式版本在开头先 `yield ("text", LOW_CONFIDENCE_NOTE)`（当 `low_confidence and blocks`），其余不变。

- [ ] **Step 4: 修改 `app/api/v1/chat.py`** — 两个端点都改为「检索 → 组装 → 生成」

在两处 `retrieved = retrieve(db, req.message)` 之后加：
```python
    blocks = assemble_context(db, retrieved)
    low_conf = is_low_confidence(retrieved)
```
并把 `generate_answer(req.message, retrieved)` 改为 `generate_answer(req.message, blocks, low_conf)`；
把 `generate_answer_stream(user_message, retrieved)` 改为 `generate_answer_stream(user_message, blocks, low_conf)`。
补 import：
```python
from app.services.context_service import assemble_context
from app.services.generation_service import (
    generate_answer, generate_answer_stream, is_low_confidence,
)
```
`_build_retrieval_log_payload(retrieved)` 保持用**子块**（日志记录命中的子块，不是父块）。

- [ ] **Step 5: 运行确认通过 + 全量无回归**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全部 passed。

- [ ] **Step 6: Commit**

```bash
git add rag-backend/app/services/generation_service.py rag-backend/app/api/v1/chat.py rag-backend/tests/unit/test_generation_context.py
git commit -m "$(cat <<'EOF'
feat(p2a): generation consumes ContextBlock + low-confidence notice (T6)

Prompt now carries section_path breadcrumbs; chat wires retrieve -> assemble ->
generate. Retrieval log still records the matched child chunks.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 最小评估夹具与前后对比

**Files:** Create: `tests/eval/__init__.py`, `tests/eval/golden_set.py`, `tests/eval/run_eval.py`

**Interfaces:** Produces: `GOLDEN: list[dict]`（`{question, expected_filename, expected_page}`）；`run_eval(db) -> dict`（`precision_at_3`、`hit_rate`、`n`）。

- [ ] **Step 1: 建 `tests/eval/__init__.py`（空）与 `tests/eval/golden_set.py`**

```python
"""最小评估集：P2a 的质量闸门，同时作为 P5 Golden Set 的种子。

expected_filename/expected_page 指向应当被检索到的来源。
问题覆盖已提交的 fixtures（real_scanned.pdf 的验收关键词）与常见问法。
"""

GOLDEN: list[dict] = [
    {"question": "合同编号是多少？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "甲方是哪家公司？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "乙方是谁？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "合同标的金额是多少？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "合同生效日期？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "星曜科技在合同中是什么角色？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "黄河智能装备厂出现在哪份文件？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "HT-2026-0087 对应什么？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "人民币壹佰贰拾伍万元是什么金额？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "这份扫描件的主要内容是什么？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "合同双方各是谁？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {"question": "文件里提到的日期有哪些？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
]
```

- [ ] **Step 2: 建 `tests/eval/run_eval.py`**

```python
"""对已入库的语料跑最小评估，输出 Precision@3 与命中率。

用法（需已配置 .env 且语料已入库）：
    uv run python -m tests.eval.run_eval
"""
from __future__ import annotations

from app.dependencies import _SessionLocal
from app.services.retrieval_service import retrieve
from tests.eval.golden_set import GOLDEN


def run_eval(db) -> dict:
    hits = 0
    prec_sum = 0.0
    for case in GOLDEN:
        results = retrieve(db, case["question"], top_k=3)
        matched = [
            r for r in results
            if r.filename == case["expected_filename"]
            and (case["expected_page"] is None or r.page_num == case["expected_page"])
        ]
        if matched:
            hits += 1
        prec_sum += (len(matched) / len(results)) if results else 0.0
    n = len(GOLDEN)
    return {
        "n": n,
        "hit_rate": round(hits / n, 3) if n else 0.0,
        "precision_at_3": round(prec_sum / n, 3) if n else 0.0,
    }


def main() -> None:
    with _SessionLocal() as db:
        print(run_eval(db))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 语法与导入自检**

Run: `cd rag-backend && .venv/bin/python -c "from tests.eval.golden_set import GOLDEN; print(len(GOLDEN))"`
Expected: `12`

Run: `cd rag-backend && .venv/bin/ruff check tests/eval/`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add rag-backend/tests/eval/
git commit -m "$(cat <<'EOF'
test(p2a): minimal eval fixture — Precision@3 / hit-rate runner (T7)

Seeds P5's Golden Set; used as the before/after quality gate for P2a.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: 最终验收 gate

**Files:** 无新增（仅跑命令）。

- [ ] **Step 1: 全量单测**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全绿。

- [ ] **Step 2: 迁移未受影响确认**（P2a 无新迁移）

Run: `cd rag-backend && .venv/bin/pytest tests/integration/test_migration_003.py -q`
Expected: `1 passed`（无 Docker 则 skipped）。

- [ ] **Step 3: ruff**

Run: `cd rag-backend && .venv/bin/ruff check app/services/ app/config.py app/api/v1/chat.py tests/unit/ tests/eval/`
Expected: 仅剩既有债（`_db_scope`/`_cohere_client` ANN202、docx.py SIM108），**无 P2a 新引入错误**。

- [ ] **Step 4: 评估对比（需真实 key + 已入库语料）**

在 P2a 分支与 main 各跑一次 `uv run python -m tests.eval.run_eval`，记录 `precision_at_3` / `hit_rate`。
Expected: P2a 不低于 main。若低于，回到 Task 2 调 `child_chunk_tokens` / `parent_chunk_tokens` 后重测。

---

## Self-Review（对照 spec）

- **Spec 覆盖**：§3 分块两个 bug→T2；§4 管线（阈值/去重/扩展/预算/LiM/citation）→T4+T5+T6；§5 护栏→T4(阈值可空)+T6(拒答/低置信)；§6 兼容（NULL 父块回落）→T5 `assemble_context`；§7 配置→T1；§8 测试与评估→各 task + T7 + T8。
- **占位扫描**：无 TBD/TODO；每步含完整代码/命令/预期。
- **类型一致**：`chunk_unit`/`ParentGroup`/`ChildChunk`（T2）被 T3 使用；`RetrievedChunk` 新字段（T4）被 T5 使用；`ContextBlock`（T5）被 T6 使用；`is_latest`/`parent_chunk_id` 沿用 P1a 列。
- **已知取舍**：`_cosine` 用纯 Python（候选 ≤20，无需 numpy）；`_order_and_budget` 先按分数贪心装箱再升序输出，保证「预算不足时先丢最不相关的」且「最相关放最后」。
- **任务排序（自查时修正的一个缺陷）**：分块器改造走「**先加新 API → T3 迁移调用方 → 再删旧 API**」三步。若 T2 直接删掉 `chunk_page`，`ingestion_service` 的 import 会崩、整套测试在收集阶段就失败，T2 便不再是可独立验收的交付。因此 T2 只追加 `chunk_unit` 并保留旧 API，删除动作放在 T3 迁移完成之后（含 `grep` 确认 `app/` 无残留引用）。
