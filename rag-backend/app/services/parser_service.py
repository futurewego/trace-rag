"""Mime-type dispatcher for document parsers.

Returns: list[dict] with keys page_num (int|None), text (str), kind (str),
parse_confidence (float), section_path (list[str]).
Subclass-specific kinds:
  - pdf:   kind='page',    page_num=1-based page number
  - pptx:  kind='slide',   page_num=1-based slide number
  - xlsx:  kind='sheet',   page_num=1-based sheet index
  - docx:  kind='section', page_num=None (no page concept in docx)
"""
from pathlib import Path

from app.services.parsers import parse_docx, parse_pdf, parse_pptx, parse_xlsx

_EXT_MAP = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}

_ALLOWED_EXT = {"pdf", "docx", "pptx", "xlsx"}


def detect_format(mime_type: str | None, filename: str | None) -> str:
    if mime_type and mime_type in _EXT_MAP:
        return _EXT_MAP[mime_type]
    if filename:
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix in _ALLOWED_EXT:
            return suffix
    raise ValueError(
        f"cannot detect file type: mime={mime_type} filename={filename}"
    )


def parse(
    source: bytes | str | Path,
    mime_type: str | None = None,
    filename: str | None = None,
) -> list[dict]:
    fmt = detect_format(mime_type, filename)
    if fmt == "pdf":
        return parse_pdf(source)
    if fmt == "docx":
        return parse_docx(source)
    if fmt == "pptx":
        return parse_pptx(source)
    if fmt == "xlsx":
        return parse_xlsx(source)
    raise ValueError(f"unsupported format: {fmt}")
