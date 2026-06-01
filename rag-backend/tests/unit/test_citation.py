from app.utils.citation_utils import extract_citations


def test_extract_single_citation():
    text = "答案是这样 [1]。还有更多内容 [2]。"
    assert extract_citations(text) == [1, 2]


def test_extract_no_citations_returns_empty():
    assert extract_citations("纯文本无引用") == []


def test_extract_dedup_keeps_order():
    text = "结论 [1]。再次引用 [1]。新来源 [3]。"
    assert extract_citations(text) == [1, 3]


def test_extract_ignores_invalid():
    text = "[abc] [12.3] [1] [2]"
    assert extract_citations(text) == [1, 2]
