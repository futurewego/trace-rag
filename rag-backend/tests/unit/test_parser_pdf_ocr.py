from pathlib import Path
from unittest.mock import MagicMock, patch

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
def test_ocr_failure_returns_empty_page(mock_enabled: MagicMock, mock_ocr: MagicMock) -> None:
    from app.services.ocr_service import OcrError

    mock_ocr.side_effect = OcrError("aliyun timeout")

    pages = parse_pdf(SCANNED)
    assert pages == []
    mock_ocr.assert_called_once()


@patch("app.services.parsers.pdf.ocr_image")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=False)
def test_ocr_disabled_when_no_key(mock_enabled: MagicMock, mock_ocr: MagicMock) -> None:
    pages = parse_pdf(SCANNED)
    assert pages == []
    mock_ocr.assert_not_called()
