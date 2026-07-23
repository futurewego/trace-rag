from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.ocr_service import OcrError
from app.services.parsers.pdf import parse_pdf

SCANNED = Path(__file__).parent / "fixtures" / "scanned.pdf"


@patch("app.services.parsers.pdf.PdfReader")
@patch("app.services.parsers.pdf.ocr_image")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=True)
def test_text_pdf_skips_ocr(
    mock_enabled: MagicMock, mock_ocr: MagicMock, mock_reader: MagicMock
) -> None:
    """页面文本 > 50 字符时，不应触发 OCR。"""
    long_text = (
        "The quick brown fox jumps over the lazy dog repeatedly today "
        "and tomorrow and forever amen."
    )
    mock_page = MagicMock()
    mock_page.extract_text.return_value = long_text
    mock_reader.return_value.pages = [mock_page]

    pages = parse_pdf(SCANNED)

    assert len(pages) == 1
    assert "fox" in pages[0]["text"].lower()
    assert pages[0]["page_num"] == 1
    assert pages[0]["kind"] == "page"
    mock_ocr.assert_not_called()


@patch("app.services.parsers.pdf.ocr_image", return_value="recognized scan content here")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=True)
def test_scanned_pdf_triggers_ocr(mock_enabled: MagicMock, mock_ocr: MagicMock) -> None:
    pages = parse_pdf(SCANNED)
    assert len(pages) == 1
    assert pages[0]["page_num"] == 1
    assert pages[0]["text"] == "recognized scan content here"
    mock_ocr.assert_called_once()
    img_bytes = mock_ocr.call_args.args[0]
    assert isinstance(img_bytes, bytes)
    assert len(img_bytes) > 0


@patch("app.services.parsers.pdf.ocr_image")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=True)
def test_all_pages_ocr_failure_raises(mock_enabled: MagicMock, mock_ocr: MagicMock) -> None:
    """整篇文档零内容且 OCR 失败时必须抛错，不能伪装成功入库（否则 status=indexed / 0 chunk）。"""
    mock_ocr.side_effect = OcrError("InvalidAccessKeyId: specified access key is not found")

    with pytest.raises(OcrError) as exc:
        parse_pdf(SCANNED)

    assert "InvalidAccessKeyId" in str(exc.value)
    mock_ocr.assert_called_once()


@patch("app.services.parsers.pdf._render_page_to_image", return_value=b"\xff\xd8fake-jpeg")
@patch("app.services.parsers.pdf.PdfReader")
@patch("app.services.parsers.pdf.ocr_image")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=True)
def test_partial_ocr_failure_keeps_good_pages(
    mock_enabled: MagicMock,
    mock_ocr: MagicMock,
    mock_reader: MagicMock,
    mock_render: MagicMock,
) -> None:
    """一页有文本层、另一页 OCR 失败：应保留好页、不抛错（单页失败不阻塞整篇）。"""
    long_text = (
        "This page has a real text layer with more than fifty characters of content here."
    )
    text_page = MagicMock()
    text_page.extract_text.return_value = long_text
    scan_page = MagicMock()
    scan_page.extract_text.return_value = ""  # triggers OCR -> fails
    mock_reader.return_value.pages = [text_page, scan_page]
    mock_ocr.side_effect = OcrError("Throttling.User: request was denied due to throttling")

    pages = parse_pdf(SCANNED)

    assert len(pages) == 1
    assert pages[0]["page_num"] == 1
    assert "text layer" in pages[0]["text"]
    mock_ocr.assert_called_once()


@patch("app.services.parsers.pdf.ocr_image")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=False)
def test_ocr_disabled_when_no_key(mock_enabled: MagicMock, mock_ocr: MagicMock) -> None:
    """OCR 未启用（无 key）：扫描页被丢，返回空，且不抛错（等同 M2 行为）。"""
    pages = parse_pdf(SCANNED)
    assert pages == []
    mock_ocr.assert_not_called()
