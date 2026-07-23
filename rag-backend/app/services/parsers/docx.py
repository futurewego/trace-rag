from io import BytesIO
from pathlib import Path

from docx import Document as _Doc

_TARGET_CHARS = 2000


def parse_docx(source: bytes | str | Path) -> list[dict]:
    """Returns list of {page_num=None, text, kind='section', parse_confidence, section_path}.

    docx 无页概念；按段落聚合到 ~2000 字符的 section。section_path 由 Heading 样式栈推导。
    """
    if isinstance(source, (bytes, bytearray)):
        doc = _Doc(BytesIO(source))
    else:
        doc = _Doc(str(source))

    heading_stack: list[str] = []
    sections: list[dict] = []
    buf: list[str] = []
    buf_len = 0
    path_at_start: list[str] = []

    for p in doc.paragraphs:
        para = p.text.strip() if p.text else ""
        if not para:
            continue

        style = (p.style.name or "") if p.style is not None else ""
        if style.startswith("Heading"):
            try:
                level = max(int(style.split()[-1]), 1)
            except (ValueError, IndexError):
                level = 1
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(para)

        if not buf:
            path_at_start = list(heading_stack)

        if buf_len + len(para) > _TARGET_CHARS and buf:
            sections.append({
                "page_num": None, "text": "\n".join(buf), "kind": "section",
                "parse_confidence": 0.95, "section_path": path_at_start,
            })
            buf = []
            buf_len = 0
            path_at_start = list(heading_stack)

        buf.append(para)
        buf_len += len(para)

    if buf:
        sections.append({
            "page_num": None, "text": "\n".join(buf), "kind": "section",
            "parse_confidence": 0.95, "section_path": path_at_start,
        })

    return sections
