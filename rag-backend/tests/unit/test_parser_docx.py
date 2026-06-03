from pathlib import Path

from app.services.parsers.docx import parse_docx

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.docx"


def test_parse_docx_returns_sections():
    chunks = parse_docx(FIXTURE)
    assert len(chunks) >= 1
    assert all(c["kind"] == "section" for c in chunks)
    assert all(c["page_num"] is None for c in chunks)
    full_text = "\n".join(c["text"] for c in chunks)
    assert "测试" in full_text or "Hello" in full_text


def test_parse_docx_accepts_bytes():
    raw = FIXTURE.read_bytes()
    chunks = parse_docx(raw)
    assert len(chunks) >= 1
    assert chunks[0]["kind"] == "section"
