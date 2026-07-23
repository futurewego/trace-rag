# P1a 入库地基 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一次性把 PRD §7.1 的全部元数据列落到 `chunks`/`documents` 并让入库写入它们，且不改变任何检索/生成行为。

**Architecture:** 扩展 Pipeline A（同步栈 + pgvector + BackgroundTask）。本阶段只做「加列迁移 + 解析器元数据增强 + 入库写列 + 检索 is_latest 过滤」。**保留 `chunk_page` 512/64 与检索语义字节级不变**，父子块/扩展/tsvector 全留 P2。

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, PostgreSQL 16 + pgvector, pytest 8, testcontainers[postgres]（已在 dev 依赖）, tiktoken, python-docx/openpyxl/python-pptx, pypdf/pypdfium2。

Spec：`docs/specs/2026-07-23-p1a-ingestion-foundation-design.md`

## Global Constraints

- 不改 `app/services/chunker_service.py`（`chunk_page` 签名/语义不变）；不改检索排序/生成语义。
- 所有新增 NOT NULL 列必须带 `server_default`（`chunk_type='text'`、`is_latest=true`、`doc_version=1`）。
- `section_path` 类型为 Postgres `text[]`（`ARRAY(Text)`），存 `list[str]`。
- `parse_confidence`：原生文本 0.9 / OCR 0.6 / native-XML(docx/xlsx/pptx) 0.95；`parse_pdf` 两个分支分别标注。
- pdf 的 `section_path` 一律 `[]`（不做启发式标题，避免错误 citation）。
- `knowledge_base_id` 仅预留 nullable 列，不加逻辑/约束。
- 不建 `tsvector` 列、不加新 unique 约束（留 P2）。
- 迁移 revision id `003_p1a_foundation`，`down_revision = "002_m1_schema"`。
- 每个改动文件 `ruff check` 干净；沿用 `tests/unit/conftest.py`（无 `.env` 也能跑）。
- 提交信息结尾：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## File Structure

**Create:**
- `app/models/parent_chunk.py` — `ParentChunk` ORM（父块表，本期空表，P2 填充）
- `alembic/versions/003_p1a_foundation.py` — 加列迁移
- `tests/unit/test_models_p1a.py` — 模型列自省
- `tests/integration/__init__.py`、`tests/integration/test_migration_003.py` — 迁移往返（testcontainers）
- `tests/unit/test_parser_confidence.py`、`tests/unit/test_parser_section_path.py`
- `tests/unit/test_ingestion_metadata.py`、`tests/unit/test_retrieval_is_latest.py`

**Modify:**
- `app/models/chunk.py`、`app/models/document.py`、`app/models/__init__.py` — 加列/注册模型
- `app/services/parsers/{pdf,docx,xlsx,pptx}.py` — 补 `parse_confidence` + `section_path`
- `app/services/ingestion_service.py` — 抽 `build_chunk_rows`，写入新列
- `app/services/retrieval_service.py` — 抽 `_candidates_stmt`，加 `WHERE is_latest`

---

## Task 1: ORM 模型加列 + ParentChunk

**Files:**
- Modify: `app/models/chunk.py`, `app/models/document.py`, `app/models/__init__.py`
- Create: `app/models/parent_chunk.py`
- Test: `tests/unit/test_models_p1a.py`

**Interfaces:**
- Produces: `Chunk`（+`chunk_type/section_path/parse_confidence/content_hash/is_latest/knowledge_base_id/parent_chunk_id`）、`Document`（+`doc_version/is_latest/doc_group_id/knowledge_base_id`）、`ParentChunk`（新表模型）。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_models_p1a.py`

```python
from app.models import Chunk, Document, ParentChunk


def test_chunk_has_p1a_columns():
    cols = Chunk.__table__.columns
    for c in (
        "chunk_type", "section_path", "parse_confidence", "content_hash",
        "is_latest", "knowledge_base_id", "parent_chunk_id",
    ):
        assert c in cols, f"missing chunks.{c}"
    assert cols["chunk_type"].nullable is False
    assert cols["is_latest"].nullable is False
    assert cols["parse_confidence"].nullable is True
    assert cols["knowledge_base_id"].nullable is True


def test_document_has_versioning_columns():
    cols = Document.__table__.columns
    for c in ("doc_version", "is_latest", "doc_group_id", "knowledge_base_id"):
        assert c in cols, f"missing documents.{c}"
    assert cols["doc_version"].nullable is False
    assert cols["is_latest"].nullable is False


def test_parent_chunk_model():
    assert ParentChunk.__tablename__ == "parent_chunks"
    cols = ParentChunk.__table__.columns
    for c in ("id", "document_id", "content", "section_path", "page_num", "token_count", "created_at"):
        assert c in cols, f"missing parent_chunks.{c}"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/test_models_p1a.py -q`
Expected: FAIL — `ImportError: cannot import name 'ParentChunk'`。

- [ ] **Step 3: 创建 `app/models/parent_chunk.py`**

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ParentChunk(Base):
    __tablename__ = "parent_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    page_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 4: 修改 `app/models/chunk.py`** — 在 `metadata_` 行后追加列，并补 import

把顶部 import 行改为（追加 `Boolean, Float`）：
```python
from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
```

在 `metadata_` 那一行下面、`document` relationship 之前插入：
```python
    chunk_type: Mapped[str] = mapped_column(
        String(32), server_default="text", nullable=False
    )
    section_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    parse_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_latest: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )
    knowledge_base_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    parent_chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("parent_chunks.id", ondelete="SET NULL"), nullable=True
    )
```

- [ ] **Step 5: 修改 `app/models/document.py`** — 追加列，补 import

顶部 import 改为（追加 `Boolean, text`）：
```python
from sqlalchemy import BigInteger, Boolean, Integer, String, Text, text
```
在 `chunk_count` 行下面、`chunks` relationship 之前插入：
```python
    doc_version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    is_latest: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )
    doc_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    knowledge_base_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
```

- [ ] **Step 6: 注册模型** — `app/models/__init__.py` 加 `ParentChunk`

```python
from app.models.base import Base, TimestampMixin
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.message import Message
from app.models.parent_chunk import ParentChunk
from app.models.retrieval_log import RetrievalLog
from app.models.session import Session

__all__ = [
    "Base", "TimestampMixin", "Document", "Chunk", "ParentChunk",
    "Session", "Message", "RetrievalLog",
]
```

- [ ] **Step 7: 运行确认通过**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/test_models_p1a.py -q`
Expected: `3 passed`。

- [ ] **Step 8: Commit**

```bash
git add rag-backend/app/models/ rag-backend/tests/unit/test_models_p1a.py
git commit -m "$(cat <<'EOF'
feat(p1a): ORM models — chunk/document metadata columns + ParentChunk (T1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Alembic 迁移 003 + 往返集成测试

**Files:**
- Create: `alembic/versions/003_p1a_foundation.py`
- Create: `tests/integration/__init__.py`, `tests/integration/test_migration_003.py`

**Interfaces:**
- Consumes: Task 1 的模型（`Base.metadata` 供 env.py）。
- Produces: 数据库 schema 与 Task 1 模型一致；`003_p1a_foundation` 可 up/down 往返。

- [ ] **Step 1: 写失败测试** — `tests/integration/__init__.py`（空文件）+ `tests/integration/test_migration_003.py`

```python
import pytest

pytest.importorskip("testcontainers.postgres")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text as sa_text  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402


@pytest.fixture(scope="module")
def pg():
    try:
        with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as c:
            yield c
    except Exception as e:  # Docker 不可用
        pytest.skip(f"Docker/testcontainers unavailable: {e}")


def _names(engine, sql, params=None):
    with engine.connect() as c:
        return {r[0] for r in c.execute(sa_text(sql), params or {}).fetchall()}


def _cols(engine, table):
    return _names(
        engine,
        "SELECT column_name FROM information_schema.columns WHERE table_name=:t",
        {"t": table},
    )


def _tables(engine):
    return _names(
        engine,
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
    )


def test_migration_003_roundtrip(pg, monkeypatch):
    url = pg.get_connection_url()
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings
    get_settings.cache_clear()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url)

    command.upgrade(cfg, "head")

    with engine.begin() as c:
        c.execute(sa_text(
            "INSERT INTO documents (filename, file_hash, file_path, file_size, status, chunk_count)"
            " VALUES ('a.pdf','h1','/tmp/a.pdf',10,'indexed',0)"
        ))

    assert {"doc_version", "is_latest", "doc_group_id", "knowledge_base_id"} <= _cols(engine, "documents")
    assert {
        "chunk_type", "section_path", "parse_confidence", "content_hash",
        "is_latest", "knowledge_base_id", "parent_chunk_id",
    } <= _cols(engine, "chunks")
    assert "parent_chunks" in _tables(engine)

    with engine.connect() as c:
        r = c.execute(sa_text(
            "SELECT id, doc_group_id, doc_version, is_latest FROM documents"
        )).fetchone()
    assert r.doc_group_id == r.id
    assert r.doc_version == 1
    assert r.is_latest is True

    command.downgrade(cfg, "002_m1_schema")
    assert "doc_version" not in _cols(engine, "documents")
    assert "parent_chunk_id" not in _cols(engine, "chunks")
    assert "parent_chunks" not in _tables(engine)

    get_settings.cache_clear()
    engine.dispose()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && .venv/bin/pytest tests/integration/test_migration_003.py -q`
Expected: FAIL — `command.upgrade` 找不到 `003_p1a_foundation`（或断言列缺失）。若无 Docker 则 skip（正常）。

- [ ] **Step 3: 创建 `alembic/versions/003_p1a_foundation.py`**

```python
"""P1a ingestion foundation: chunk/document metadata + parent_chunks

Revision ID: 003_p1a_foundation
Revises: 002_m1_schema
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003_p1a_foundation"
down_revision = "002_m1_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # documents
    op.add_column("documents", sa.Column("doc_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("documents", sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("documents", sa.Column("doc_group_id", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("knowledge_base_id", sa.BigInteger(), nullable=True))
    op.execute("UPDATE documents SET doc_group_id = id WHERE doc_group_id IS NULL")
    op.create_index("ix_documents_doc_group_id", "documents", ["doc_group_id"])
    op.create_index("ix_documents_is_latest", "documents", ["is_latest"])

    # parent_chunks (empty until P2)
    op.create_table(
        "parent_chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "document_id", sa.BigInteger,
            sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("section_path", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("page_num", sa.Integer, nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_parent_chunks_document_id", "parent_chunks", ["document_id"])

    # chunks
    op.add_column("chunks", sa.Column("chunk_type", sa.String(32), nullable=False, server_default="text"))
    op.add_column("chunks", sa.Column("section_path", postgresql.ARRAY(sa.Text), nullable=True))
    op.add_column("chunks", sa.Column("parse_confidence", sa.Float(), nullable=True))
    op.add_column("chunks", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column("chunks", sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("chunks", sa.Column("knowledge_base_id", sa.BigInteger(), nullable=True))
    op.add_column("chunks", sa.Column("parent_chunk_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_chunks_parent_chunk_id", "chunks", "parent_chunks",
        ["parent_chunk_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_chunks_is_latest", "chunks", ["is_latest"])
    op.create_index("ix_chunks_parent_chunk_id", "chunks", ["parent_chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_parent_chunk_id", table_name="chunks")
    op.drop_index("ix_chunks_is_latest", table_name="chunks")
    op.drop_constraint("fk_chunks_parent_chunk_id", "chunks", type_="foreignkey")
    op.drop_column("chunks", "parent_chunk_id")
    op.drop_column("chunks", "knowledge_base_id")
    op.drop_column("chunks", "is_latest")
    op.drop_column("chunks", "content_hash")
    op.drop_column("chunks", "parse_confidence")
    op.drop_column("chunks", "section_path")
    op.drop_column("chunks", "chunk_type")

    op.drop_index("ix_parent_chunks_document_id", table_name="parent_chunks")
    op.drop_table("parent_chunks")

    op.drop_index("ix_documents_is_latest", table_name="documents")
    op.drop_index("ix_documents_doc_group_id", table_name="documents")
    op.drop_column("documents", "knowledge_base_id")
    op.drop_column("documents", "doc_group_id")
    op.drop_column("documents", "is_latest")
    op.drop_column("documents", "doc_version")
```

- [ ] **Step 4: 运行确认通过**（需 Docker 运行）

Run: `cd rag-backend && .venv/bin/pytest tests/integration/test_migration_003.py -q`
Expected: `1 passed`（无 Docker 时 `1 skipped`）。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/alembic/versions/003_p1a_foundation.py rag-backend/tests/integration/
git commit -m "$(cat <<'EOF'
feat(p1a): alembic 003 — additive metadata migration + roundtrip test (T2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 解析器 parse_confidence

**Files:**
- Modify: `app/services/parsers/pdf.py`, `docx.py`, `xlsx.py`, `pptx.py`
- Test: `tests/unit/test_parser_confidence.py`

**Interfaces:**
- Produces: 每个 parser 返回的 unit dict 新增键 `parse_confidence: float`。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_parser_confidence.py`

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.parsers.docx import parse_docx
from app.services.parsers.pdf import parse_pdf
from app.services.parsers.pptx import parse_pptx
from app.services.parsers.xlsx import parse_xlsx

FX = Path(__file__).parent / "fixtures"


def test_native_xml_parsers_confidence_095():
    for parse, fx in [(parse_docx, "tiny.docx"), (parse_xlsx, "tiny.xlsx"), (parse_pptx, "tiny.pptx")]:
        units = parse(FX / fx)
        assert units and all(u["parse_confidence"] == 0.95 for u in units)


@patch("app.services.parsers.pdf.ocr_image", return_value="scanned text recovered")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=True)
def test_pdf_ocr_page_confidence_06(mock_en, mock_ocr):
    pages = parse_pdf(FX / "scanned.pdf")
    assert pages and pages[0]["parse_confidence"] == 0.6


@patch("app.services.parsers.pdf.PdfReader")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=True)
def test_pdf_native_page_confidence_09(mock_en, mock_reader):
    page = MagicMock()
    page.extract_text.return_value = "native long text " * 20
    mock_reader.return_value.pages = [page]
    pages = parse_pdf(FX / "scanned.pdf")
    assert pages and pages[0]["parse_confidence"] == 0.9
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/test_parser_confidence.py -q`
Expected: FAIL — `KeyError: 'parse_confidence'`。

- [ ] **Step 3a: 改 `pdf.py`** — 每页 confidence（native 0.9 / OCR 0.6）

把 `parse_pdf` 里的循环体改为（在 `for i, page ...` 内）：
```python
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        confidence = 0.9

        if len(text) < threshold and use_ocr:
            try:
                img_bytes = _render_page_to_image(source, i - 1)
                text = (ocr_image(img_bytes) or "").strip()
                confidence = 0.6
            except OcrError as e:
                logger.error("OCR fail page=%d: %s", i, e)
                ocr_errors += 1
                last_ocr_error = str(e)
                text = ""
            except Exception as e:
                logger.warning("PDF render fail page=%d: %s", i, e)
                text = ""

        if text:
            pages.append(
                {"page_num": i, "text": text, "kind": "page", "parse_confidence": confidence}
            )
```

- [ ] **Step 3b: 改 `docx.py`** — 两处 `sections.append(...)` 各加 `"parse_confidence": 0.95`

```python
            sections.append({"page_num": None, "text": "\n".join(buf), "kind": "section", "parse_confidence": 0.95})
```
（循环内与循环后的 `if buf:` 各一处，均加该键。）

- [ ] **Step 3c: 改 `xlsx.py`** — `chunks.append(...)` 加键

```python
            chunks.append({
                "page_num": i,
                "text": f"[Sheet: {sheet_name}]\n{body}",
                "kind": "sheet",
                "parse_confidence": 0.95,
            })
```

- [ ] **Step 3d: 改 `pptx.py`** — `chunks.append(...)` 加键

```python
            chunks.append({"page_num": i, "text": text, "kind": "slide", "parse_confidence": 0.95})
```

- [ ] **Step 4: 运行确认通过 + 无回归**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/test_parser_confidence.py tests/unit/test_parser_docx.py tests/unit/test_parser_xlsx.py tests/unit/test_parser_pptx.py tests/unit/test_parser_pdf_ocr.py -q`
Expected: 全部 passed（现有解析器测试因 additive 不受影响）。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/parsers/ rag-backend/tests/unit/test_parser_confidence.py
git commit -m "$(cat <<'EOF'
feat(p1a): parsers emit parse_confidence (native 0.9 / OCR 0.6 / xml 0.95) (T3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 解析器 section_path

**Files:**
- Modify: `app/services/parsers/docx.py`（标题栈）, `xlsx.py`, `pptx.py`, `pdf.py`
- Test: `tests/unit/test_parser_section_path.py`

**Interfaces:**
- Produces: 每个 unit dict 新增键 `section_path: list[str]`。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_parser_section_path.py`

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.parsers.docx import parse_docx
from app.services.parsers.pdf import parse_pdf
from app.services.parsers.pptx import parse_pptx
from app.services.parsers.xlsx import parse_xlsx

FX = Path(__file__).parent / "fixtures"


def test_docx_section_path_from_headings(tmp_path):
    from docx import Document as D

    d = D()
    d.add_heading("第一章 总则", level=1)
    d.add_paragraph("本章规定了适用范围与基本原则。")
    d.add_heading("1.1 定义", level=2)
    d.add_paragraph("本合同中的术语含义如下。")
    f = tmp_path / "h.docx"
    d.save(f)

    units = parse_docx(f)
    assert units
    assert all(isinstance(u["section_path"], list) for u in units)
    assert any("第一章 总则" in u["section_path"] for u in units)


def test_xlsx_section_path_is_sheet_name():
    units = parse_xlsx(FX / "tiny.xlsx")
    for u in units:
        assert len(u["section_path"]) == 1
        assert u["section_path"][0] in u["text"]


def test_pptx_section_path_is_list():
    units = parse_pptx(FX / "tiny.pptx")
    assert all(isinstance(u["section_path"], list) for u in units)


@patch("app.services.parsers.pdf.PdfReader")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=False)
def test_pdf_section_path_empty(mock_en, mock_reader):
    page = MagicMock()
    page.extract_text.return_value = "some native text " * 10
    mock_reader.return_value.pages = [page]
    pages = parse_pdf(FX / "scanned.pdf")
    assert pages and pages[0]["section_path"] == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/test_parser_section_path.py -q`
Expected: FAIL — `KeyError: 'section_path'`。

- [ ] **Step 3a: 改 `docx.py`** — 完整替换 `parse_docx` 为标题栈版本

```python
def parse_docx(source: bytes | str | Path) -> list[dict]:
    """Returns list of {page_num=None, text, kind='section', parse_confidence, section_path}.

    docx 无页概念；按段落聚合到 ~2000 字符的 section。section_path 由 Heading 样式栈推导。
    """
    if isinstance(source, (bytes, bytearray)):
        doc = _Doc(BytesIO(source))
    else:
        doc = _Doc(str(source))

    heading_stack: list[str] = []
    sections: list[dict] = []
    buf: list[str] = []
    buf_len = 0
    path_at_start: list[str] = []

    for p in doc.paragraphs:
        para = p.text.strip() if p.text else ""
        if not para:
            continue

        style = (p.style.name or "") if p.style is not None else ""
        if style.startswith("Heading"):
            try:
                level = int(style.split()[-1])
            except (ValueError, IndexError):
                level = 1
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(para)

        if not buf:
            path_at_start = list(heading_stack)

        if buf_len + len(para) > _TARGET_CHARS and buf:
            sections.append({
                "page_num": None, "text": "\n".join(buf), "kind": "section",
                "parse_confidence": 0.95, "section_path": path_at_start,
            })
            buf = []
            buf_len = 0
            path_at_start = list(heading_stack)

        buf.append(para)
        buf_len += len(para)

    if buf:
        sections.append({
            "page_num": None, "text": "\n".join(buf), "kind": "section",
            "parse_confidence": 0.95, "section_path": path_at_start,
        })

    return sections
```

- [ ] **Step 3b: 改 `xlsx.py`** — append 加 `"section_path": [sheet_name]`

```python
            chunks.append({
                "page_num": i,
                "text": f"[Sheet: {sheet_name}]\n{body}",
                "kind": "sheet",
                "parse_confidence": 0.95,
                "section_path": [sheet_name],
            })
```

- [ ] **Step 3c: 改 `pptx.py`** — 取 slide 标题占位符作 section_path

在 `for i, slide in enumerate(...)` 循环体开头、构造 `parts` 之后、`chunks.append` 之前加：
```python
        title = ""
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = (slide.shapes.title.text or "").strip()
```
把 append 改为：
```python
            chunks.append({
                "page_num": i, "text": text, "kind": "slide",
                "parse_confidence": 0.95,
                "section_path": [title] if title else [],
            })
```

- [ ] **Step 3d: 改 `pdf.py`** — page dict 加 `"section_path": []`

```python
            pages.append({
                "page_num": i, "text": text, "kind": "page",
                "parse_confidence": confidence, "section_path": [],
            })
```

- [ ] **Step 4: 运行确认通过 + 无回归**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/ -q`
Expected: 全部 passed（现有解析器/OCR/chunker 测试不受影响）。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/parsers/ rag-backend/tests/unit/test_parser_section_path.py
git commit -m "$(cat <<'EOF'
feat(p1a): parsers emit section_path (docx heading stack / xlsx sheet / pptx title / pdf []) (T4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 入库写入新列（`build_chunk_rows`）

**Files:**
- Modify: `app/services/ingestion_service.py`
- Test: `tests/unit/test_ingestion_metadata.py`

**Interfaces:**
- Consumes: Task 1 的 `Chunk` 模型；`chunker_service.Chunk`（dataclass，字段 `chunk_index/content/page_num/token_count`）。
- Produces: `build_chunk_rows(chunked: list[tuple[PageChunk, dict]], vectors: list[list[float]], doc_id: int, source_mime: str | None) -> list[Chunk]`；`_KIND_TO_CHUNK_TYPE: dict[str, str]`。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_ingestion_metadata.py`

```python
import hashlib

from app.services.chunker_service import Chunk as PageChunk
from app.services.ingestion_service import build_chunk_rows


def test_build_chunk_rows_maps_metadata():
    ck = PageChunk(chunk_index=0, content="合同编号 HT-2026-0087", page_num=3, token_count=6)
    unit = {"page_num": 3, "kind": "sheet", "parse_confidence": 0.95, "section_path": ["Sheet1"]}
    rows = build_chunk_rows([(ck, unit)], [[0.1] * 1536], doc_id=7, source_mime="application/pdf")

    assert len(rows) == 1
    r = rows[0]
    assert r.document_id == 7
    assert r.chunk_type == "table"            # sheet -> table
    assert r.parse_confidence == 0.95
    assert r.section_path == ["Sheet1"]
    assert r.is_latest is True
    assert r.parent_chunk_id is None
    assert r.knowledge_base_id is None
    assert r.content_hash == hashlib.sha256("合同编号 HT-2026-0087".encode()).hexdigest()


def test_build_chunk_rows_kind_defaults_to_text():
    ck = PageChunk(chunk_index=0, content="正文段落", page_num=1, token_count=2)
    unit = {"page_num": 1, "kind": "page", "parse_confidence": 0.9, "section_path": []}
    rows = build_chunk_rows([(ck, unit)], [[0.0] * 1536], doc_id=1, source_mime=None)
    assert rows[0].chunk_type == "text"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/test_ingestion_metadata.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_chunk_rows'`。

- [ ] **Step 3: 修改 `app/services/ingestion_service.py`**

顶部 import 增加 `hashlib`；`from app.services.chunker_service import chunk_page, Chunk as PageChunk`（若已 import chunk_page 则补 PageChunk）。在 `ingest_document` 之前加：

```python
import hashlib

_KIND_TO_CHUNK_TYPE = {"page": "text", "section": "text", "slide": "text", "sheet": "table"}


def _chunk_units(parsed_units: list[dict]) -> list[tuple[PageChunk, dict]]:
    rows: list[tuple[PageChunk, dict]] = []
    for p in parsed_units:
        for ck in chunk_page(p["text"], page_num=p["page_num"]):
            rows.append((ck, p))
    return rows


def build_chunk_rows(
    chunked: list[tuple[PageChunk, dict]],
    vectors: list[list[float]],
    doc_id: int,
    source_mime: str | None,
) -> list[Chunk]:
    out: list[Chunk] = []
    for (ck, p), vec in zip(chunked, vectors, strict=True):
        out.append(
            Chunk(
                document_id=doc_id,
                chunk_index=ck.chunk_index,
                content=ck.content,
                page_num=ck.page_num,
                token_count=ck.token_count,
                embedding=vec,
                chunk_type=_KIND_TO_CHUNK_TYPE.get(p.get("kind"), "text"),
                content_hash=hashlib.sha256(ck.content.encode()).hexdigest(),
                parse_confidence=p.get("parse_confidence"),
                section_path=p.get("section_path"),
                is_latest=True,
                parent_chunk_id=None,
                knowledge_base_id=None,
                metadata_={"source_mime": source_mime, "kind": p.get("kind")},
            )
        )
    return out
```

然后把 `ingest_document` 的 try 块改为用这两个函数（替换原「all_chunks / contents / vectors / for ck,vec 」段）：

```python
    try:
        parsed_units = parse(doc_path, mime_type=doc_mime, filename=doc_filename)
        chunked = _chunk_units(parsed_units)

        if not chunked:
            with _db_scope() as db:
                doc = db.get(Document, doc_id)
                doc.status = "indexed"
                doc.page_count = len(parsed_units)
                doc.chunk_count = 0
            return

        contents = [ck.content for ck, _ in chunked]
        vectors = embed_texts(contents)
        rows = build_chunk_rows(chunked, vectors, doc_id, doc_mime)

        with _db_scope() as db:
            for row in rows:
                db.add(row)
            doc = db.get(Document, doc_id)
            doc.status = "indexed"
            doc.page_count = len(parsed_units)
            doc.chunk_count = len(rows)
    except Exception as e:
        logger.exception("ingest failed for doc %s", doc_id)
        with _db_scope() as db:
            doc = db.get(Document, doc_id)
            if doc:
                doc.status = "failed"
                doc.error_msg = str(e)[:1000]
```

（确保顶部有 `from app.models import Chunk, Document` 与 `from app.services.chunker_service import chunk_page, Chunk as PageChunk`。）

- [ ] **Step 4: 运行确认通过**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/test_ingestion_metadata.py -q`
Expected: `2 passed`。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/ingestion_service.py rag-backend/tests/unit/test_ingestion_metadata.py
git commit -m "$(cat <<'EOF'
feat(p1a): ingestion writes chunk_type/section_path/parse_confidence/content_hash/is_latest (T5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 检索 is_latest 预过滤

**Files:**
- Modify: `app/services/retrieval_service.py`
- Test: `tests/unit/test_retrieval_is_latest.py`

**Interfaces:**
- Produces: `_candidates_stmt(q_vec: list[float], limit: int) -> Select`（含 `WHERE chunks.is_latest`）；`_cosine_candidates` 改用它。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_retrieval_is_latest.py`

```python
from sqlalchemy.dialects import postgresql

from app.services.retrieval_service import _candidates_stmt


def test_candidates_stmt_filters_is_latest():
    stmt = _candidates_stmt([0.0] * 1536, 5)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "is_latest" in sql
    assert "LIMIT" in sql.upper()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/test_retrieval_is_latest.py -q`
Expected: FAIL — `ImportError: cannot import name '_candidates_stmt'`。

- [ ] **Step 3: 修改 `app/services/retrieval_service.py`** — 抽出 stmt 构造并加过滤

新增函数（放在 `_cosine_candidates` 之前）：
```python
def _candidates_stmt(q_vec: list[float], limit: int):
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page_num,
            Chunk.content,
            (1 - Chunk.embedding.cosine_distance(q_vec)).label("score"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.is_latest)
        .order_by(Chunk.embedding.cosine_distance(q_vec))
        .limit(limit)
    )
```
把 `_cosine_candidates` 里的 `stmt = (...)` 整段替换为：
```python
    stmt = _candidates_stmt(q_vec, limit)
```

- [ ] **Step 4: 运行确认通过 + 全量无回归**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/ -q`
Expected: 全部 passed。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/retrieval_service.py rag-backend/tests/unit/test_retrieval_is_latest.py
git commit -m "$(cat <<'EOF'
feat(p1a): retrieval pre-filters chunks.is_latest (default true, no-op now) (T6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 最终验收 gate

**Files:** 无新增（仅跑命令）。

- [ ] **Step 1: 全量单测**

Run: `cd rag-backend && DATABASE_URL=postgresql+psycopg://u:p@localhost:5435/db OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/pytest tests/unit/ -q`
Expected: 全绿（22 现存 + 本期新增，无 fail）。

- [ ] **Step 2: 迁移往返（需 Docker）**

Run: `cd rag-backend && .venv/bin/pytest tests/integration/test_migration_003.py -q`
Expected: `1 passed`（无 Docker 则 skipped）。

- [ ] **Step 3: ruff**

Run: `cd rag-backend && .venv/bin/ruff check app/models/ app/services/parsers/ app/services/ingestion_service.py app/services/retrieval_service.py tests/unit/test_models_p1a.py tests/unit/test_parser_confidence.py tests/unit/test_parser_section_path.py tests/unit/test_ingestion_metadata.py tests/unit/test_retrieval_is_latest.py tests/integration/`
Expected: `All checks passed!`

- [ ] **Step 4:（可选）真实 DB 冒烟** — `make up && cd rag-backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`，确认无错。

---

## Self-Review（对照 spec）

- **Spec 覆盖**：§3 迁移→T1/T2；§5 解析器 confidence→T3、section_path→T4；§6 入库写列→T5；§7 检索 is_latest→T6；§9 测试策略→各 task 测试 + T7；§4 决策（tsvector 不做/kb_id 预留/版本模型）→约束与迁移体现。全部有对应 task。
- **占位扫描**：无 TBD/TODO；每步含完整代码/命令/预期。
- **类型一致**：`build_chunk_rows` / `_chunk_units` / `_candidates_stmt` / `_KIND_TO_CHUNK_TYPE` 在 T5/T6 定义并被同名引用；`ParentChunk` 在 T1 定义，T2 迁移与之对齐（`parent_chunks` 表字段一致）。
- **留后项已明记**：父子块 chunker 重写 + 200 子块 + 父块扩展（去重/预算）+ tsvector 表达式索引 + 版本翻转逻辑 + 多租户逻辑 → P2/P4。
