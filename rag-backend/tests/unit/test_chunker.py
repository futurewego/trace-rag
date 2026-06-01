from app.services.chunker_service import chunk_page


def test_chunk_short_page_returns_single_chunk():
    text = "Hello world. " * 5
    chunks = chunk_page(text, page_num=1, chunk_size=512, overlap=64)
    assert len(chunks) == 1
    assert chunks[0].page_num == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content.startswith("Hello world")


def test_chunk_long_page_splits_with_overlap():
    text = "word " * 1000
    chunks = chunk_page(text, page_num=2, chunk_size=200, overlap=50)
    assert len(chunks) >= 4
    assert all(c.page_num == 2 for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    for c in chunks[:-1]:
        assert c.token_count <= 200


def test_chunk_empty_text_returns_empty():
    assert chunk_page("", page_num=1) == []
    assert chunk_page("   ", page_num=1) == []
