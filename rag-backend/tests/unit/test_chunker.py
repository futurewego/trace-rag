from app.services.chunker_service import chunk_unit, count_tokens


def test_short_page_single_parent():
    groups = chunk_unit("Hello world. " * 5, page_num=1)
    assert len(groups) == 1
    assert groups[0].page_num == 1
    assert groups[0].children[0].content.startswith("Hello world")


def test_long_page_splits_into_children_and_parents():
    text = "\n\n".join("word " * 120 for _ in range(30))
    groups = chunk_unit(text, page_num=2)
    children = [c for g in groups for c in g.children]
    assert len(children) >= 4
    assert all(g.page_num == 2 for g in groups)
    assert all(c.token_count <= 200 for c in children)


def test_empty_text_returns_empty():
    assert chunk_unit("", page_num=1) == []
    assert chunk_unit("   ", page_num=1) == []


def test_count_tokens_monotonic():
    assert count_tokens("abc") < count_tokens("abc abc abc")
