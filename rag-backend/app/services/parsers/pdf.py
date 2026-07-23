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
    ocr_errors = 0
    last_ocr_error: str | None = None
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        confidence = 0.9

        if len(text) < threshold and use_ocr:
            try:
                img_bytes = _render_page_to_image(source, i - 1)
                text = (ocr_image(img_bytes) or "").strip()
                confidence = 0.6
            except OcrError as e:
                # OCR call rejected (bad key / RAM policy / region / throttle /
                # quota / timeout). Log at ERROR so a misconfigured key is visible,
                # and remember it: if it turns out the whole document produced no
                # content, we must fail loudly rather than report a false success.
                logger.error("OCR fail page=%d: %s", i, e)
                ocr_errors += 1
                last_ocr_error = str(e)
                text = ""
            except Exception as e:
                logger.warning("PDF render fail page=%d: %s", i, e)
                text = ""

        if text:
            pages.append({
                "page_num": i, "text": text, "kind": "page",
                "parse_confidence": confidence, "section_path": [],
            })

    # A document that yielded zero content *because every OCR call failed* is an
    # ingestion failure, not an empty document. Raising here lets the caller mark
    # the doc status="failed" (with the Aliyun error) instead of a silent
    # status="indexed"/0-chunk success. Partial failures (some pages recovered)
    # still succeed — single-page failures must not block the whole document.
    if not pages and ocr_errors:
        raise OcrError(
            f"all {ocr_errors} scanned page(s) failed OCR; last error: {last_ocr_error}"
        )

    return pages
