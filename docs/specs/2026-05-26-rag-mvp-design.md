# 企业级多模态 RAG 系统 — MVP 设计文档 (v2)

> 版本：v2（替代 PRD_enterprise_multimodal_rag.md 作为短期开发依据）
> 日期：2026-05-26
> 作者：Marvin（决策者）+ Claude（协助）
> 状态：待 review

---

## 0. 项目定位（必读，所有决策的根）

**目的**：**内部团队工具 + 主导者亲自构建**

不是：对外商业产品 / SaaS / 卖给客户。

**为什么不直接装 Dify**（决策记录）：
1. 想要完全控制权（数据 / 模型 / Prompt / 检索策略全部可调）
2. 把它当一次深度学习项目（混合检索 + 多轮串联是真正想吃透的部分）
3. 未来想根据团队工作流深度定制（Dify 黑盒难改）

**成功定义（3 周后必须达到的 3 件事）**：
1. 你和团队**在自己工作流里日常使用**，不是给别人看的 demo
2. 比直接问 Claude/ChatGPT **可感知地更好**——理由必须能用一句话说清（私有知识 / 强制引用 / 多轮串联）
3. 你**已经吃透了混合检索 + 多轮 RAG 编排**，能跟同行讲清楚每个选择背后的取舍

---

## 1. 范围（与原 PRD 的关键差异）

### 1.1 保留的 P0

- 多格式解析：PDF / Word / Excel 必做；PPT / 图片 M2 任选 1 个
- 混合检索 + RRF 融合 + Reranker + 阈值过滤 + 近重复去重
- 多轮对话 + Query Reformulation（隐式指代消解）
- 强制引用 + 无据拒答
- 流式输出 + 浏览器 chat UI
- 知识库管理后台（上传 / 列表 / 删除 / 重试）

### 1.2 砍掉/简化（7 处剥离）

| PRD 原方案 | v2 替换 | 砍掉理由 |
|---|---|---|
| Qdrant + SPLADE 稀疏向量 | pgvector + Postgres FTS(zhparser) | 单库栈，少 2 个服务 |
| BGE Reranker 本地 GPU | Jina Rerank API | CPU 跑 BGE 150ms/次，iter 杀手 |
| Celery + Redis 异步队列 | FastAPI BackgroundTasks | 内部用户 < 10，不需要分布式 |
| MinIO 对象存储 | 本地文件系统 | 单机部署不需要 S3 协议 |
| 自研 Next.js Chat UI | Vercel AI SDK template fork | 节省 1 周 |
| 5 级降级链 + pybreaker | try/except + 报错给用户 | 无生产流量时是噪音 |
| Golden Set + Prometheus 看板 | 手测 + logging.info | 内部用不需要 SLO 看板 |

### 1.3 范围外（明确不做）

- 多跳推理（4 跳）
- HyDE（假设文档嵌入）
- 子查询分解
- 多语言对齐
- 文档版本历史回溯
- 评估自动跑批（Golden Set）
- 多租户 / RBAC
- 移动端 UI
- 推理链可视化

---

## 2. 技术架构

### 2.1 基础设施（单一 docker-compose）

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16    # 内置 pgvector 扩展
    # 启动时安装 zhparser 扩展用于中文 FTS
```

**就这一个服务**。原 PRD 中的 Qdrant / Redis / MinIO 全部砍掉。

### 2.2 后端

- Python 3.11 + FastAPI（sync handler 够用，无需 async 复杂度）
- SQLAlchemy 2.0（同步模式）
- BackgroundTasks 处理文档解析
- pypdf / python-docx / openpyxl 做文档解析
- 外部 API：Claude（生成）/ OpenAI text-embedding-3-small（嵌入）/ Jina Rerank（精排）

### 2.3 前端

- **Fork** Vercel AI SDK Chatbot template（不自研）
- Next.js 14 App Router + shadcn/ui + Tailwind
- 内置：流式输出 + Markdown 渲染 + 消息历史
- 自加：citation 跳转、文档管理页

### 2.4 数据流（M2 完成后的最终态，M1 是其简化子集）

> **注**：M1 阶段没有 Query Reformulation / 稀疏检索 / RRF / Rerank / 去重，只走"Dense 检索 → 拼 prompt → Claude"最短路径。下图是 M2 结束后的完整态。

```
[Upload 流程]
Frontend → POST /api/documents (multipart)
            ↓
        保存文件到 ./uploads/<doc_id>/
            ↓
        BackgroundTask 启动:
            parse → chunk(512 tokens, overlap 64) → embed (OpenAI batch)
            → insert pgvector + Postgres FTS index

[Query 流程]
Frontend → POST /api/chat (SSE)
            ↓
        load session history (PG)
            ↓
        Query Reformulation (Claude, 一次调用)
            ↓
        ┌─────────────────┬──────────────────┐
        │ Dense (pgvector) │ Sparse (PG FTS) │  并行
        └────────┬─────────┴────────┬─────────┘
                 ↓                  ↓
            RRF Fusion (k=60, 0.6/0.4 权重)
                 ↓
            Jina Rerank API (top 20 → top 5)
                 ↓
            阈值过滤 (≥ 0.4) + 近重复去重 (cosine ≥ 0.92)
                 ↓
            Assemble Context (放 prompt 最后)
                 ↓
            Claude streaming → SSE → Frontend
                 ↓
        retrieval_log 落库（全链路）
```

---

## 3. 数据模型

基于现有 `rag-backend/alembic/versions/001_initial_tables.py` 简化：

| 表 | 关键字段 | 备注 |
|---|---|---|
| `knowledge_base` | id, name | M1/M2/M3 全程用 1 个默认库（id=1, name="default"），表结构留好但不暴露切库 UI；多库能力进 backlog（M4+）|
| `document` | id, filename, file_hash, status, error_msg, kb_id, created_at | status: queued / parsing / indexed / failed |
| `chunk` | id, doc_id, parent_id, content, embedding(vector(1536)), metadata(jsonb), parse_confidence, page_num, section_path | 父子块结构（Small-to-Big） |
| `session` | id, user_id, title, created_at | |
| `message` | id, session_id, role, content, citations(jsonb), created_at | |
| `retrieval_log` | id, session_id, query_original, query_reformulated, dense_top20, sparse_top20, rrf_top10, rerank_top5, chunks_sent, llm_latency_ms, total_latency_ms | 单表存全链路 |

---

## 4. 现有 3.7K 行代码取舍

| 类别 | 处理 | 文件 |
|---|---|---|
| ✅ **保留** | `alembic/`, `app/models/` | 数据模型设计有价值，直接复用 |
| ⚠️ **参考** | `app/pipeline/retrieval/*` | 算法骨架可搬，但要重写适配 pgvector |
| ❌ **弃用** | `app/integrations/qdrant_client.py`, `app/integrations/minio_client.py`, `app/workers/*`, `app/core/circuit_breaker.py`, `app/core/fallback_chain.py` | 与简化栈不符 |
| 🔄 **重写** | `app/main.py`, `app/api/v1/*`, `app/config.py`, `app/dependencies.py` | 适配新栈 |

**关键判断**：不在弃用代码上续写。"参考"指看着写新代码，不是 git diff。

---

## 5. 里程碑

### 🎯 M1 — 端到端最朴素打通（5 天）

**验证假设**：核心管线在简化栈下能跑通。

| Day | 任务 |
|---|---|
| **D1** | docker-compose 改为单 pgvector PG16 + 现有代码盘点 + 确定保留/弃用清单 + DB schema 初始化 |
| **D2** | 后端骨架：3 个接口（`POST /documents`, `GET /documents`, `POST /chat` 先同步版）+ 配置 + 依赖 |
| **D3** | 文档处理：PDF (pypdf) → 512-token chunking → OpenAI embedding(batch=64) → insert pgvector |
| **D4** | 检索 + 生成：pgvector 余弦 top-5 → 拼 prompt（含 system prompt 强制 citation）→ Claude 同步调用 → 解析 citation → 返回 |
| **D5** | 前端：clone Vercel AI SDK template → 配置环境 → 接你的 `/chat` → 改 SSE 流式 → 实测 3 份真实 PDF + 录 30 秒视频 |

**M1 验收**：浏览器中上传一份真实 PDF，问 3 个问题，每个回答都带正确页码 citation，点击 citation 跳转到 PDF 对应页。

### 🎯 M2 — 检索质量到"非创造者能感知到价值"（5-7 天）

**验证假设**：非自己人用了 15 分钟后觉得比 ChatGPT 强。

| Day | 任务 |
|---|---|
| **D1** | Postgres FTS（装 zhparser 扩展）+ 稀疏检索接口 |
| **D2** | RRF 融合（k=60, 稠密:稀疏=0.6:0.4）+ Jina Rerank API 集成（top 20 → top 5）|
| **D3** | 阈值过滤（≥ 0.4）+ 近重复去重（cosine ≥ 0.92）+ retrieval_log 落库 |
| **D4** | 多格式解析：Word（python-docx）+ Excel（openpyxl）+ 表格切块策略（整表为单块） |
| **D5** | Query Reformulation：会话历史 + 当前 query → Claude 改写 → 异常时降级用原 query |
| **D6** | 会话持久化（session/message 表）+ 前端多轮对话渲染 + 选做 PPT 或图片解析（二选一） |
| **D7** | 拉 1 个真人用 15 分钟，录反应 + 收集反馈 |

**M2 验收**：非创造者反馈"这个比直接问 ChatGPT 好"，且能说出至少 1 个具体原因。

### 🎯 M3 — 内测 5 人 × 1 周（7-10 天）

**验证假设**：内部团队愿意持续用，不是一次性。

| Day | 任务 |
|---|---|
| **D1-2** | 知识库后台：上传进度 / 状态 / 失败重试 / 删除 / 批量上传 |
| **D3** | 异步处理稳定性：失败队列（DB 状态机）+ 文件哈希幂等去重 + 超时控制（10 分钟） |
| **D4** | 部署：单台 4C8G 服务器（阿里云/腾讯云）+ nginx + systemd（不上 K8s） |
| **D5** | 简单监控：logging.info 关键指标（检索 P95 / API 成本 / 错误率） + `/admin/logs` 页面查 retrieval_log |
| **D6** | 邀请 5 个内测用户（团队同事），建 Slack/微信反馈群，写 1 页使用说明 |
| **D7-10** | 观察使用 + bug fix + 每天看一次 retrieval_log 调阈值 / prompt |

**M3 验收**：5 个内测用户中 ≥ 3 个第二周仍主动使用。

---

## 6. Kill Criteria（什么情况下停掉/转向）

| 触发条件 | 应做 |
|---|---|
| M1 第 5 天没跑通基础 E2E | 转 Fork RAGFlow，承认从零成本太高 |
| M2 真人反馈"不如 ChatGPT"且说不出差异化 | 停下来重新定位（可能是知识库内容本身价值不够，不是工具问题）|
| M3 第二周持续使用人数 < 2 | 停项目，复盘原因 |
| 任何时点：API 月成本 > $300 | 立即切便宜模型（Claude Haiku / text-embedding-3-small）或暂停 |
| 任何 milestone 延期 > 50% | 强制 review 范围，砍而不是拖 |

---

## 7. 风险登记

| 风险 | 影响 | 对冲 |
|---|---|---|
| 现有 3.7K 行代码集成失败，需要更多重写 | M1 工期 +2-3 天 | D1 留半天评估，超时立刻按弃用方案处理 |
| pgvector 在 10K+ chunk 后性能退化 | 检索延迟上升 | 加 HNSW 索引；若仍不够换 Qdrant（架构层预留切换接口） |
| Postgres 中文 FTS（zhparser）效果差 | 稀疏召回低 | M2 备选：用 BM25 简单实现 或 BGE-M3 lexical 输出 |
| Jina Rerank API 限流/挂 | 检索质量降级 | try/except 跳过 rerank 路径，标注"精排不可用" |
| Vercel AI SDK template 上手成本超预期 | M1 D5 拖延 | plan B：最简 HTML + fetch 临时顶 |
| 学习曲线导致整体延期 | 全程节奏问题 | 每个 milestone 结束诚实判断，不死撑 |
| API 成本超预算 | 项目被迫停 | 提前在代码里加 token 限流 + 每日成本日志 |

---

## 8. 决策记录（不再讨论的事，避免反复）

1. **数据库**：pgvector + Postgres FTS（不用 Qdrant + SPLADE）
2. **队列**：FastAPI BackgroundTasks（不用 Celery + Redis）
3. **对象存储**：本地文件系统（不用 MinIO）
4. **Rerank**：Jina API（不用本地 BGE GPU）
5. **前端**：Fork Vercel AI SDK template（不自研 chat UI）
6. **监控**：logging + DB 日志表（不上 Prometheus）
7. **多跳推理**：不做
8. **HyDE**：不做
9. **现有代码**：参考为主，不在弃用模块上续写
10. **PRD 文档**：作为长期愿景保留，本 spec 为短期执行依据
11. **范围扩张**：任何 M1-M3 期间冒出的"好想法"进 backlog，不打断当期

---

## 9. 后续（M3 完成后）

- ✅ **验证成功**（5 用户 ≥ 3 持续使用） → 进入 M4：可观测性 + 性能优化 + PRD 中的 P1 功能（多跳 / HyDE / 评估体系 / 完整后台）
- ❌ **验证失败** → 复盘 → 决定继续 / 转向 / 停止

**M4+ 不在本 spec 范围**。任何超 M3 的承诺都是空头支票。

---

## 10. 附录 — 与原 PRD 的对照表

| PRD 章节 | v2 处理 |
|---|---|
| F1 文档处理与知识入库 | M1/M2 实现核心（PDF/Word/Excel），其余 M2/M4 选做 |
| F2 检索引擎 | M1 朴素版 + M2 完整版（除 HyDE） |
| F3 多轮对话与多跳 | M2 实现多轮 + Query Reformulation；多跳不做 |
| F4 生成与回答质量 | M1 实现 citation + 无据拒答；其他 M2 |
| F5 稳定性设计 | 砍 80%（保留 try/except + 简单超时） |
| F6 知识库管理后台 | M3 实现基本管理；评估体系 / Dashboard 砍掉 |
