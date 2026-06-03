# M2 Handoff

> Date: 2026-06-03
> Status: **M2 代码完成 9/11 task, 待 E2E（需 API key）**
> Plan: `docs/plans/2026-06-03-m2-plan.md`

## 已交付（vs M1 增量）

| 能力 | M1 | M2 |
|---|---|---|
| 支持格式 | PDF | PDF + Word + PPT + Excel |
| 答案响应方式 | 5-10s 整段冒出 | 第一个字 <1s 流式逐字出 |
| 检索准确度 | top-5 纯 cosine | top-20 cosine → Cohere rerank top-5 (无 key 自动降级到 M1 行为) |
| 单元测试 | 7 | 13 |

## 完成的 9 个 task

### P0 多格式解析
- T1 ✅ parsers/ 包重构 + mime dispatcher（python-docx / python-pptx / openpyxl）
- T2 ✅ docx parser + 2 tests + fixture
- T3 ✅ pptx parser + 2 tests + fixture（含 speaker notes）
- T4 ✅ xlsx parser + 2 tests + fixture（多 sheet）
- T5 ✅ documents.py 415 校验 + 前端 accept `.docx,.pptx,.xlsx`
- T6 ⏸ ingestion E2E 跑通（需 API key 才跑，代码已就位）

### P1 流式输出
- T7 ✅ backend `/chat/stream` SSE + Anthropic streaming
- T8 ✅ frontend fetch+ReadableStream 消费 SSE, 逐字 render

### P2 Cohere 重排
- T9 ✅ retrieval_service oversample + rerank + fallback（无 key 走 cosine）

### 收尾
- T10 ⏸ E2E smoke（4 格式各 1 份 + 1 个问题）—— 需你填 key 后跑
- T11 ✅ 本文档

## 你要做的 E2E 验收

```bash
# 1. 已有的 OPENAI/ANTHROPIC key 不动；可选填 COHERE
$EDITOR rag-backend/.env
# COHERE_API_KEY=...  (可选，去 https://cohere.com 申请 free trial)

# 2. 启动
make dev &
cd rag-frontend && npm run dev &

# 3. 准备 4 份测试文件：PDF / docx / pptx / xlsx 各 1 份

# 4. 浏览器
# - http://localhost:3000/documents 上传 4 份，等 status → indexed
# - http://localhost:3000 提问，应看到答案逐字蹦出 + citations
```

## 已知问题 / M3 候选（按演示价值排）

1. **OCR 扫描件**（解锁历史合同/PDF 扫描件）— 2-3 天
2. **多用户/团队隔离**（决定能不能对外）— 3-5 天
3. **删除文档 / 重建索引**（管理体验）— 1 天
4. **演示品牌可配**（白标）— 0.5 天
5. **本地 BGE rerank**（成本 / 隐私）— 2 天

## 信心评级

| 项 | 信心 | 备注 |
|---|---|---|
| 编译 / 启动 | ⭐⭐⭐⭐⭐ | 13/13 tests + 多次 app boot |
| 单元测试 | ⭐⭐⭐⭐⭐ | 全绿 |
| 多格式解析 | ⭐⭐⭐⭐ | fixture 是程序生成的；真实复杂文档可能有 corner case |
| SSE 流式 | ⭐⭐⭐⭐ | 代码直观，但未与真 Anthropic 流跑通 |
| Cohere rerank | ⭐⭐⭐⭐ | fallback 路径已覆盖；正路径需 key 才确认 |
| 大表格/扫描件 | ⭐⭐ | 已知不行，M3 |

## Git 标签建议

E2E 跑通后：

```bash
git tag m2-done-$(date +%Y%m%d)
```
