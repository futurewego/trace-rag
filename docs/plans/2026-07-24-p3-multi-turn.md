# P3 串联多轮对话 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 含指代的多轮追问被改写为独立查询用于检索，同时把对话历史传给 LLM，使串联问答真正生效（PRD §2.1 场景 A / F3.1 / F3.2）。

**Architecture:** 扩展 Pipeline A。新增 `history_service`（读最近 N 轮消息）与 `query_rewriter`（同步版 LLM 指代消解，失败降级回原句）。`chat.py` 两端点改为：取历史 → 写入当前问句 → 改写 → **检索用改写后查询、生成用原始问句+历史**。`RetrievalLog` 增记 `original_query`。

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, Anthropic SDK（复用 `generation_service._client()`），pytest 8。

Spec：`docs/specs/2026-07-24-p3-multi-turn-design.md`

## Global Constraints

- **检索用改写后的查询；生成用原始问句 + 历史**（两者不可混淆）。
- **历史必须在写入当前 user Message 之前读取**，否则当前问句混入历史。
- `history` 为空 → `rewrite_query` **直接返回原句且不调用 LLM**（首轮零成本）。
- 改写任何异常/不合理 → 回落原句（PRD 降级 L5），绝不抛出。
- 合理性检查用**绝对上限** `rewrite_max_chars`，**禁止** `len(query)*3` 相对阈值（中文短问句「乙方呢」×3=9 字，正确改写必超，全部误杀——Pipeline B 的已知缺陷）。
- 三个既有不变量不得破坏：无 blocks 拒答且**不调 LLM**；低置信按 `reranked` 门控；`[N]` 引用映射基于 blocks 索引。
- 迁移 `005_p3_multi_turn`，`down_revision = "004_p2b_sparse"`，纯加列可空，真实库（192.168.5.31:5435）up/down 验证。
- 不引入 Redis/缓存；不做子查询分解/多跳/会话摘要（P7/后续）。
- 每个改动文件 `ruff check` 干净；沿用 `tests/unit/conftest.py`；报告套件失败必须验证是否本阶段引入（父提交对照）。
- 提交信息结尾：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## File Structure

**Create:**
- `rag-backend/app/services/history_service.py` — `get_history()`
- `rag-backend/app/services/query_rewriter.py` — `rewrite_query()` + `REWRITE_PROMPT`
- `rag-backend/alembic/versions/005_p3_multi_turn.py` — `retrieval_logs.original_query`
- `rag-backend/tests/unit/test_history_service.py`、`test_query_rewriter.py`、`test_chat_multi_turn.py`

**Modify:**
- `rag-backend/app/config.py` — 4 个配置项
- `rag-backend/app/models/retrieval_log.py` — `original_query` 列
- `rag-backend/app/services/generation_service.py` — 两个生成函数加 `history` 参数
- `rag-backend/app/api/v1/chat.py` — 两端点接线
- `rag-backend/tests/unit/test_generation_context.py` — 补历史相关断言

---

## Task 1: 配置项

**Files:**
- Modify: `rag-backend/app/config.py`
- Test: `rag-backend/tests/unit/test_config_p3.py`

**Interfaces:**
- Produces: `Settings.history_max_turns=5 / history_content_max_chars=500 / enable_query_rewrite=True / rewrite_max_chars=200`

- [ ] **Step 1: 写失败测试** — `tests/unit/test_config_p3.py`

```python
from app.config import get_settings


def test_p3_defaults():
    s = get_settings()
    assert s.history_max_turns == 5
    assert s.history_content_max_chars == 500
    assert s.enable_query_rewrite is True
    assert s.rewrite_max_chars == 200
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_config_p3.py -q`
Expected: FAIL — `AttributeError: ... 'history_max_turns'`

- [ ] **Step 3: 实现** — 在 `app/config.py` 的 `enable_sparse` 行之后插入

```python
    # Multi-turn conversation (P3)
    history_max_turns: int = 5
    history_content_max_chars: int = 500
    enable_query_rewrite: bool = True
    rewrite_max_chars: int = 200
```
（无需 alias：`case_sensitive=False` 下 pydantic-settings 按字段名匹配环境变量，`ENABLE_QUERY_REWRITE=false` 可直接覆盖——P2b 复核已证实。）

- [ ] **Step 4: 运行确认通过**

Run: 同 Step 2。Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/config.py rag-backend/tests/unit/test_config_p3.py
git commit -m "$(cat <<'EOF'
feat(p3): config — history window + query-rewrite knobs (T1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 迁移 005 + RetrievalLog 模型列

**Files:**
- Create: `rag-backend/alembic/versions/005_p3_multi_turn.py`
- Modify: `rag-backend/app/models/retrieval_log.py`

**Interfaces:**
- Consumes: 迁移头 `004_p2b_sparse`。
- Produces: `retrieval_logs.original_query`（Text, nullable）列 + ORM 属性 `RetrievalLog.original_query`。

- [ ] **Step 1: 创建迁移文件**

```python
"""P3 multi-turn: record the pre-rewrite original query on retrieval logs

Revision ID: 005_p3_multi_turn
Revises: 004_p2b_sparse
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005_p3_multi_turn"
down_revision = "004_p2b_sparse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # query 列存改写后的检索用查询；original_query 存用户原话。
    # P5 诊断"答得不好"时必须能区分"用户问得含糊"与"改写改坏了"。
    op.add_column("retrieval_logs", sa.Column("original_query", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("retrieval_logs", "original_query")
```

- [ ] **Step 2: ORM 模型加列** — `app/models/retrieval_log.py`，在现有 `query` 列之后插入

```python
    original_query: Mapped[str | None] = mapped_column(Text, nullable=True)
```
（确认文件已 import `Text` 与 `Mapped/mapped_column`——该文件既有列已在用；若无则补 import。）

- [ ] **Step 3: 单一迁移头校验**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -c "
import os; os.environ.setdefault('DATABASE_URL','postgresql+psycopg://u:p@127.0.0.1:1/x')
os.environ.setdefault('OPENAI_API_KEY','x'); os.environ.setdefault('ANTHROPIC_API_KEY','x')
from alembic.config import Config; from alembic.script import ScriptDirectory
print('heads:', ScriptDirectory.from_config(Config('alembic.ini')).get_heads())"`
Expected: `heads: ('005_p3_multi_turn',)`

- [ ] **Step 4: 真实库 up/down/up 验证**

Run:
```bash
cd rag-backend && for CMD in "upgrade head" "downgrade 004_p2b_sparse" "upgrade head"; do
  DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' \
  OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/alembic $CMD || break
done
ssh ubuntu-lan "sudo docker exec trace-rag-pg psql -U raguser -d ragdb -tAc \
  \"SELECT column_name FROM information_schema.columns WHERE table_name='retrieval_logs' AND column_name='original_query';\""
```
Expected: 三步 alembic 全部成功；最后 psql 输出 `original_query`。

- [ ] **Step 5: 全量单测无回归 + Commit**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全绿（模型加可空列不影响现有测试）。

```bash
git add rag-backend/alembic/versions/005_p3_multi_turn.py rag-backend/app/models/retrieval_log.py
git commit -m "$(cat <<'EOF'
feat(p3): alembic 005 — retrieval_logs.original_query (T2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: history_service

**Files:**
- Create: `rag-backend/app/services/history_service.py`
- Test: `rag-backend/tests/unit/test_history_service.py`

**Interfaces:**
- Consumes: `Message` 模型（`id/session_id/role/content` 列）。
- Produces: `get_history(db: Session, session_id: int, max_turns: int, content_max_chars: int) -> list[dict]` — 时间正序 `[{"role": ..., "content": ...}]`。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_history_service.py`

```python
from unittest.mock import MagicMock

from app.services.history_service import get_history


def _msg(mid, role, content):
    m = MagicMock()
    m.id, m.role, m.content = mid, role, content
    return m


def _db_returning(msgs_desc):
    """模拟 db.execute(...).scalars().all() 返回 id 倒序的消息列表。"""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = msgs_desc
    return db


def test_history_reversed_to_chronological_order():
    db = _db_returning([_msg(4, "assistant", "答2"), _msg(3, "user", "问2"),
                        _msg(2, "assistant", "答1"), _msg(1, "user", "问1")])
    out = get_history(db, session_id=7, max_turns=5, content_max_chars=500)
    assert [m["content"] for m in out] == ["问1", "答1", "问2", "答2"]
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]


def test_history_truncates_long_content():
    db = _db_returning([_msg(1, "assistant", "长" * 999)])
    out = get_history(db, session_id=7, max_turns=5, content_max_chars=100)
    assert len(out[0]["content"]) == 100


def test_history_empty_session_returns_empty():
    db = _db_returning([])
    assert get_history(db, session_id=7, max_turns=5, content_max_chars=500) == []


def test_history_limit_is_two_messages_per_turn():
    db = _db_returning([])
    get_history(db, session_id=7, max_turns=3, content_max_chars=500)
    stmt = db.execute.call_args.args[0]
    assert "LIMIT" in str(stmt.compile()).upper()
    assert stmt._limit_clause.value == 6  # 3 轮 = 6 条
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_history_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.history_service`

- [ ] **Step 3: 实现** — `app/services/history_service.py`

```python
"""读取会话历史，供 query 改写与生成共用。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Message


def get_history(
    db: Session, session_id: int, max_turns: int, content_max_chars: int
) -> list[dict]:
    """最近 max_turns 轮（=max_turns*2 条）消息，时间正序。

    必须在写入当前这轮 user Message 之前调用，否则当前问句会混入历史。
    以 id 倒序取最近 N 条再反转——id 自增即时间序，避免 created_at 同秒并列。
    """
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(max_turns * 2)
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {"role": m.role, "content": (m.content or "")[:content_max_chars]}
        for m in reversed(rows)
    ]
```

- [ ] **Step 4: 运行确认通过**

Run: 同 Step 2。Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/history_service.py rag-backend/tests/unit/test_history_service.py
git commit -m "$(cat <<'EOF'
feat(p3): history_service — recent turns in chronological order (T3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: query_rewriter（核心）

**Files:**
- Create: `rag-backend/app/services/query_rewriter.py`
- Test: `rag-backend/tests/unit/test_query_rewriter.py`

**Interfaces:**
- Consumes: `generation_service._client()`（lru_cache 的 Anthropic 客户端）、`Settings`（T1）。
- Produces: `rewrite_query(query: str, history: list[dict]) -> str`。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_query_rewriter.py`

```python
from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.services.query_rewriter import rewrite_query

HISTORY = [
    {"role": "user", "content": "HT-2026-0087 合同的甲方是谁？"},
    {"role": "assistant", "content": "甲方是星曜科技有限公司 [1]。"},
]


def _mock_client(text):
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text=text)]
    return client


@patch("app.services.query_rewriter._client")
def test_no_history_returns_original_without_llm(mock_client):
    assert rewrite_query("甲方是谁？", []) == "甲方是谁？"
    mock_client.assert_not_called()


@patch("app.services.query_rewriter._client")
def test_rewrites_coref_question(mock_client):
    mock_client.return_value = _mock_client("HT-2026-0087 合同的乙方是谁")
    assert rewrite_query("那乙方呢？", HISTORY) == "HT-2026-0087 合同的乙方是谁"


@patch("app.services.query_rewriter._client")
def test_short_chinese_query_long_rewrite_is_kept(mock_client):
    """锁死 Pipeline B 的 len*3 缺陷：3 字问句的 17 字正确改写必须保留。"""
    mock_client.return_value = _mock_client("HT-2026-0087 合同的乙方是谁")
    out = rewrite_query("乙方呢", HISTORY)
    assert out == "HT-2026-0087 合同的乙方是谁"


@patch("app.services.query_rewriter._client")
def test_llm_exception_falls_back(mock_client):
    mock_client.return_value.messages.create.side_effect = RuntimeError("api down")
    assert rewrite_query("那乙方呢？", HISTORY) == "那乙方呢？"


@patch("app.services.query_rewriter._client")
def test_overlong_rewrite_falls_back(mock_client):
    mock_client.return_value = _mock_client("废" * 300)
    assert rewrite_query("那乙方呢？", HISTORY) == "那乙方呢？"


@patch("app.services.query_rewriter._client")
def test_empty_rewrite_falls_back(mock_client):
    mock_client.return_value = _mock_client("   ")
    assert rewrite_query("那乙方呢？", HISTORY) == "那乙方呢？"


@patch("app.services.query_rewriter._client")
def test_multiline_rewrite_takes_first_line(mock_client):
    mock_client.return_value = _mock_client("HT-2026-0087 合同的乙方是谁\n\n解释：因为上一轮…")
    assert rewrite_query("那乙方呢？", HISTORY) == "HT-2026-0087 合同的乙方是谁"


@patch("app.services.query_rewriter._client")
def test_disabled_via_env_skips_llm(mock_client, monkeypatch):
    monkeypatch.setenv("ENABLE_QUERY_REWRITE", "false")
    get_settings.cache_clear()
    try:
        assert rewrite_query("那乙方呢？", HISTORY) == "那乙方呢？"
        mock_client.assert_not_called()
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_query_rewriter.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.query_rewriter`

- [ ] **Step 3: 实现** — `app/services/query_rewriter.py`

```python
"""多轮追问的查询改写（指代消解）。

改写只服务于【检索】：把"那乙方呢？"结合历史改写成"HT-2026-0087 合同的乙方是谁"
再去召回；生成侧仍使用用户原话 + 完整历史。任何失败都回落原句（PRD 降级 L5）。

与 Pipeline B 的 query_rewriter 三处刻意不同：
- 同步、无 Redis 缓存（同一"问题+历史"几乎不重复，不值得引入基建）；
- 合理性检查用绝对上限 rewrite_max_chars，不用 len(query)*3——中文短问句
  （"乙方呢"×3=9 字）会把所有正确改写误杀；
- 复用 generation_service._client()，不自建第二个 Anthropic 客户端。
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.services.generation_service import _client

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """你是一个查询改写助手。用户正在进行多轮对话，请根据对话历史，把当前问题改写为一个独立完整的检索查询。

要求：
1. 解析所有代词和指代（"它"、"这个"、"那个产品"、"呢"等）
2. 保留用户原本的意图，不要改变语义
3. 输出一个无需对话历史即可理解的独立查询
4. 只输出改写后的查询本身，不要任何解释或前缀

对话历史：
{history}

当前问题：{question}

改写后的查询："""


def rewrite_query(query: str, history: list[dict]) -> str:
    """把含指代的追问改写为独立检索查询；任何异常或不合理结果回落原 query。"""
    settings = get_settings()
    if not settings.enable_query_rewrite or not history:
        return query

    history_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}" for m in history
    )
    prompt = REWRITE_PROMPT.format(history=history_text, question=query)

    try:
        resp = _client().messages.create(
            model=settings.anthropic_model,
            max_tokens=256,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        rewritten = (resp.content[0].text or "").strip()
    except Exception as e:
        logger.warning("query rewrite failed, using original: %s", e)
        return query

    # 模型偶尔附带解释：只取首行
    rewritten = rewritten.splitlines()[0].strip() if rewritten else ""

    if not rewritten or len(rewritten) > settings.rewrite_max_chars:
        logger.warning(
            "query rewrite unreasonable (len=%d), using original", len(rewritten)
        )
        return query
    return rewritten
```

- [ ] **Step 4: 运行确认通过**

Run: 同 Step 2。Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/query_rewriter.py rag-backend/tests/unit/test_query_rewriter.py
git commit -m "$(cat <<'EOF'
feat(p3): sync query rewriter — coref resolution with fallback (T4)

Absolute-length sanity check instead of Pipeline B's len*3 (which killed every
correct rewrite of short Chinese questions).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 生成侧带历史

**Files:**
- Modify: `rag-backend/app/services/generation_service.py`
- Test: `rag-backend/tests/unit/test_generation_context.py`（追加）

**Interfaces:**
- Produces: `generate_answer(query, blocks, low_confidence=False, history=None)`；`generate_answer_stream(query, blocks, low_confidence=False, history=None)`。`history: list[dict] | None`。

- [ ] **Step 1: 写失败测试** — 追加到 `tests/unit/test_generation_context.py`

```python
def test_generate_answer_passes_history_before_user_prompt(monkeypatch):
    import app.services.generation_service as gen

    captured = {}

    class _FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            resp = MagicMock()
            resp.content = [MagicMock(text="回答 [1]")]
            return resp

    fake = MagicMock()
    fake.messages = _FakeMessages()
    monkeypatch.setattr(gen, "_client", lambda: fake)

    history = [
        {"role": "user", "content": "甲方是谁？"},
        {"role": "assistant", "content": "星曜科技 [1]。"},
    ]
    blocks = [_blk(1, "乙方为黄河智能装备厂")]
    gen.generate_answer("那乙方呢？", blocks, history=history)

    msgs = captured["messages"]
    assert msgs[0] == {"role": "user", "content": "甲方是谁？"}
    assert msgs[1] == {"role": "assistant", "content": "星曜科技 [1]。"}
    assert msgs[-1]["role"] == "user"
    assert "那乙方呢？" in msgs[-1]["content"]
    assert "<context>" in msgs[-1]["content"]


def test_generate_answer_no_blocks_refuses_even_with_history(monkeypatch):
    import app.services.generation_service as gen

    def _boom():
        raise AssertionError("client must not be constructed")

    monkeypatch.setattr(gen, "_client", _boom)
    answer, cites = gen.generate_answer(
        "那乙方呢？", [], history=[{"role": "user", "content": "x"}]
    )
    assert answer == "根据现有知识库无法回答这个问题。"
    assert cites == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_generation_context.py -q`
Expected: 新增第一条 FAIL —— `TypeError: generate_answer() got an unexpected keyword argument 'history'`。

- [ ] **Step 3: 实现** — `generation_service.py` 两个函数

`generate_answer` 改为：
```python
def generate_answer(
    query: str,
    blocks: list[ContextBlock],
    low_confidence: bool = False,
    history: list[dict] | None = None,
) -> tuple[str, list[Citation]]:
    if not blocks:
        return ("根据现有知识库无法回答这个问题。", [])

    settings = get_settings()
    user_prompt = _build_user_prompt(query, blocks)
    resp = _client().messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[*(history or []), {"role": "user", "content": user_prompt}],
    )
    answer = resp.content[0].text
    if low_confidence:
        answer = LOW_CONFIDENCE_NOTE + answer
    return (answer, _map_citations(answer, blocks))
```
`generate_answer_stream` 同样加 `history: list[dict] | None = None` 参数，`messages=[*(history or []), {"role": "user", "content": user_prompt}]`；拒答短路与低置信 yield 顺序**不动**。

- [ ] **Step 4: 运行确认通过 + 全量无回归**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/services/generation_service.py rag-backend/tests/unit/test_generation_context.py
git commit -m "$(cat <<'EOF'
feat(p3): generation accepts conversation history as native multi-turn messages (T5)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: chat.py 两端点接线

**Files:**
- Modify: `rag-backend/app/api/v1/chat.py`
- Test: `rag-backend/tests/unit/test_chat_multi_turn.py`

**Interfaces:**
- Consumes: `get_history`（T3）、`rewrite_query`（T4）、`generate_answer(_stream)` 的 `history` 参数（T5）、`RetrievalLog.original_query`（T2）。

- [ ] **Step 1: 写失败测试** — `tests/unit/test_chat_multi_turn.py`

```python
from unittest.mock import MagicMock, patch

import app.api.v1.chat as chat_mod
from app.api.v1.chat import ChatRequest, chat
from app.models import RetrievalLog


HISTORY = [{"role": "user", "content": "甲方是谁？"},
           {"role": "assistant", "content": "星曜科技 [1]。"}]


def _mock_db_with_session(session_id=7):
    db = MagicMock()
    fake_session = MagicMock()
    fake_session.id = session_id
    db.get.return_value = fake_session
    return db


@patch.object(chat_mod, "generate_answer", return_value=("答 [1]", []))
@patch.object(chat_mod, "is_low_confidence", return_value=False)
@patch.object(chat_mod, "assemble_context", return_value=[])
@patch.object(chat_mod, "retrieve", return_value=[])
@patch.object(chat_mod, "rewrite_query", return_value="HT-2026-0087 合同的乙方是谁")
@patch.object(chat_mod, "get_history", return_value=HISTORY)
def test_chat_uses_rewritten_for_retrieval_and_original_for_generation(
    mock_hist, mock_rw, mock_ret, mock_asm, mock_low, mock_gen
):
    db = _mock_db_with_session()
    chat(ChatRequest(session_id=7, message="那乙方呢？"), db)

    # 历史在写入当前问句之前读取
    assert mock_hist.call_args.args[1] == 7
    # 改写收到原句 + 历史
    mock_rw.assert_called_once_with("那乙方呢？", HISTORY)
    # 检索用改写后
    assert mock_ret.call_args.args[1] == "HT-2026-0087 合同的乙方是谁"
    # 生成用原句 + 历史
    gen_kwargs = mock_gen.call_args
    assert gen_kwargs.args[0] == "那乙方呢？"
    assert gen_kwargs.kwargs["history"] == HISTORY

    # RetrievalLog: query=改写后, original_query=原句
    logs = [c.args[0] for c in db.add.call_args_list
            if isinstance(c.args[0], RetrievalLog)]
    assert len(logs) == 1
    assert logs[0].query == "HT-2026-0087 合同的乙方是谁"
    assert logs[0].original_query == "那乙方呢？"


@patch.object(chat_mod, "generate_answer", return_value=("答", []))
@patch.object(chat_mod, "is_low_confidence", return_value=False)
@patch.object(chat_mod, "assemble_context", return_value=[])
@patch.object(chat_mod, "retrieve", return_value=[])
@patch.object(chat_mod, "rewrite_query", side_effect=lambda q, h: q)
@patch.object(chat_mod, "get_history", return_value=[])
def test_first_turn_behaves_like_before(
    mock_hist, mock_rw, mock_ret, mock_asm, mock_low, mock_gen
):
    db = _mock_db_with_session()
    chat(ChatRequest(session_id=7, message="甲方是谁？"), db)
    assert mock_ret.call_args.args[1] == "甲方是谁？"
    assert mock_gen.call_args.kwargs["history"] == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit/test_chat_multi_turn.py -q`
Expected: FAIL — `ImportError`/`AttributeError`（chat 模块尚无 `rewrite_query`/`get_history`）。

- [ ] **Step 3: 实现** — `chat.py` 两端点同构改造

imports 追加：
```python
from app.services.history_service import get_history
from app.services.query_rewriter import rewrite_query
```
`chat()` 的开头改为（**顺序即正确性**）：
```python
    session = _get_or_create_session(db, req)
    settings = get_settings()
    history = get_history(
        db, session.id, settings.history_max_turns, settings.history_content_max_chars
    )
    db.add(Message(session_id=session.id, role="user", content=req.message))
    db.flush()

    search_query = rewrite_query(req.message, history)

    t0 = time.perf_counter()
    retrieved = retrieve(db, search_query)
    retrieval_ms = int((time.perf_counter() - t0) * 1000)
```
（需在文件顶部补 `from app.config import get_settings`。）
生成调用改为 `generate_answer(req.message, blocks, low_conf, history=history)`。
`RetrievalLog(...)` 改为 `query=search_query, original_query=req.message, ...`。

`chat_stream()` 同构：取历史 → 写消息 → `search_query = rewrite_query(...)` → `retrieve(db, search_query)` → `generate_answer_stream(user_message, blocks, low_conf, history=history)`；`db2` 里的 `RetrievalLog` 同样 `query=search_query, original_query=user_message`（注意闭包里把 `search_query` 也捕获成局部变量，模式与现有 `user_message` 一致）。

- [ ] **Step 4: 运行确认通过 + 全量无回归**

Run: `cd rag-backend && env -u DATABASE_URL -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/pytest tests/unit -q`
Expected: 全绿。

- [ ] **Step 5: Commit**

```bash
git add rag-backend/app/api/v1/chat.py rag-backend/tests/unit/test_chat_multi_turn.py
git commit -m "$(cat <<'EOF'
feat(p3): chat endpoints — history-aware rewrite for retrieval, original+history for generation (T6)

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

- [ ] **Step 2: 集成迁移测试**

Run: `cd rag-backend && .venv/bin/pytest tests/integration -q`
Expected: `1 passed`（无 Docker 则 skipped）。

- [ ] **Step 3: ruff（P3 改动文件）**

Run: `cd rag-backend && .venv/bin/ruff check app/config.py app/models/retrieval_log.py app/services/history_service.py app/services/query_rewriter.py app/services/generation_service.py app/api/v1/chat.py alembic/versions/005_p3_multi_turn.py tests/unit/`
Expected: 仅剩既有债（`_cohere_client` ANN202、chat.py 既有 Depends/ANN），**无 P3 新引入**。

- [ ] **Step 4: 真实库迁移状态**

Run: `cd rag-backend && DATABASE_URL='postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb' OPENAI_API_KEY=x ANTHROPIC_API_KEY=x .venv/bin/alembic current`
Expected: `005_p3_multi_turn (head)`

---

## Self-Review（对照 spec）

- **Spec 覆盖**：§3 历史读取→T3；§4 改写（含三处 B 差异与短问句专项）→T4；§5 生成带历史→T5；§6 调用顺序（先取历史/检索用改写/生成用原句）→T6 及其测试断言；§7 配置→T1；§8 迁移→T2；§9 测试 1-10 → T4(1-6)/T3(7)/T5(8)/T6(9-10)。无缺口。
- **占位扫描**：无 TBD/TODO；每步含完整代码/命令/预期。
- **类型一致**：`get_history(db, session_id, max_turns, content_max_chars)`（T3）与 T6 调用一致；`rewrite_query(query, history)`（T4）与 T6 一致；`history: list[dict] | None`（T5）与 T6 的 kwarg 一致；`RetrievalLog.original_query`（T2）与 T6 写入一致。
- **既有不变量**：T5 Step1 第二条测试锁死「无 blocks 拒答且不构造 client」；低置信/引用映射未触碰。
