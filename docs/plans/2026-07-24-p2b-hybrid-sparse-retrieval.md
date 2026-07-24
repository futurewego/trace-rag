# P2b 混合检索（稠密 + zhparser 稀疏 + RRF）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `retrieve()` 同时做稠密余弦召回与 zhparser 中文稀疏召回，用 RRF 融合后复用 P2a 的 rerank/阈值/去重/组装管线。

**Architecture:** 扩展 Pipeline A。稀疏侧用 Postgres `to_tsvector('zh', content)` + 表达式 GIN 索引（免建列、免大表重写、自动覆盖存量）。融合用纯 rank-based RRF——余弦分与 ts_rank 分只用名次不用分值，天然规避量纲不匹配。阈值仍只在 Cohere 校准分时生效（延续 P2a 的关键修复）。

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, PostgreSQL 16 + pgvector + zhparser, pytest 8。

Spec：`docs/specs/2026-07-24-p2b-hybrid-sparse-retrieval-design.md`

## Global Constraints

- **RRF 是 rank-based**：融合只用名次，绝不把余弦分与 ts_rank 分直接相加/比较。
- **RRF 分不做阈值**：`_apply_threshold` 仍**只在 `reranked=True`（Cohere 校准分）时**套用。纯稠密/纯 RRF 路径不得因阈值误拒（P2a 已修复的回归，不得倒退）。
- 稀疏 SQL 里的 `to_tsvector('zh', content)` 表达式必须与迁移建的索引表达式**逐字一致**，否则不走 GIN 索引。
- 稀疏或稠密任一路为空，RRF 必须安全退化为另一路；两路皆空返回 `[]`（由生成侧拒答）。
- `enable_sparse=False` 时跳过稀疏与 RRF，行为等同 P2a（供无 zhparser 环境）。
- 稀疏 SELECT 必须带 `WHERE Chunk.is_latest`（与稠密一致）。
- 融合后的 `RetrievedChunk` 必须保留 `parent_chunk_id / section_path / embedding`（P2a 下游依赖）。
- 真实 DB 验证目标：`postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb`（zhparser 已就绪）。
- 每个改动文件 `ruff check` 干净；沿用 `tests/unit/conftest.py`。
- 提交信息结尾：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## File Structure

**Create:**
- `rag-backend/alembic/versions/004_p2b_sparse.py` — zhparser 扩展 + zh 配置 + 表达式 GIN 索引
- `rag-backend/tests/unit/test_rrf_fusion.py`、`rag-backend/tests/unit/test_sparse_retrieval.py`、`rag-backend/tests/unit/test_hybrid_retrieve.py`
- `rag-backend/scripts/verify_sparse.py` — 对真实 zhparser DB 的迁移与中文稀疏验证脚本

**Modify:**
- `rag-backend/app/config.py` — 5 个新配置项
- `rag-backend/app/services/retrieval_service.py` — `_sparse_candidates` / `_rrf_fuse` / `retrieve()` 接线
- `deploy/postgres-zhparser/` — 随本阶段提交（Dockerfile / init SQL / README / vendored 源码）

---

## Task 1: 配置项 + deploy 产物入库

**Files:**
- Modify: `rag-backend/app/config.py`
- Add: `deploy/postgres-zhparser/**`（已在工作区，本任务纳入版本控制）
- Test: `rag-backend/tests/unit/test_config_p2b.py`

**Interfaces:**
- Produces: `Settings.sparse_candidate_k / rrf_k / rrf_dense_weight / rrf_sparse_weight / enable_sparse`

- [ ] **Step 1: 写失败测试** — `tests/unit/test_config_p2b.py`

```python
from app.config import get_settings


def test_p2b_defaults():
    s = get_settings()
    assert s.sparse_candidate_k == 20
    assert s.rrf_k == 60
    assert s.rrf_dense_weight == 0.6
    assert s.rrf_sparse_weight == 0.4
    assert s.enable_sparse is True
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_config_p2b.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'sparse_candidate_k'`

- [ ] **Step 3: 实现** — 在 `app/config.py` 的 `context_token_budget` 行之后插入

```python
    # Hybrid sparse retrieval (P2b)
    sparse_candidate_k: int = 20
    rrf_k: int = 60
    rrf_dense_weight: float = 0.6
    rrf_sparse_weight: float = 0.4
    enable_sparse: bool = True
```

- [ ] **Step 4: 运行确认通过**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_config_p2b.py -q`
Expected: `1 passed`

- [ ] **Step 5: 把 deploy 产物纳入版本控制**

`deploy/postgres-zhparser/` 已存在于工作区（Dockerfile / init-extensions.sql / README.md / vendor/scws-1.2.3.tar.bz2 / vendor/zhparser.tar.gz）。**vendored 源码要一并提交**——构建主机 ubuntu-lan 无法访问 GitHub，源码入库才能让镜像构建自包含可复现（约 6.5MB）。

Run: `cd /Users/marvin/data/ai_workspaces/trace-rag && ls -la deploy/postgres-zhparser deploy/postgres-zhparser/vendor`
Expected: 5 个文件都在。

- [ ] **Step 6: Commit**

```bash
git add rag-backend/app/config.py rag-backend/tests/unit/test_config_p2b.py deploy/postgres-zhparser
git commit -m "$(cat <<'EOF'
feat(p2b): config for hybrid sparse retrieval + pg-zhparser image build context (T1)

Vendors scws/zhparser sources because the build host cannot reach GitHub.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 迁移 004 — zhparser 扩展 + zh 配置 + 表达式 GIN 索引

**Files:**
- Create: `rag-backend/alembic/versions/004_p2b_sparse.py`

**Interfaces:**
- Consumes: 迁移链头 `003_p1a_foundation`
- Produces: DB 中的 `zh` 文本搜索配置与索引 `ix_chunks_content_zh`

- [ ] **Step 1: 创建迁移文件**

```python
"""P2b sparse retrieval: zhparser extension + zh config + expression GIN index

Revision ID: 004_p2b_sparse
Revises: 003_p1a_foundation
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op

revision = "004_p2b_sparse"
down_revision = "003_p1a_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # zhparser must be present in the image (deploy/postgres-zhparser).
    op.execute("CREATE EXTENSION IF NOT EXISTS zhparser")

    # 'zh' text-search configuration (idempotent).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'zh') THEN
                CREATE TEXT SEARCH CONFIGURATION zh (PARSER = zhparser);
                ALTER TEXT SEARCH CONFIGURATION zh
                    ADD MAPPING FOR n,v,a,i,e,l,j,x,t,z WITH simple;
            END IF;
        END
        $$
        """
    )

    # Expression GIN index: no new column, no table rewrite, covers existing rows.
    # The retrieval query MUST use the identical expression to hit this index.
    op.execute(
        "CREATE INDEX ix_chunks_content_zh ON chunks "
        "USING gin (to_tsvector('zh', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_zh")
    # The 'zh' configuration and the zhparser extension are intentionally kept:
    # other objects may reference them and dropping is riskier than leaving them.
```

- [ ] **Step 2: 校验迁移链单一头**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -c "
import os; os.environ.setdefault('DATABASE_URL','postgresql+psycopg://u:p@127.0.0.1:1/x')
os.environ.setdefault('OPENAI_API_KEY','x'); os.environ.setdefault('ANTHROPIC_API_KEY','x')
from alembic.config import Config; from alembic.script import ScriptDirectory
sd = ScriptDirectory.from_config(Config('alembic.ini')); print('heads:', sd.get_heads())
"`
Expected: `heads: ('004_p2b_sparse',)` —— 单一头，链完整。

- [ ] **Step 3: 对真实 zhparser DB 跑迁移**

Run:
```bash
cd rag-backend && DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' \
  OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/alembic upgrade head
```
Expected: 无错误。若报 `zhparser` 扩展缺失，说明连错库（该 DB 由 `deploy/postgres-zhparser` 镜像提供）。

- [ ] **Step 4: 验证索引与配置存在**

Run:
```bash
ssh ubuntu-lan "sudo docker exec trace-rag-pg psql -U raguser -d ragdb -tAc \
  \"SELECT indexname FROM pg_indexes WHERE indexname='ix_chunks_content_zh'; \
    SELECT cfgname FROM pg_ts_config WHERE cfgname='zh';\""
```
Expected: 输出 `ix_chunks_content_zh` 与 `zh`。

- [ ] **Step 5: 验证 downgrade 删索引后再 upgrade 回来**

Run:
```bash
cd rag-backend && DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' \
  OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/alembic downgrade 003_p1a_foundation && \
  DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' \
  OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/alembic upgrade head
```
Expected: 两步都成功；downgrade 后索引消失、upgrade 后重建。

- [ ] **Step 6: Commit**

```bash
git add rag-backend/alembic/versions/004_p2b_sparse.py
git commit -m "$(cat <<'EOF'
feat(p2b): alembic 004 — zhparser ext + zh config + expression GIN index (T2)

Expression index (not a STORED column): no table rewrite, covers existing rows.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 稀疏检索 `_sparse_candidates`

**Files:**
- Modify: `rag-backend/app/services/retrieval_service.py`
- Test: `rag-backend/tests/unit/test_sparse_retrieval.py`

**Interfaces:**
- Consumes: `Chunk`/`Document` 模型、`Settings`
- Produces: `_sparse_stmt(query: str, limit: int) -> Select`；`_sparse_candidates(db: Session, query: str, limit: int) -> list[RetrievedChunk]`

- [ ] **Step 1: 写失败测试** — `tests/unit/test_sparse_retrieval.py`

```python
from sqlalchemy.dialects import postgresql

from app.services.retrieval_service import _sparse_stmt


def _sql() -> str:
    return str(_sparse_stmt("合同 编号", 20).compile(dialect=postgresql.dialect()))


def test_sparse_stmt_uses_zh_tsvector_and_tsquery():
    sql = _sql()
    assert "to_tsvector" in sql
    assert "plainto_tsquery" in sql
    assert "@@" in sql


def test_sparse_stmt_filters_is_latest_and_limits():
    sql = _sql()
    assert "is_latest" in sql
    assert "LIMIT" in sql.upper()


def test_sparse_stmt_orders_by_rank_desc():
    sql = _sql()
    assert "ts_rank" in sql
    assert "DESC" in sql.upper()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_sparse_retrieval.py -q`
Expected: FAIL — `ImportError: cannot import name '_sparse_stmt'`

- [ ] **Step 3: 实现** — 在 `retrieval_service.py` 的 `_cosine_candidates` 之后插入

顶部 import 补 `func`：把 `from sqlalchemy import Select, select` 改为 `from sqlalchemy import Select, func, select`。

```python
# NOTE: this expression must stay byte-identical to the one in migration 004's
# `CREATE INDEX ... USING gin (to_tsvector('zh', content))`, otherwise Postgres
# will not use the GIN index.
def _zh_tsvector():
    return func.to_tsvector("zh", Chunk.content)


def _sparse_stmt(query: str, limit: int) -> Select:
    tsq = func.plainto_tsquery("zh", query)
    tsv = _zh_tsvector()
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page_num,
            Chunk.content,
            Chunk.section_path,
            Chunk.parent_chunk_id,
            Chunk.embedding,
            func.ts_rank(tsv, tsq).label("score"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.is_latest)
        .where(tsv.op("@@")(tsq))
        .order_by(func.ts_rank(tsv, tsq).desc())
        .limit(limit)
    )


def _sparse_candidates(
    db: Session, query: str, limit: int
) -> list[RetrievedChunk]:
    """zhparser 词面召回。无匹配时返回 []（RRF 会退化为纯稠密）。"""
    rows = db.execute(_sparse_stmt(query, limit)).all()
    return [
        RetrievedChunk(
            chunk_id=r.id,
            doc_id=r.document_id,
            filename=r.filename,
            page_num=r.page_num,
            content=r.content,
            score=float(r.score),
            section_path=r.section_path,
            parent_chunk_id=r.parent_chunk_id,
            embedding=list(r.embedding) if r.embedding is not None else None,
        )
        for r in rows
    ]
```

- [ ] **Step 4: 运行确认通过**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_sparse_retrieval.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/retrieval_service.py rag-backend/tests/unit/test_sparse_retrieval.py
git commit -m "$(cat <<'EOF'
feat(p2b): zhparser sparse retrieval candidates (T3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: RRF 融合 `_rrf_fuse`

**Files:**
- Modify: `rag-backend/app/services/retrieval_service.py`
- Test: `rag-backend/tests/unit/test_rrf_fusion.py`

**Interfaces:**
- Produces: `_rrf_fuse(dense: list[RetrievedChunk], sparse: list[RetrievedChunk], k: int, dense_w: float, sparse_w: float) -> list[RetrievedChunk]`

- [ ] **Step 1: 写失败测试** — `tests/unit/test_rrf_fusion.py`

```python
from app.services.retrieval_service import RetrievedChunk, _rrf_fuse


def _rc(cid: int, score: float = 0.0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, doc_id=1, filename="a.pdf", page_num=1, content=f"c{cid}",
        score=score, section_path=["S"], parent_chunk_id=cid * 10, embedding=[0.1],
    )


def test_chunk_in_both_lists_outranks_single_list_chunks():
    dense = [_rc(1), _rc(2)]
    sparse = [_rc(3), _rc(1)]
    fused = _rrf_fuse(dense, sparse, k=60, dense_w=0.6, sparse_w=0.4)
    assert fused[0].chunk_id == 1  # 两路都命中 -> RRF 分最高


def test_empty_sparse_degrades_to_dense_order():
    dense = [_rc(1), _rc(2), _rc(3)]
    fused = _rrf_fuse(dense, [], k=60, dense_w=0.6, sparse_w=0.4)
    assert [c.chunk_id for c in fused] == [1, 2, 3]


def test_empty_dense_degrades_to_sparse_order():
    sparse = [_rc(7), _rc(8)]
    fused = _rrf_fuse([], sparse, k=60, dense_w=0.6, sparse_w=0.4)
    assert [c.chunk_id for c in fused] == [7, 8]


def test_both_empty_returns_empty():
    assert _rrf_fuse([], [], k=60, dense_w=0.6, sparse_w=0.4) == []


def test_representative_keeps_downstream_fields():
    fused = _rrf_fuse([_rc(5)], [], k=60, dense_w=0.6, sparse_w=0.4)
    c = fused[0]
    assert c.parent_chunk_id == 50
    assert c.section_path == ["S"]
    assert c.embedding == [0.1]


def test_score_is_overwritten_with_rrf_score():
    fused = _rrf_fuse([_rc(1, score=0.99)], [], k=60, dense_w=0.6, sparse_w=0.4)
    assert fused[0].score == 0.6 * (1 / 61)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_rrf_fusion.py -q`
Expected: FAIL — `ImportError: cannot import name '_rrf_fuse'`

- [ ] **Step 3: 实现** — 在 `_sparse_candidates` 之后插入

```python
def _rrf_fuse(
    dense: list[RetrievedChunk],
    sparse: list[RetrievedChunk],
    k: int,
    dense_w: float,
    sparse_w: float,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion —— 只用名次，不用分值。

    稠密的余弦分与稀疏的 ts_rank 分量纲不可比，RRF 以 1/(k+rank) 加权求和天然
    规避该问题。任一路为空即安全退化为另一路。融合后 score 覆写为 RRF 分。
    """
    scores: dict[int, float] = {}
    rep: dict[int, RetrievedChunk] = {}

    for weight, results in ((dense_w, dense), (sparse_w, sparse)):
        for rank, c in enumerate(results, start=1):
            scores[c.chunk_id] = scores.get(c.chunk_id, 0.0) + weight / (k + rank)
            rep.setdefault(c.chunk_id, c)

    fused: list[RetrievedChunk] = []
    for cid in sorted(scores, key=lambda i: scores[i], reverse=True):
        c = rep[cid]
        c.score = scores[cid]
        fused.append(c)
    return fused
```

- [ ] **Step 4: 运行确认通过**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_rrf_fusion.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/retrieval_service.py rag-backend/tests/unit/test_rrf_fusion.py
git commit -m "$(cat <<'EOF'
feat(p2b): rank-based RRF fusion of dense + sparse candidates (T4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `retrieve()` 混合接线

**Files:**
- Modify: `rag-backend/app/services/retrieval_service.py`
- Test: `rag-backend/tests/unit/test_hybrid_retrieve.py`

**Interfaces:**
- Consumes: `_cosine_candidates`（既有）、`_sparse_candidates`（T3）、`_rrf_fuse`（T4）、`_apply_threshold`/`_dedup_by_embedding`（P2a）
- Produces: 混合版 `retrieve()`

- [ ] **Step 1: 写失败测试** — `tests/unit/test_hybrid_retrieve.py`

```python
from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.services.retrieval_service import RetrievedChunk, retrieve


def _rc(cid: int, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, doc_id=1, filename="a.pdf", page_num=1, content=f"c{cid}",
        score=score, section_path=None, parent_chunk_id=None, embedding=None,
    )


@patch("app.services.retrieval_service._sparse_candidates")
@patch("app.services.retrieval_service._cosine_candidates")
@patch("app.services.retrieval_service.embed_query", return_value=[0.0] * 1536)
def test_hybrid_fuses_dense_and_sparse(mock_embed, mock_dense, mock_sparse, monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "")
    get_settings.cache_clear()
    mock_dense.return_value = [_rc(1, 0.9), _rc(2, 0.8)]
    mock_sparse.return_value = [_rc(3, 0.7), _rc(1, 0.6)]

    out = retrieve(MagicMock(), "合同编号", top_k=5)

    mock_sparse.assert_called_once()
    assert out[0].chunk_id == 1          # 两路都命中 -> 融合后第一
    assert {c.chunk_id for c in out} == {1, 2, 3}
    get_settings.cache_clear()


@patch("app.services.retrieval_service._sparse_candidates")
@patch("app.services.retrieval_service._cosine_candidates")
@patch("app.services.retrieval_service.embed_query", return_value=[0.0] * 1536)
def test_enable_sparse_false_skips_sparse(mock_embed, mock_dense, mock_sparse, monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "")
    monkeypatch.setenv("ENABLE_SPARSE", "false")
    get_settings.cache_clear()
    mock_dense.return_value = [_rc(1, 0.9)]

    out = retrieve(MagicMock(), "合同编号", top_k=5)

    mock_sparse.assert_not_called()
    assert [c.chunk_id for c in out] == [1]
    get_settings.cache_clear()


@patch("app.services.retrieval_service._sparse_candidates", return_value=[])
@patch("app.services.retrieval_service._cosine_candidates")
@patch("app.services.retrieval_service.embed_query", return_value=[0.0] * 1536)
def test_low_scores_survive_without_cohere(mock_embed, mock_dense, mock_sparse, monkeypatch):
    """无 Cohere 时不得因 rerank 阈值误拒（P2a 修复不可倒退）。"""
    monkeypatch.setenv("COHERE_API_KEY", "")
    get_settings.cache_clear()
    mock_dense.return_value = [_rc(1, 0.2), _rc(2, 0.3)]

    out = retrieve(MagicMock(), "查询", top_k=5)

    assert {c.chunk_id for c in out} == {1, 2}
    get_settings.cache_clear()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_hybrid_retrieve.py -q`
Expected: FAIL — 稀疏未接线（`_sparse_candidates` 未被调用 / 融合顺序不符）。

- [ ] **Step 3: 实现** — 完整替换 `retrieve()`

`config.py` 的 `enable_sparse` 需可由 env 覆盖，改为：
```python
    enable_sparse: bool = Field(True, alias="ENABLE_SPARSE")
```

```python
def retrieve(db: Session, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    settings = get_settings()
    top_k = top_k or settings.top_k

    q_vec = embed_query(query)
    use_rerank = bool(settings.cohere_api_key)
    candidate_n = settings.retrieval_candidate_k if use_rerank else top_k

    dense = _cosine_candidates(db, q_vec, limit=candidate_n)

    # Hybrid: fuse dense with zhparser sparse hits by RANK (scores are not
    # comparable across the two retrievers). Either side may be empty.
    if settings.enable_sparse:
        sparse = _sparse_candidates(db, query, limit=settings.sparse_candidate_k)
        candidates = _rrf_fuse(
            dense, sparse,
            k=settings.rrf_k,
            dense_w=settings.rrf_dense_weight,
            sparse_w=settings.rrf_sparse_weight,
        )
    else:
        candidates = dense

    reranked = False
    if use_rerank and len(candidates) > top_k:
        try:
            candidates = _rerank_with_cohere(query, candidates, top_n=candidate_n)
            reranked = True
        except Exception as e:
            logger.warning("cohere rerank failed, fallback to fused order: %s", e)

    # rerank_min_score is calibrated for Cohere relevance (0..1) — NOT for cosine
    # and NOT for RRF scores (which are rank-derived and have no absolute meaning).
    # Apply the hard threshold only when rerank actually produced the scores.
    if reranked:
        candidates = _apply_threshold(candidates, settings.rerank_min_score)
    candidates = _dedup_by_embedding(candidates, settings.dedup_cosine_threshold)
    return candidates[:top_k]
```

- [ ] **Step 4: 运行确认通过 + 全量无回归**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全绿（含 P2a 既有的阈值/去重/组装测试）。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/config.py rag-backend/app/services/retrieval_service.py rag-backend/tests/unit/test_hybrid_retrieve.py
git commit -m "$(cat <<'EOF'
feat(p2b): retrieve() fuses dense + zhparser sparse via RRF (T5)

RRF scores are rank-derived, so the Cohere-calibrated threshold still only
applies when rerank actually ran.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 对真实 zhparser DB 的中文稀疏验证

**Files:**
- Create: `rag-backend/scripts/verify_sparse.py`

**Interfaces:**
- Consumes: `_sparse_candidates`（T3）、迁移 004（T2）

- [ ] **Step 1: 写验证脚本** — `rag-backend/scripts/verify_sparse.py`

```python
"""对真实 zhparser 库验证中文稀疏检索（需迁移 004 已执行）。

用法：
    DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' \
    OPENAI_API_KEY=x ANTHROPIC_API_KEY=x \
    .venv/bin/python -m scripts.verify_sparse
"""
from __future__ import annotations

from sqlalchemy import text

from app.dependencies import _SessionLocal
from app.services.retrieval_service import _sparse_candidates

DOC_SQL = """
INSERT INTO documents (filename, file_hash, file_path, file_size, status, chunk_count)
VALUES ('p2b_probe.pdf', 'p2b-probe-hash', '/tmp/p2b_probe.pdf', 1, 'indexed', 1)
ON CONFLICT (file_hash) DO UPDATE SET filename = EXCLUDED.filename
RETURNING id
"""

CHUNK_SQL = """
INSERT INTO chunks (document_id, chunk_index, content, page_num, token_count,
                    embedding, chunk_type, is_latest)
VALUES (:doc_id, 0,
        '星曜科技有限公司与黄河智能装备厂签订合同，合同编号 HT-2026-0087，金额壹佰贰拾伍万元。',
        1, 40, :vec, 'text', true)
RETURNING id
"""


def main() -> None:
    with _SessionLocal() as db:
        doc_id = db.execute(text(DOC_SQL)).scalar_one()
        vec = "[" + ",".join(["0"] * 1536) + "]"
        chunk_id = db.execute(
            text(CHUNK_SQL), {"doc_id": doc_id, "vec": vec}
        ).scalar_one()
        db.commit()
        print(f"probe doc={doc_id} chunk={chunk_id}")

        for q in ["合同编号", "星曜科技", "黄河智能装备", "HT-2026-0087"]:
            hits = _sparse_candidates(db, q, limit=5)
            ok = any(h.chunk_id == chunk_id for h in hits)
            print(f"query={q!r:20} hits={len(hits)} matched_probe={ok}")

        # cleanup
        db.execute(text("DELETE FROM chunks WHERE id = :cid"), {"cid": chunk_id})
        db.execute(text("DELETE FROM documents WHERE id = :did"), {"did": doc_id})
        db.commit()
        print("probe rows cleaned up")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 对真实库运行**

Run:
```bash
cd rag-backend && DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' \
  OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/python -m scripts.verify_sparse
```
Expected: 四个中文/编号查询里**至少 `合同编号` 与 `星曜科技` 命中探针 chunk**（`matched_probe=True`），证明 zhparser 分词 + 表达式 GIN 索引 + `_sparse_candidates` 全链路生效；末尾打印 `probe rows cleaned up`。

- [ ] **Step 3: 确认查询走了 GIN 索引**

Run:
```bash
ssh ubuntu-lan "sudo docker exec trace-rag-pg psql -U raguser -d ragdb -c \
  \"EXPLAIN SELECT id FROM chunks WHERE to_tsvector('zh', content) @@ plainto_tsquery('zh','合同编号');\""
```
Expected: 计划中出现 `Bitmap Index Scan on ix_chunks_content_zh`（若为 Seq Scan，说明查询表达式与索引表达式不一致，需修 T3 的 `_zh_tsvector`）。

- [ ] **Step 4: ruff + 提交**

Run: `cd rag-backend && .venv/bin/ruff check scripts/verify_sparse.py`
Expected: `All checks passed!`

```bash
git add rag-backend/scripts/verify_sparse.py
git commit -m "$(cat <<'EOF'
test(p2b): real-DB Chinese sparse retrieval probe against zhparser (T6)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 最终验收 gate

**Files:** 无新增（仅跑命令）。

- [ ] **Step 1: 全量单测**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全绿。

- [ ] **Step 2: ruff（P2b 改动文件）**

Run: `cd rag-backend && .venv/bin/ruff check app/config.py app/services/retrieval_service.py alembic/versions/004_p2b_sparse.py scripts/ tests/unit/`
Expected: 仅剩既有债（`_db_scope`/`_cohere_client` ANN202、chat.py 的 FastAPI Depends/ANN、docx.py SIM108），**无 P2b 新引入错误**。

- [ ] **Step 3: 迁移状态确认**

Run:
```bash
cd rag-backend && DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' \
  OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/alembic current
```
Expected: `004_p2b_sparse (head)`

---

## Self-Review（对照 spec）

- **Spec 覆盖**：§4 迁移→T2；§5 稀疏检索→T3；§6 RRF→T4；§7 接线→T5；§8 配置→T1；§9 测试（单元 1-3 → T3/T4/T5；真实 DB 4-5 → T2/T6）；§11 DoD 中 deploy 产物入库→T1 Step 5。全部有对应 task。
- **占位扫描**：无 TBD/TODO；每步含完整代码/命令/预期。
- **类型一致**：`_zh_tsvector`/`_sparse_stmt`/`_sparse_candidates`（T3）被 T5、T6 引用；`_rrf_fuse`（T4）签名与 T5 调用一致；`RetrievedChunk` 沿用 P2a 字段（含 parent_chunk_id/section_path/embedding）。
- **关键不倒退项**：T5 的测试显式断言「无 Cohere 时低分不被误拒」，锁住 P2a 终审修复的回归。
