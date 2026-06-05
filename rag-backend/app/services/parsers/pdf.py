import io
import logging
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

from app.config import get_settings
from app.services.ocr_service import OcrError, ocr_enabled, ocr_image

logger = logging.getLogger(__name__)


def _render_page_to_image(source: bytes | str | Path, page_index_zero_based: int) -> bytes:
    """Render a single PDF page to JPEG bytes via pypdfium2."""
    if isinstance(source, (bytes, bytearray)):
        pdf = pdfium.PdfDocument(bytes(source))
    else:
        pdf = pdfium.PdfDocument(str(source))

    page = pdf[page_index_zero_based]
    bitmap = page.render(scale=200 / 72)  # 200 dpi
    pil = bitmap.to_pil()
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def parse_pdf(source: bytes | str | Path) -> list[dict]:
    """Returns list of {page_num, text, kind: 'page'}.

    Per-page flow:
      1. Try pypdf text extraction.
      2. If text < threshold AND OCR enabled, render page via pypdfium2 and call OCR.
      3. On OCR error or render error: log warning, treat page as empty (dropped).
    """
    threshold = get_settings().ocr_fallback_char_threshold
    use_ocr = ocr_enabled()

    if isinstance(source, (bytes, bytearray)):
        reader = PdfReader(io.BytesIO(source))
    else:
        reader = PdfReader(str(source))

    pages: list[dict] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()

        if len(text) < threshold and use_ocr:
            try:
                img_bytes = _render_page_to_image(source, i - 1)
                text = (ocr_image(img_bytes) or "").strip()
            except OcrError as e:
                logger.warning("OCR fail page=%d: %s", i, e)
                text = ""
            except Exception as e:
                logger.warning("PDF render fail page=%d: %s", i, e)
                text = ""

        if text:
            pages.append({"page_num": i, "text": text, "kind": "page"})
    return pages
