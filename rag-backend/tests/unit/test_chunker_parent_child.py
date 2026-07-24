from app.config import get_settings
from app.services.chunker_service import chunk_unit, count_tokens


def test_no_child_exceeds_limit_even_without_paragraph_breaks():
    """整页无 '\\n\\n' 也必须递归子切，不得塌成巨块。"""
    limit = get_settings().child_chunk_tokens
    text = "这是一段没有任何空行的长文本。" * 400
    groups = chunk_unit(text, page_num=1)
    children = [c for g in groups for c in g.children]
    assert children
    assert all(c.token_count <= limit for c in children)


def test_every_child_is_substring_of_its_parent():
    """覆盖性不变量：父块必须包含它自己的每个子块。"""
    text = "\n\n".join(f"第{i}段内容，用于构造足够长的文本。" * 12 for i in range(40))
    groups = chunk_unit(text, page_num=2)
    assert groups
    for g in groups:
        for c in g.children:
            assert c.content in g.content


def test_long_element_yields_multiple_parents():
    """长元素必须产出多个父块，而不是一个被截断的父块。"""
    text = "\n\n".join(f"段落{i}：" + "内容" * 200 for i in range(30))
    groups = chunk_unit(text, page_num=3)
    assert len(groups) > 1
    limit = get_settings().parent_chunk_tokens
    assert all(count_tokens(g.content) <= limit for g in groups)


def test_short_text_single_parent_single_child():
    groups = chunk_unit("很短的一句话。", page_num=1)
    assert len(groups) == 1
    assert len(groups[0].children) == 1
    assert groups[0].children[0].content.strip() == "很短的一句话。"


def test_empty_text_returns_empty():
    assert chunk_unit("", page_num=1) == []
    assert chunk_unit("   ", page_num=1) == []


def test_table_kept_whole_when_under_cap():
    rows = "\n".join(f"列A\t列B\n值{i}\t值{i}" for i in range(3))
    groups = chunk_unit(rows, page_num=1, chunk_type="table")
    assert len(groups) == 1
    assert len(groups[0].children) == 1


def test_large_table_is_row_grouped_with_header_repeated():
    header = "订单号\t金额\t客户"
    body = "\n".join(f"HT-{i}\t{i*1000}\t客户{i}" for i in range(2000))
    groups = chunk_unit(f"{header}\n{body}", page_num=1, chunk_type="table")
    children = [c for g in groups for c in g.children]
    assert len(children) > 1
    cap = get_settings().table_max_tokens
    assert all(c.token_count <= cap for c in children)
    assert all(header in c.content for c in children)
