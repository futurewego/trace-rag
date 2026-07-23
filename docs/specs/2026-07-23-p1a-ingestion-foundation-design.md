# P1a — 入库地基（数据模型 + 元数据）设计

> 日期：2026-07-23
> 阶段：PRD 全量对齐 · 第 1 阶段（拆分后的 P1a）
> 架构基线：扩展 Pipeline A（同步栈 + pgvector + BackgroundTask），把 Pipeline B 当零件库挖
> 前置评审：4 视角对抗式设计评审（`wf_39ac19c9-2c1`），全判 needs-changes，已据此优化

---

## 1. 背景与本阶段目标

「PRD 全量对齐」共 7 个后端阶段，P1 是所有后续阶段的共同依赖。经对抗评审，原 P1 被拆为：

- **P1a（本 spec）**：只做**加列式迁移 + 解析器元数据增强 + 入库写入新列**。**保留现有 512 chunker 与检索行为不变**，因此现存 22 个单测全绿、零回归。这是唯一「不可逆、必须一次做对」的地基。
- **P1b → 并入 P2**：父子块 chunker 重写（修掉 B 的父块截断 bug）+ 200 子块 + 父块扩展（去重 + token 预算 + rerank 用子块 + citation 用子块页码），作为 F2.3「上下文组装」整体交付，用 Precision@3 验收。

**为什么拆**：200 子块与父块扩展是强耦合的检索行为变更（今天 flat 512 块生成正常，无回归倒逼），必须一起上并做 A/B；而 schema 迁移是唯一昂贵不可逆的动作，应独立、先行、做全。

**P1a 目标一句话**：把 PRD §7.1「Day-1 必做、后补极难」的全部元数据列一次性落到大表上（`chunks`/`documents`），并让入库开始写入它们——但不改变任何检索/生成行为。

---

## 2. 范围

### 做（In）
1. 一次性加列迁移 `003`（`down_revision="002_m1_schema"`），覆盖后续 P2–P7 会读到的全部列。
2. `parent_chunks` 空表（P2 才填充），含正确 FK 级联。
3. 解析器补 2 个字段：`parse_confidence`（硬编码）、`section_path`（best-effort）。
4. 入库写入新列（`chunk_type` 由 `kind` 推导、`content_hash`），`parent_chunk_id=NULL`。
5. 检索加 `WHERE chunks.is_latest`（默认 true，当前 no-op，为 P4 版本翻转预埋）。
6. 迁移 up/down 往返 + 存量行 backfill 测试。

### 不做（Out — 明确留给后续阶段）
- **父子块 chunker 重写、200 子块、父块扩展** → P2（F2.3）。P1a **保留 `chunk_page` 512/64 不动**。
- **`tsvector` 全文列** → P2，用**表达式 GIN 索引** `gin(to_tsvector(cfg, content))` 实现，**不建 STORED 生成列、不重写表**，届时再定中文分词器（zhparser vs simple，涉及 DB 镜像）。见 §4 决策记录。
- **版本翻转逻辑**（重传把旧版 `is_latest=false`）→ P4。P1a 只落列 + 检索过滤。
- **多知识库逻辑**（复合唯一、seed、按 kb 预过滤）→ 真做多租户时。P1a 只**预留 nullable `knowledge_base_id` 列**（避免未来重写大表）。
- **xlsx 大表行分组、真实质量分 `parse_confidence`、pdf 版面标题提取** → 后续迭代。

---

## 3. 数据模型 / 迁移 `003`（本阶段唯一不可逆产物，务必一次做对）

### 3.1 `chunks` 加列

| 列 | 类型 | 约束/默认 | 用途 / 服务阶段 |
|---|---|---|---|
| `parent_chunk_id` | BigInteger | FK→`parent_chunks.id`, **nullable, ON DELETE SET NULL** | 父子块（P2 填充；存量与 P1a 新写均为 NULL=自身为父）|
| `section_path` | **ARRAY(Text)**（text[]）| nullable | 面包屑章节（Citation 精确溯源）。用**数组**避免后续拆分迁移 |
| `parse_confidence` | Float | nullable | 解析置信度；<0.7 在结果标 ⚠️（消费在 P2/P5）|
| `content_hash` | String(64) | nullable | P4 增量重索引（只重嵌变化块）|
| `chunk_type` | String(32) | **NOT NULL, server_default `'text'`** | text/table/image_desc；分块与多模态用 |
| `is_latest` | Boolean | **NOT NULL, server_default `true`** | 版本预过滤（**落在 chunks 供 HNSW 预过滤、免 join**）|
| `knowledge_base_id` | BigInteger | nullable（**预留**）| 多知识库（逻辑留后）|

### 3.2 新表 `parent_chunks`（P1a 建表，P2 才写入）

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | BigInteger | PK autoincrement |
| `document_id` | BigInteger | FK→`documents.id`, **NOT NULL, ON DELETE CASCADE** |
| `content` | Text | NOT NULL |
| `section_path` | ARRAY(Text) | nullable |
| `page_num` | Integer | nullable |
| `token_count` | Integer | nullable |
| `created_at` | DateTime(tz) | server_default now() |

> 采用**独立父块表**（评审确认优于 B 的 `is_parent` 标志）：父块不嵌入、不进 HNSW，避免污染 ANN 索引；`chunks.embedding` 保持 NOT NULL 不变。

### 3.3 `documents` 加列

| 列 | 类型 | 约束/默认 | 用途 |
|---|---|---|---|
| `doc_version` | Integer | NOT NULL, server_default `1` | 版本号（P4 递增）|
| `is_latest` | Boolean | NOT NULL, server_default `true` | 最新版标记（P4 翻转）|
| `doc_group_id` | BigInteger | nullable，**迁移内 backfill = `id`** | **逻辑文档身份**：关联 v1↔v2（`file_hash` 全局唯一无法关联版本）|
| `knowledge_base_id` | BigInteger | nullable（**预留**）| 多知识库 |

### 3.4 迁移机制要点（评审 [MEDIUM] 项）
- NOT NULL 列一律 **server_default**（`chunk_type='text'`、`is_latest=true`、`doc_version=1`），保证存量行 backfill、迁移不因非空表失败。
- `doc_group_id` 建列后 `UPDATE documents SET doc_group_id = id`（存量各自成组）。
- `downgrade()` 按 **FK 安全序**：先删 `chunks.parent_chunk_id` FK/列 → 再 `drop_table('parent_chunks')` → 删 documents/chunks 其余列（参照 `002:106-111` 的有序拆除）。
- 无 `tsvector`、无新 GIN/unique 索引（留 P2）。

---

## 4. 决策记录（评审驳回/纠偏）

1. **tsvector 推迟到 P2、用表达式索引**（纠偏 yagni 视角「必须现在加」）：STORED 生成列才会全表重写；表达式 GIN 索引 `gin(to_tsvector(cfg, content))` 只建索引不重写表，且能延后定中文分词器。P1a 不碰。
2. **父块=覆盖子块的分组/窗口，绝不照抄 B 的 800-token 截断**（blocker，4/4 确认）——但这属 P2 chunker 重写，本 spec 仅记录，防止 P2 复制 `chunk.py:101`。
3. **section_path 用数组而非拍平 text**（避免后续 transform 迁移）。
4. **kb_id 仅预留列**（Marvin 决策）：把最贵的「改大表」一次做完，多租户逻辑留后。
5. **版本模型 = 新行 + `doc_group_id` + `is_latest` 落 chunks**；翻转逻辑 P4。

---

## 5. 解析器元数据增强（`app/services/parsers/*` + `parser_service`）

每个 parser 返回的 dict 增加 2 键（现有消费方全用 key 访问，additive 安全）：

- **`parse_confidence`（硬编码）**：原生文本 `0.9`、OCR `0.6`、native-XML（docx/xlsx/pptx）`0.95`。
  - `parse_pdf`：**两个分支都要设**——原生提取路径 0.9、OCR 兜底路径 0.6（评审 [MEDIUM]：单点构造 dict 会漏标 OCR 页）。`OcrError 整篇失败抛出`（M3 修复）保持不动。
- **`section_path`（best-effort，list[str]）**：
  - docx：**重写为按 `p.style.name` 维护标题栈**（`Heading 1..9` 可靠，质量高、成本低，本期做对）。
  - xlsx：`[sheet_name]`（现成）。
  - pptx：`[slide_title]`（占位）。
  - **pdf：留空 `[]`**（pypdf 丢版面信息，启发式标题会产出**错误 citation，比留空更糟**；版面提取留后续 PyMuPDF 字号分析）。

> 关键：**列建对**即达 PRD §7.1 Day-1 硬需求；填充质量可迭代。

---

## 6. 入库改动（`ingestion_service.ingest_document`）

- **`chunk_page` 签名与 512/64 语义不变**（`test_chunker` 才能保持绿）。改动只在 `ingest_document` 的循环里：**逐 unit** 调 `chunk_page(unit["text"], unit["page_num"])`，再把**该 unit 的元数据盖到它产出的每个 chunk 上**——`chunk_type`（由该 unit 的 `kind` 映射：pdf page/docx section/pptx slide→`text`，xlsx sheet→`table`）、`section_path`、`parse_confidence`、`content_hash=sha256(content)`、`parent_chunk_id=NULL`、`is_latest=true`、`knowledge_base_id=NULL`。
- **不再用 `parsed_units[0].kind` 给全篇打一个 kind**（评审 [HIGH]：混合格式文档会被误标；改为逐 unit 取 kind）。
- 嵌入、检索、生成路径**字节级不变**。

> 涉及文件：ORM 模型同步加列 `app/models/chunk.py`、`app/models/document.py`，新增 `app/models/parent_chunk.py`；迁移 `alembic/versions/003_*.py`；`app/services/parsers/{pdf,docx,xlsx,pptx}.py` + `parser_service.py`；`app/services/ingestion_service.py`；`app/services/retrieval_service.py`。`chunker_service.py` **不改**。

---

## 7. 检索改动（`retrieval_service`）— 极小

- `_cosine_candidates` 的 SQL 加 `WHERE chunks.is_latest`（默认全 true → 当前 no-op，为 P4 版本翻转预埋预过滤）。
- **不做**父块扩展（留 P2）。`RetrievedChunk` 结构、评分、citation 全不变。

---

## 8. 向后兼容

- 存量 `chunks`/`documents` 行经 server_default/backfill 获得合理默认（`chunk_type='text'`、`is_latest=true`、`doc_version=1`、`doc_group_id=id`，其余 nullable=NULL）。
- 无检索行为变更 → 存量文档问答不受影响；`test_chunker` 等因 `chunk_page` 不变而保持绿。

---

## 9. 测试策略（沿用 `tests/unit/conftest.py`，保持全绿）

1. **迁移往返**：在**已有种子行**的库上 `upgrade→downgrade→upgrade`，断言列增删、`parent_chunks` 建/删、`doc_group_id` backfill、FK 级联方向。
2. **解析器**：`parse_pdf` 原生页 `parse_confidence==0.9` / OCR 页 `==0.6`；docx `section_path` 反映标题栈；xlsx `[sheet_name]`；扩展 `test_parser_pdf_ocr`。
3. **chunk_type 映射**：多 kind 的 `parsed_units` → 每 chunk 正确 `chunk_type`（xlsx sheet→table）。
4. **入库写列**：mock 下断言 chunk 带 `content_hash/parse_confidence/section_path/is_latest`。
5. **检索 is_latest**：`is_latest=false` 的 chunk 不被召回；默认全 true 时结果与今天一致。
6. 现存测试保持通过：`chunk_page`/检索语义不变 → `test_chunker` 及检索相关全绿；docx 解析为 **additive**（新增 `section_path`、文本提取不变），`test_parser_docx` 至多补一条断言即可，不改原有断言。

---

## 10. 风险与非目标

| 风险 | 缓解 |
|---|---|
| 迁移在非空生产表失败 | 全部 server_default + backfill + up/down 往返测试 |
| docx parser 重写引入回归 | 保留纯文本提取为主路径，标题栈为附加；补断言 |
| 列建多但暂无消费（`content_hash`/版本/kb_id/`parse_confidence`）| **有意为之**——一次迁移落全，消费在 P2/P4/P5；spec 明确标注「仅建列」 |

**非目标**：任何检索/生成质量变化、父子块、混合检索、版本翻转、多租户逻辑。P1a 是纯地基。

---

## 11. 完成标准（DoD）

- [ ] 迁移 `003` up/down 在有种子行的库往返成功
- [ ] 解析器 4 类 `parse_confidence`/`section_path` 断言通过
- [ ] 入库写入全部新列，`chunk_type` 按 kind 正确映射
- [ ] 检索加 `is_latest` 过滤，默认行为与今天一致
- [ ] 全套单测通过（22 现存 + 新增，全绿）
- [ ] `ruff check` 改动文件干净
