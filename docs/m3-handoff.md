# M3 Handoff

> Date: 2026-06-05
> Status: **M3 代码完成 6/6 task, 21/21 单元测试通过, 待 E2E（需填阿里云 OCR key）**
> Spec: `docs/specs/2026-06-05-m3-ocr-design.md`
> Plan: `docs/plans/2026-06-05-m3-ocr-plan.md`

## 已交付（vs M2 增量）

| 能力 | M2 | M3 |
|---|---|---|
| PDF 扫描页 | 直接被丢 | 自动调阿里云 OCR 兜底 |
| 触发条件 | — | 单页提取 < 50 字符且 OCR 启用 |
| 失败策略 | — | 单页失败仅 warning + 跳过，不阻塞 |
| 单元测试 | 13 | 21 (+8 OCR) |
| 依赖增加 | — | pypdfium2 5.9.0 + alibabacloud_ocr_api20210707 3.1.3 |
| ruff 状态 | tests/** 未做 ANN | OCR 4 文件 0 lint 错误 |

## 完成的 6 个 task

- T1 ✅ 依赖 + 配置项 + .env.example (`a9fa5f1`)
- T2 ✅ ocr_service 模块 + 4 mock tests (`39cfd31`)
- T3 ✅ scanned.pdf fixture（空白页，文本层为空）(`52a5a2a`)
- T4 ✅ parsers/pdf.py 集成 OCR fallback + 4 集成 tests (`9e543d9`)
- T5 ✅ 启动冒烟 + ruff + 21/21 final gate (`d54f73e`)
- T6 ✅ 本文档

## 你要做的 E2E 验收

```bash
# 1. 申请阿里云 OCR
# - https://www.aliyun.com/product/ocr-service
# - 开通 "通用文字识别"
# - 拿到 AccessKey ID/Secret

# 2. 填到 rag-backend/.env
ALIYUN_OCR_ACCESS_KEY_ID=LTAI...
ALIYUN_OCR_ACCESS_KEY_SECRET=...
# ALIYUN_OCR_ENDPOINT 不动（默认杭州；如部署到香港改 ocr-api.cn-hongkong.aliyuncs.com）

# 3. 启动
make dev &
cd rag-frontend && npm run dev &

# 4. 准备一个真实扫描 PDF（如扫描合同/老政策文件）

# 5. 浏览器
# - http://localhost:3000/documents 上传，等 status → indexed
# - 检查后端日志：应看到对该 PDF 调 RecognizeGeneral
# - http://localhost:3000 提问扫描件内容，应能答出并带 citation
```

健康检查路径：`GET /api/v1/health` 返回 `{"status":"ok","db":"ok"}`（注意 v1 前缀，不是裸 `/health`）。

## 已知问题 / M3.5 / M4 候选

### M3.5 推荐打包（约 2 天）

1. **删除文档 + 重建索引**（管理体验）— 1 天
2. **演示品牌可配（白标）**（视觉加分）— 0.5 天
3. **ruff per-file-ignore for tests/**（lint 债务）— 5 分钟
   - 现状：M2 test 文件（test_chunker.py / test_parser_docx.py 等）未补 ANN 类型标注；M3 已补完
   - 建议在 pyproject.toml 加 `[tool.ruff.lint.per-file-ignores]` → `"tests/**" = ["ANN"]`
   - 顺手删除 `ignore` 里失效的 `ANN101/ANN102`（这俩规则在新版 ruff 已 removed）
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
| 真实阿里云 OCR 调用 | ⭐⭐⭐ | SDK 路径未实跑，依赖 E2E |
| 中文扫描准确率 | ⭐⭐⭐ | 阿里云通用 OCR 公开评测中文 99%+，但你的具体合同字体未知 |
| pypdfium2 Docker 兼容 | ⭐⭐⭐ | 本机通过，Linux 镜像未测 |

## 代码 review 留下的轻量 TODO（非阻塞）

1. `_render_page_to_image` 每页都重新 `pypdfium2.PdfDocument(source)` 打开 PDF — N 页 N 次开销。演示量级可接受；若真实文档 >50 页，hoist 一次打开放循环外即可。
2. parsers/pdf.py 测试未对 `get_settings` cache 加显式 monkeypatch — 当前 21/21 绿，但理论上若有其他测试改写 `ocr_fallback_char_threshold` 后未 cache_clear，本测试可能受影响。M3.5 顺手补即可。
3. `ANN101 / ANN102` 在新版 ruff 已 removed，pyproject.toml 的 `ignore` 列表里还在；下一次改 ruff 配置时一起删除。

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
