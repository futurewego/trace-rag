# M3: OCR 扫描件支持 — Design Spec

> Date: 2026-06-05
> Status: **Approved by Marvin** (brainstorm 已确认推荐方案)
> Brainstorm 上下文: 演示场景 / 客户文档约半为扫描件 / 部署在阿里云香港 / 单人轻运维

---

## 目标

PDF 上传后，若某页文本提取为空或极少，自动走阿里云 OCR 兜底，对调用方透明。Word/PPT/Excel 不在 M3 范围（M2 已覆盖且无 OCR 需求）。

## 非目标

- 不做表格结构识别 / 公式识别
- 不做手写识别专门优化
- 不做 OCR 结果缓存（M4 视量再说）
- 不替换 M2 已工作的原生 PDF 文本提取路径（仅做兜底）
- 不做多语言切换（默认中英文混排）

## 时间预算

2-3 天（6 个 task，TDD）。

---

## 1. 架构

### 核心数据流

```
parser_service.parse(pdf_source)
  └─ parsers/pdf.py :: parse_pdf(source)
       for i, page in enumerate(pdf.pages, start=1):
         text = pypdf.extract_text(page)
         if len(text.strip()) < OCR_FALLBACK_CHAR_THRESHOLD  # 默认 50
            and ocr_service.ocr_enabled():
           try:
             img_bytes = _render_page_to_image(source, i, dpi=200)  # pypdfium2
             text = ocr_service.ocr_image(img_bytes)                # 阿里云 SDK
           except OcrError as e:
             logger.warning("OCR fail page=%d: %s", i, e)
             text = ""
         if text.strip():
           yield {page_num: i, text, kind: 'page'}
```

### 边界

- OCR 触发**只在 `parsers/pdf.py` 内部**。`ingestion_service` / `chunker_service` / 上层 API 不感知。
- 单页 OCR 失败不抛错，只 warning + 跳过该页。整个 PDF 全部 OCR 失败时，行为同 M1/M2（无可用 chunk → Document.status="failed"）。
- 阿里云 key 未配置时，`ocr_service.ocr_enabled()` 返回 False，行为完全退化为 M2。

---

## 2. 关键决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| PDF → 图像渲染 | `pypdfium2>=4.30.0` | 纯 Python，无 poppler 系统依赖，Docker 镜像不增重 |
| OCR 服务 | 阿里云通用文字识别 (`RecognizeGeneral`) | 同生态 + 中文准确率 + 按量 ¥0.01/页 + 同账单 |
| SDK | `alibabacloud_ocr_api20210707>=3.0.0` | 官方 SDK，与未来部署在阿里云一致 |
| 触发阈值 | 单页提取 `< 50` 字符 | 经验值，覆盖纯扫描页 + 大部分图文混排 |
| 失败策略 | 单页空 + warning，不抛错 | 不让单页问题污染整篇入库 |
| 启用开关 | `ALIYUN_OCR_ACCESS_KEY_ID` 为空 → 模块禁用 | 与 Cohere 一致的 lazy 模式 |
| 渲染 DPI | 200 | A4 ~ 1.5MB JPEG，准确率与大小平衡 |
| 并发 | 串行 | 演示量小，避免阿里云 QPS 限流踩坑 |
| 缓存 | 不做 | YAGNI；演示量级（< 千页）每次重做也不痛 |

---

## 3. 文件变更

### 新建

- `rag-backend/app/services/ocr_service.py` — 阿里云 SDK wrapper + `ocr_image(bytes) -> str` + `ocr_enabled() -> bool` + `OcrError` 异常类
- `rag-backend/tests/unit/test_ocr_service.py` — mock 阿里云 SDK 的 4 个测试
- `rag-backend/tests/unit/test_parser_pdf_ocr.py` — 扫描 PDF fixture + 集成测试
- `rag-backend/tests/unit/fixtures/scanned.pdf` — 程序生成的无文本层 1 页 PDF
- `docs/m3-handoff.md` — M3 收尾文档（结构同 m2-handoff.md）

### 修改

- `rag-backend/app/services/parsers/pdf.py` — 加 OCR fallback 分支 + `_render_page_to_image()` 内部函数
- `rag-backend/app/config.py` — 4 个新配置项
- `rag-backend/.env.example` — 占位
- `rag-backend/.env` — 占位（本地）
- `rag-backend/pyproject.toml` — 加 `pypdfium2` + `alibabacloud_ocr_api20210707`

### 配置项（config.py）

```python
aliyun_ocr_access_key_id: str = Field("", alias="ALIYUN_OCR_ACCESS_KEY_ID")
aliyun_ocr_access_key_secret: str = Field("", alias="ALIYUN_OCR_ACCESS_KEY_SECRET")
aliyun_ocr_endpoint: str = Field(
    "ocr-api.cn-hangzhou.aliyuncs.com",
    alias="ALIYUN_OCR_ENDPOINT",
)
ocr_fallback_char_threshold: int = 50
```

---

## 4. 接口契约

### `ocr_service.py`

```python
class OcrError(Exception):
    """OCR 调用失败的统一异常。"""

def ocr_enabled() -> bool:
    """阿里云 key 是否配置。"""

def ocr_image(image_bytes: bytes) -> str:
    """单张图像 → 文本。失败抛 OcrError。

    Args:
        image_bytes: JPEG 或 PNG 字节流。

    Returns:
        识别出的文本（空字符串若图像无文字）。

    Raises:
        OcrError: 当 SDK 调用失败、返回错误码、或服务超时。
    """
```

### `parsers/pdf.py`

```python
def parse_pdf(source: bytes | str | Path) -> list[dict]:
    """与 M2 签名完全一致；内部加 OCR fallback。"""
```

调用方（`ingestion_service.py`）**无需修改**。

---

## 5. 错误处理 / 降级矩阵

| 场景 | 行为 |
|---|---|
| 阿里云 key 未配 | `ocr_enabled()=False`，扫描页直接被丢，等同 M2 行为 |
| 单页 OCR 超时/异常 | 该页 text="" + warning log，文档其他页正常入库 |
| 整个 PDF 全是扫描页 + OCR 全失败 | 无 chunk 生成 → `Document.status="failed"`（M1 既有行为） |
| pypdfium2 渲染失败 | 视为 OCR 失败，单页跳过 + warning |
| 阿里云返回空文本 | 该页正常被丢（与文本不足同处理） |

---

## 6. 测试策略

### 单元测试（mock SDK，不调外网）

| 测试 | 覆盖 |
|---|---|
| `test_ocr_service::test_ocr_image_success` | mock SDK 返回 "hello world"，校验返回 |
| `test_ocr_service::test_ocr_image_api_error` | mock SDK 抛 ClientException，校验抛 OcrError |
| `test_ocr_service::test_ocr_enabled_with_key` | 设置 key，返回 True |
| `test_ocr_service::test_ocr_enabled_without_key` | 空 key，返回 False |
| `test_parser_pdf_ocr::test_text_pdf_skips_ocr` | 正常文本 PDF + mock OCR 不被调用 |
| `test_parser_pdf_ocr::test_scanned_pdf_triggers_ocr` | 扫描 fixture + mock OCR 返回值进入结果 |
| `test_parser_pdf_ocr::test_ocr_failure_returns_empty_page` | mock OCR 抛 OcrError，单页 text=空但不抛 |
| `test_parser_pdf_ocr::test_ocr_disabled_when_no_key` | 空 key，扫描页直接丢，不调 SDK |

总数：M2 13 + M3 8 = **21 个单元测试**。

### Fixture: `scanned.pdf` 生成方式

通过测试 conftest 用 `pypdfium2` 或 reportlab 生成 1 页只含**图像**（无文本层）的 PDF —— 程序化、无外部依赖，纳入 git。

### 不在自动化测试范围（E2E 时验证）

- 真实阿里云 OCR 调用
- 真实扫描合同 PDF 解析准确率
- 中英文混排、表格、印章场景

---

## 7. 验收标准

- [ ] 21/21 单元测试通过
- [ ] 空 key 启动正常，行为完全等同 M2
- [ ] 配置真 key 后，扫描 PDF 上传 → 答案能引用到扫描页内容（手测）
- [ ] Docker 镜像增重 < 100MB
- [ ] M3 handoff doc 提交

---

## 8. 风险 / 已知未知

1. **阿里云 SDK 与 Python 3.12 兼容性** — 文档说 3.7+ 支持，实测前是未知。Fallback：若不兼容，临时切到 HTTP 直调 (`POST /api/predict/ocr_general`)。
2. **`pypdfium2` 在 Docker Linux 渲染嵌中文字体 PDF** — 部分 PDF 可能渲染失败。Fallback：dpi 调低 + warning，单页跳过。
3. **演示文档真实命中率** — 半半场景下，阈值 50 可能需要根据 E2E 数据调整。设为配置项即可动态调。
4. **阿里云 OCR 按量计费上限** — 演示规模可控（< 千页 = < ¥20）；建议在阿里云后台设月度告警。

---

## 9. 与后续 Milestone 的关系

- **M3.5（候选，0.5-1.5 天）**：删除文档 + 重建索引 + 白标。OCR 落地后再启动。
- **M4 候选**：OCR 结果缓存（按文件 SHA + 页码键控）—— 若 OCR 调用量起来再做。
- **M5 候选**：多用户隔离 + 部署（v2 plan 接续）。

---

## 决策日志

| 日期 | 决策 | 备选 | 选择理由 |
|---|---|---|---|
| 2026-06-05 | 选 M3 = OCR 单点 | 多用户 / 删除文档 / 白标 / 打包 | 演示价值最高 + 避免 M1/Deploy v1 的过度打包教训 |
| 2026-06-05 | OCR 用云 API（阿里云）非本地 PaddleOCR | 本地 + 容器 +1GB / Mistral OCR | 同账单 + 不增重 + 2c4G 部署友好 |
| 2026-06-05 | 阈值 50 字符 | 30 / 100 | 经验中位数，可配置 |
| 2026-06-05 | 不做 OCR 缓存 | 加 SHA 缓存 | YAGNI，演示量小 |
| 2026-06-05 | 不打包删除文档/白标 | 与 OCR 一起做 | 单点突破，避免过度打包 |
