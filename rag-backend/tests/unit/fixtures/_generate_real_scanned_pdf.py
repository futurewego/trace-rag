"""Generate real_scanned.pdf — an IMAGE-ONLY PDF whose page is a rendered
bitmap of real Chinese + English text (no text layer at all).

Unlike scanned.pdf (a truly blank page), this fixture actually carries legible
text *as pixels*, so it exercises the full OCR path end to end:
  pypdf.extract_text() -> "" (triggers OCR fallback)
  pypdfium2 renders the page back to a bitmap that a real OCR engine can read.

Use it for E2E: with a real Aliyun key configured, uploading this PDF should
produce chunks containing the sentences below, retrievable via /chat.

Re-run with: uv run python tests/unit/fixtures/_generate_real_scanned_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "real_scanned.pdf"

# Candidate CJK-capable fonts (macOS). Falls back to PIL default (English only)
# if none are present — the committed PDF was generated with a CJK font.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

# Lines rendered as pixels. Mixed zh/en so E2E can assert on either.
LINES = [
    "扫描合同存档件 · SCANNED CONTRACT (image only)",
    "甲方：星曜科技有限公司    乙方：黄河智能装备厂",
    "合同编号 HT-2026-0087    生效日期 2026-01-01",
    "标的金额：人民币壹佰贰拾伍万元整 (1,250,000 CNY)",
    "本页无文本层，仅位图 —— This page has NO text layer.",
    "验收关键词：星曜科技 / 黄河智能 / HT-2026-0087",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> None:
    # A4-ish at ~150 dpi, white background.
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = _load_font(40)

    y = 120
    for line in LINES:
        draw.text((90, y), line, fill=(15, 15, 15), font=font)
        y += 130

    # Save as a single-image PDF -> no text layer.
    img.save(OUT, "PDF", resolution=150.0)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
