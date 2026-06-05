"""Generate scanned.pdf fixture — a 1-page PDF with no extractable text.

This simulates a scanned document (image-only page) for OCR fallback testing.
The fixture does NOT contain a real image — tests mock OCR responses anyway.
What matters: pypdf.extract_text() returns empty string for this PDF, which
triggers the OCR code path.

Re-run with: uv run python tests/unit/fixtures/_generate_scanned_pdf.py
"""

from pathlib import Path

from pypdf import PdfWriter

OUT = Path(__file__).parent / "scanned.pdf"


def main() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)  # A4 in points
    with OUT.open("wb") as f:
        writer.write(f)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
