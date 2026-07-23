from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.parsers.docx import parse_docx
from app.services.parsers.pdf import parse_pdf
from app.services.parsers.pptx import parse_pptx
from app.services.parsers.xlsx import parse_xlsx

FX = Path(__file__).parent / "fixtures"


def test_native_xml_parsers_confidence_095():
    for parse, fx in [
        (parse_docx, "tiny.docx"),
        (parse_xlsx, "tiny.xlsx"),
        (parse_pptx, "tiny.pptx"),
    ]:
        units = parse(FX / fx)
        assert units and all(u["parse_confidence"] == 0.95 for u in units)


@patch("app.services.parsers.pdf.ocr_image", return_value="scanned text recovered")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=True)
def test_pdf_ocr_page_confidence_06(mock_en, mock_ocr):
    pages = parse_pdf(FX / "scanned.pdf")
    assert pages and pages[0]["parse_confidence"] == 0.6


@patch("app.services.parsers.pdf.PdfReader")
@patch("app.services.parsers.pdf.ocr_enabled", return_value=True)
def test_pdf_native_page_confidence_09(mock_en, mock_reader):
    page = MagicMock()
    page.extract_text.return_value = "native long text " * 20
    mock_reader.return_value.pages = [page]
    pages = parse_pdf(FX / "scanned.pdf")
    assert pages and pages[0]["parse_confidence"] == 0.9
