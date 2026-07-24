# P2a — 父子块（small-to-big）与上下文组装 设计

> 日期：2026-07-23
> 阶段：PRD 全量对齐 · 第 2 阶段前半（P2 按风险拆分后的 P2a）
> 前置：P1a 入库地基已合并 main（`059cd04`），元数据列与 `parent_chunks` 空表已就位
> 架构基底：扩展 Pipeline A；从未接线的 Pipeline B 只**移植算法**，不接通

---

## 1. 背景与目标

P1a 把 PRD §7.1 的元数据列一次性落到大表并开始写入，但 `parent_chunks` 仍是空表、检索仍是「稠密 top-k 直接喂给 LLM」。P2a 补上 PRD 的**检索精度与上下文质量**核心：用小子块提升检索精度，用父块提供完整上下文，并加上 PRD F2.3/F5.2 要求的组装与护栏。

**P2a 目标**：子块用于检索、父块用于生成；命中后按父块去重扩展、受 Token 预算约束、按 Lost-in-the-Middle 排序；低相关性按 PRD 两档处理（拒答 / 低置信提示）。

**为什么与 P2b 拆开**：父子块 + 扩展是**强耦合**的一组（只缩小子块而不做扩展，会让生成上下文比现状更差），且会改变生成质量、需要单独验收；而稀疏检索依赖「自建 pgvector+zhparser 镜像」这一基建决策。两者风险来源不同，分开交付、分别验收。

---

## 2. 范围

### 做（In）
1. `chunker_service` 重写为父子块，**修掉从 Pipeline B 继承会带来的两个 bug**（见 §3）。
2. 入库写入 `parent_chunks` 行并回填子块 `parent_chunk_id`；**只对子块做 embedding**。
3. 检索管线加：重排阈值、近重复去重、父块去重扩展、Token 预算、Lost-in-the-Middle 排序。
4. 护栏：无有效 chunk → 拒答（不调 LLM）；top-1 分数 0.4–0.6 → 低置信提示。
5. 最小评估夹具（~12 条 Q→期望来源），作为本期质量前后对比闸门，并为 P5 Golden Set 打底。

### 不做（Out）
- **稀疏检索 / RRF / zhparser 镜像** → P2b。
- **本地 BGE 重排** → 继续用 Cohere（本期只在其外围加阈值/去重/降级）；BGE 待隐私或成本诉求出现再议。
- 版本翻转、多租户逻辑、评估体系全量（Golden Set/RAGAS/Dashboard）→ P4 / P5。
- **存量文档不强制重建索引**：老块 `parent_chunk_id` 为 NULL，按 §6 兼容处理；全量重建属 P4。

---

## 3. 分块设计（核心，务必避开两个已知 bug）

### 3.1 必须修掉的两个 bug（来自 Pipeline B `ingestion/steps/chunk.py`）
- **父块截断**：B 用「元素前 800 token」当父块（`chunk.py:101`），长元素中后段的子块，其父块**根本不含自己的原文** → 命中后扩展出的上下文缺失被引用的那句，small-to-big 静默失效。
- **子块并不小**：B 的 `_split_text` 只按 `\n\n` 切且不再递归；pypdf 抽出的页常无 `\n\n`，整页会塌成**一个巨块**，既毁检索精度又可能超 embedding 输入上限（OpenAI 8191 token）。

### 3.2 正确构造（覆盖性由构造保证）
对每个解析 unit（`{text, page_num, kind, parse_confidence, section_path}`）：

1. **先切子块**：按段落边界切；**单段仍超限则递归子切**（句边界 → 定长 token 窗 + 重叠）。硬不变量：**任何子块 token 数 ≤ `child_chunk_tokens`**（测试断言，含「无 `\n\n` 整页」用例）。
2. **再由子块分组成父块**：把**连续**子块累积到 ≤ `parent_chunk_tokens` 为一组，`parent.content = 该组子块文本拼接`。因此 **每个子块的文本必定是其父块文本的子串**；一个长元素产出**多个父块**，而不是一个被截断的父块。
3. **表格类**（`chunk_type='table'`，主要是 xlsx sheet）：整体 ≤ `table_max_tokens` 则保持整块；超限则**按行分组**，每组重复表头以便独立检索，每组 ≤ `table_max_tokens`；该元素的父块为其行组集合。
4. 子块继承 unit 的 `page_num / section_path / parse_confidence / chunk_type`，并计算 `content_hash`；父块记录 `content / section_path / page_num（取首个子块）/ token_count`。

**重叠策略**：子块间小重叠（默认 ~32 token，约 15%），尽量落在句边界；**父块之间零重叠**（父块是去重后的上下文单位，重叠会造成重复注入）。

---

## 4. 检索与组装管线（**顺序即正确性**）

```
1) 稠密余弦召回（仅子块；沿用 P1a 的 WHERE is_latest）→ retrieval_candidate_k (20)
2) Cohere 重排，输入必须是【子块】文本（父块文本会稀释、拉低排序质量）
3) 阈值过滤：丢弃 rerank_score < rerank_min_score (0.4)
4) 近重复去重：对存活子块用【embedding 余弦】≥ dedup_cosine_threshold (0.92) 判重，保留高分者
5) 取 top_k 子块 (5)
6) 收集 DISTINCT parent_chunk_id，每个父块只取一次
7) 组装：每个父块作为一个上下文块，按「其最佳子块分数」升序排列 —— 最相关的放最后（Lost-in-the-Middle）
8) Token 预算：按序累积直到 context_token_budget，超出部分丢弃
9) Citation 取自命中的【子块】（page_num / section_path / chunk_id / score），不取父块
```

**为什么用 embedding 余弦做去重**：Pipeline B 用 `text.split()` 的 Jaccard——中文无空格，整段会变成一个 token，相似度非 0 即 1，对中文语料形同虚设。子块向量本就在 pgvector 里，余弦去重语言无关且几乎免费。

**为什么 citation 用子块**：父块可能跨页，只能带一个 `page_num`；用子块才能把引用指到真正含该事实的位置。

---

## 5. 护栏（PRD F4.1 / F5.2 两档处理）

- **无据拒答**：§4 第 3 步后若无任何子块存活 → 检索返回空 → 直接返回「根据现有知识库无法回答这个问题。」**不调用 LLM**。
  - **明确不采用** Pipeline B 的「全被过滤则保留 top-1」兜底（`reranker.py:117-119`）——它与 PRD 的无据拒答直接冲突。
- **低置信提示**：top-1 重排分落在 `[rerank_min_score, low_confidence_score)`（0.4–0.6）→ 正常作答，但回答附加「⚠️ 检索到的内容相关性较低，请核实」。需从检索侧把该标志传到 chat/生成侧（同步返回体与 SSE 事件都要带）。

---

## 6. 数据与向后兼容

- 复用 P1a 已建的 `parent_chunks` 表与 `chunks.parent_chunk_id`，**本期无需新迁移**（除非 §7 配置项需要落库，当前不需要）。
- **存量子块 `parent_chunk_id` 为 NULL**：检索侧必须用 **LEFT JOIN `parent_chunks` + `COALESCE(parent.content, chunk.content)`**。若误用 INNER JOIN，所有 P1a 之前入库的文档会静默从检索中消失——必须有专门测试覆盖。
- 新旧结构混存可接受：老文档按自身内容作答，新文档享受父块扩展。

---

## 7. 新增配置项（`app/config.py`）

| 配置 | 默认 | 说明 |
|---|---|---|
| `child_chunk_tokens` | 200 | 子块目标大小（检索精度）|
| `parent_chunk_tokens` | 800 | 父块目标大小（生成上下文）|
| `child_overlap_tokens` | 32 | 子块重叠（~15%）|
| `table_max_tokens` | 1024 | 表格整块上限，超限按行分组 |
| `rerank_min_score` | 0.4 | 低于此分丢弃（PRD F5.2）|
| `low_confidence_score` | 0.6 | 低于此分作答但标注低置信 |
| `dedup_cosine_threshold` | 0.92 | 近重复去重阈值 |
| `context_token_budget` | 8000 | 送入 LLM 的上下文 token 上限 |

> PRD 写的是「不超过上下文窗口的 50%」。Claude 的窗口很大，50% 在成本/延迟/Lost-in-the-Middle 上都不划算，故取一个显式的绝对预算（8000）作为默认，并把「窗口 50%」当作硬天花板。

---

## 8. 测试与质量验收

**单元测试（不依赖 DB）**
1. **子块上限不变量**：任何子块 token ≤ `child_chunk_tokens`，含「整页无 `\n\n`」用例（直击巨块 bug）。
2. **父子覆盖不变量**：随机/长元素下，**每个子块文本都是其父块文本的子串**；2000+ token 元素 → 产出**多个**父块（直击截断 bug）。
3. 表格：≤上限保持整块；超限按行分组且**每组重复表头**、每组 ≤ 上限。
4. 组装：2 个子块同父 → 上下文只出现 **1 个**父块块；排序为最佳分数在**最后**；超预算被截断。
5. 兼容：`parent_chunk_id` 为 NULL 的老块能被召回，且上下文用其**自身**内容。
6. 护栏：全部低于 0.4 → 返回拒答且**未调用 LLM**；top-1 在 0.4–0.6 → 带低置信标志。
7. Citation 取自子块（页码/section_path 与命中子块一致，而非父块）。

**最小评估夹具（本期质量闸门）**
- 提交 ~12 条 `{question, expected_doc, expected_page}`（覆盖已有 fixtures + `real_scanned.pdf` 的验收关键词）。
- 提供一个可重复跑的脚本，输出 **Precision@3 与命中率**；P2a 合并前需给出**改动前 / 改动后**对比，父子块方案不得低于现状。
- 该夹具即 P5 Golden Set 的种子。

---

## 9. 风险与非目标

| 风险 | 缓解 |
|---|---|
| 子块变小导致召回漂移 | 评估夹具前后对比作闸门；不达标则调 `child_chunk_tokens` 或回退 |
| 父块扩展抬高输入 token / 成本 | `context_token_budget` 硬约束 + 父块去重；把上下文 token 记入 `RetrievalLog.total_tokens`（该列已存在但一直未用）使其可观测 |
| INNER JOIN 误用导致老文档消失 | §6 专门测试 + code review 检查点 |
| Cohere 重排对子块粒度的适配 | 重排输入固定为子块文本；阈值可配置，先按 PRD 的 0.4 起调 |

**非目标**：稀疏/RRF、zhparser 镜像、本地 BGE、版本翻转、评估体系全量、多模态。

---

## 10. 完成标准（DoD）

- [ ] 子块上限与父子覆盖两个不变量测试通过（含无 `\n\n` 整页、2000+ token 元素多父块）
- [ ] 表格超限按行分组且重复表头
- [ ] 父块去重扩展 + LiM 排序 + Token 预算测试通过
- [ ] 老块（NULL 父块）召回并回落到自身内容的测试通过
- [ ] 拒答 / 低置信两档护栏测试通过（拒答路径不调 LLM）
- [ ] Citation 取自子块
- [ ] 评估夹具给出改动前后 Precision@3 对比，未劣化
- [ ] 全量单测绿；改动文件 `ruff check` 干净
