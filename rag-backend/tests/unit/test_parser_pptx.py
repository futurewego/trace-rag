from pathlib import Path

from app.services.parsers.pptx import parse_pptx

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.pptx"


def test_parse_pptx_slide_per_chunk():
    chunks = parse_pptx(FIXTURE)
    assert len(chunks) >= 1
    assert all(c["kind"] == "slide" for c in chunks)
    assert chunks[0]["page_num"] == 1
    if len(chunks) > 1:
        assert chunks[1]["page_num"] == 2


def test_parse_pptx_includes_notes():
    chunks = parse_pptx(FIXTURE)
    full = "\n".join(c["text"] for c in chunks)
    assert "备注" in full or "Speaker note" in full
