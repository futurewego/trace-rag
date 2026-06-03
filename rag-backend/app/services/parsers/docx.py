from io import BytesIO
from pathlib import Path

from docx import Document as _Doc

_TARGET_CHARS = 2000


def parse_docx(source: bytes | str | Path) -> list[dict]:
    """Returns list of {page_num=None, text, kind='section'}.

    docx 无页概念；按段落聚合到 ~2000 字符的 section。
    """
    if isinstance(source, (bytes, bytearray)):
        doc = _Doc(BytesIO(source))
    else:
        doc = _Doc(str(source))

    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    sections: list[dict] = []
    buf: list[str] = []
    buf_len = 0

    for para in paragraphs:
        if buf_len + len(para) > _TARGET_CHARS and buf:
            sections.append({"page_num": None, "text": "\n".join(buf), "kind": "section"})
            buf = []
            buf_len = 0
        buf.append(para)
        buf_len += len(para)

    if buf:
        sections.append({"page_num": None, "text": "\n".join(buf), "kind": "section"})

    return sections
