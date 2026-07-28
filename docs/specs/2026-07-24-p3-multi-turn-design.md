# P3 — 串联多轮对话（Query 改写 + 历史上下文）设计

> 日期：2026-07-24
> 阶段：PRD 全量对齐 · 第 3 阶段
> 前置：P1a + P2a 已合并 main；P2b 待合并
> 架构基底：扩展 Pipeline A；从未接线的 Pipeline B 移植 `query_rewriter` 的**思路**（不照搬实现）

---

## 1. 背景与目标

PRD §2.1 场景 A（串联式多轮问答）是**旗舰场景**，F3.1/F3.2 全是 P0。但现状：`chat.py` 两个端点都把**原始问句**直接送进 `retrieve()` 与 `generate_answer()`，`Message` 表里存了历史却**从未被读出来用过**。

结果：用户问「甲方是谁？」→「那乙方呢？」，第二问系统完全无法理解「那」，只会拿字面「那乙方呢」去检索——多轮追问实际不生效。

**P3 目标**：
1. **Query 改写**：把含指代/省略的追问，结合历史改写为独立完整的检索查询（PRD F3.2）。
2. **历史进生成**：把最近若干轮对话传给 LLM，让回答本身具备连续性（PRD F3.1）。
3. **改写失败降级**：改写异常/不合理 → 回落原始问句检索（PRD F3.2 明确要求，属降级链 L5）。

---

## 2. 范围

### 做（In）
1. `history_service`：按 session 读最近 N 轮消息（时间正序），供改写与生成共用。
2. `query_rewriter`（同步版）：LLM 指代消解 + 合理性校验 + 失败降级。
3. `retrieve()` 用**改写后**的查询；`generate_answer(_stream)` 接收**历史**并保持引用/拒答/低置信行为不变。
4. `RetrievalLog` 同时记录 `query`（改写后，实际检索用）与原始问句，便于 P5 排查。
5. 配置项 + 测试。

### 不做（Out）
- **子查询分解 / 多跳推理**（PRD F3.2 子查询、F3.3 4 跳）→ P7。
- **会话摘要压缩**（超 10 轮压成摘要）→ 本期只做定长窗口截断；等真实会话变长再做。
- **Redis 缓存改写结果** → 不做。同一「问题+历史」几乎不重复，缓存收益低却引入基建依赖。
- 前端多轮 UI 改造 → 前端并行线（本期后端已能支撑：`session_id` 已在 API 里）。

---

## 3. 历史读取（`app/services/history_service.py`）

```python
def get_history(db, session_id: int, max_turns: int) -> list[dict]:
    """返回最近 max_turns 轮的消息，时间正序：[{"role": "user"|"assistant", "content": str}, ...]

    一轮 = 一问一答，故取最近 max_turns*2 条消息。当前这一问已写入 Message 表，
    调用方需在写入【之前】取历史，或由本函数排除它——见 §6 调用顺序。
    """
```
- SQL：`WHERE session_id = :sid ORDER BY id DESC LIMIT :n` 再反转为正序（`id` 自增即时间序，避免依赖 `created_at` 的同秒并列）。
- 助手消息内容按 `history_content_max_chars` 截断（长回答会挤爆改写 prompt）。
- 新会话/无历史 → `[]`。

---

## 4. Query 改写（`app/services/query_rewriter.py`）

```python
def rewrite_query(query: str, history: list[dict]) -> str:
    """把含指代的追问改写为独立查询；任何异常或不合理结果都回落原始 query。"""
```

**行为规则（顺序即语义）**
1. `history` 为空 → **直接返回原 query**，不调 LLM（首轮零成本、零延迟）。
2. 构造 prompt（移植 B 的 `REWRITE_PROMPT` 中文版，要求：解析代词指代、不改变语义、只输出查询本身）。
3. 调 LLM：复用 `generation_service._client()`（已有 lru_cache 的 Anthropic 客户端），`max_tokens=256`、`temperature=0.0`。
4. **合理性校验**（不通过则回落原 query）：
   - 空或纯空白 → 回落
   - `len(rewritten) > rewrite_max_chars`（默认 200）→ 回落
   - 含换行符且首行以外仍有实质内容（模型在解释而非只输出查询）→ 取首行；首行为空则回落
5. **任何异常** → `logger.warning` + 回落原 query（PRD F5.1 降级 L5）。

**与 Pipeline B 实现的三处刻意差异**（B 的版本不能照搬）：
| B 的做法 | 本期做法 | 原因 |
|---|---|---|
| `async` + Redis 缓存 | 同步、无缓存 | 本项目是同步栈；改写缓存命中率极低，不值得引入 Redis 依赖 |
| 合理性检查 `len(rewritten) > len(query) * 3` | 绝对上限 `rewrite_max_chars` | **对中文短问句误伤严重**：「乙方呢」(3字) 阈值仅 9 字，而正确改写「HT-2026-0087 合同的乙方是谁」必然超限 → 好改写会被全部判为不合理 |
| 自建 `anthropic.AsyncAnthropic` | 复用 `generation_service._client()` | 避免第二个客户端与第二份 key 读取路径 |

---

## 5. 生成侧带历史（`generation_service`）

- `generate_answer(query, blocks, low_confidence, history=None)` / `generate_answer_stream(...)` 增加 `history` 参数（默认 `None`，向后兼容）。
- 历史以**多轮 messages** 形式传给 Anthropic（`messages=[*history, {"role":"user","content": user_prompt}]`），而不是拼进 system prompt——原生多轮格式更可靠。
- **不变量（必须保持）**：无 `blocks` 时仍旧**不调用 LLM**直接拒答；低置信提示逻辑不变；`[N]` 引用映射仍基于 `blocks` 索引。
- 历史里的 assistant 消息**不带 citations 结构**，只取纯文本（避免污染引用编号）。

---

## 6. 调用顺序（`chat.py` 两个端点，顺序即正确性）

```
1) session = _get_or_create_session(...)
2) history = get_history(db, session.id, max_turns)      # ← 必须在写入当前 user message 之前
3) db.add(Message(user, 当前问句)); db.flush()
4) search_query = rewrite_query(req.message, history)    # 无历史直接原样返回
5) retrieved = retrieve(db, search_query)                # ← 用改写后的查询
6) blocks = assemble_context(db, retrieved)
7) answer = generate_answer(req.message, blocks, low_conf, history=history)
                                ^^^^^^^^^^^^ 生成用【原始问句】+历史，检索用【改写后】
8) RetrievalLog(query=search_query, original_query=req.message, ...)
```

**两个关键点**：
- **检索用改写后、生成用原问句**：改写是为了让向量/词面检索命中，而 LLM 有完整历史，用原话回答更自然（改写句可能措辞生硬）。
- **历史必须在写入当前问句之前取**，否则当前问句会成为「历史」的一部分，改写 prompt 里出现重复。

---

## 7. 新增配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `history_max_turns` | 5 | 参与改写与生成的最近轮数（PRD 建议 10，先取 5 控成本，可调）|
| `history_content_max_chars` | 500 | 单条历史消息截断长度 |
| `enable_query_rewrite` | True | 关闭则始终用原始问句（降级开关 / A-B 对比用）|
| `rewrite_max_chars` | 200 | 改写结果长度上限，超出视为不合理 |

---

## 8. 数据模型改动

`retrieval_logs` 加一列 `original_query`（Text, nullable）——记录改写前的原始问句。迁移 `005_p3_multi_turn`，纯加列、可空、无回填、无表重写。

> 为什么值得加：P5 要诊断「答得不好」时，必须能区分「用户问得含糊」与「改写改坏了」。只存改写后的查询会丢掉这个信息。

---

## 9. 测试策略

**单元（mock LLM，无 DB）**
1. `rewrite_query` 无历史 → 原样返回且**不调用 LLM**（断言 client 未被调用）。
2. 有历史 → 返回改写结果（mock 返回「HT-2026-0087 合同的乙方是谁」）。
3. LLM 抛异常 → 回落原 query，不抛出。
4. 改写结果超长 / 空 / 多行解释 → 按 §4 规则回落或取首行。
5. `enable_query_rewrite=False` → 直接返回原 query，不调 LLM。
6. **中文短问句不误伤**：query=「乙方呢」、改写=「HT-2026-0087 合同的乙方是谁」→ **必须保留改写**（这条专门锁死 B 的 `len*3` 缺陷不被重新引入）。

**历史服务**
7. 按 session 取最近 N 轮、时间正序、超长内容被截断、空会话返回 `[]`。

**生成侧**
8. `history` 传入时进入 messages 数组且顺序正确；无 blocks 仍拒答且不调 LLM；`[N]` 引用映射不受历史影响。

**端点级**
9. 第二轮请求：`retrieve` 收到的是**改写后**查询、`generate_answer` 收到的是**原始**问句 + 历史；`RetrievalLog` 两个字段都对。
10. 首轮（无历史）行为与 P2b 完全一致（无回归）。

---

## 10. 风险与非目标

| 风险 | 缓解 |
|---|---|
| 改写引入一次额外 LLM 调用（延迟 + 成本）| 首轮不调；`enable_query_rewrite` 可关；`max_tokens=256` 限制 |
| 改写改坏语义导致检索更差 | 合理性校验 + 失败降级 + `original_query` 入库便于诊断；P5 用评估夹具量化 |
| 历史过长挤爆上下文 | `history_max_turns` + 单条截断；会话摘要压缩留待后续 |
| 与 P2b 的 RRF/阈值交互 | 改写只改**查询文本**，不碰检索管线；P2b 的所有不变量保持不变 |

**非目标**：子查询分解、多跳、会话摘要压缩、前端改造、评估体系全量。

---

## 11. 完成标准（DoD）

- [ ] 无历史时零 LLM 调用、行为与 P2b 一致
- [ ] 含指代的追问被改写为独立查询，检索用改写后、生成用原问句 + 历史
- [ ] 中文短问句改写不被合理性检查误伤（专项测试）
- [ ] 改写失败/不合理 → 回落原问句，不抛出
- [ ] `enable_query_rewrite=False` 完全绕过改写
- [ ] 迁移 005 加 `original_query` 列，真实库 up/down 验证
- [ ] 拒答 / 低置信 / 引用映射三个既有不变量不受影响
- [ ] 全量单测绿；改动文件 ruff 干净
