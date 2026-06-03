from pathlib import Path

from app.services.parsers.xlsx import parse_xlsx

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.xlsx"


def test_parse_xlsx_one_chunk_per_sheet():
    chunks = parse_xlsx(FIXTURE)
    assert len(chunks) >= 2
    assert all(c["kind"] == "sheet" for c in chunks)
    assert chunks[0]["page_num"] == 1
    assert chunks[1]["page_num"] == 2


def test_parse_xlsx_includes_cell_values():
    chunks = parse_xlsx(FIXTURE)
    full = "\n".join(c["text"] for c in chunks)
    assert "产品" in full
    assert "A1" in full
    assert "订单号" in full
