# P2b — 混合检索（稠密 + zhparser 稀疏 + RRF）设计

> 日期：2026-07-24
> 阶段：PRD 全量对齐 · 第 2 阶段后半（P2b）
> 前置：P1a + P2a 已合并 main；**zhparser 基建已就绪并验证**（见 §2）
> 架构基底：扩展 Pipeline A；从 Pipeline B 移植 `rrf_fusion.py`

---

## 1. 背景与目标

P2a 把检索做成了「稠密子块 → rerank/阈值/去重 → 父块组装」。但纯稠密对**精确词/编号/专有名词**（如 `HT-2026-0087`、`星曜科技`）召回不稳。PRD F2.1 要求**混合检索**：稠密（语义）+ 稀疏（词面）经 RRF 融合。中文稀疏需分词——已确定用 Postgres `tsvector` + **zhparser**。

**P2b 目标**：`retrieve()` 并行做稠密余弦召回 + zhparser 稀疏召回，用 RRF 融合成一个候选集，再复用 P2a 的 rerank/阈值/去重/组装管线。

---

## 2. 基建（已完成，2026-07-24）

- `ubuntu-lan`（192.168.5.31）已装 Docker；自建镜像 `trace-rag/pg-zhparser:pg16`（`deploy/postgres-zhparser/`，pgvector + zhparser，源码 vendored）。
- 容器 `trace-rag-pg` 跑在 **192.168.5.31:5435**，卷持久化、`unless-stopped`。
- **已验证** `to_tsvector('zh', 中文)` 切出真实词。
- app 连接：`DATABASE_URL=postgresql+psycopg://raguser:ragpass@192.168.5.31:5435/ragdb`
- 迁移/E2E 直接对这台真实 DB 验证（不依赖本地 Docker）。

---

## 3. 范围

### 做（In）
1. 迁移：`CREATE EXTENSION zhparser` + `zh` 文本搜索配置 + `chunks.content` 的**表达式 GIN 索引** `gin(to_tsvector('zh', content))`。
2. 稀疏检索 `_sparse_candidates`：`to_tsvector('zh',content) @@ plainto_tsquery('zh',q)`，按 `ts_rank` 排序，`WHERE is_latest`。
3. RRF 融合：移植 B 的 `rrf_fusion.py`，适配 `RetrievedChunk` / chunk_id。
4. `retrieve()` 接线：稠密 + 稀疏 → RRF → 复用 P2a（rerank/阈值/去重/组装）。
5. 配置项 + 测试 + 对真实 DB 的迁移与中文稀疏 E2E。

### 不做（Out）
- **SPLADE 学习型稀疏** → 未来（zhparser 词面稀疏已满足 PRD F2.1 的混合检索）。
- 本地 BGE 重排、多跳、评估体系全量 → 后续阶段。
- **不建 STORED 生成列**：用表达式 GIN 索引（免建列、免大表重写、自动覆盖 P1a/P2a 存量数据）。

---

## 4. 迁移（`004_p2b_sparse`）

```
down_revision = "003_p1a_foundation"
upgrade:
  CREATE EXTENSION IF NOT EXISTS zhparser;
  -- zh 配置（幂等：存在则跳过）
  DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname='zh') THEN
      CREATE TEXT SEARCH CONFIGURATION zh (PARSER = zhparser);
      ALTER TEXT SEARCH CONFIGURATION zh ADD MAPPING FOR n,v,a,i,e,l,j,x,t,z WITH simple;
    END IF;
  END $$;
  CREATE INDEX ix_chunks_content_zh ON chunks USING gin (to_tsvector('zh', content));
downgrade:
  DROP INDEX ix_chunks_content_zh;
  -- 保留 zh 配置与扩展（其它对象可能引用；drop 风险大于收益），仅注释说明
```

- 表达式索引在 ADD 时对存量行构建，无需回填、无表重写。
- **验证**：对 192.168.5.31:5435 真实 DB `alembic upgrade head` / `downgrade`，确认索引建/删、`to_tsvector('zh',…)` 可用。testcontainers 版可选（需把镜像推到可拉取处，本期不做）。

---

## 5. 稀疏检索（`retrieval_service._sparse_candidates`）

```python
def _sparse_candidates(db, query, limit):
    tsq = func.plainto_tsquery('zh', query)
    tsv = func.to_tsvector('zh', Chunk.content)
    stmt = (
        select(Chunk.id, Chunk.document_id, Document.filename, Chunk.page_num,
               Chunk.content, Chunk.section_path, Chunk.parent_chunk_id, Chunk.embedding,
               func.ts_rank(tsv, tsq).label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.is_latest)
        .where(tsv.op("@@")(tsq))
        .order_by(func.ts_rank(tsv, tsq).desc())
        .limit(limit)
    )
    # -> list[RetrievedChunk]（与 _cosine_candidates 同构，score 是 ts_rank）
```

- 返回同构 `RetrievedChunk`，`score` 语义为 ts_rank（**仅用于稀疏侧内部排名**，RRF 只取 rank 不取分值，量纲不匹配无碍）。
- 稀疏无命中（中文查询无词面匹配）时返回 `[]`——RRF 退化为纯稠密。

---

## 6. RRF 融合（`retrieval_service._rrf_fuse`，移植自 B `rrf_fusion.py`）

```python
def _rrf_fuse(dense, sparse, k, dense_w, sparse_w):
    scores: dict[int, float] = {}
    rep: dict[int, RetrievedChunk] = {}
    for rank, c in enumerate(dense, 1):
        scores[c.chunk_id] = scores.get(c.chunk_id, 0) + dense_w * (1/(k+rank)); rep.setdefault(c.chunk_id, c)
    for rank, c in enumerate(sparse, 1):
        scores[c.chunk_id] = scores.get(c.chunk_id, 0) + sparse_w * (1/(k+rank)); rep.setdefault(c.chunk_id, c)
    fused = [rep[cid] for cid in sorted(scores, key=scores.get, reverse=True)]
    # 每个 chunk 的 RetrievedChunk.score 覆写为其 RRF 分（供下游可选阈值/日志）
    for c in fused: c.score = scores[c.chunk_id]
    return fused
```

- 纯 rank-based，稠密的余弦分与稀疏的 ts_rank 分**不参与**融合（只用名次），天然规避量纲问题。
- 代表 `RetrievedChunk` 取先出现者（含 parent_chunk_id/section_path/embedding，供 P2a 下游）。

---

## 7. `retrieve()` 接线（顺序即正确性）

```
1) q_vec = embed_query(q)
2) dense  = _cosine_candidates(db, q_vec, retrieval_candidate_k)
3) sparse = _sparse_candidates(db, q, sparse_candidate_k)   # zhparser
4) fused  = _rrf_fuse(dense, sparse, rrf_k, dense_weight, sparse_weight)   # RRF 分覆写 score
5) 若配 Cohere 且 fused>top_k: 重排(子块文本)，reranked=True（重排分覆写 score）
6) 若 reranked: _apply_threshold(rerank_min_score)   # 仅重排时套阈值（P2a 校准修复）
7) _dedup_by_embedding(dedup_cosine_threshold)
8) return [:top_k]
```

- **RRF 分不做阈值**（rank 融合分无绝对语义）；阈值仍只在 Cohere 重排（校准分）时生效——延续 P2a 的关键修复。
- Cohere 未配时：RRF → 去重 → top_k（不误拒）。
- 稠密/稀疏任一为空都安全：RRF 退化为另一路。

---

## 8. 新增配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `sparse_candidate_k` | 20 | 稀疏召回数 |
| `rrf_k` | 60 | RRF 标准常数 |
| `rrf_dense_weight` | 0.6 | 稠密权重 |
| `rrf_sparse_weight` | 0.4 | 稀疏权重 |
| `enable_sparse` | True | 关闭则纯稠密（无 zhparser 环境的降级开关）|

> `enable_sparse=False` 时 `retrieve()` 跳过稀疏与 RRF，行为等同 P2a——用于本地无 zhparser DB 的开发/测试。

---

## 9. 测试与验收

**单元（无 DB）**
1. `_rrf_fuse`：共享 chunk 名次靠前得分更高；单路为空时退化为另一路；代表块保留 parent/section/embedding。
2. `_sparse_candidates` 语句编译含 `to_tsvector('zh'`、`plainto_tsquery('zh'`、`@@`、`is_latest`、`ORDER BY ts_rank`、`LIMIT`。
3. `retrieve()`（mock 稠密/稀疏/rerank）：融合顺序、`enable_sparse=False` 走纯稠密、阈值仅重排时套用（延续 P2a 断言）。

**对真实 DB（192.168.5.31:5435）**
4. `alembic upgrade head` 建 zhparser 扩展 + zh 配置 + `ix_chunks_content_zh`；downgrade 删索引。
5. **中文稀疏 E2E**：插入含 `HT-2026-0087`/`星曜科技` 的 chunk，`_sparse_candidates` 用 `编号 星曜` 能命中（词面），验证 zhparser 分词生效。

---

## 10. 风险与非目标

| 风险 | 缓解 |
|---|---|
| 无 zhparser 环境跑 `to_tsvector('zh',…)` 报错 | `enable_sparse` 开关；纯稠密降级；迁移只在有 zhparser 的 DB 上跑 |
| 表达式 GIN 索引查询未命中索引 | `to_tsvector('zh',content)` 表达式需与索引表达式**逐字一致**才走索引——测试 + `EXPLAIN` 校验 |
| RRF 权重/召回数需调 | 用 P2a 的评估夹具（Precision@3）对比纯稠密 vs 混合，调 `rrf_*` |

**非目标**：SPLADE、本地 BGE、多跳、评估体系全量、多租户。

---

## 11. 完成标准（DoD）

- [ ] 迁移 `004` 在真实 DB up/down 通过（索引建/删、zh 配置可用）
- [ ] `_sparse_candidates` 语句编译断言通过
- [ ] `_rrf_fuse` 单元测试通过（退化/权重/代表块）
- [ ] `retrieve()` 混合接线测试通过（`enable_sparse` 开关、阈值仅重排）
- [ ] 中文稀疏 E2E：词面查询命中含编号/专名的 chunk
- [ ] 全量单测绿；改动文件 ruff 干净
- [ ] `deploy/postgres-zhparser/` 随本阶段提交（含 Dockerfile / init / README；vendored 源码大文件 gitignore + 下载脚本）
