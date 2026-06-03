from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


def parse_pdf(source: bytes | str | Path) -> list[dict]:
    """Returns list of {page_num, text, kind: 'page'}."""
    if isinstance(source, (bytes, bytearray)):
        reader = PdfReader(BytesIO(source))
    else:
        reader = PdfReader(str(source))

    pages: list[dict] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append({"page_num": i, "text": text, "kind": "page"})
    return pages
