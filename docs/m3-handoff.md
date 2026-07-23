# M3 Handoff

> Date: 2026-06-05
> Status: **M3 代码完成；E2E 代码侧验证已过（2026-07-23）——22/22 单测、Docker/Linux 兼容确认、SDK 契约核实、修复 1 个 HIGH bug；仅剩真实阿里云 key 下的 OCR 准确率实跑（需你填 key）**
> Spec: `docs/specs/2026-06-05-m3-ocr-design.md`
> Plan: `docs/plans/2026-06-05-m3-ocr-plan.md`

## 已交付（vs M2 增量）

| 能力 | M2 | M3 |
|---|---|---|
| PDF 扫描页 | 直接被丢 | 自动调阿里云 OCR 兜底 |
| 触发条件 | — | 单页提取 < 50 字符且 OCR 启用 |
| 失败策略 | — | 单页失败仅 warning + 跳过，不阻塞 |
| 单元测试 | 13 | 22 (+9 OCR) |
| 依赖增加 | — | pypdfium2 5.9.0 + alibabacloud_ocr_api20210707 3.1.3 |
| ruff 状态 | tests/** 未做 ANN | OCR 4 文件 0 lint 错误 |

## 完成的 6 个 task

- T1 ✅ 依赖 + 配置项 + .env.example (`a9fa5f1`)
- T2 ✅ ocr_service 模块 + 4 mock tests (`39cfd31`)
- T3 ✅ scanned.pdf fixture（空白页，文本层为空）(`52a5a2a`)
- T4 ✅ parsers/pdf.py 集成 OCR fallback + 4 集成 tests (`9e543d9`)
- T5 ✅ 启动冒烟 + ruff + 21/21 final gate (`d54f73e`)
- T6 ✅ 本文档

## E2E 代码侧验证进展（2026-07-23）

不依赖付费 key 就能验的，全部跑掉了：

| 验证项 | 结果 |
|---|---|
| 真实运行路径是否含 OCR | ✅ 上传→FastAPI BackgroundTask→`ingest_document`→`parse_pdf`→OCR。**这是唯一接线的入库路径** |
| SDK 请求/响应契约 | ✅ 对着 `.venv` 里安装的 `alibabacloud_ocr_api20210707==3.1.3` 源码核实：`body=BytesIO` 类型正确、`recognize_general_with_options(req, runtime)` 签名匹配、`resp.body.data` 为 JSON 串、`.get("content")` 键正确。**无 schema 不匹配，不会白烧额度** |
| Docker / Linux 兼容 | ✅ `python:3.12-slim` 干净构建，pypdfium2 自带 manylinux wheel 零额外 apt 依赖，容器内真实渲染 JPEG 成功，镜像 607MB |
| 真实渲染链（macOS + Linux） | ✅ image-only PDF → pypdf 提取 0 字（触发 OCR）→ pypdfium2 渲染 200dpi JPEG（有真实文字像素、<阿里云 10MB 限） |
| 空 key 降级 = M2 行为 | ✅ 真实扫描件在无 key 下 → `[]`（扫描页丢弃，无异常） |
| 单测回归 | ✅ 22/22（clean checkout 无 `.env` 也可跑，见下）|

**⚠️ 本轮修复的 HIGH bug（会直接坑 E2E）：** 原实现里任何 OCR 调用失败（key 错 / region 错 / RAM 子账号无 `ocr:RecognizeGeneral` 权限 / 限流 / 超额）都被静默降级成空页，整篇文档仍被标 `status="indexed"`（成功）、0 chunk、不抛异常。你会看到「入库成功」却答不出内容，唯一线索是被埋掉的一条 WARNING。已修：整篇因 OCR 失败而零内容时 `parse_pdf` 抛 `OcrError` → `ingest_document` 既有 `except` 将其标为 `status="failed"` 并把阿里云错误写入 `error_msg`；单页失败仍不阻塞多页文档（韧性保留）。OCR 失败日志级别 `warning→error`。

**新增 E2E 资产：** `tests/unit/fixtures/real_scanned.pdf`（中英文图像层、无文本层的真实扫描件）+ 可复现生成脚本 `_generate_real_scanned_pdf.py`。

## 你要做的 E2E 验收（真实 OCR 准确率实跑）

**最小依赖：只要一个 pgvector Postgres 容器 + 3 个 API key。** 真实路径不碰 Qdrant/MinIO/Redis/Celery（那套 `app/pipeline/ingestion/**` 是未接线的死代码），别去搭 prod 全栈。

```bash
# 1. 申请阿里云 OCR：https://www.aliyun.com/product/ocr-service
#    开通「通用文字识别」，拿 AccessKey ID/Secret（建议主账号或授权了 ocr:RecognizeGeneral 的 RAM 子账号）

# 2. cp rag-backend/.env.example rag-backend/.env，至少填这 4 类（OCR + 嵌入 + 生成 + DB）：
#    DATABASE_URL=postgresql+psycopg://raguser:ragpass@localhost:5435/ragdb   # 见 docker-compose.yml
#    OPENAI_API_KEY=sk-...            # 嵌入（text-embedding-3-small）
#    ANTHROPIC_API_KEY=sk-ant-...     # 生成
#    ALIYUN_OCR_ACCESS_KEY_ID=LTAI... / ALIYUN_OCR_ACCESS_KEY_SECRET=...
#    ALIYUN_OCR_ENDPOINT 默认杭州；香港部署改 ocr-api.cn-hongkong.aliyuncs.com

# 3. 起 Postgres + 建表
make up                    # docker compose 起 pgvector（host 5435）
cd rag-backend && uv run alembic upgrade head

# 4. 起后端（前端可选；扫描件验证用 curl 即可）
uv run uvicorn app.main:app --port 8000 &

# 5. 上传自带的真实扫描件（或你的扫描合同）
curl -F "file=@tests/unit/fixtures/real_scanned.pdf;type=application/pdf" \
     http://localhost:8000/api/v1/documents          # 返回 {id, status:"queued", ...}

# 6. 轮询状态：应 → "indexed"；后端日志应有对该 PDF 调 RecognizeGeneral
curl http://localhost:8000/api/v1/documents/<id>
#    ✅ 修复后：若 key/region/权限有问题，status 会是 "failed" 且 error_msg 带阿里云 Code（不再假装成功）

# 7. 提问扫描件内容，应能答出并带 citation
curl -X POST http://localhost:8000/api/v1/chat \
     -H 'content-type: application/json' \
     -d '{"message":"合同编号是多少？甲方是谁？"}'
#    fixture 的验收关键词：星曜科技 / 黄河智能 / HT-2026-0087 / 1,250,000
```

健康检查：`GET /api/v1/health` → `{"status":"ok","db":"ok"}`（注意 `/api/v1` 前缀）；`/api/v1/health/live` 为 liveness。

**（可选）不花配额先验 key 是否有效：** 填好 key 后 `uv run python -c "from app.services.ocr_service import ocr_enabled; print(ocr_enabled())"` 应打印 `True`；真正的一次识别会消耗 1 次「通用文字识别」调用额度。

## 已知问题 / M3.5 / M4 候选

### M3.5 推荐打包（约 2 天）

1. **删除文档 + 重建索引**（管理体验）— 1 天
2. **演示品牌可配（白标）**（视觉加分）— 0.5 天
3. ~~**ruff per-file-ignore for tests/** + 删除失效 `ANN101/ANN102`~~ ✅ 已于 2026-07-23 完成
   - 注：`ruff check app/ tests/` 仍有 ~44 个既有报错，**几乎全在死代码 Pipeline B（`app/workers/`、`app/pipeline/ingestion/`）与未标注的 M1/M2 文件**，与真实路径无关；本轮改动文件全部 lint 干净
4. **OCR 阈值 alias**（小调优）— 1 分钟
   - 现 `ocr_fallback_char_threshold: int = 50` 无 alias，无法 env 覆盖
   - 改为 `Field(50, alias="OCR_FALLBACK_CHAR_THRESHOLD")` 即可

### M4 候选（按演示价值排）

1. **多用户/团队隔离**（决定能否对外卖）— 3-5 天
2. **OCR 结果缓存**（按 SHA + page_num 缓存）— 1 天 — 量起来再做
3. **本地 BGE rerank**（成本/隐私）— 2 天 — 待客户隐私要求出现再做
4. **表格结构识别（OCR + table extract）** — 3-5 天 — 高价值但风险高

## 信心评级

| 项 | 信心 | 备注 |
|---|---|---|
| 编译 / 启动 | ⭐⭐⭐⭐⭐ | 21/21 tests + 启动冒烟通过（empty key 路径） |
| 单元测试 | ⭐⭐⭐⭐⭐ | 全绿；4 个 OCR fallback 分支全覆盖（成功/失败/启用/禁用） |
| OCR 触发逻辑 | ⭐⭐⭐⭐⭐ | mock 覆盖了所有分支 |
| Lint（OCR 文件） | ⭐⭐⭐⭐⭐ | ruff 0 错 |
| 真实阿里云 OCR 调用 | ⭐⭐⭐⭐ | 请求/响应契约已对着安装源码核实正确；仅剩真实网络往返未跑 |
| OCR 失败可见性 | ⭐⭐⭐⭐⭐ | 已修 HIGH bug：整篇失败 → status="failed" + error_msg，不再假装成功 |
| 中文扫描准确率 | ⭐⭐⭐ | 阿里云通用 OCR 公开评测中文 99%+，但你的具体合同字体未知 |
| pypdfium2 Docker 兼容 | ⭐⭐⭐⭐⭐ | slim 镜像干净构建，manylinux wheel 零额外 apt 依赖，容器内真实渲染成功（607MB） |

## 代码 review 留下的轻量 TODO（非阻塞）

1. `_render_page_to_image` 每页都重新 `pypdfium2.PdfDocument(source)` 打开 PDF — N 页 N 次开销。演示量级可接受；若真实文档 >50 页，hoist 一次打开放循环外即可。
2. parsers/pdf.py 测试未对 `get_settings` cache 加显式 monkeypatch — 当前 21/21 绿，但理论上若有其他测试改写 `ocr_fallback_char_threshold` 后未 cache_clear，本测试可能受影响。M3.5 顺手补即可。
3. ~~`ANN101 / ANN102` 在新版 ruff 已 removed，pyproject.toml 的 `ignore` 列表里还在~~ ✅ 已删（2026-07-23）
4. **本轮新发现（已修）：** Pillow 是 `pdf.py` 渲染的硬依赖，却未在 pyproject 声明（仅靠 python-pptx 间接带入）；已显式加 `pillow>=10.0.0`。
5. **架构提醒（非阻塞）：** 仓库存在两套入库管线，真实 App 只用 Pipeline A（`services/ingestion_service.py` + pgvector + 本地磁盘 + BackgroundTask）；`app/pipeline/ingestion/**`（Celery + Qdrant + MinIO + `ParserFactory`/`DocumentChunk`）**完全未接线**，OCR 也没接到那套。做 M4「多用户/团队隔离」前需先决定二者取舍，否则易踩坑。

## Git 标签建议

E2E 跑通后：

```bash
git tag m3-done-$(date +%Y%m%d)
```

## M3.5 速通建议（若 OCR 验收顺利）

一轮约 2 天的"小而美"打包，3 个能直接看见效果的能力：

- 删除文档接口 + 前端按钮 + 级联清 chunk + 级联清 embedding
- 白标：`NEXT_PUBLIC_BRAND_NAME` / `NEXT_PUBLIC_BRAND_COLOR` 两个 env 驱动 page header/title
- ruff per-file-ignore + 阈值 alias（5 分钟收尾）
- 一并打 `m3.5-done` 标签
